# MetaWeave LLM 异步调用改造方案

## 文档信息

- **版本**: v1.2
- **创建时间**: 2025-12-06
- **更新时间**: 2025-12-06
- **目标**: 在 MetaWeave 模块中引入 LLM 异步调用，提升关系发现和注释生成的效率
- **改造范围**: `src/metaweave` 模块（不涉及模块外代码）

---

## 0. 版本更新说明

### 0.1 v1.0 → v1.1 改进

**v1.0 存在的问题**：

| 问题 | 描述 | 影响 |
|------|------|------|
| **并发控制未执行** | `LLMRelationshipDiscovery._batch_call_llm_async` 没有使用 Semaphore | 78 个协程同时启动，可能触发 API 限流 |
| **内存爆炸风险** | 一次性为所有表对构建 prompt | 大规模场景（1000+ 表对）可能 OOM |
| **并发控制割裂** | `LLMService` 和 `LLMRelationshipDiscovery` 各自实现并发逻辑 | 违背统一抽象原则，难以维护 |

**v1.1 改进**：

| 改进点 | v1.0 | v1.1 |
|--------|------|------|
| **并发控制位置** | `LLMRelationshipDiscovery` 内部 | 集中在 `LLMService.batch_call_llm_async` |
| **Semaphore 使用** | ❌ 无 | ✅ 在 `LLMService` 内部强制执行 |
| **Prompt 构建** | 一次性构建所有 | 分批构建（`batch_size` 可配置） |
| **内存管理** | 无控制 | 每批处理完释放内存 |

### 0.2 v1.1 → v1.2 改进

**v1.1 存在的问题**：

| 问题 | 描述 | 影响 |
|------|------|------|
| **库层调用 asyncio.run()** | `discover()` 内部对每批次调用 `asyncio.run()` | 嵌入 asyncio 环境（notebook/异步服务）时抛出 `RuntimeError` |
| **进度日志过多** | 每次 LLM 调用完成都 `logger.info()` | 上千次调用产生大量日志，I/O 风暴 |
| **索引未被使用** | 用 `zip()` 而非返回的索引关联表对 | 若返回顺序改变，结果与表对错位 |

**v1.2 改进**：

| 改进点 | v1.1 | v1.2 |
|--------|------|------|
| **事件循环管理** | 库层调用 `asyncio.run()` | 提供 `discover_async()` 异步入口，CLI 层管理循环 |
| **进度日志** | 每次调用都 INFO | 节流：每批/每 N 次才 INFO，其余 DEBUG |
| **索引使用** | `zip(results, batch_pairs)` | `pair_by_idx[idx]` 正确映射 |
| **双入口** | 仅 `discover()` | `discover()` + `discover_async()` |

### 0.3 架构演进

**v1.0 架构**（有问题）：

```
LLMRelationshipDiscovery
    │
    ├── _call_llm_async()        # 单次调用
    │       │
    │       └── LLMService._call_llm_async()  # 无并发控制
    │
    └── _batch_call_llm_async()  # 自己管理协程
            │
            └── asyncio.as_completed()  # ❌ 无 Semaphore
```

**v1.2 架构**（最终版）：

```
CLI / Notebook / 异步服务
    │
    ├── discover()           # 同步入口（内部用 _run_async 安全处理）
    │       │
    │       └── _run_async() # 检测事件循环，安全调用
    │
    └── discover_async()     # 异步入口（直接 await）
            │
            └── _discover_llm_candidates_async()
                    │
                    ├── 分批循环（batch_size）
                    │
                    ├── 构建当前批次 prompts
                    │
                    ├── await LLMService.batch_call_llm_async()
                    │       │
                    │       └── asyncio.Semaphore ✅
                    │       └── asyncio.gather()
                    │
                    ├── 使用索引映射 pair_by_idx[idx] ✅
                    │
                    └── 释放内存，进度日志节流 ✅
```

---

## 1. 背景与目标

### 1.1 当前问题

**性能瓶颈**：
- 关系发现阶段：78 个表对组合需要 210 秒（串行调用）
- 注释生成阶段：N 个表需要 N×2 次 LLM 调用（表注释+字段注释）
- LLM 调用是 I/O 密集型任务，串行执行浪费大量等待时间

**当前实现**：
- `LLMService._call_llm()`: 使用 LangChain 的同步 `invoke()` 方法
- `LLMRelationshipDiscovery._call_llm()`: 循环串行调用
- `CommentGenerator`: 表级别串行处理

### 1.2 优化目标

**性能提升**：
- 关系发现：210秒 → 预期 20-30 秒（**7-10 倍提升**）
- 注释生成：N×2 秒 → 预期 N×2/并发数 秒

**保持兼容性**：
- 继续支持多个 LLM 提供商（Qwen, DeepSeek）
- 使用 LangChain 的统一抽象层（`ainvoke`）
- 不破坏现有的同步调用接口

### 1.3 测试验证结果

**性能测试**（78 个表对，真实 API 调用）：

| 实现方式 | 总耗时 | 平均耗时 | 成功率 |
|---------|--------|---------|--------|
| **当前（串行）** | 210 秒 | 2.7 秒/次 | - |
| **LangChain ainvoke** | **16.91 秒** | **0.22 秒/次** | 100% |
| DashScope AioGeneration | 38.54 秒 | 0.49 秒/次 | 100% |

**结论**：LangChain ainvoke 性能最优，比串行快 **12.4 倍**！

