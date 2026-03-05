# 76_父图Checkpoint瘦身优化设计

## 文档信息

- **创建日期**: 2026-03-05 (基于会话上下文)
- **版本**: v1.3（审核修订）
- **状态**: 待实施
- **目标**: 解决 LangGraph 父图 Checkpoint 单行 payload 随对话轮次跨轮累加膨胀的问题，实现”按轮次覆盖”的轻量级状态管理；配合定期清理历史行（参见 4.6 节），控制 checkpoint 表的整体体积。

---

## 一、 背景与问题分析

### 1.1 现状与痛点

在当前的架构中：
1. **多轮对话长连接**：同一用户在同一个对话窗口中持续提问，系统复用同一个 `thread_id`。
2. **LangGraph 的 Append-Only 机制**：LangGraph 的 Checkpoint 机制是追加写入的。在每个节点执行完毕后，都会将完整的 State 序列化并 Insert 到数据库中。
3. **State 累加器导致膨胀**：在 `src/modules/nl2sql_father/state.py` 中，`sub_queries` 和 `execution_results` 使用了 `Annotated[..., add]` 累加器。
   ```python
   sub_queries: Annotated[List[SubQueryInfo], add]
   execution_results: Annotated[List[SQLExecutionResult], add]
   ```
   **后果**：每一轮新对话产生的子查询和 SQL 执行结果（可能包含大量数据行），都会被追加到这个列表中并永久存储在 Checkpoint 里。到了第 10 轮对话，Checkpoint 里将包含前 9 轮所有的中间执行结果，导致数据库体积呈几何级数爆炸，读写性能急剧下降。

### 1.2 优化可行性分析

1. **对话记录已独立**：我们已经引入了 `PostgresStore` 专门存储跨轮次的对话记录（QA 文本）。
2. **中间状态仅本轮有效**：`sub_queries` 和 `execution_results` 仅仅是**当前这一轮**查询任务的中间态数据，它们在跨轮次（跨问题）时没有任何复用价值。
3. **子图 Checkpoint 当前关闭**：子图的 Checkpoint 开关当前通过配置项 `langgraph_persistence.checkpoint.subgraph_enabled` 关闭（代码层面支持开启），因此本优化只需针对父图（NL2SQLFather）。

---

## 二、 核心优化策略：按轮次状态覆盖（Overwrite）

**总体思路：移除跨轮次累加器，改用单轮内部手动维护的覆盖策略。**

当用户发起新一轮提问时，系统会调用 `create_initial_state` 初始化 `sub_queries=[]` 和 `execution_results=[]`。如果我们在 State 中去掉 `add` 累加器，LangGraph 就会用这个新的空列表直接**覆盖** State 中上一轮遗留的庞大数据。从而保证**新产生的 checkpoint 行的 payload** 只包含当前一轮的数据量。

> **重要区分**：此处的”覆盖”仅指 **State 值层面**的覆盖（新一轮的 `[]` 替换了上一轮的累加列表），而非数据库行层面的删除。LangGraph 的 `PostgresSaver` 采用 append-only 机制（每个节点执行后 INSERT 一行），**旧轮次产生的 checkpoint 行仍然保留在数据库中**。关于历史行的清理，参见第四章 4.6 节。

---

## 三、 具体实施方案

### 3.1 修改 State 定义（移除累加器）

**文件**：`src/modules/nl2sql_father/state.py`

将 `Annotated[..., add]` 移除，恢复为普通的 `List`。这样 LangGraph 默认会使用覆盖（Overwrite）行为，而不是合并（Append）行为。

```python
# 修改前
sub_queries: Annotated[List[SubQueryInfo], add]
execution_results: Annotated[List[SQLExecutionResult], add]

# 修改后
sub_queries: List[SubQueryInfo]
execution_results: List[SQLExecutionResult]
```

### 3.2 节点逻辑适配（单轮内部手动维护状态）

去掉了 `add` 之后，在**单轮对话内部**（尤其是 Phase 2 Complex Path 存在多轮循环执行的场景下），我们需要在代码中手动拼接列表并显式返回，以确保当轮循环的数据不丢失。

需要修改以下节点（凡是修改了 `sub_queries` 或新增了 `execution_results` 的节点，都必须显式地在返回值中带上它们）：

