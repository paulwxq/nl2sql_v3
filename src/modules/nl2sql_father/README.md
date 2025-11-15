# NL2SQL 父图模块 (Phase 1: Fast Path)

NL2SQL 父图是整个 NL2SQL 系统的顶层编排器，负责将用户的自然语言问题转换为 SQL 查询并执行，最终返回自然语言总结。

## 功能概述

Phase 1 实现了 **Fast Path**（快速路径），用于处理简单问题（可用一条 SQL 完成的问题）。

### 核心流程

```
START → Router → Simple Planner → SQL Generation → SQL Execution → Summarizer → END
```

### 节点职责

1. **Router**: 判定问题复杂度（simple/complex）
2. **Simple Planner**: 为 Fast Path 准备参数（纯函数，<1ms）
3. **SQL Generation Wrapper**: 调用 SQL 生成子图
4. **SQL Execution**: 执行验证通过的 SQL
5. **Summarizer**: 构建用户友好的响应

## 快速开始

### 基础使用

```python
from src.modules.nl2sql_father.graph import run_nl2sql_query

# 执行查询
result = run_nl2sql_query("查询2024年的销售额")

# 访问结果
print(result["summary"])        # 自然语言总结
print(result["sql"])            # 执行的 SQL（快捷访问）
print(result["execution_results"])  # 完整执行结果
```

### 自定义 query_id

```python
result = run_nl2sql_query(
    query="查询销售额",
    query_id="custom-query-001"
)
```

## 返回结果结构

```python
{
    "user_query": "查询2024年的销售额",          # 用户原始问题
    "query_id": "q_abc123",                    # 查询ID
    "complexity": "simple",                     # 问题复杂度
    "path_taken": "fast",                       # 执行路径
    "summary": "2024年的总销售额为15万元。",    # 自然语言总结
    "sql": "SELECT SUM(amount) ...",            # SQL快捷访问
    "sub_queries": [                           # 子查询列表
        {
            "sub_query_id": "q_abc123_sq1",
            "query": "查询2024年的销售额",
            "status": "completed",
            "validated_sql": "SELECT SUM...",
            "execution_result": {...},
            "iteration_count": 2
        }
    ],
    "execution_results": [                     # 执行结果列表
        {
            "sub_query_id": "q_abc123_sq1",
            "sql": "SELECT SUM...",
            "success": true,
            "columns": ["total_amount"],
            "rows": [[150000.00]],
            "row_count": 1,
            "execution_time_ms": 45.2
        }
    ],
    "metadata": {                              # 元数据
        "total_execution_time_ms": 1234.5,
        "router_latency_ms": 123.4
    }
}
```

## 配置

### 主配置文件

位置: `src/modules/nl2sql_father/config/nl2sql_father_graph.yaml`

```yaml
router:
  model: qwen-turbo          # 轻量模型（快速分类）
  temperature: 0
  timeout: 5
  default_on_error: complex  # 失败时默认复杂度

sql_execution:
  timeout_per_sql: 30        # 单条SQL超时
  max_concurrency: 1         # Phase 1: 串行执行
  log_sql: true              # 记录SQL日志

summarizer:
  model: qwen-plus           # 高质量模型（总结生成）
  temperature: 0.3
  timeout: 10
  max_rows_in_prompt: 10     # 提示词中最大行数
  use_template: false        # 是否使用模板（不调用LLM）
```

### 全局配置

位置: `src/configs/config.yaml`

```yaml
nl2sql_father:
  enabled: true
  father_graph_config_path: src/modules/nl2sql_father/config/nl2sql_father_graph.yaml
  total_timeout: 120
  fast_path_enabled: true
  complex_path_enabled: false  # Phase 2
```

## 技术架构

### State 管理

使用 TypedDict + Annotated Reducer 模式：

```python
class NL2SQLFatherState(TypedDict):
    user_query: str
    query_id: str
    sub_queries: Annotated[List[SubQueryInfo], add]  # Reducer: 累加
    execution_results: Annotated[List[SQLExecutionResult], add]
    ...
```