---

## 2. 架构设计

### 2.1 设计原则

1. **向后兼容**：保留同步接口，添加异步接口，调用方可选择
2. **配置驱动**：通过 `metadata_config.yaml` 控制是否启用异步
3. **统一抽象**：使用 LangChain，保持多提供商兼容性
4. **并发控制**：使用 `asyncio.Semaphore` 防止 API 限流
5. **集中控制**：并发控制逻辑集中在 `LLMService`，上层模块只负责业务逻辑
6. **内存安全**：分批构建 prompt，避免一次性占用大量内存

### 2.2 配置项设计

在 `metadata_config.yaml` 中已添加：

```yaml
llm:
  # LangChain 客户端配置（通用）
  langchain_config:
    use_async: true               # 是否使用异步 API (ainvoke)
    async_concurrency: 20         # 异步并发限制（建议 10-50，防止触发限流）
    max_retries: 3                # SDK 内部网络重试次数（覆盖默认值）
    batch_size: 50                # 分批构建 prompt 的批次大小（控制内存）
```

**字段说明**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `use_async` | bool | `false` | 全局开关，控制是否使用异步模式 |
| `async_concurrency` | int | `20` | 同时进行的 API 调用数量限制（Semaphore） |
| `max_retries` | int | `3` | LangChain 内部重试次数 |
| `batch_size` | int | `50` | 每批构建的 prompt 数量，用于控制内存 |

**配置项关系**：

```
batch_size = 50          # 每批构建 50 个 prompt
async_concurrency = 20   # 每批内最多同时执行 20 个 API 调用

对于 78 个表对：
- 第1批：构建 prompt 1-50，执行（最多20个并发），释放内存
- 第2批：构建 prompt 51-78，执行（最多20个并发），释放内存
```

---

## 3. 详细改造方案

### 3.1 模块1：LLMService 异步化

**文件**: `src/metaweave/services/llm_service.py`

#### 3.1.1 读取异步配置

在 `__init__` 方法中添加：

```python
def __init__(self, config: Dict[str, Any]):
    # ... 现有代码 ...
    
    # 读取 LangChain 异步配置
    langchain_config = config.get("langchain_config", {})
    self.use_async = langchain_config.get("use_async", False)
    self.async_concurrency = langchain_config.get("async_concurrency", 20)
    
    # 更新 max_retries（优先使用 langchain_config 中的配置）
    self.retry_times = langchain_config.get("max_retries", config.get("retry_times", 3))
    
    logger.info(
        f"LLM 服务已初始化: {self.provider_type} ({self.model}), "
        f"异步模式: {'启用' if self.use_async else '禁用'}, "
        f"并发限制: {self.async_concurrency}"
    )
```

#### 3.1.2 添加异步调用方法

**新增方法**：

```python
async def _call_llm_async(
    self, 
    prompt: str, 
    system_message: Optional[str] = None
) -> str:
    """异步调用 LLM（兼容所有提供商）
    
    Args:
        prompt: 用户提示词
        system_message: 系统消息（可选）
        
    Returns:
        LLM 响应文本
    """
    messages = []
    
    if system_message:
        messages.append(SystemMessage(content=system_message))
    
    messages.append(HumanMessage(content=prompt))
    
    try:
        # 使用 LangChain 的异步接口（兼容所有提供商）
        response = await self.llm.ainvoke(messages)
        return response.content
    except Exception as e:
        logger.error(f"异步调用 LLM 失败: {e}")
        raise
```

#### 3.1.3 添加批量异步调用方法

**新增方法**：

```python
async def batch_call_llm_async(
    self,
    prompts: List[str],
    system_message: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None
) -> List[Tuple[int, str]]:
    """批量异步调用 LLM（带并发控制）
    
    这是所有模块调用异步 LLM 的统一入口。并发控制（Semaphore）在此方法内部实现，
    调用方无需关心并发逻辑，只需传入 prompts 列表即可。
    
    Args:
        prompts: 提示词列表
        system_message: 系统消息（可选）
        on_progress: 进度回调函数 (completed, total)，可选
        
    Returns:
        List of (index, response) tuples，按原始顺序排列
        - index: 原始 prompts 中的索引
        - response: LLM 响应文本，失败时为空字符串
    """
    if not self.use_async:
        # 如果未启用异步，回退到同步逐个调用
        logger.warning("异步模式未启用，回退到同步调用")
        results = []
        for i, prompt in enumerate(prompts):
            try:
                response = self._call_llm(prompt, system_message)
                results.append((i, response))
            except Exception as e:
                logger.error(f"Prompt {i} 调用失败: {e}")
                results.append((i, ""))
            if on_progress:
                on_progress(i + 1, len(prompts))
        return results
    
    # ✅ 关键：使用 Semaphore 控制并发，防止 API 限流
    semaphore = asyncio.Semaphore(self.async_concurrency)
    total = len(prompts)
    completed = [0]  # 使用列表以便在闭包中修改
    
    async def bounded_call(index: int, prompt: str) -> Tuple[int, str]:
        """带并发控制的单次调用"""
        async with semaphore:  # ✅ 并发控制点
            try:
                response = await self._call_llm_async(prompt, system_message)
                return (index, response)
            except Exception as e:
                logger.error(f"Prompt {index} 调用失败: {e}")
                return (index, "")
            finally:
                completed[0] += 1
                if on_progress:
                    on_progress(completed[0], total)
    
    # 创建所有任务并并发执行
    tasks = [bounded_call(i, prompt) for i, prompt in enumerate(prompts)]
    results = await asyncio.gather(*tasks)
    
    # 按原始索引排序返回
    return sorted(results, key=lambda x: x[0])
```

