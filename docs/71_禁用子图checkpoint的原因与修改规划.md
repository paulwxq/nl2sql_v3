# 禁用子图 Checkpoint 的原因与修改规划

## 决策背景

当前 NL2SQL 系统采用父图+子图架构：
- **父图**：`nl2sql_father`（Fast Path + Complex Path）
- **子图**：`sql_generation`（SQL 生成和验证）

经过分析，决定**禁用子图的 checkpoint**，仅保留父图的 checkpoint。

---

## 禁用原因

### 1. 命名空间混线与状态串线（核心风险）

**问题本质**：
父图与子图复用同一个 `thread_id`，且两者的 `checkpoint_ns` 都会落库为空字符串 `''`，导致所有 checkpoints 混在同一个 `(thread_id, checkpoint_ns)` 命名空间下。

> ⚠️ **术语澄清**：这里讨论的 `checkpoint_ns` 是**写入到 PostgreSQL 表 `checkpoints.checkpoint_ns` 字段的值**，而非运行期 `config["configurable"]["checkpoint_ns"]` 传入的参数。两者有区别：用户可以在 config 中传入任意值，但 LangGraph 对 root graph 会将其归一化为空字符串后再写入数据库。

**为什么落库的 checkpoint_ns 都是空的？**

这是 LangGraph 的设计行为：**root graph（顶层图）的 checkpoint_ns 在落库时始终被归一化为空字符串 `''`**。

> ⚠️ **版本说明**：以上行为基于当前项目使用的 `langgraph>=1.0.0` 和 `langgraph-checkpoint-postgres==3.0.2`。未来版本升级后行为可能变化，届时需重新验证。

- 父图作为 root graph 执行 → 落库 checkpoint_ns = `''`
- 子图通过命令式调用（`subgraph.invoke()`）→ 等价于另一个 root graph 执行 → 落库 checkpoint_ns = `''`
- 用户传入的 `configurable.checkpoint_ns` 对 root graph 的落库值不生效

**导致的风险**：

| 风险 | 说明 |
|------|------|
| **恢复点不确定** | 恢复时使用 `thread_id` + `checkpoint_id` 定位，但由于父图和多个子图的 checkpoints 历史混在同一个 `(thread_id, '')` 命名空间下，选择正确的 `checkpoint_id` 变得困难且难以自动化 |
| **状态串线（条件性）** | 在共享同一 `(thread_id, '')` 命名空间并发生 `resume`/`get_state`/`update_state` 等操作时，**可能**出现"把上一次子图残留 state 带入下一次子图"的语义串线。注意：纯 `.invoke()` 的内存态执行不会发生此问题，问题出在持久化和恢复环节。 |
| **历史混乱** | 不同执行（父图/多次子图调用）的历史追加在一起，`get_state_history()` 排障困难 |
| **语义混淆** | `get_state_history()` 返回的结果混杂了父图和子图的状态，难以解读 |

**场景示例**：
```
同一个 thread_id = "user123:20241222T100000000Z"

checkpoints 表中的记录（checkpoint_ns 字段）：
┌────────────────────────────────┬──────────────┬─────────────────────┐
│ thread_id                      │ checkpoint_ns│ 来源                │
├────────────────────────────────┼──────────────┼─────────────────────┤
│ user123:20241222T100000000Z    │ ''           │ 父图 节点1          │
│ user123:20241222T100000000Z    │ ''           │ 子图1 schema_retr   │
│ user123:20241222T100000000Z    │ ''           │ 子图1 sql_gen       │
│ user123:20241222T100000000Z    │ ''           │ 父图 节点2          │
│ user123:20241222T100000000Z    │ ''           │ 子图2 schema_retr   │  ← 全部混在一起！
│ user123:20241222T100000000Z    │ ''           │ 子图2 sql_gen       │
│ ...                            │ ''           │ ...                 │
└────────────────────────────────┴──────────────┴─────────────────────┘
```

**结论**：禁用子图 checkpoint 可以彻底避免这种命名空间混线。

---

### 2. 循环调用子图的潜在问题

在 Complex Path 的 `sql_gen_batch_wrapper` 节点中，需要在同一个节点内循环调用子图多次：