#### 1. SQL 执行节点 (`src/modules/nl2sql_father/nodes/sql_execution.py`)
在单次循环中，可能会产生新的执行结果。我们需要把新结果拼接到历史结果（仅限本轮）中，并显式返回。
同时，节点原地修改了 `sub_query["status"]` 和 `sub_query["execution_result"]`，所以也需要把 `sub_queries` 一并返回。

**注意**：该节点有 2 条返回路径，**都需要保留已有结果**。

**路径 A：无待执行 SQL 的早返回**（当 `sqls_to_execute` 为空时）

```python
if not sqls_to_execute:
    query_logger.warning("没有待执行的SQL")
    # ⚠ 必须返回 state 中已有的 execution_results，而非 []
    # 否则 Complex Path 循环中前几轮的结果会被覆盖清空
    return {
        "execution_results": state.get("execution_results", []),
        "parallel_execution_count": state.get("parallel_execution_count") or 0,
    }
```

**路径 B：正常执行路径**（执行 SQL 并拼接结果）

```python
def sql_execution_node(state: NL2SQLFatherState, config: Dict[str, Any] = None) -> Dict[str, Any]:
    # ... 前置逻辑不变 ...

    # 获取本轮已有的结果（用于 Complex Path 多轮循环时的手动拼接）
    existing_results = state.get("execution_results", [])
    new_results: List[SQLExecutionResult] = []

    # ... 执行 SQL 并将结果追加到 new_results 中，同时原地更新了 sub_queries 的元素 ...

    # 手动拼接列表（替代原来 add 累加器的角色）
    final_results = existing_results + new_results

    return {
        "execution_results": final_results,
        "sub_queries": state.get("sub_queries", []), # 显式返回更新后的 sub_queries，确保原地修改被保存
        "parallel_execution_count": max_parallel_count,
    }
```

#### 2. 参数注入节点 (`src/modules/nl2sql_father/nodes/inject_params.py`)
该节点原地更新了 `sq["dependencies_results"]` 和 `sq["status"]`，必须显式返回 `sub_queries` 才能让 Checkpoint 保存这些修改。

```python
def inject_params_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    # ... 逻辑不变 ...
    
    return {
        "current_batch_ids": batch_ids,
        "sub_queries": state.get("sub_queries", []) # 显式返回以触发覆盖
    }
```

#### 3. SQL 生成 Wrapper (`src/modules/nl2sql_father/graph.py`)
`sql_gen_wrapper` 和 `sql_gen_batch_wrapper` 原地更新了 `sub_query["validated_sql"]` 等字段。必须在返回值中包含 `sub_queries`。

**`sql_gen_wrapper`** 有 4 条返回路径，**所有路径**都需要添加 `"sub_queries"` 返回（其中路径 C、D 修改了 `sub_queries` 中的 dict 对象，必须返回；路径 A、B 虽未修改但为了一致性也应返回）：

```python
def sql_gen_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    # 路径 A: current_sub_query_id 缺失
    if not current_sub_query_id:
        return {
            "error": "No current sub_query_id",
            "error_type": "internal_error",
            "sub_queries": state.get("sub_queries", []),
        }

    # 路径 B: 未找到对应的子查询
    if not current_sub_query:
        return {
            "error": f"Sub query {current_sub_query_id} not found",
            "error_type": "internal_error",
            "sub_queries": state.get("sub_queries", []),
        }

    try:
        # ... 调用子图 ...
        # 路径 C: 正常返回（成功或失败）
        # ⚠ 此处原地修改了 current_sub_query["status"]、["validated_sql"] 等
        return {
            "validated_sql": subgraph_output.get("validated_sql"),
            "error": subgraph_output.get("error"),
            "error_type": subgraph_output.get("error_type"),
            "iteration_count": subgraph_output.get("iteration_count"),
            "sub_queries": state.get("sub_queries", []),  # 显式返回
        }
    except Exception as e:
        # 路径 D: 异常兜底
        # ⚠ 此处原地修改了 current_sub_query["status"]="failed" 和 ["error"]
        current_sub_query["status"] = "failed"
        current_sub_query["error"] = error_msg
        return {
            "validated_sql": None,
            "error": error_msg,
            "error_type": "generation_failed",
            "iteration_count": 0,
            "sub_queries": state.get("sub_queries", []),  # 必须返回，否则 failed 状态丢失
        }
```

**`sql_gen_batch_wrapper`**：

```python
def sql_gen_batch_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    # ... 逻辑不变 ...
    # 原注释 "直接修改 sub_queries，无需返回" 不再成立
    # 移除 add 后，必须显式返回 sub_queries 才能让原地修改被 Checkpoint 保存
    return {"sub_queries": state.get("sub_queries", [])}
```