**设计说明**：

| 设计点 | 说明 |
|--------|------|
| **Semaphore 位置** | 在 `bounded_call` 内部，确保只有获得信号量的协程才会执行 API 调用 |
| **返回格式** | `(index, response)` 元组，便于调用方关联请求和响应 |
| **进度回调** | 可选的 `on_progress` 参数，用于显示进度 |
| **异常隔离** | 单个调用失败不影响其他调用，返回空字符串 |

#### 3.1.4 保留现有同步接口

**不修改**：
- `_call_llm()`: 保持不变，供不需要异步的场景使用
- `generate_table_comment()`: 保持不变
- `generate_column_comments()`: 保持不变

**向后兼容性**：现有代码继续工作，不受影响。

---

### 3.2 模块2：LLMRelationshipDiscovery 异步化

**文件**: `src/metaweave/core/relationships/llm_relationship_discovery.py`

#### 3.2.1 设计改进说明

**原方案问题**（已修复）：

| 问题 | 原方案 | 改进后 |
|------|--------|--------|
| **并发未控制** | `_batch_call_llm_async` 无 Semaphore | 使用 `LLMService.batch_call_llm_async`（内置 Semaphore） |
| **内存爆炸** | 一次性构建所有 prompt | 分批构建，每批处理完释放内存 |
| **逻辑割裂** | 自己管理协程和并发 | 统一使用 `LLMService` 的批量接口 |

**改进后的架构**：

```
LLMRelationshipDiscovery                    LLMService
        │                                       │
        │  1. 准备表对数据                        │
        │  2. 分批构建 prompt                    │
        │                                       │
        ├──────────────────────────────────────►│
        │  调用 batch_call_llm_async(prompts)   │
        │                                       │
        │◄──────────────────────────────────────┤
        │  返回 [(index, response), ...]        │
        │                                       │
        │  3. 解析响应                           │
        │  4. 释放当前批次内存                    │
        │  5. 处理下一批...                      │
        ▼                                       ▼
```

#### 3.2.2 修改 `__init__` 方法

读取异步配置：

```python
def __init__(self, config: Dict, connector: DatabaseConnector):
    # ... 现有代码 ...
    
    # 读取异步配置（仅记录，实际控制在 LLMService）
    langchain_config = config.get("llm", {}).get("langchain_config", {})
    self.use_async = langchain_config.get("use_async", False)
    
    # 分批大小（控制内存，每批构建多少个 prompt）
    self.batch_size = langchain_config.get("batch_size", 50)
    
    logger.info(
        f"关系发现配置: use_async={self.use_async}, "
        f"batch_size={self.batch_size}"
    )
```

#### 3.2.3 添加 prompt 构建方法

**新增方法**（延迟构建 prompt，控制内存）：

```python
def _build_prompt(self, table1: Dict, table2: Dict) -> str:
    """构建 LLM prompt
    
    此方法应在需要时才调用，避免一次性构建所有 prompt 占用内存。
    
    Args:
        table1: 表1的元数据
        table2: 表2的元数据
        
    Returns:
        格式化后的 prompt 字符串
    """
    table1_info = table1.get("table_info", {})
    table2_info = table2.get("table_info", {})
    
    table1_name = f"{table1_info['schema_name']}.{table1_info['table_name']}"
    table2_name = f"{table2_info['schema_name']}.{table2_info['table_name']}"
    
    return RELATIONSHIP_DISCOVERY_PROMPT.format(
        table1_name=table1_name,
        table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
        table2_name=table2_name,
        table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
    )
```

#### 3.2.4 添加异步辅助方法

**关键设计**：库层不调用 `asyncio.run()`，由 CLI 层统一管理事件循环。

```python
async def _discover_llm_candidates_async(
    self,
    tables: Dict[str, Dict],
    table_pairs: List[Tuple[str, str]]
) -> List[Dict]:
    """异步发现 LLM 候选关系（内部方法）
    
    ⚠️ 此方法是 async 协程，不应直接调用 asyncio.run()。
    由 CLI 层或调用方负责管理事件循环。
    
    Args:
        tables: 所有表的元数据
        table_pairs: 表对列表
        
    Returns:
        所有候选关系的列表
    """
    total_pairs = len(table_pairs)
    llm_candidates = []
    
    # 进度日志节流：每批一次或每 N 次完成一次
    progress_step = max(1, total_pairs // 5)  # 最多 5 条进度日志
    
    # ✅ 分批处理，控制内存
    for batch_start in range(0, total_pairs, self.batch_size):
        batch_end = min(batch_start + self.batch_size, total_pairs)
        batch_pairs = table_pairs[batch_start:batch_end]
        batch_num = batch_start // self.batch_size + 1
        
        logger.info(f"处理批次 {batch_num}: 表对 {batch_start+1}-{batch_end}/{total_pairs}")
        
        # ✅ 仅为当前批次构建 prompt（控制内存）
        batch_prompts = [
            self._build_prompt(tables[t1], tables[t2])
            for t1, t2 in batch_pairs
        ]
        
        # ✅ 进度回调：节流日志输出
        def on_progress(completed, total):
            global_completed = batch_start + completed
            # 只在每 progress_step 次或批次完成时记录 INFO
            if completed == total or global_completed % progress_step == 0:
                logger.info(f"LLM 调用进度: {global_completed}/{total_pairs}")
            else:
                # 其他情况降级为 DEBUG
                logger.debug(f"LLM 调用完成: {global_completed}/{total_pairs}")
        
        # ✅ await 异步批量接口（不调用 asyncio.run）
        results = await self.llm_service.batch_call_llm_async(
            batch_prompts,
            on_progress=on_progress
        )
        
        # ✅ 使用索引正确关联表对（而非依赖顺序）
        pair_by_idx = dict(enumerate(batch_pairs))
        for idx, response in results:
            t1, t2 = pair_by_idx[idx]
            if response:  # 非空响应
                candidates = self._parse_llm_response(response)
                llm_candidates.extend(candidates)
            else:
                logger.warning(f"表对 {t1} <-> {t2} 无响应")
        
        # ✅ 释放当前批次的内存
        del batch_prompts
        del pair_by_idx
    
    return llm_candidates
```