```python
def sql_gen_batch_wrapper(state):
    current_batch_ids = state.get("current_batch_ids", [])  # 2-5 个子查询
    
    # 在同一个节点内循环调用子图
    for sub_query_id in current_batch_ids:
        subgraph_output = run_sql_generation_subgraph(
            query=sub_query["query"],
            sub_query_id=sub_query_id,
            thread_id=state.get("thread_id"),  # 相同的 thread_id
        )
```

**LangGraph 的相关限制**：

LangGraph 官方文档中提到（参考链接见文末）：

> "calling subgraphs multiple times within a single LangGraph node with checkpointing enabled is currently not allowed due to internal restrictions on checkpoint namespacing"

**适用范围说明**：
- ⚠️ 这段限制**严格针对声明式子图节点**（将 compiled subgraph 直接作为父图的 node）
- 命令式调用（在节点函数内调用 `subgraph.invoke()`）不一定触发同名错误
- **但命令式调用仍存在上述命名空间混线/状态串线问题**

**结论**：禁用子图 checkpoint 可以规避这个限制和潜在风险。

---

### 3. 符合实际使用场景

**HIL（Human-in-the-Loop）计划**：
- ✅ 在**父图**层面实现 HIL
- ✅ 基于父图的"数据导出节点"
- ❌ 不需要在子图内部中断

**故障恢复计划**：
- ✅ 从**父图**层面恢复
- ✅ 父图的 state 包含所有子图结果
- ❌ 不需要恢复到子图的中间节点

**子图定位**：
- 子图只是一个"SQL 生成和验证模块"
- 类似于一个纯函数：输入查询 → 输出 SQL
- 不需要持久化内部状态

---

### 4. 性能优化

**减少数据库写入**（粗略估算）：
```
场景：Complex Path 处理 3 个子查询

之前（子图有 checkpoint）：
- 每个子图多个节点（schema_retrieval, sql_generation, validation 等）
- 涉及 checkpoints、checkpoint_writes、checkpoint_blobs 等表写入
- 子图可能有重试/循环，次数会浮动
- 粗略估算：3 子查询 × 多个节点 ≈ 20-30 次数据库操作
- 加上父图的写入：总计可能 30+ 次

之后（子图无 checkpoint）：
- 子图不写入 checkpoint：0 次
- 只有父图写入：约 6-10 次
- 粗略估算减少约 60-80% 的数据库操作

注意：以上为粗略估算，实际次数取决于图结构、重试逻辑、LangGraph 内部实现等因素。
```

**优点**：
- ✅ 减少数据库压力
- ✅ 提升执行性能
- ✅ 降低存储成本

---

## 影响评估

### ✅ 不会受影响的功能

#### 1. 子图的正常运行
- **State 传递**：节点之间通过内存中的 State 传递数据，不依赖 checkpoint
- **执行流程**：子图会正常执行所有节点，返回完整结果
- **示例**：
  ```python
  初始 State → schema_retrieval → sql_generation → 
  validation → 返回最终结果
  ```
  整个流程完全正常，State 在内存中传递。

#### 2. 父图的 checkpoint 功能
- **父图 State 持久化**：父图的 checkpoint 会保存子图返回的所有结果
- **故障恢复**：从父图层面恢复，子图会重新执行（代价可接受）
  > ⚠️ 注意：恢复/重跑时子图会重新执行，意味着会产生额外的 LLM 调用。业务上需接受这部分可重复成本和潜在副作用（如重复调用外部 API）。
- **HIL 能力**：在父图节点实现 interrupt，完全不受影响

#### 3. 子图的最终结果
父图 State 会完整保存子图的输出：
```python
{
    "sub_queries": [
        {
            "sub_query_id": "sq1",
            "query": "查询销售额",
            "validated_sql": "SELECT SUM(amount) FROM sales WHERE year=2024",
            "iteration_count": 2,
            "status": "completed",
            "execution_result": {...}
        }
    ]
}
```

---

### ❌ 会失去的功能

#### 1. 子图的执行历史
- **无法查询**：数据库中不会保存子图各节点的中间状态
- **影响**：调试时看不到 schema_retrieval、sql_generation 等节点的详细输出

**缓解措施**：
- ✅ 通过日志记录子图的关键信息
- ✅ 父图 State 保存子图的最终结果
- ✅ 子图返回的元数据（iteration_count 等）

#### 2. 子图内部的 interrupt/resume
- **无法使用**：不能在子图内部调用 `interrupt()`
- **影响**：无（我们本就计划在父图层面实现 HIL）