#### 4. Check Completion 节点 (`src/modules/nl2sql_father/nodes/check_completion.py`)
该节点有 4 条返回路径，按是否原地修改了 `sub_queries` 分为两类：

| 返回路径 | 是否原地修改 `sub_queries` | 是否必须返回 `sub_queries` |
|---|---|---|
| 正常完成（all done） | 否 | 否（但为一致性建议返回） |
| 最大轮次保护 | **是**（标记 pending/in_progress → failed） | **必须** |
| 依赖环检测 | **是**（标记 pending → failed） | **必须** |
| 继续循环 | 否 | 否 |

```python
def check_completion_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    sub_queries = state.get("sub_queries", [])
    # ... 统计逻辑不变 ...

    # 路径 1: 正常完成（无原地修改）
    if status_count["pending"] == 0 and status_count["in_progress"] == 0:
        return {}

    # 路径 2: 最大轮次保护（⚠ 原地修改了 sub_queries 中的 status 和 error）
    if current_round >= max_rounds:
        for sq in sub_queries:
            if sq.get("status") in ["pending", "in_progress"]:
                sq["status"] = "failed"
                sq["error"] = f"超过最大轮次 {max_rounds}，强制终止"
        return {"sub_queries": sub_queries}  # 必须返回，否则 failed 标记丢失

    # 路径 3: 依赖环检测（⚠ 原地修改了 sub_queries 中的 status 和 error）
    if enable_cycle_detection and not has_ready:
        for sq in sub_queries:
            if sq.get("status") == "pending":
                sq["status"] = "failed"
                sq["error"] = "依赖环或孤立子查询，无法继续推进"
        return {"sub_queries": sub_queries}  # 必须返回，否则 failed 标记丢失

    # 路径 4: 继续循环（无原地修改）
    return {"current_round": next_round}
```

#### 5. Simple Planner 节点 & Planner 节点
它们目前的逻辑是直接返回 `{"sub_queries": [...]}`。由于去掉了 `add`，LangGraph 会直接用它们返回的列表覆盖 `state`，这正是我们期望的（每轮重新开始），因此**这两个节点不需要修改**。

---

## 四、 影响评估与保障机制

### 4.1 对当前功能的影响
- **Fast Path（简单问题）**：完全无影响。每一轮都是全新的 `sub_queries` 列表，执行一次后结束。
- **Complex Path（复杂问题）**：完全无影响。虽然去掉了自动累加器，但我们在 `sql_execution.py` 中加入了 `existing_results + new_results` 的手动拼接逻辑，完美兼容了 Phase 2 中的多步循环依赖机制。

### 4.2 性能与存储收益

本优化带来两层收益，需区分理解：

**第一层：单行 payload 瘦身（本方案直接实现）**
- 移除 `add` 累加器后，每轮对话开始时 State 中的 `sub_queries` 和 `execution_results` 被重置为 `[]`，**新产生的 checkpoint 行**只包含当前轮的数据。
- 对比优化前：第 N 轮的 checkpoint 行包含前 N-1 轮所有累加数据（可达几十 MB）；优化后：每行仅包含当前轮数据（通常几十 KB）。
- **读写性能提升**：LangGraph 每次 `invoke` 需要先读取最新 checkpoint 并反序列化。payload 从几十 MB 降到几十 KB，直接消除了序列化/反序列化的 CPU 和 IO 瓶颈。

**第二层：历史行清理（需 DBA 配合，参见 4.6 节）**
- LangGraph 的 `PostgresSaver` 是 append-only 的，3 张表（`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`）中旧轮次产生的行**不会被自动删除**。其中 `checkpoint_blobs` 存储 List/Dict 类型的 channel 值，是大体积数据的主要所在。
- 本方案解决的是"每行越来越大"的问题，但"行数越来越多"的问题需要定期清理。

### 4.3 HIL（人工介入）兼容性
如果未来在此方案上启用 HIL（比如在 SQL 执行前暂停），系统仍然能完美工作。因为单次执行轮次内部，`sub_queries` 被不断显式覆盖更新，断点状态依然准确完整。

### 4.4 `parallel_execution_count` 等非累加字段的跨轮次行为

`parallel_execution_count` 是普通的 `Optional[int]` 字段（无 `add` 累加器），其跨轮次行为**不受本次优化影响**。每轮 `create_initial_state` 设置 `parallel_execution_count=None`，LangGraph 的默认覆盖行为会自动将其重置，无需额外处理。