#### 3.2.5 修改 `discover` 方法（同步入口）

**核心改动**：`discover()` 保持同步，通过辅助函数 `_run_async()` 处理事件循环。

```python
def _run_async(self, coro):
    """安全地运行异步协程
    
    检测当前是否已在事件循环中，避免 RuntimeError。
    如果已在循环中，抛出明确错误提示使用 discover_async()。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # ✅ get_running_loop() 抛出异常 = 没有运行中的循环
        # 安全使用 asyncio.run()
        return asyncio.run(coro)
    else:
        # ✅ get_running_loop() 成功 = 已在事件循环中
        # 抛出自定义异常（不会被上面的 except 捕获）
        raise RuntimeError(
            "检测到已存在运行中的事件循环。"
            "请改用 await discovery.discover_async() 或在 CLI 层调用 asyncio.run()。"
        )


def discover(self) -> Dict:
    """发现关联关系，返回 rel JSON 格式的结果（同步入口）
    
    注意：如果调用环境已在 asyncio 事件循环中（如 Jupyter notebook），
    请改用 await discover_async()。
    """
    import time
    start_time = time.time()
    
    # ... 阶段1-2 ...
    
    # 3. 调用 LLM（支持异步/同步）
    table_pairs = list(combinations(tables.keys(), 2))
    total_pairs = len(table_pairs)
    logger.info(f"共 {total_pairs} 个表对需要处理")
    
    if self.use_async:
        logger.info(f"阶段3: 异步并发调用 LLM (分批大小={self.batch_size})")
        
        # ✅ 调用异步辅助方法（事件循环在此处统一管理）
        llm_candidates = self._run_async(
            self._discover_llm_candidates_async(tables, table_pairs)
        )
    else:
        # 保留原有的同步实现
        logger.info("阶段3: 同步串行调用 LLM")
        llm_candidates = []
        
        for i, (table1_name, table2_name) in enumerate(table_pairs):
            candidates = self._call_llm(tables[table1_name], tables[table2_name])
            llm_candidates.extend(candidates)
            
            if (i + 1) % 10 == 0:
                logger.info(f"LLM 调用进度: {i+1}/{total_pairs}")
    
    logger.info(f"LLM 返回候选: {len(llm_candidates)} 个")
    
    # ... 阶段4-7 ...


async def discover_async(self) -> Dict:
    """发现关联关系（异步入口）
    
    供已在 asyncio 环境中的调用方使用（如 Jupyter notebook、异步 web 服务）。
    
    使用示例：
        # 在 Jupyter notebook 中
        result = await discovery.discover_async()
        
        # 或在异步函数中
        async def main():
            result = await discovery.discover_async()
    """
    # ... 阶段1-2 与同步版本相同 ...
    
    table_pairs = list(combinations(tables.keys(), 2))
    total_pairs = len(table_pairs)
    logger.info(f"共 {total_pairs} 个表对需要处理")
    
    if self.use_async:
        logger.info(f"阶段3: 异步并发调用 LLM (分批大小={self.batch_size})")
        llm_candidates = await self._discover_llm_candidates_async(tables, table_pairs)
    else:
        # 同步模式仍串行执行
        llm_candidates = []
        for i, (t1, t2) in enumerate(table_pairs):
            candidates = self._call_llm(tables[t1], tables[t2])
            llm_candidates.extend(candidates)
    
    # ... 阶段4-7 ...
```

#### 3.2.6 CLI 层调用方式

**推荐做法**：CLI 层统一管理事件循环。

```python
# src/metaweave/cli/metadata_cli.py

def run_rel_llm(config):
    """CLI 入口：运行关系发现"""
    discovery = LLMRelationshipDiscovery(config, connector)
    
    # ✅ 方式1：使用同步入口（内部自动处理事件循环）
    result = discovery.discover()
    
    # ✅ 方式2：显式管理事件循环（更推荐）
    # if discovery.use_async:
    #     result = asyncio.run(discovery.discover_async())
    # else:
    #     result = discovery.discover()
    
    return result
```

#### 3.2.7 移除的方法

**不再需要以下方法**（并发控制已移至 `LLMService`）：

- ~~`_call_llm_async()`~~：改用 `LLMService.batch_call_llm_async`
- ~~`_batch_call_llm_async()`~~：并发控制已集中在 `LLMService`