#### 3. 子图的时间旅行
- **无法使用**：不能恢复到子图的某个历史节点
- **影响**：无（我们不需要这个功能）

---

## 修改规划

### 修改文件清单

1. ✅ `src/modules/sql_generation/subgraph/create_subgraph.py`
   - 修改 `get_compiled_subgraph()` 函数
   - 明确传入 `checkpointer=None`（禁用）

2. ✅ `src/configs/config.yaml`（可选）
   - 添加配置项说明禁用子图 checkpoint

3. ✅ `docs/71_禁用子图checkpoint的原因与修改规划.md`
   - 本文档，记录决策和修改

---

### 详细修改步骤

#### 步骤 1：修改子图编译逻辑

**文件**：`src/modules/sql_generation/subgraph/create_subgraph.py`

**修改位置**：`get_compiled_subgraph()` 函数

**实际函数签名**：
```python
def create_sql_generation_subgraph(checkpointer=None) -> CompiledStateGraph:
```

> ⚠️ **注意**：实际代码使用 `checkpointer=None` 表示禁用，而非 `checkpointer=False`。以实际函数定义为准。

**修改后的代码**：
```python
def get_compiled_subgraph() -> CompiledStateGraph:
    """获取编译后的子图（带缓存）
    
    说明：
        子图禁用了 checkpoint，原因：
        1. 避免命名空间混线（父图和子图的 checkpoint_ns 落库后都是空字符串）
        2. 避免状态串线（同一 thread_id 下不同调用的 checkpoint 混在一起）
        3. 符合使用场景（HIL 和故障恢复都在父图层面）
        4. 性能优化（减少数据库写入）
    
    影响：
        - 子图的中间状态不会持久化到数据库
        - 但子图会正常运行，State 在内存中传递
        - 父图的 checkpoint 会保存子图的最终结果
    """
    global _compiled_subgraph
    
    # 如果缓存存在，直接返回（避免重复编译）
    if _compiled_subgraph is not None:
        return _compiled_subgraph
    
    # 【关键修改】子图始终不使用 checkpointer
    # 原因：
    # 1. 避免与父图的 checkpoint 混在同一个 (thread_id, '') 命名空间下
    # 2. 避免在 sql_gen_batch_wrapper 中循环调用时的命名空间/状态问题
    # 3. HIL 和故障恢复在父图层面，不需要子图的 checkpoint
    # 4. 减少数据库写入压力
    _compiled_subgraph = create_sql_generation_subgraph(checkpointer=None)
    
    logger.info(
        "子图已编译（已禁用 Checkpoint）：子图只负责 SQL 生成，HIL 和恢复在父图层面"
    )
    
    return _compiled_subgraph
```

**变更说明**：
- 移除了 `get_postgres_saver("subgraph")` 的调用
- 移除了 `SafeCheckpointer` 的包装
- 直接传入 `checkpointer=None`（禁用）
- 简化了缓存逻辑（不再需要根据 checkpoint_enabled 判断）
- 添加详细的文档注释说明原因

---

#### 步骤 2：更新配置文件（可选）

**文件**：`src/configs/config.yaml`

**位置**：`langgraph_persistence` 部分

```yaml
langgraph_persistence:
  enabled: true                      # 总开关（当前已启用）

  checkpoint:
    enabled: true                    # checkpoint 组件开关（仅对父图生效）
    father_namespace: nl2sql_father  # 父图标识
    # 注：此值实际 checkpoint_ns 落库后会是空字符串（LangGraph 对 root graph 的行为）
    # 保留此配置的用途：
    # - 业务标识/可读性（代码中区分父图/子图）
    # - 日志记录（便于追踪）
    # - 未来可能的扩展（如果 LangGraph 支持自定义 root checkpoint_ns）
    #   注意：即使未来支持，仍需考虑命令式子图调用是否会被视作独立 root，
    #   不一定能直接用于数据库字段过滤
    # 目前不能用于数据库字段过滤依据
    
    # subgraph_namespace: sql_generation  # 已废弃，子图禁用 checkpoint
    
    # 【设计说明】
    # 子图禁用 checkpoint 的原因：
    # 1. LangGraph 中 root graph 的 checkpoint_ns 落库时始终为空字符串
    # 2. 命令式调用的子图等价于另一个 root graph，落库 checkpoint_ns 也为空
    # 3. 父图和子图共用同一 thread_id，会导致 checkpoint 混在一起
    # 4. 禁用子图 checkpoint 可避免命名空间混线和状态串线
```