### 4.5 关于 LangGraph in-place 修改行为的前提假设

本方案的核心设计依赖以下前提：**节点在 `state` 字典中原地修改 dict/list 对象后，通过显式返回该字段来保存修改**。具体机制为：

1. LangGraph 将当前 state 传入节点（Python 引用传递，非深拷贝）
2. 节点原地修改 `sub_queries` 中的某个 dict 元素（如 `sq["status"] = "failed"`）
3. 节点返回 `{"sub_queries": state.get("sub_queries", [])}` —— 返回的是同一个被修改过的列表引用
4. LangGraph 用返回值覆盖 Checkpoint 中的 `sub_queries` 字段，修改得以持久化

为了**防御性安全**，本方案选择在所有修改了 `sub_queries` 的节点中显式返回它，避免依赖未文档化的框架行为。实施后应通过 5.2 节的新增单元测试验证此机制的正确性。

### 4.6 Checkpoint 历史行清理（DBA 手动执行）

LangGraph 的 `PostgresSaver` 使用 3 张表存储 checkpoint 数据：

| 表名 | 存储内容 | 膨胀风险 |
|---|---|---|
| `checkpoints` | checkpoint 元数据 + 内联原始值（str/int/float/bool） | 中（每个节点步骤一行） |
| `checkpoint_blobs` | 非原始类型的 channel 值（List/Dict 等，**包括 `sub_queries` 和 `execution_results`**） | **高**（大体积 payload 存在此表） |
| `checkpoint_writes` | 节点增量写入数据 | 中 |

这 3 张表均为 append-only，**旧行永远不会被自动删除**。本方案解决了"每行 payload 越来越大"的核心问题，但行数仍会持续增长，建议 DBA 定期清理。

**清理策略**：对于每个 `(thread_id, checkpoint_ns)` 组合，只保留最新的 checkpoint，删除更早的所有行。

> **关于 `MAX(checkpoint_id)` 的可靠性**：LangGraph 的 `checkpoint_id` 使用 UUID v6 生成（`uuid6(clock_seq=step)`），UUID v6 是时间有序的，字符串排序等价于时间排序。LangGraph 自身也使用 `ORDER BY checkpoint_id DESC LIMIT 1` 来获取最新 checkpoint。因此 `MAX(checkpoint_id)` 可靠地表示"最新"。

```sql
-- ============================================================
-- Checkpoint 历史行清理脚本
-- 注意：以下 SQL 在 langgraph schema 下执行
-- 请根据实际 schema 名称调整（配置项：langgraph_persistence.database.schema）
-- 建议在低峰期执行，整体包在事务中以保证一致性
-- ============================================================

BEGIN;

-- 1. 找出每个 (thread_id, checkpoint_ns) 的最新 checkpoint_id
-- 放入临时表，避免子查询重复计算
CREATE TEMP TABLE _latest_checkpoints AS
SELECT thread_id, checkpoint_ns, MAX(checkpoint_id) AS checkpoint_id
FROM langgraph.checkpoints
GROUP BY thread_id, checkpoint_ns;

-- 2. 清理 checkpoint_writes（先清理，因为它引用 checkpoint_id）
DELETE FROM langgraph.checkpoint_writes cw
WHERE NOT EXISTS (
    SELECT 1 FROM _latest_checkpoints lc
    WHERE lc.thread_id = cw.thread_id
      AND lc.checkpoint_ns = cw.checkpoint_ns
      AND lc.checkpoint_id = cw.checkpoint_id
);

-- 3. 清理 checkpoint_blobs（大体积数据所在，清理收益最大）
-- blobs 通过 (thread_id, checkpoint_ns, channel, version) 关联
-- 保留最新 checkpoint 引用的 (channel, version) 对，删除其余
DELETE FROM langgraph.checkpoint_blobs bl
WHERE NOT EXISTS (
    SELECT 1 FROM _latest_checkpoints lc
    INNER JOIN langgraph.checkpoints c
        ON c.thread_id = lc.thread_id
       AND c.checkpoint_ns = lc.checkpoint_ns
       AND c.checkpoint_id = lc.checkpoint_id
    WHERE bl.thread_id = c.thread_id
      AND bl.checkpoint_ns = c.checkpoint_ns
    -- channel_versions 记录了每个 channel 对应的 version
    -- 只保留最新 checkpoint 引用的 version
      AND jsonb_extract_path_text(c.checkpoint, 'channel_versions', bl.channel) = bl.version
);

-- 4. 清理 checkpoints 主表（只保留最新行）
DELETE FROM langgraph.checkpoints c
WHERE NOT EXISTS (
    SELECT 1 FROM _latest_checkpoints lc
    WHERE lc.thread_id = c.thread_id
      AND lc.checkpoint_ns = c.checkpoint_ns
      AND lc.checkpoint_id = c.checkpoint_id
);

-- 5. 清理临时表
DROP TABLE _latest_checkpoints;

COMMIT;

-- 6. 回收磁盘空间（COMMIT 后执行，不能在事务内）
VACUUM ANALYZE langgraph.checkpoint_blobs;
VACUUM ANALYZE langgraph.checkpoints;
VACUUM ANALYZE langgraph.checkpoint_writes;
```