**保留的方法**：

- `_call_llm()`：同步调用，保留用于非异步模式
- `_parse_llm_response()`：解析 LLM 响应，保持不变

#### 3.2.8 设计优势

| 优势 | 说明 |
|------|------|
| **事件循环安全** | 库层不调用 `asyncio.run()`，可嵌入任意 asyncio 环境 |
| **双入口支持** | `discover()` 同步入口 + `discover_async()` 异步入口 |
| **并发控制集中** | Semaphore 在 `LLMService` 内部，所有模块自动受控 |
| **内存可控** | 每批 50 个 prompt（可配置），用完即释放 |
| **日志节流** | 进度日志降为每批/每 N 次，避免 I/O 风暴 |
| **索引正确** | 使用返回的索引定位表对，不依赖顺序 |
| **代码复用** | 未来 `CommentGenerator` 或其他模块可直接调用同一接口 |

---

### 3.3 模块3：CommentGenerator 异步化

**文件**: `src/metaweave/core/metadata/comment_generator.py`

#### 3.3.1 添加批量异步注释生成

CommentGenerator 的改造策略与 LLMRelationshipDiscovery 不同：

- **关系发现**：需要处理 78 个表对（独立任务），适合完全并发
- **注释生成**：在 MetadataGenerator 中已经用 ThreadPoolExecutor 并行处理表
  - 如果再在单表内部异步化，会导致两层并发（线程池 × asyncio）
  - 可能触发更严重的限流问题

**推荐策略**：

**方案A（推荐）**：保持 CommentGenerator 同步，由外层控制并发
- 优点：架构清晰，避免两层并发
- 缺点：单表的表注释+字段注释仍是串行

**方案B（激进）**：在 CommentGenerator 内部实现表级异步
- 为每个表创建异步任务（表注释 + 字段注释并发）
- 需要将 `enrich_metadata_with_comments` 改为异步方法
- 需要修改 MetadataGenerator 的调用方式

**建议**：采用方案A，因为：
1. 注释生成的并发需求远低于关系发现（13 张表 vs 78 个表对）
2. 当前的 ThreadPoolExecutor 已经提供了表级并发
3. 避免复杂的嵌套并发控制

如果未来需要优化，可以：
- 将 MetadataGenerator 改为 asyncio 模式
- 或者增加 ThreadPoolExecutor 的 max_workers

---

## 4. 实施步骤

### 阶段1：LLMService 改造（核心）

**文件**: `src/metaweave/services/llm_service.py`

**修改点**：
1. ✅ 在 `__init__` 中读取 `langchain_config` 配置
2. ✅ 添加 `_call_llm_async()` 方法（异步单次调用）
3. ✅ 添加 `batch_call_llm_async()` 方法（异步批量调用）
4. ✅ 添加必要的 import（`asyncio`）

**不修改**：
- ❌ 不修改现有的同步方法（`_call_llm`, `generate_table_comment`, `generate_column_comments`）
- ❌ 不修改 `_init_llm` 等初始化逻辑

### 阶段2：LLMRelationshipDiscovery 改造（高优先级）

**文件**: `src/metaweave/core/relationships/llm_relationship_discovery.py`

**修改点**：
1. ✅ 在 `__init__` 中读取异步配置（`use_async`, `batch_size`）
2. ✅ 添加 `_build_prompt()` 方法（延迟构建 prompt）
3. ✅ 添加 `_discover_llm_candidates_async()` 方法（异步内部实现）
4. ✅ 添加 `_run_async()` 方法（安全运行协程）
5. ✅ 修改 `discover()` 方法（同步入口，调用 `_run_async`）
6. ✅ 添加 `discover_async()` 方法（异步入口，供 notebook/异步服务使用）
7. ✅ 添加必要的 import（`asyncio`）

**不修改**：
- ❌ 保留原有的同步 `_call_llm()` 方法
- ❌ 不修改其他阶段的逻辑（评分、过滤、合并等）

**不再需要**（并发控制已移至 `LLMService`）：
- ~~`_call_llm_async()`~~：改用 `LLMService.batch_call_llm_async`
- ~~`_batch_call_llm_async()`~~：并发控制已集中在 `LLMService`

### 阶段3：配置文件更新（已完成）

**文件**: `configs/metaweave/metadata_config.yaml`

**已添加配置**：
```yaml
llm:
  langchain_config:
    use_async: true
    async_concurrency: 20
    max_retries: 3
    batch_size: 50
```

### 阶段4：测试验证

**测试文件**: `tests/test_llm_async_performance.py`（已完成）

**测试步骤**：
1. ✅ 完整测试：78 个表对，真实 API 调用
2. ✅ 对比 LangChain 和 DashScope 性能
3. ✅ 验证成功率和错误处理

**生产验证**：
1. 运行 `python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm`
2. 对比异步前后的总耗时
3. 验证输出结果的正确性（关系数量、内容一致性）

---

## 5. 代码修改清单

### 5.1 必须修改的文件

| 文件 | 修改类型 | 优先级 | 预计行数 |
|------|---------|--------|---------|
| `src/metaweave/services/llm_service.py` | 添加异步方法（含 Semaphore） | 🔴 高 | +70 |
| `src/metaweave/core/relationships/llm_relationship_discovery.py` | 分批构建 + 调用 LLMService | 🔴 高 | +50 |
| `configs/metaweave/metadata_config.yaml` | 添加 `batch_size` 配置 | ✅ 完成 | +1 |