---

#### 步骤 3：清理相关代码（可选）

如果需要彻底清理，可以考虑：

1. **移除 `get_postgres_saver("subgraph")` 的调用**
   - 位置：`src/services/langgraph_persistence/postgres.py`
   - 由于子图不再使用，可以移除"subgraph"类型的 saver 创建逻辑
   - 但保留也无妨（不影响功能）

2. **移除子图相关的 checkpoint_ns 设置**
   - 位置：`src/modules/sql_generation/subgraph/create_subgraph.py` 中的 `run_sql_generation_subgraph()`
   - 移除尝试设置 checkpoint_ns 的代码（因为已经无效）

**示例**：
```python
# 修改前
invoke_config = None
if is_checkpoint_enabled() and thread_id:
    subgraph_namespace = get_checkpoint_namespace("subgraph")
    checkpoint_ns = f"{subgraph_namespace}:{sub_query_id or query_id}"
    invoke_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,  # ← 对 root graph 落库无效
        }
    }

# 修改后
# 子图已禁用 checkpoint，不需要传递 config
final_state = subgraph.invoke(initial_state)
```

**建议**：先保留这些代码，确认子图禁用 checkpoint 后运行正常，再考虑清理。

---

### 步骤 4：测试验证

#### 测试清单

1. **Fast Path 测试**
   - 执行简单查询
   - 验证子图正常运行
   - 验证父图 checkpoint 正常

2. **Complex Path 测试**
   - 执行复杂查询（需要拆分多个子查询）
   - 验证 `sql_gen_batch_wrapper` 中循环调用子图不报错
   - 验证所有子查询都正常生成 SQL

3. **故障恢复测试**
   - 模拟父图执行到一半时崩溃
   - 验证能从父图层面恢复
   - 验证子图会重新执行（预期行为）

4. **数据库验证**

   > ⚠️ **注意**：由于 checkpoint_ns 落库始终为空字符串，不能用 checkpoint_ns 来区分父图和子图。推荐使用以下方法：

   **方法 A：通过 checkpoint 数量变化验证**
   ```sql
   -- 禁用前：记录某个 thread_id 的 checkpoint 数量
   SELECT COUNT(*) FROM langgraph.checkpoints 
   WHERE thread_id = 'user123:20241222T100000000Z';
   -- 假设返回 25
   
   -- 禁用后：执行相同查询，checkpoint 数量应该明显减少
   SELECT COUNT(*) FROM langgraph.checkpoints 
   WHERE thread_id = 'user456:20241222T110000000Z';
   -- 应该返回约 6-10（只有父图的 checkpoint）
   ```
   
   > ⚠️ **对比注意事项**：
   > - 父图节点数、重试次数、是否触发 Complex Path 都会影响 checkpoint 数量
   > - 建议使用**同类查询**对比（如都是 Fast Path 简单查询）
   > - 或多次执行取**平均值**来对比

   **方法 B：通过同一 thread_id 的 checkpoint 增量验证**
   ```sql
   -- 使用特定 thread_id 避免多人/并发环境干扰
   
   -- 执行前记录该 thread_id 的 checkpoint 数量
   SELECT COUNT(*) FROM langgraph.checkpoints 
   WHERE thread_id = 'test_user:20241222T100000000Z';  -- 假设返回 0
   
   -- 执行一次查询（使用该 thread_id）...
   
   -- 执行后记录该 thread_id 的 checkpoint 数量
   SELECT COUNT(*) FROM langgraph.checkpoints 
   WHERE thread_id = 'test_user:20241222T100000000Z';  -- 假设返回 8
   
   -- 增量 = 8 - 0 = 8（只有父图的 checkpoint）
   -- 禁用前同样查询增量可能是 25-30（包含子图 checkpoint）
   ```
   - 禁用后，单次执行的 checkpoints 增量应**显著减少**
   - 使用同一 thread_id 对比，避免其他用户/并发请求的干扰

5. **日志验证**
   - 确认日志中有"子图已编译（已禁用 Checkpoint）"
   - 确认子图的关键步骤有日志记录

---

## 回滚方案