> **执行频率建议**：视业务量而定，日均对话量较大时建议每周执行一次；量少时每月一次即可。执行前建议先用 `SELECT COUNT(*)` 确认各表行数，评估清理规模。

---

## 五、 测试与验收要点

### 5.1 现有单元测试适配（必须先完成）

本次改动直接影响 3 个节点的返回值格式，**必须同步更新**对应的单元测试。以下是需要修改的具体断言：

**`src/tests/unit/nl2sql_father/test_sql_execution.py`**：
- `test_no_sql_to_execute`：`assert result["execution_results"] == []` → 改为验证返回 `state.get("execution_results", [])`（保留已有结果，非空列表覆盖）
- 所有成功/失败用例（`test_execute_sql_success`, `test_execute_sql_failure`, `test_dual_binding_*`, `test_multiple_sql_execution` 等）：新增 `assert "sub_queries" in result` 断言

**`src/tests/unit/nl2sql_father/test_check_completion.py`**：
- `test_max_rounds_protection`：`assert result == {}` → `assert "sub_queries" in result`，并验证 failed 状态在返回值的 `sub_queries` 中
- `test_cycle_detection`：同上
- `test_orphaned_query_detection`：同上

**`src/tests/unit/nl2sql_father/test_inject_params.py`**：
- 所有用例：新增 `assert "sub_queries" in result` 断言，验证返回值包含原地修改后的 `sub_queries`

**`src/tests/unit/nl2sql_father/test_graph.py`**：
- `TestSQLGenWrapper` 中所有用例：新增 `assert "sub_queries" in result` 断言（含异常路径 `test_wrapper_exception_handling`）

### 5.2 新增单元测试（覆盖高风险路径）

1. **`test_sql_execution.py` — Complex Path 多轮循环结果拼接**：
   - 构造 state 中 `execution_results` 已有第 1 轮的结果（模拟循环第 2 次进入 `sql_exec`）
   - 执行节点后验证返回值是 `existing + new`，而非仅 `new`

2. **`test_sql_execution.py` — 早返回路径保留结果**：
   - 构造 state 中 `execution_results` 已有结果，但 `sub_queries` 全部已执行完（`sqls_to_execute` 为空）
   - 执行节点后验证 `result["execution_results"]` 等于已有结果，而非 `[]`

3. **`test_check_completion.py` — 返回值包含原地修改**：
   - 触发最大轮次保护，验证 `result["sub_queries"]` 中对应子查询的 `status == "failed"`

### 5.3 端到端验证

1. **多轮对话瘦身验证**：在 CLI 中使用同一个 `thread_id` 连续提问 3 次，然后通过以下方式之一验证瘦身效果：
   - **方式 A（推荐，通过 API）**：调用 `checkpointer.get_tuple(config)` 获取最新 checkpoint，检查其 `channel_values` 中的 `execution_results` 是否只包含第 3 次提问的结果。
   - **方式 B（通过 SQL）**：`execution_results` 等非原始类型值会被 `PostgresSaver` 剥离到 `checkpoint_blobs` 表（而非 `checkpoints.checkpoint` JSONB 字段）。需联查 `checkpoints` 的 `channel_versions` 与 `checkpoint_blobs` 来验证。
   - 无论哪种方式，若第 3 次提问后的 `execution_results` 不包含前 2 次的结果，即代表瘦身策略生效。

2. **复杂路径循环验证**：发起一个需要拆分出 3 个子查询（含依赖链）的 Complex 问题，验证 `sql_execution.py` 的手动列表拼接是否成功。确保最后一个子查询可以正确拿到前序子查询的执行结果。