### 5.2 不修改的文件

| 文件 | 原因 |
|------|------|
| `src/metaweave/core/metadata/comment_generator.py` | 保持同步，外层已有并发控制 |
| `src/metaweave/core/metadata/generator.py` | ThreadPoolExecutor 已提供并发 |
| `src/metaweave/cli/*.py` | CLI 层不需要感知异步 |

---

## 6. 性能预期

### 6.1 关系发现（rel_llm）

**场景**: 13 张表，78 个表对

| 指标 | 同步模式 | 异步模式 | 提升 |
|------|---------|---------|------|
| **总耗时** | 210 秒 | **~17 秒** | **12.4x** |
| **平均耗时** | 2.7 秒/次 | 0.22 秒/次 | 12.3x |
| **并发数** | 1 | 20 | - |

**预期收益**：
- 从 3.5 分钟 → 17 秒
- 对于 100 张表（4950 个表对）：从 3.7 小时 → 18 分钟

### 6.2 注释生成（json_llm）

**场景**: 13 张表，每表 2 次调用（表注释 + 字段注释）

| 指标 | 当前（ThreadPool） | 异步优化后 | 提升 |
|------|------------------|-----------|------|
| **总耗时** | ~26 次调用 / max_workers | ~26 次调用 / 1（全并发） | 小幅 |

**说明**：
- 注释生成已有 ThreadPoolExecutor 并发
- 异步优化的收益不大（除非并发数很大）
- **建议保持现状**，避免过度优化

---

## 7. 风险评估

### 7.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| **API 限流** | 高并发触发限流 | 配置合理的 `async_concurrency`（建议 10-20） |
| **内存占用** | 大量 prompt 占用内存 | 分批构建 prompt（`batch_size`），每批处理完释放 |
| **异常处理** | 某个任务失败影响整体 | 使用 `return_exceptions=True` 隔离异常 |
| **向后兼容** | 破坏现有代码 | 保留同步接口，异步通过配置启用 |
| **并发控制割裂** | 多模块重复实现 | 集中在 `LLMService.batch_call_llm_async` |
| **事件循环冲突** | 嵌入 asyncio 环境时失败 | 提供 `discover_async()` 入口，库层不调用 `asyncio.run()` |
| **日志风暴** | 大量调用产生过多日志 | 节流：每批/每 N 次才输出 INFO |

### 7.2 业务风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| **结果不一致** | 异步调用顺序变化导致结果不同 | 使用确定性的 relationship_id，结果与顺序无关 |
| **调试困难** | 异步代码调试复杂 | 添加详细日志，保留同步模式供对比 |

---

## 8. 配置说明

### 8.1 启用异步模式

在 `configs/metaweave/metadata_config.yaml` 中：

```yaml
llm:
  langchain_config:
    use_async: true               # 启用异步
    async_concurrency: 20         # 并发数（根据 API 限流调整）
    max_retries: 3                # 重试次数
    batch_size: 50                # 分批大小（控制内存）
```

### 8.2 禁用异步模式（回退）

```yaml
llm:
  langchain_config:
    use_async: false              # 禁用异步，回退到同步模式
```

### 8.3 调优建议

**并发数调优**（`async_concurrency`）：

| 场景 | 推荐并发数 | 说明 |
|------|-----------|------|
| **小规模**（<50次调用） | 10-15 | 保守，避免限流 |
| **中规模**（50-200次） | 15-25 | 平衡性能和稳定性 |
| **大规模**（>200次） | 20-30 | 激进，需监控失败率 |
| **测试环境** | 5-10 | 避免频繁触发限流 |

**批次大小调优**（`batch_size`）：

| 场景 | 推荐批次大小 | 说明 |
|------|-------------|------|
| **内存充足** | 100-200 | 减少批次切换开销 |
| **内存有限** | 30-50 | 避免内存溢出 |
| **超大规模**（>1000次） | 50-100 | 平衡内存和效率 |

**限流检测**：
- 如果失败率 > 5%，减少并发数
- 如果错误信息包含 "rate limit" 或 "too many requests"，减少并发数
- 如果内存占用过高，减少 `batch_size`

---

## 9. 测试计划

### 9.1 单元测试

**新增测试文件**: `tests/unit/metaweave/services/test_llm_service_async.py`

测试内容：
- ✅ `_call_llm_async()` 单次调用
- ✅ `batch_call_llm_async()` 批量调用
- ✅ 并发控制（Semaphore）
- ✅ 异常处理和重试

### 9.2 集成测试

**已完成**: `tests/test_llm_async_performance.py`

测试结果：
- ✅ LangChain ainvoke: 16.91 秒, 100% 成功率
- ✅ DashScope AioGeneration: 38.54 秒, 100% 成功率
- ✅ 性能提升：12.4 倍

### 9.3 生产验证

**步骤**：
1. 备份当前输出结果
2. 启用异步模式，运行 `--step rel_llm`
3. 对比输出文件 `relationships_global.json`
4. 验证关系数量和内容一致
5. 对比总耗时

**验收标准**：
- ✅ 关系数量一致
- ✅ 关系内容一致（relationship_id, from/to, columns）
- ✅ 总耗时减少 > 80%
- ✅ 成功率 > 95%

---

## 10. 实施检查清单

### 阶段1：代码修改