### Wrapper 模式

SQL 生成子图通过 Wrapper 调用，避免父图 State 污染：

```python
def sql_gen_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Wrapper: 数据转换 + 子图调用 + 异常兜底"""
    subgraph_output = run_sql_generation_subgraph(
        query=current_sub_query["query"],
        query_id=state["query_id"],
        user_query=state["user_query"],
        dependencies_results={},  # Fast Path 无依赖
        parse_hints=None
    )
    ...
```

### 条件边路由

```python
def route_by_complexity(state: NL2SQLFatherState) -> str:
    """Router 后路由: simple → simple_planner, complex → summarizer"""
    return "simple_planner" if state["complexity"] == "simple" else "summarizer"

def route_after_sql_gen(state: NL2SQLFatherState) -> str:
    """SQL生成后路由: 成功 → sql_exec, 失败 → summarizer"""
    return "sql_exec" if state.get("validated_sql") else "summarizer"
```

## 错误处理

### Summarizer 的 4 个场景

1. **场景 0**: Complex 问题暂不支持（Phase 1）
2. **场景 1**: SQL 生成失败 → 技术错误转换为友好提示
3. **场景 2**: SQL 执行失败 → 返回错误汇总
4. **场景 3**: SQL 执行成功 → 生成自然语言总结

### 错误类型映射

```python
error_templates = {
    "parsing_failed": "抱歉，系统无法理解您的问题。建议您换一种方式描述...",
    "schema_retrieval_failed": "抱歉，系统暂时无法找到相关的数据表...",
    "generation_failed": "抱歉，系统在生成查询时遇到了问题...",
    "validation_failed": "抱歉，系统生成的查询存在问题，无法执行..."
}
```

## 测试

### 运行单元测试

```bash
uv run pytest src/tests/unit/nl2sql_father/ -v
```

70 个单元测试覆盖：
- Router 节点 (9 tests)
- Simple Planner 节点 (10 tests)
- SQL Execution 节点 (11 tests)
- Summarizer 节点 (18 tests)
- Graph 编译和 Wrapper (22 tests)

### 运行集成测试

```bash
uv run pytest src/tests/integration/nl2sql_father/ -v
```

10 个集成测试覆盖：
- Fast Path 端到端流程 (3 tests)
- Complex Path 流程 (1 test)
- 便捷函数完整性 (6 tests)

## 性能特点

- **Router 延迟**: ~100-200ms (qwen-turbo)
- **Simple Planner**: <1ms (纯函数)
- **SQL Generation**: 取决于子图性能
- **SQL Execution**: 取决于查询复杂度
- **Summarizer**: ~100-300ms (qwen-plus)

**总体 E2E 延迟**: 通常 1-3 秒（取决于 SQL 复杂度）

## Phase 2 预留

Phase 2 将支持 **Complex Path**（复杂路径），用于处理需要多步查询的复杂问题：

- ✅ State 已预留 `sub_queries` 列表（支持多子查询）
- ✅ SQL Execution 支持多 SQL 执行
- ✅ Summarizer 支持多结果总结
- ❌ Complex Planner 节点（待实现）
- ❌ 依赖解析与执行编排（待实现）

## 日志

使用结构化日志，支持 query_id 关联：

```python
query_logger = with_query_id(logger, query_id)
query_logger.info("Router 开始判定问题复杂度")
```

日志输出示例：
```
INFO nl2sql.router:router.py:65 [q_abc123] Router 开始判定问题复杂度
INFO nl2sql.router:router.py:122 [q_abc123] Router 判定完成: complexity=simple, latency=123.45ms
```

## 依赖

- LangGraph 1.0.x
- LangChain 1.0.x
- Python 3.12+
- PostgreSQL（用于 SQL 执行）
- Qwen API（Router 和 Summarizer）

## 许可

遵循项目主许可证。