如果禁用子图 checkpoint 后发现问题，可以快速回滚：

```python
# 恢复之前的逻辑
def get_compiled_subgraph():
    checkpoint_enabled = is_checkpoint_enabled()
    if checkpoint_enabled:
        real_checkpointer = get_postgres_saver("subgraph")
        if real_checkpointer is not None:
            checkpointer = SafeCheckpointer(real_checkpointer, enabled=True)
        else:
            checkpointer = None
        _compiled_subgraph = create_sql_generation_subgraph(checkpointer=checkpointer)
    else:
        _compiled_subgraph = create_sql_generation_subgraph(checkpointer=None)
    return _compiled_subgraph
```

> ⚠️ **警告**：回滚后会恢复命名空间混线问题。如果确实需要子图 checkpoint，需要同时解决以下问题：
> 
> | 隔离方案 | 描述 | 代价 |
> |---------|------|------|
> | **独立 thread_id** | 每次子图调用使用不同的 thread_id | 丢失"同一会话内子图 checkpoint 与父图 checkpoint 的连续可追溯性"；需要额外的映射关系表来关联父图和子图的 thread_id，否则只是把混线问题换成对账问题 |
> | **独立 checkpointer** | 每次子图调用使用独立的 checkpointer 实例 | 增加连接数和资源开销；需要管理多个 checkpointer 的生命周期 |
> | **声明式子图** | 改用声明式子图集成 | 需重构状态转换逻辑；父图和子图需要兼容的 State 结构；不适用于循环调用场景 |

但根据分析，应该不需要回滚。

---

## 后续优化建议

### 1. 增强日志记录

在子图的关键节点增加详细日志：

```python
def schema_retrieval_node(state):
    logger.debug(
        f"[{state['query_id']}] Schema检索结果: "
        f"找到 {len(schema_context['tables'])} 张表"
    )
    return {"schema_context": schema_context}
```

### 2. 监控子图执行

在父图 State 中添加子图执行的统计信息：

```python
{
    "sub_queries": [{
        "sub_query_id": "sq1",
        "validated_sql": "...",
        "iteration_count": 2,
        "execution_time_ms": 1234.5,  # ← 记录执行时间
        "retry_count": 0,  # ← 记录重试次数
    }]
}
```

---

## 总结

### 决策

✅ **禁用子图的 checkpoint，仅保留父图的 checkpoint**

### 核心原因

1. **命名空间混线**（首要）：父图和子图共用 `(thread_id, '')` 导致 checkpoint 混在一起
2. **状态串线风险**：在 resume/get_state 等操作时可能导致语义混乱
3. 符合使用场景（HIL 和故障恢复都在父图层面）
4. 性能优化（减少数据库写入）

### 技术背景

- LangGraph 中 root graph 的 checkpoint_ns **落库时**始终被归一化为空字符串 `''`
- 命令式调用的子图等价于另一个 root graph 执行
- 用户传入的 `configurable.checkpoint_ns` 对 root graph 的落库值不生效

### 影响

- ✅ 子图正常运行（State 在内存中传递）
- ✅ 父图 checkpoint 完整（保存子图结果）
- ✅ HIL 和故障恢复不受影响
- ⚠️ 失去子图执行历史（通过日志补偿）

### 工作量

- **代码修改**：1 个函数，约 20 行代码
- **测试验证**：Fast Path + Complex Path + 故障恢复
- **风险等级**：低（可快速回滚）

---

## 参考文档

### 项目内文档
- [checkpoint_ns为空的根本原因分析.md](./checkpoint_ns为空的根本原因分析.md)
- [LangGraph子图集成方式完整分析.md](./LangGraph子图集成方式完整分析.md)
- [保持现状的完整评估与建议.md](./保持现状的完整评估与建议.md)

### LangGraph 官方文档
> ⚠️ **链接说明**：LangGraph 官方文档有多个入口，以下列出常用的两个。建议团队统一使用其中一个作为"官方来源"，避免后续审计/链接失效时产生争议。

- **GitHub Pages 版本**：[langchain-ai.github.io/langgraph/how-tos/subgraph/](https://langchain-ai.github.io/langgraph/how-tos/subgraph/)
  - "Multiple subgraph calls" 章节描述了循环调用子图的限制
- **LangChain Docs 版本**：[docs.langchain.com - use-subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
  - 项目此前对齐的文档来源