- [ ] 修改 `src/metaweave/services/llm_service.py`
  - [ ] 读取 `langchain_config` 配置（`use_async`, `async_concurrency`）
  - [ ] 添加 `_call_llm_async()` 方法（异步单次调用）
  - [ ] 添加 `batch_call_llm_async()` 方法（带 Semaphore 的批量接口）
  - [ ] 添加必要的 import（`asyncio`, `Callable`, `Tuple`）

- [ ] 修改 `src/metaweave/core/relationships/llm_relationship_discovery.py`
  - [ ] 读取异步配置（`use_async`, `batch_size`）
  - [ ] 添加 `_build_prompt()` 方法（延迟构建 prompt）
  - [ ] 添加 `_discover_llm_candidates_async()` 方法（异步内部实现）
  - [ ] 添加 `_run_async()` 方法（安全运行协程，检测事件循环）
  - [ ] 修改 `discover()` 方法（同步入口）
  - [ ] 添加 `discover_async()` 方法（异步入口）
  - [ ] 添加必要的 import（`asyncio`）

### 阶段2：测试验证

- [x] 创建性能测试程序 `tests/test_llm_async_performance.py`
- [x] 验证 LangChain ainvoke 性能
- [ ] 运行生产环境测试（`--step rel_llm`）
- [ ] 对比输出结果一致性
- [ ] 记录性能提升数据

### 阶段3：文档更新

- [x] 创建本修改方案文档
- [ ] 更新 `src/metaweave/README.md`（添加异步使用说明）
- [ ] 更新配置文件注释（说明异步参数）

### 阶段4：部署上线

- [ ] Code Review
- [ ] Merge 到主分支
- [ ] 更新部署文档

---

## 11. 回滚方案

如果异步模式出现问题，可以快速回滚：

### 方式1：配置回滚（推荐）

```yaml
llm:
  langchain_config:
    use_async: false  # 改为 false
```

无需修改代码，立即生效。

### 方式2：代码回滚

如果代码有 bug，回滚到改造前的版本：

```bash
git revert <commit_hash>
```

### 方式3：临时禁用

如果只是特定表出问题，可以：
- 使用同步模式处理问题表
- 其他表继续使用异步模式

---

## 12. 后续优化方向

### 12.1 短期（1-2 个版本）

1. **监控和调优**：
   - 收集生产环境的并发数据
   - 根据失败率动态调整 `async_concurrency`

2. **错误重试优化**：
   - 在批量调用层面实现智能重试
   - 失败的任务单独重试，不影响成功的任务

### 12.2 长期（3+ 个版本）

1. **全面异步化**：
   - 将 MetadataGenerator 改为 asyncio 模式
   - CommentGenerator 支持异步批量注释

2. **流式处理**：
   - 使用 LLM 的流式输出（streaming）
   - 提前开始解析，减少等待时间

3. **智能批处理**：
   - 相似的表对合并为一个请求
   - 减少 API 调用次数

---

## 13. 参考文档

### 13.1 内部文档

- `docs/gen_rag/2.数据库元数据生成模块设计.md`: 元数据生成模块设计
- `src/metaweave/README.md`: MetaWeave 模块说明
- `tests/README_ASYNC_PERFORMANCE.md`: 异步性能测试说明

### 13.2 外部文档

- [LangChain 异步支持文档](https://python.langchain.com/docs/how_to/chat_models_universal_init)
- [Python asyncio 官方文档](https://docs.python.org/3/library/asyncio.html)
- [DashScope SDK 文档](https://help.aliyun.com/zh/dashscope/developer-reference/api-details)

---

## 14. 附录

### 14.1 性能测试原始数据

**测试环境**：
- 机器：Windows 10
- Python：3.11
- 模型：qwen-plus
- 网络：家庭宽带

**测试1: LangChain ainvoke**（完全并发，无 Semaphore）
```
总耗时: 16.91 秒
成功调用: 78 / 78 (100.0%)
平均耗时: 0.22 秒/次
```

**测试2: DashScope AioGeneration**（完全并发，无 Semaphore）
```
总耗时: 38.54 秒
成功调用: 78 / 78 (100.0%)
平均耗时: 0.49 秒/次
```

**结论**: LangChain ainvoke 比 DashScope 原生 API 快 **2.28 倍**

### 14.2 关键代码示例

**LangChain 异步调用**：
```python
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import HumanMessage

llm = ChatTongyi(model='qwen-plus', dashscope_api_key='...')
messages = [HumanMessage(content=prompt)]
response = await llm.ainvoke(messages)
```

**DashScope 异步调用**：
```python
from dashscope import AioGeneration

response = await AioGeneration.call(
    model='qwen-plus',
    prompt=prompt,
    api_key='...'
)
```

### 14.3 FAQ

**Q1: 为什么 LangChain 比 DashScope 原生 API 更快？**

A: 可能的原因：
1. LangChain 使用了更优化的 HTTP 客户端（如 httpx with connection pooling）
2. LangChain 可能使用了不同的 API 端点
3. DashScope SDK 内部可能有额外的处理逻辑

**Q2: 异步模式是否适用于所有场景？**

A: 适用于：
- ✅ 大量独立的 LLM 调用（关系发现：78 个表对）
- ✅ I/O 密集型任务

不适用于：
- ❌ 单次调用（无并发收益）
- ❌ 已经有外层并发控制的场景（避免两层并发）

**Q3: 如果触发 API 限流怎么办？**

A: 调整配置：
```yaml
async_concurrency: 10  # 从 20 降低到 10
```

或者禁用异步：
```yaml
use_async: false  # 回退到同步模式
```

**Q4: 异步模式是否影响结果的确定性？**

A: 不影响：
- relationship_id 的生成是确定性的（基于表名和列名的哈希）
- 关系的顺序可能变化，但内容完全一致
- JSON 输出时可以按 relationship_id 排序，保证一致性

**Q5: 为什么要分批构建 prompt 而不是一次性构建？**

A: 内存控制：
- 每个 prompt 可能包含完整的表 JSON（几 KB 到几十 KB）
- 100 张表有 4950 个表对，一次性构建可能占用 GB 级内存
- 分批构建 + 及时释放，内存峰值可控

示例计算：
```
假设每个 prompt 约 10KB
4950 个表对 × 10KB = 约 50MB（一次性构建）
50 个表对 × 10KB = 约 500KB（分批构建，峰值）
```

**Q6: `async_concurrency` 和 `batch_size` 有什么区别？**

A: 两者控制不同维度：

| 参数 | 控制对象 | 目的 |
|------|---------|------|
| `async_concurrency` | 同时进行的 API 调用数 | 防止 API 限流 |
| `batch_size` | 每批构建的 prompt 数 | 控制内存占用 |

工作流程：
```
batch_size=50, async_concurrency=20

批次1: 构建 50 个 prompt → 最多 20 个同时调用 → 释放内存
批次2: 构建 50 个 prompt → 最多 20 个同时调用 → 释放内存
...
```

**Q7: 为什么并发控制要集中在 `LLMService`？**

A: 统一抽象的优势：
1. **一处修改，全局生效**：调整 `async_concurrency` 自动影响所有调用方
2. **避免重复实现**：`LLMRelationshipDiscovery`、`CommentGenerator` 等共用同一接口
3. **易于测试**：只需测试 `LLMService` 的并发控制逻辑
4. **符合单一职责**：业务模块专注业务，`LLMService` 专注 LLM 调用

**Q8: 为什么库层不能直接调用 `asyncio.run()`？**

A: 事件循环冲突：
```python
# 场景1：在 Jupyter notebook 中使用
# notebook 本身已有事件循环
await discovery.discover_async()  # ✅ 正确

# 场景2：在异步 web 服务中使用
async def handle_request():
    result = await discovery.discover_async()  # ✅ 正确

# 错误做法：库内部调用 asyncio.run()
def discover():
    asyncio.run(...)  # ❌ RuntimeError: cannot be called from a running event loop
```

解决方案：
- 提供 `discover()` 同步入口（内部检测事件循环）
- 提供 `discover_async()` 异步入口（直接 await）
- CLI 层统一管理事件循环

**Q9: 为什么要节流进度日志？**

A: 避免 I/O 风暴：
```
# 不节流：1000 次调用 = 1000 条 INFO 日志
LLM 调用进度: 1/1000
LLM 调用进度: 2/1000
...
LLM 调用进度: 1000/1000  # 严重影响性能，掩盖核心日志

# 节流后：最多 5 条 INFO + DEBUG（可配置）
LLM 调用进度: 200/1000
LLM 调用进度: 400/1000
LLM 调用进度: 600/1000
LLM 调用进度: 800/1000
LLM 调用进度: 1000/1000  # 清晰、可读
```

**Q10: 为什么要用索引而不是 zip？**

A: 保证正确性：
```python
# ❌ 依赖顺序（不安全）
for (idx, response), (t1, t2) in zip(results, batch_pairs):
    # 如果 results 返回顺序改变，t1/t2 就对应错了

# ✅ 使用索引（安全）
pair_by_idx = dict(enumerate(batch_pairs))
for idx, response in results:
    t1, t2 = pair_by_idx[idx]  # 永远正确
```

未来可能的变更：
- `batch_call_llm_async` 按完成顺序返回（减少排序开销）
- 返回 `(idx, response, error)` 三元组
- 任何这些变更都不会影响使用索引的代码

---

## 15. 总结

### 15.1 改造价值

**高价值改造**：
- ✅ 性能提升显著（12.4 倍）
- ✅ 实现成本低（~150 行代码）
- ✅ 风险可控（配置开关 + 向后兼容）
- ✅ 可扩展性好（适用于更大规模数据库）
- ✅ 内存安全（分批构建 + 及时释放）
- ✅ 统一抽象（并发控制集中在 `LLMService`）
- ✅ 事件循环安全（库层不调用 `asyncio.run()`）
- ✅ 双入口支持（同步 `discover()` + 异步 `discover_async()`）
- ✅ 日志可读（进度日志节流，避免 I/O 风暴）

### 15.2 推荐实施

**强烈推荐立即实施**，理由：
1. 测试已验证可行性和性能提升
2. 代码改动少，风险低
3. 向后兼容，可快速回滚
4. 对大规模数据库的支持至关重要

### 15.3 实施优先级

1. 🔴 **高优先级**：LLMRelationshipDiscovery 异步化
   - 性能瓶颈最明显（210秒 → 17秒）
   - 收益最大

2. 🟡 **中优先级**：LLMService 添加异步接口
   - 基础能力，支撑上层异步化

3. 🟢 **低优先级**：CommentGenerator 异步化
   - 当前已有 ThreadPool 并发
   - 收益相对较小

---

**文档结束**

如有疑问或需要调整方案，请联系开发团队。

