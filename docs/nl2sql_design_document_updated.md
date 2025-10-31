# NL2SQL 多步骤查询处理系统 - 概要设计文档

## 📋 文档信息

| 项目名称 | NL2SQL 多步骤查询处理系统 |
|---------|------------------------|
| 版本 | v3.0 整合版 |
| 文档类型 | 概要设计文档 |
| 创建日期 | 2025-10-31 |
| 技术栈 | Python 3.12, LangGraph v1.0+, Qwen/DeepSeek, PostgreSQL, pgvector, Neo4j |

---

## 1. 系统概述

### 1.1 项目背景

本系统旨在构建一个智能的自然语言到SQL（NL2SQL）查询处理系统，能够：
- 理解用户的自然语言查询意图
- 智能判断查询是否需要数据库支持
- 自动拆解复杂查询为多个子查询
- 并行执行SQL查询并聚合结果
- 在SQL失败时优雅降级到对话式回答

### 1.2 核心特性

| 特性 | 说明 |
|------|------|
| **智能路由** | 自动判断查询是否在数据库范围内，不在范围的直接路由到聊天Agent |
| **查询拆解** | 复杂查询自动拆分为多个简单子查询，支持依赖关系 |
| **统一架构** | 所有查询走相同流程，普通查询是复杂查询的特例（1个子查询） |
| **并行执行** | 无依赖的子查询可以批次并行执行，提升性能 |
| **多层降级** | SQL生成失败、SQL执行失败（可恢复）均可降级到聊天Agent |
| **错误透明** | 区分SQL质量问题和系统问题，明确返回错误信息 |

### 1.3 系统边界

**数据库范围**：
- 电商订单数据（2020-2025）
- 用户、商品、订单、销售、库存信息

**不在范围**：
- 天气、新闻等实时信息（通过web search获取）
- 概念解释、理论知识（通过LLM知识库回答）
- 未来预测、宏观分析（通过LLM分析能力回答）

---

## 2. 系统架构

### 2.1 整体架构图

```mermaid
graph TB
    subgraph "用户接口层"
        API[REST API / WebSocket]
    end
    
    subgraph "核心处理层"
        Orchestrator[LangGraph 流程编排器]
        Agent1[诊断和拆解Agent]
        Agent2[SQL生成Agent]
        Agent4[聊天Agent]
        Agent5[Summary Agent]
    end
    
    subgraph "工具层"
        SchemaRetrieval[Schema检索Tool]
        Validation[SQL验证Tool]
        Execution[SQL执行Tool]
        Aggregation[结果聚合Tool]
    end
    
    subgraph "数据层"
        DB[(业务数据库<br/>PostgreSQL)]
        VectorDB[(向量扩展<br/>pgvector)]
        GraphDB[(图数据库<br/>Neo4j)]
        Cache[(Redis缓存)]
    end
    
    subgraph "外部服务"
        LLM[LLM服务<br/>Qwen-Plus/DeepSeek]
        Search[Web Search<br/>DuckDuckGo]
    end
    
    API --> Orchestrator
    Orchestrator --> Agent1
    Orchestrator --> Agent2
    Orchestrator --> Agent4
    Orchestrator --> Agent5
    
    Agent1 --> LLM
    Agent2 --> LLM
    Agent4 --> LLM
    Agent4 --> Search
    Agent5 --> LLM
    
    Orchestrator --> SchemaRetrieval
    Orchestrator --> Validation
    Orchestrator --> Execution
    Orchestrator --> Aggregation
    
    SchemaRetrieval --> VectorDB
    SchemaRetrieval --> GraphDB
    Execution --> DB
    Orchestrator --> Cache
```

### 2.2 技术栈

| 层次 | 技术选型 | 说明 |
|------|---------|------|
| **编排框架** | LangGraph >= v1.0.0 | 状态机编排，支持子图、并行、条件路由 |
| **LLM** | Qwen-Plus / DeepSeek | 国产大模型，Agent推理和SQL生成 |
| **语言** | Python 3.12.x | 主要开发语言，支持最新语法特性 |
| **业务数据库** | PostgreSQL 16+ | 存储业务数据 |
| **向量数据库** | pgvector | PostgreSQL扩展，Schema和SQL示例向量检索 |
| **图数据库** | Neo4j | 存储表关系和JOIN路径 |
| **缓存** | Redis | 缓存查询结果和Schema |
| **Web Search** | DuckDuckGo API | 实时信息搜索 |
| **监控** | LangSmith | 链路追踪和性能监控 |

---

## 3. 核心组件设计

### 3.1 状态定义

系统使用LangGraph v1.0+的状态机模型，核心状态结构：

```python
from typing import Annotated
from langgraph.graph import MessagesState
from langgraph.managed import IsLastStep

# Python 3.12+ 使用 type 语句定义类型别名
type QueryID = str
type QueryStatus = "pending" | "ready" | "running" | "success" | "failed"
type RouteType = "sql" | "chat"

class MainState(MessagesState):
    """主流程状态 - 继承自LangGraph v1.0的MessagesState"""
    # 用户输入
    user_query: str
    user_id: str
    
    # 诊断结果
    in_database_scope: bool
    route_to: RouteType
    
    # 执行计划
    queries: list[dict]  # Python 3.12简化语法
    dependencies: dict[QueryID, list[QueryID]]
    
    # 执行状态
    query_status: dict[QueryID, QueryStatus]
    query_results: dict[QueryID, dict]
    current_batch: list[QueryID]
    
    # 最终输出
    final_result: dict | None
    error: str | None
    
    # 元信息
    iteration_count: int
    execution_time: float
    
    # LangGraph v1.0+ 特性
    is_last_step: IsLastStep

class SQLGenerationState(MessagesState):
    """SQL生成子图状态"""
    query: str
    query_id: QueryID
    dependencies_results: dict[QueryID, dict]
    schema_context: dict
    generated_sql: str
    validation_errors: list[str]
    iteration_count: int
    validated_sql: str | None
    error: str | None
```

### 3.2 Agent 设计

#### 3.2.1 Agent 1 - 诊断和拆解Agent

**职责**：
1. 判断查询是否在数据库范围内
2. 如果在范围内，拆解查询为多个子查询
3. 定义子查询的依赖关系

**输入输出**：

```python
# 输入
{
    "user_query": "对比2023和2024年Q1销售额，计算增长率"
}

# 输出
{
    "in_database_scope": true,
    "route_to": "sql",
    "queries": [
        {
            "query_id": "q1",
            "query": "查询2023年Q1销售额",
            "dependencies": []
        },
        {
            "query_id": "q2", 
            "query": "查询2024年Q1销售额",
            "dependencies": []
        },
        {
            "query_id": "q3",
            "query": "基于q1和q2的结果计算同比增长率",
            "dependencies": ["q1", "q2"]
        }
    ]
}
```

**Prompt 设计要点**：

```python
DIAGNOSE_AGENT_PROMPT = """
你是一个查询诊断和拆解Agent。

【第一步：判断数据库范围】
数据库覆盖范围：
- 电商订单数据（2020-2025年1月）
- 用户、商品、订单、销售、库存信息
- 不包括：天气、新闻、概念解释、行业分析

判断标准：
1. 明确涉及上述数据 → 在数据库范围内
2. 明确不涉及（天气、新闻、概念）→ 不在数据库范围内
3. 边界模糊但可能需要历史数据 → 在数据库范围内（先尝试）

【第二步：分析并拆解查询】（仅当在数据库范围内时）
- 普通查询：单个聚合/筛选 → 1个子查询
- 复杂查询：多时间段对比/多维度分析 → 多个子查询

拆分原则：
- 每个子查询独立可执行
- 明确标注依赖关系
- 按批次并行执行

输出格式：JSON
...
"""
```

**实现框架**：

```python
from langchain_community.chat_models import ChatTongyi
from langgraph.graph import StateGraph

def create_diagnose_agent():
    """创建诊断和拆解Agent - 使用Qwen-Plus"""
    # 通义千问API（Qwen-Plus）
    llm = ChatTongyi(
        model="qwen-plus",
        temperature=0,
        api_key="your-dashscope-api-key"
    )
    
    def diagnose_node(state: MainState) -> MainState:
        """诊断和拆解节点"""
        from langchain_core.messages import SystemMessage, HumanMessage
        
        response = llm.invoke([
            SystemMessage(content=DIAGNOSE_AGENT_PROMPT),
            HumanMessage(content=state["user_query"])
        ])
        
        # 解析JSON输出
        import json
        result = json.loads(response.content)
        
        return {
            **state,
            "in_database_scope": result["in_database_scope"],
            "route_to": result["route_to"],
            "queries": result.get("queries", [])
        }
    
    return diagnose_node
```

#### 3.2.2 Agent 2 - SQL生成Agent（在子图内）

**职责**：
- 基于Schema上下文生成单条SQL
- 考虑依赖子查询的结果
- 生成高质量、可执行的SQL

**输入输出**：

```python
# 输入
{
    "query": "查询2023年Q1销售额",
    "query_id": "q1",
    "schema_context": {
        "tables": ["orders", "order_items"],
        "columns": {...},
        "joins": {...},
        "examples": [...]
    },
    "dependencies_results": {}
}

# 输出
{
    "generated_sql": "SELECT SUM(amount) FROM orders WHERE ...",
    "validated_sql": "SELECT SUM(amount) FROM orders WHERE ..."  # 验证通过后
}
```

**Prompt 设计要点**：

```python
SQL_GENERATION_PROMPT = """
你是一个SQL生成专家。

【任务】：根据自然语言查询生成SQL

【Schema上下文】：
{schema_context}

【历史成功SQL示例】：
{examples}

【依赖查询结果】（如果有）：
{dependencies_results}

【要求】：
1. 生成标准的PostgreSQL语法
2. 使用合适的索引和JOIN策略
3. 添加必要的WHERE条件和聚合函数
4. 考虑性能优化
5. 只返回SQL，不要解释

【输出格式】：
纯SQL语句，不包含markdown标记
"""
```

#### 3.2.3 Agent 4 - 聊天Agent

**职责**：
- 处理不在数据库范围内的查询
- 自主决定是否需要web搜索
- 提供友好的自然语言回答

**实现框架（ReAct模式）**：

```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI  # DeepSeek兼容OpenAI API

@tool
def search_tool(query: str) -> str:
    """搜索网络获取最新信息"""
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=3))
    return format_search_results(results)

def create_chat_agent():
    """创建聊天Agent - 使用DeepSeek"""
    # DeepSeek使用OpenAI兼容接口
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key="your-deepseek-api-key",
        base_url="https://api.deepseek.com",
        temperature=0.7
    )
    
    # LangGraph v1.0+ 的 create_react_agent
    chat_agent = create_react_agent(
        model=llm,  # v1.0+ 参数名改为 model
        tools=[search_tool],
        state_schema=MainState,  # v1.0+ 显式指定state schema
        prompt="""
你是一个友好的助手。

当需要最新信息、实时数据时，使用search_tool。
当回答概念性问题、理论知识时，直接使用知识库。

自主决策示例：
- "什么是机器学习？" → 不搜索
- "今天北京天气？" → 调用search_tool
- "最新AI新闻？" → 调用search_tool
        """
    )
    
    return chat_agent
```

#### 3.2.4 Agent 5 - Summary Agent

**职责**：
- 格式化SQL执行结果
- 生成用户友好的摘要
- 支持图表、表格等多种展示形式

```python
SUMMARY_AGENT_PROMPT = """
你是一个数据分析师，负责将SQL查询结果转化为用户友好的回答。

【查询结果】：
{query_results}

【原始问题】：
{user_query}

【要求】：
1. 用自然语言描述结果
2. 突出关键数字和趋势
3. 必要时建议可视化方式
4. 保持简洁专业

【输出格式】：
{
    "summary": "文字摘要",
    "key_metrics": {...},
    "visualization_suggestion": "bar_chart/line_chart/table"
}
"""
```

### 3.3 Tool 设计

#### 3.3.1 Schema检索Tool

**职责**：
- 向量检索：找到语义相关的表、列
- 图检索：找到JOIN路径
- 历史SQL检索：找到类似的成功案例

**实现框架**：

```python
from pgvector.psycopg import register_vector
import psycopg

class SchemaRetrievalTool:
    def __init__(self, db_config: dict, graph_db, sql_cache):
        # PostgreSQL连接（包含pgvector扩展）
        self.conn = psycopg.connect(**db_config)
        register_vector(self.conn)  # 注册pgvector类型
        
        self.graph_db = graph_db    # Neo4j
        self.sql_cache = sql_cache  # Redis
        self.embedding_model = self._init_embedding_model()
    
    def _init_embedding_model(self):
        """初始化嵌入模型 - 使用Qwen Embedding"""
        from langchain_community.embeddings import DashScopeEmbeddings
        return DashScopeEmbeddings(
            model="text-embedding-v2",
            dashscope_api_key="your-api-key"
        )
    
    def retrieve_schema(self, query: str, top_k: int = 5) -> dict:
        """检索相关Schema信息"""
        
        # 1. 向量检索：使用pgvector检索相关表和列
        query_embedding = self.embedding_model.embed_query(query)
        
        with self.conn.cursor() as cur:
            # pgvector的向量相似度搜索
            cur.execute("""
                SELECT 
                    table_name,
                    column_name,
                    column_type,
                    description,
                    1 - (embedding <=> %s::vector) as similarity
                FROM schema_embeddings
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, top_k))
            
            tables_columns = [
                {
                    "table": row[0],
                    "column": row[1],
                    "type": row[2],
                    "description": row[3],
                    "similarity": row[4]
                }
                for row in cur.fetchall()
            ]
        
        # 2. 图检索：JOIN路径（Neo4j）
        unique_tables = list(set(tc["table"] for tc in tables_columns))
        join_paths = self.graph_db.query(
            """
            MATCH path = (t1:Table)-[:JOINS*1..3]-(t2:Table)
            WHERE t1.name IN $tables AND t2.name IN $tables
            RETURN path
            """,
            tables=unique_tables
        )
        
        # 3. 历史SQL检索（使用Redis + pgvector）
        similar_sqls = self._search_similar_sqls(query_embedding, top_k=3)
        
        return {
            "tables": tables_columns,
            "join_paths": join_paths,
            "examples": similar_sqls,
            "metadata": {
                "retrieval_time": __import__("time").time()
            }
        }
    
    def _search_similar_sqls(self, query_embedding: list[float], top_k: int) -> list[dict]:
        """从历史SQL库中检索相似案例"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    sql_text,
                    query_text,
                    success_count,
                    1 - (embedding <=> %s::vector) as similarity
                FROM sql_history
                WHERE success_count > 0
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, top_k))
            
            return [
                {
                    "sql": row[0],
                    "query": row[1],
                    "success_count": row[2],
                    "similarity": row[3]
                }
                for row in cur.fetchall()
            ]
```

#### 3.3.2 SQL验证Tool

**职责**：三层验证确保SQL质量和安全

```python
class SQLValidationTool:
    def validate(self, sql: str) -> Dict[str, any]:
        """三层验证SQL"""
        errors = []
        
        # 第1层：语法检查
        syntax_errors = self._check_syntax(sql)
        if syntax_errors:
            errors.extend(syntax_errors)
            return {"valid": False, "errors": errors, "layer": "syntax"}
        
        # 第2层：安全验证
        security_errors = self._check_security(sql)
        if security_errors:
            errors.extend(security_errors)
            return {"valid": False, "errors": errors, "layer": "security"}
        
        # 第3层：语义验证
        semantic_errors = self._check_semantics(sql)
        if semantic_errors:
            errors.extend(semantic_errors)
            return {"valid": False, "errors": errors, "layer": "semantic"}
        
        return {"valid": True, "errors": [], "layer": "all_passed"}
    
    def _check_syntax(self, sql: str) -> List[str]:
        """语法检查：使用sqlparse"""
        try:
            parsed = sqlparse.parse(sql)
            if not parsed:
                return ["SQL解析失败"]
            return []
        except Exception as e:
            return [f"语法错误: {str(e)}"]
    
    def _check_security(self, sql: str) -> List[str]:
        """安全检查：防SQL注入、限制危险操作"""
        errors = []
        
        # 禁止的操作
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE"]
        sql_upper = sql.upper()
        
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                errors.append(f"禁止使用 {keyword} 操作")
        
        # 必须有WHERE或LIMIT（防止全表扫描）
        if "SELECT" in sql_upper and "WHERE" not in sql_upper and "LIMIT" not in sql_upper:
            errors.append("查询必须包含WHERE或LIMIT子句")
        
        return errors
    
    def _check_semantics(self, sql: str) -> List[str]:
        """语义验证：表/列存在性、JOIN合理性"""
        errors = []
        
        # 使用EXPLAIN检查查询计划（不实际执行）
        try:
            explain_result = self.db.execute(f"EXPLAIN {sql}")
            # 分析查询计划，检测潜在问题
            if "Seq Scan" in explain_result and "large_table" in sql:
                errors.append("警告：大表全表扫描，建议添加索引")
        except Exception as e:
            errors.append(f"语义错误: {str(e)}")
        
        return errors
```

#### 3.3.3 SQL执行Tool

**职责**：
- 执行SQL查询（只读）
- 超时控制
- 结果格式化

```python
class SQLExecutionTool:
    def __init__(self, db_config, timeout=30):
        self.db = Database(db_config)
        self.timeout = timeout
    
    def execute(self, sql: str) -> Dict:
        """执行SQL并返回结果"""
        try:
            # 只读用户执行
            result = self.db.execute_readonly(
                sql=sql,
                timeout=self.timeout
            )
            
            return {
                "success": True,
                "data": result.to_dict(),
                "rows": len(result),
                "execution_time": result.execution_time
            }
            
        except Exception as e:
            # 错误分类
            error_type = self._classify_error(e)
            
            return {
                "success": False,
                "error_type": error_type,
                "error_message": str(e),
                "recoverable": error_type in ["table_not_found", "column_not_found", "out_of_range"]
            }
    
    def _classify_error(self, error: Exception) -> str:
        """分类执行错误"""
        error_msg = str(error).lower()
        
        # 可恢复错误
        if "does not exist" in error_msg or "unknown" in error_msg:
            return "table_not_found" if "table" in error_msg else "column_not_found"
        if "out of range" in error_msg or "invalid date" in error_msg:
            return "out_of_range"
        
        # 不可恢复错误（系统问题）
        if "connection" in error_msg or "timeout" in error_msg:
            return "connection_error"
        if "permission denied" in error_msg or "access denied" in error_msg:
            return "permission_error"
        
        return "unknown_error"
```

#### 3.3.4 查找批次Tool

**职责**：
- 分析依赖关系
- 找出当前可执行的子查询批次

```python
def find_current_batch(state: MainState) -> List[str]:
    """找出依赖已满足的子查询"""
    current_batch = []
    
    for query in state["queries"]:
        query_id = query["query_id"]
        
        # 跳过已完成或正在执行的
        if state["query_status"][query_id] in ["success", "running"]:
            continue
        
        # 检查依赖是否都完成
        dependencies = state["dependencies"][query_id]
        all_deps_done = all(
            state["query_status"].get(dep_id) == "success"
            for dep_id in dependencies
        )
        
        if all_deps_done:
            current_batch.append(query_id)
    
    return current_batch
```

#### 3.3.5 结果聚合Tool

**职责**：
- 根据执行计划聚合结果
- 支持JOIN、UNION、自定义聚合

```python
class ResultAggregationTool:
    def aggregate(self, queries: List[Dict], results: Dict) -> Dict:
        """聚合多个子查询的结果"""
        
        # 如果只有1个查询，直接返回
        if len(queries) == 1:
            return results[queries[0]["query_id"]]
        
        # 检查是否需要聚合
        final_query = self._find_final_query(queries)
        
        if final_query:
            # 最后一个查询依赖所有前面的，直接返回它的结果
            return results[final_query["query_id"]]
        else:
            # 需要自定义聚合（JOIN/UNION）
            return self._custom_aggregate(queries, results)
    
    def _find_final_query(self, queries: List[Dict]) -> Optional[Dict]:
        """找到最终的聚合查询"""
        for query in queries:
            # 如果这个查询依赖其他所有查询，它就是最终查询
            if len(query["dependencies"]) == len(queries) - 1:
                return query
        return None
    
    def _custom_aggregate(self, queries: List[Dict], results: Dict) -> Dict:
        """自定义聚合逻辑"""
        # 根据查询类型决定聚合方式
        # 例如：时间序列合并、多维度JOIN等
        aggregated_data = []
        
        for query in queries:
            query_result = results[query["query_id"]]
            aggregated_data.append(query_result["data"])
        
        return {
            "data": aggregated_data,
            "aggregation_type": "list",
            "queries_count": len(queries)
        }
```

---

## 4. 主流程设计

### 4.1 LangGraph主图定义

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

def create_main_graph():
    """创建主流程图 - LangGraph v1.0+"""
    
    # 创建状态图
    workflow = StateGraph(MainState)
    
    # 添加节点
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("parse_plan", parse_execution_plan_node)
    workflow.add_node("find_batch", find_current_batch_node)
    workflow.add_node("generate_batch_sql", generate_batch_sql_node)
    workflow.add_node("execute_batch", execute_batch_sql_node)
    workflow.add_node("store_results", store_results_node)
    workflow.add_node("aggregate_results", aggregate_results_node)
    workflow.add_node("summary", summary_agent_node)
    workflow.add_node("chat", chat_agent_node)
    workflow.add_node("chat_fallback", chat_fallback_node)
    
    # v1.0+ 使用 START 常量替代 set_entry_point
    workflow.add_edge(START, "diagnose")
    
    # 条件路由：诊断后的路由决策
    workflow.add_conditional_edges(
        "diagnose",
        route_decision,
        {
            "sql": "parse_plan",
            "chat": "chat"
        }
    )
    
    # SQL流程的边
    workflow.add_edge("parse_plan", "find_batch")
    
    # 条件边：是否还有待处理的查询
    workflow.add_conditional_edges(
        "find_batch",
        check_has_queries,
        {
            "has_queries": "generate_batch_sql",
            "all_done": "aggregate_results"
        }
    )
    
    # 条件边：批次SQL生成是否成功
    workflow.add_conditional_edges(
        "generate_batch_sql",
        check_batch_success,
        {
            "success": "execute_batch",
            "failed": "chat_fallback"
        }
    )
    
    # 条件边：SQL执行结果检查
    workflow.add_conditional_edges(
        "execute_batch",
        check_execution_result,
        {
            "success": "store_results",
            "recoverable": "chat_fallback",
            "system_error": END
        }
    )
    
    workflow.add_edge("store_results", "find_batch")  # 循环
    workflow.add_edge("aggregate_results", "summary")
    workflow.add_edge("summary", END)
    workflow.add_edge("chat", END)
    workflow.add_edge("chat_fallback", END)
    
    # v1.0+ 编译时可选添加checkpointer（支持持久化）
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
```

### 4.2 主流程图（Mermaid）

```mermaid
graph TB
    Start([用户输入]) --> Diagnose[诊断和拆解Agent]
    
    Diagnose --> RouteDecision{路由判断}
    
    RouteDecision -->|不在DB范围| Chat[聊天Agent]
    RouteDecision -->|在DB范围| ParsePlan[解析执行计划]
    
    ParsePlan --> FindBatch[查找当前批次]
    
    FindBatch --> HasQueries{有待处理?}
    
    HasQueries -->|否| Aggregate[结果聚合]
    HasQueries -->|是| GenBatch[批次SQL生成]
    
    GenBatch --> BatchOK{全部成功?}
    
    BatchOK -->|否| ChatFallback1[聊天Agent降级]
    BatchOK -->|是| ExecBatch[并行执行批次]
    
    ExecBatch --> ExecCheck{执行结果?}
    
    ExecCheck -->|成功| Store[存储结果]
    ExecCheck -->|可恢复错误| ChatFallback2[聊天Agent Fallback]
    ExecCheck -->|系统错误| SysError[返回系统错误]
    
    Store --> FindBatch
    
    Aggregate --> Summary[Summary Agent]
    
    Summary --> End([返回用户])
    Chat --> End
    ChatFallback1 --> End
    ChatFallback2 --> End
    SysError --> End
```

### 4.3 关键节点实现

#### 4.3.1 路由决策

```python
def route_decision(state: MainState) -> str:
    """根据诊断结果决定路由"""
    if state["route_to"] == "chat":
        return "chat"
    return "sql"
```

#### 4.3.2 批次SQL生成节点

```python
def generate_batch_sql_node(state: MainState) -> MainState:
    """为当前批次的每个子查询生成SQL"""
    batch_sqls = {}
    failed_queries = []
    
    for query_id in state["current_batch"]:
        # 找到对应的查询
        query_info = next(q for q in state["queries"] if q["query_id"] == query_id)
        
        # 获取依赖查询的结果
        dep_results = {
            dep_id: state["query_results"][dep_id]
            for dep_id in query_info["dependencies"]
        }
        
        # 调用SQL生成子图
        sql_result = sql_generation_subgraph.invoke({
            "query": query_info["query"],
            "query_id": query_id,
            "dependencies_results": dep_results
        })
        
        if sql_result.get("validated_sql"):
            batch_sqls[query_id] = sql_result["validated_sql"]
            state["query_status"][query_id] = "ready"
        else:
            failed_queries.append(query_id)
            state["query_status"][query_id] = "failed"
    
    state["batch_sqls"] = batch_sqls
    state["failed_queries"] = failed_queries
    
    return state
```

#### 4.3.3 并行执行批次SQL

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

def execute_batch_sql_node(state: MainState) -> MainState:
    """并行执行当前批次的所有SQL"""
    batch_sqls = state["batch_sqls"]
    
    # 并行执行
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            query_id: executor.submit(execution_tool.execute, sql)
            for query_id, sql in batch_sqls.items()
        }
        
        # 收集结果
        for query_id, future in futures.items():
            try:
                result = future.result(timeout=30)
                
                if result["success"]:
                    state["query_results"][query_id] = result["data"]
                    state["query_status"][query_id] = "success"
                else:
                    state["execution_error"] = result
                    state["query_status"][query_id] = "failed"
                    # 出现错误立即停止
                    break
            except Exception as e:
                state["execution_error"] = {
                    "error_type": "system_error",
                    "error_message": str(e),
                    "recoverable": False
                }
                break
    
    return state
```

#### 4.3.4 执行结果检查

```python
def check_execution_result(state: MainState) -> str:
    """检查SQL执行结果并决定下一步"""
    
    # 没有错误，成功
    if "execution_error" not in state:
        return "success"
    
    error = state["execution_error"]
    
    # 根据错误类型决定
    if error.get("recoverable"):
        # 可恢复错误：表不存在、字段不存在等
        return "recoverable"
    else:
        # 系统错误：连接失败、超时等
        return "system_error"
```

---

## 5. SQL生成子图设计

### 5.1 子图流程

```mermaid
graph TB
    SubStart([子图输入]) --> SchemaRetrieval[Schema检索]
    
    SchemaRetrieval --> SQLGen[SQL生成Agent]
    
    SQLGen --> Validation[三层验证]
    
    Validation --> Valid{验证通过?}
    
    Valid -->|是| SubSuccess([返回SQL])
    Valid -->|否| Retry{迭代<3次?}
    
    Retry -->|是| SQLGen
    Retry -->|否| SubFail([返回失败])
```

### 5.2 子图实现

```python
from langgraph.graph import StateGraph, START, END

def create_sql_generation_subgraph():
    """创建SQL生成子图 - LangGraph v1.0+"""
    
    subgraph = StateGraph(SQLGenerationState)
    
    # 添加节点
    subgraph.add_node("schema_retrieval", schema_retrieval_node)
    subgraph.add_node("sql_generation", sql_generation_node)
    subgraph.add_node("validation", validation_node)
    
    # v1.0+ 使用 START 常量
    subgraph.add_edge(START, "schema_retrieval")
    
    # 添加边
    subgraph.add_edge("schema_retrieval", "sql_generation")
    subgraph.add_edge("sql_generation", "validation")
    
    # 条件边：验证结果
    subgraph.add_conditional_edges(
        "validation",
        should_retry,
        {
            "retry": "sql_generation",
            "success": END,
            "fail": END
        }
    )
    
    return subgraph.compile()

def should_retry(state: SQLGenerationState) -> str:
    """判断是否应该重试"""
    if state.get("validated_sql"):
        return "success"
    
    if state["iteration_count"] < 3:
        return "retry"
    
    return "fail"
```

---

## 6. 错误处理策略

### 6.1 错误分类

| 错误类型 | 发生阶段 | 原因 | 处理方式 |
|---------|---------|------|---------|
| **SQL生成失败** | SQL生成子图 | LLM生成质量问题 | 子图内重试3次<br/>失败后降级到聊天Agent |
| **SQL验证失败** | SQL生成子图 | 语法/安全/语义错误 | 子图内重试3次<br/>失败后降级到聊天Agent |
| **可恢复执行错误** | SQL执行阶段 | 表/字段不存在<br/>数据超出范围 | Fallback到聊天Agent |
| **不可恢复执行错误** | SQL执行阶段 | 连接失败、超时<br/>权限不足 | 返回系统错误信息<br/>不降级 |

### 6.2 错误分类代码

```python
class ErrorClassifier:
    """错误分类器"""
    
    RECOVERABLE_PATTERNS = [
        "table does not exist",
        "column does not exist",
        "no such table",
        "no such column",
        "out of range",
        "invalid date"
    ]
    
    SYSTEM_ERROR_PATTERNS = [
        "connection refused",
        "connection timeout",
        "access denied",
        "permission denied",
        "out of memory",
        "too many connections",
        "execution timeout"
    ]
    
    @classmethod
    def classify(cls, error: Exception) -> Dict:
        """分类错误"""
        error_msg = str(error).lower()
        
        # 检查可恢复错误
        for pattern in cls.RECOVERABLE_PATTERNS:
            if pattern in error_msg:
                return {
                    "type": "recoverable",
                    "recoverable": True,
                    "fallback_to_chat": True,
                    "user_message": "抱歉，数据库中找不到相关信息，让我尝试用其他方式回答您。"
                }
        
        # 检查系统错误
        for pattern in cls.SYSTEM_ERROR_PATTERNS:
            if pattern in error_msg:
                return {
                    "type": "system_error",
                    "recoverable": False,
                    "fallback_to_chat": False,
                    "user_message": "抱歉，数据库暂时无法连接，请稍后重试。"
                }
        
        # 默认作为系统错误
        return {
            "type": "unknown",
            "recoverable": False,
            "fallback_to_chat": False,
            "user_message": "系统遇到未知错误，请联系管理员。"
        }
```

---

## 7. 数据流转

### 7.1 完整数据流示例

```
【输入】用户查询：
"对比2023和2024年Q1销售额，计算增长率"

↓

【步骤1】诊断和拆解Agent
输出：
{
  "in_database_scope": true,
  "route_to": "sql",
  "queries": [
    {"query_id": "q1", "query": "查询2023年Q1销售额", "dependencies": []},
    {"query_id": "q2", "query": "查询2024年Q1销售额", "dependencies": []},
    {"query_id": "q3", "query": "计算增长率", "dependencies": ["q1", "q2"]}
  ]
}

↓

【步骤2】解析执行计划
State初始化：
{
  "queries": [...],
  "query_status": {"q1": "pending", "q2": "pending", "q3": "pending"},
  "query_results": {},
  "dependencies": {"q1": [], "q2": [], "q3": ["q1", "q2"]}
}

↓

【步骤3】查找第一批次
current_batch = ["q1", "q2"]  # 无依赖，可并行

↓

【步骤4】批次SQL生成
- q1调用子图 → SQL1: "SELECT SUM(amount) FROM orders WHERE year=2023 AND quarter=1"
- q2调用子图 → SQL2: "SELECT SUM(amount) FROM orders WHERE year=2024 AND quarter=1"

↓

【步骤5】并行执行
结果：
- q1: {"amount": 1500000}
- q2: {"amount": 1800000}

↓

【步骤6】存储结果并更新状态
{
  "query_status": {"q1": "success", "q2": "success", "q3": "pending"},
  "query_results": {
    "q1": {"amount": 1500000},
    "q2": {"amount": 1800000}
  }
}

↓

【步骤7】查找第二批次
current_batch = ["q3"]  # q1、q2已完成

↓

【步骤8】生成q3的SQL（可使用q1、q2结果）
SQL3: 基于前两个结果计算增长率

↓

【步骤9】执行q3并存储

↓

【步骤10】结果聚合
最终结果 = q3的结果（已经包含完整分析）

↓

【步骤11】Summary Agent
输出：
{
  "summary": "2024年Q1销售额相比2023年Q1增长了20%，从150万增长到180万。",
  "key_metrics": {
    "2023_q1": 1500000,
    "2024_q1": 1800000,
    "growth_rate": 0.20
  },
  "visualization_suggestion": "bar_chart"
}
```

---

## 8. 接口设计

### 8.1 REST API

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class QueryRequest(BaseModel):
    query: str
    user_id: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    execution_time: float
    trace_id: str

@app.post("/api/v1/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """处理自然语言查询"""
    
    try:
        # 初始化状态
        initial_state = {
            "user_query": request.query,
            "user_id": request.user_id,
            "session_id": request.session_id or generate_session_id()
        }
        
        # 执行主流程图
        result = main_graph.invoke(initial_state)
        
        return QueryResponse(
            success=True,
            data=result.get("final_result"),
            execution_time=result.get("execution_time"),
            trace_id=result.get("trace_id")
        )
        
    except Exception as e:
        logger.error(f"Query processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 8.2 WebSocket (流式输出)

```python
from fastapi import WebSocket

@app.websocket("/ws/query")
async def websocket_query(websocket: WebSocket):
    """WebSocket端点，支持流式输出"""
    await websocket.accept()
    
    try:
        # 接收查询
        data = await websocket.receive_json()
        query = data["query"]
        
        # 发送状态更新
        await websocket.send_json({
            "type": "status",
            "message": "正在分析查询..."
        })
        
        # 执行流程，定期发送进度
        async for event in main_graph.astream({"user_query": query}):
            await websocket.send_json({
                "type": "progress",
                "event": event
            })
        
        # 发送最终结果
        await websocket.send_json({
            "type": "result",
            "data": result
        })
        
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        await websocket.close()
```

---

## 9. 性能优化

### 9.1 缓存策略

```python
class CacheManager:
    """多层缓存管理"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def cache_schema(self, table_name: str, schema: Dict, ttl: int = 3600):
        """缓存Schema信息"""
        key = f"schema:{table_name}"
        self.redis.setex(key, ttl, json.dumps(schema))
    
    def cache_query_result(self, query_hash: str, result: Dict, ttl: int = 300):
        """缓存查询结果"""
        key = f"query:{query_hash}"
        self.redis.setex(key, ttl, json.dumps(result))
    
    def get_cached_result(self, query: str) -> Optional[Dict]:
        """获取缓存的查询结果"""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        key = f"query:{query_hash}"
        
        cached = self.redis.get(key)
        return json.loads(cached) if cached else None
```

### 9.2 并行执行优化

```python
async def parallel_execute_sqls(sqls: List[str]) -> List[Dict]:
    """异步并行执行多个SQL"""
    
    async def execute_one(sql: str):
        """异步执行单个SQL"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,  # 使用默认executor
            execution_tool.execute,
            sql
        )
    
    # 并发执行
    tasks = [execute_one(sql) for sql in sqls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return results
```

### 9.3 Schema索引优化

```python
from langchain_community.embeddings import DashScopeEmbeddings
import psycopg

def build_schema_vector_index(db_config: dict):
    """构建Schema向量索引 - 使用pgvector"""
    
    # 初始化嵌入模型（使用通义千问）
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v2",
        dashscope_api_key="your-api-key"
    )
    
    conn = psycopg.connect(**db_config)
    
    # 1. 创建pgvector扩展和表
    with conn.cursor() as cur:
        # 创建扩展
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        
        # 创建schema embedding表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_embeddings (
                id SERIAL PRIMARY KEY,
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                column_type TEXT,
                description TEXT,
                embedding vector(1536),  -- text-embedding-v2的维度
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 创建向量索引（HNSW算法，性能更好）
        cur.execute("""
            CREATE INDEX IF NOT EXISTS schema_embeddings_idx 
            ON schema_embeddings 
            USING hnsw (embedding vector_cosine_ops)
        """)
        
        conn.commit()
    
    # 2. 收集所有表和列的描述并生成向量
    schema_docs = []
    for table in get_all_tables():
        for column in table.columns:
            text = f"{table.name} 表的 {column.name} 列，类型：{column.type}，描述：{column.description}"
            
            # 生成嵌入向量
            embedding = embeddings.embed_query(text)
            
            schema_docs.append({
                "table_name": table.name,
                "column_name": column.name,
                "column_type": column.type,
                "description": column.description,
                "embedding": embedding
            })
    
    # 3. 批量插入向量数据
    with conn.cursor() as cur:
        for doc in schema_docs:
            cur.execute("""
                INSERT INTO schema_embeddings 
                (table_name, column_name, column_type, description, embedding)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                doc["table_name"],
                doc["column_name"],
                doc["column_type"],
                doc["description"],
                doc["embedding"]
            ))
        
        conn.commit()
    
    conn.close()
    print(f"✅ 成功索引 {len(schema_docs)} 个schema项")
```

---

## 10. 监控和日志

### 10.1 LangSmith集成

```python
from langsmith import Client

langsmith_client = Client()

def trace_execution(func):
    """装饰器：追踪执行过程"""
    def wrapper(*args, **kwargs):
        run_id = str(uuid.uuid4())
        
        # 开始追踪
        langsmith_client.create_run(
            name=func.__name__,
            run_type="chain",
            inputs={"args": args, "kwargs": kwargs},
            run_id=run_id
        )
        
        try:
            result = func(*args, **kwargs)
            
            # 记录成功
            langsmith_client.update_run(
                run_id=run_id,
                outputs={"result": result},
                end_time=datetime.now()
            )
            
            return result
            
        except Exception as e:
            # 记录失败
            langsmith_client.update_run(
                run_id=run_id,
                error=str(e),
                end_time=datetime.now()
            )
            raise
    
    return wrapper
```

### 10.2 性能指标

```python
class MetricsCollector:
    """性能指标收集"""
    
    def __init__(self):
        self.metrics = {
            "total_queries": 0,
            "sql_route": 0,
            "chat_route": 0,
            "sql_success": 0,
            "sql_failed": 0,
            "fallback_count": 0,
            "avg_execution_time": 0,
            "avg_sql_generation_time": 0
        }
    
    def record_query(self, route: str, success: bool, execution_time: float):
        """记录查询指标"""
        self.metrics["total_queries"] += 1
        
        if route == "sql":
            self.metrics["sql_route"] += 1
            if success:
                self.metrics["sql_success"] += 1
            else:
                self.metrics["sql_failed"] += 1
        else:
            self.metrics["chat_route"] += 1
        
        # 更新平均执行时间
        self._update_avg("avg_execution_time", execution_time)
    
    def record_fallback(self, reason: str):
        """记录降级"""
        self.metrics["fallback_count"] += 1
        self.metrics[f"fallback_{reason}"] = self.metrics.get(f"fallback_{reason}", 0) + 1
```

---

## 11. 测试策略

### 11.1 单元测试

```python
import pytest

class TestDiagnoseAgent:
    """测试诊断和拆解Agent"""
    
    def test_in_database_scope(self):
        """测试数据库范围判断"""
        result = diagnose_agent.invoke({
            "user_query": "去年销售额是多少？"
        })
        assert result["in_database_scope"] == True
        assert result["route_to"] == "sql"
    
    def test_out_database_scope(self):
        """测试非数据库范围"""
        result = diagnose_agent.invoke({
            "user_query": "今天天气怎么样？"
        })
        assert result["in_database_scope"] == False
        assert result["route_to"] == "chat"
    
    def test_simple_query_decomposition(self):
        """测试简单查询拆解"""
        result = diagnose_agent.invoke({
            "user_query": "2024年总销售额"
        })
        assert len(result["queries"]) == 1
        assert result["queries"][0]["dependencies"] == []
    
    def test_complex_query_decomposition(self):
        """测试复杂查询拆解"""
        result = diagnose_agent.invoke({
            "user_query": "对比2023和2024年销售额，计算增长率"
        })
        assert len(result["queries"]) == 3
        assert result["queries"][2]["dependencies"] == ["q1", "q2"]
```

### 11.2 集成测试

```python
class TestMainWorkflow:
    """测试主流程"""
    
    @pytest.mark.asyncio
    async def test_simple_query_flow(self):
        """测试简单查询流程"""
        result = await main_graph.ainvoke({
            "user_query": "2024年总销售额"
        })
        
        assert result["final_result"] is not None
        assert "execution_time" in result
    
    @pytest.mark.asyncio
    async def test_complex_query_flow(self):
        """测试复杂查询流程"""
        result = await main_graph.ainvoke({
            "user_query": "对比各季度销售额"
        })
        
        # 验证执行了多个子查询
        assert len(result["query_results"]) > 1
        
        # 验证结果已聚合
        assert result["final_result"] is not None
    
    @pytest.mark.asyncio
    async def test_chat_route(self):
        """测试聊天路由"""
        result = await main_graph.ainvoke({
            "user_query": "什么是销售额？"
        })
        
        # 应该路由到聊天
        assert result["route_to"] == "chat"
```

### 11.3 测试用例库

```python
TEST_CASES = [
    # DB范围内 - 简单查询
    {
        "query": "去年销售额",
        "expected_route": "sql",
        "expected_subqueries": 1
    },
    
    # DB范围内 - 复杂查询
    {
        "query": "对比2023和2024年各季度销售额",
        "expected_route": "sql",
        "expected_subqueries": 5  # q1-q4 + 汇总
    },
    
    # DB范围外 - 概念解释
    {
        "query": "什么是转化率？",
        "expected_route": "chat",
        "expected_search": False
    },
    
    # DB范围外 - 实时信息
    {
        "query": "今天北京天气",
        "expected_route": "chat",
        "expected_search": True
    },
    
    # 边界情况
    {
        "query": "2030年销售预测",
        "expected_route": "sql",  # 先尝试SQL
        "expected_fallback": True  # 可能会fallback
    }
]
```

---

## 12. 部署架构

### 12.1 系统组件

```
┌─────────────────────────────────────────────────┐
│                   负载均衡器                      │
│              (Nginx / AWS ALB)                   │
└────────────────┬────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼──────┐  ┌──────▼────────┐
│  API Server  │  │  API Server   │
│  (FastAPI)   │  │  (FastAPI)    │
└───────┬──────┘  └───────┬───────┘
        │                 │
        └────────┬────────┘
                 │
        ┌────────▼────────┐
        │  LangGraph      │
        │  Orchestrator   │
        └────────┬────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
┌───▼───┐  ┌────▼───┐  ┌────▼────┐
│ LLM   │  │Database│  │ Vector  │
│ API   │  │  Pool  │  │   DB    │
└───────┘  └────────┘  └─────────┘
```

### 12.2 Docker部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: 
      context: .
      dockerfile: Dockerfile
      args:
        PYTHON_VERSION: 3.12
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/nl2sql
      - REDIS_URL=redis://redis:6379
      - DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
    depends_on:
      - db
      - redis
      - neo4j
    restart: unless-stopped
    
  db:
    image: pgvector/pgvector:pg16
    environment:
      - POSTGRES_DB=nl2sql
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/init.sql
    restart: unless-stopped
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
  
  neo4j:
    image: neo4j:5.15-community
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  neo4j_data:
```

**Dockerfile 示例**：

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**init-db.sql** (初始化pgvector):

```sql
-- 创建pgvector扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 创建schema embeddings表
CREATE TABLE IF NOT EXISTS schema_embeddings (
    id SERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    column_type TEXT,
    description TEXT,
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建HNSW索引
CREATE INDEX IF NOT EXISTS schema_embeddings_idx 
ON schema_embeddings 
USING hnsw (embedding vector_cosine_ops);

-- 创建SQL历史表
CREATE TABLE IF NOT EXISTS sql_history (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    sql_text TEXT NOT NULL,
    embedding vector(1536),
    success_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sql_history_idx 
ON sql_history 
USING hnsw (embedding vector_cosine_ops);
```

---

## 13. 扩展性设计

### 13.1 新增Agent

```python
# 系统设计为易于扩展，添加新Agent只需：

# 1. 定义Agent函数
def new_agent_node(state: MainState) -> MainState:
    """新的Agent逻辑"""
    # ... Agent实现
    return updated_state

# 2. 添加到流程图
workflow.add_node("new_agent", new_agent_node)

# 3. 连接边
workflow.add_edge("some_node", "new_agent")
workflow.add_edge("new_agent", "next_node")
```

### 13.2 新增Tool

```python
# 添加新Tool同样简单：

class NewTool:
    """新的工具"""
    
    def execute(self, input_data):
        """工具逻辑"""
        # ... 实现
        return result

# 在需要的节点中使用
new_tool = NewTool()
result = new_tool.execute(data)
```

### 13.3 支持新数据库

```python
# 抽象数据库接口
class DatabaseAdapter(ABC):
    @abstractmethod
    def execute(self, sql: str) -> Dict:
        pass
    
    @abstractmethod
    def get_schema(self) -> Dict:
        pass

# PostgreSQL实现
class PostgreSQLAdapter(DatabaseAdapter):
    def execute(self, sql: str) -> Dict:
        # PostgreSQL特定实现
        pass

# MySQL实现
class MySQLAdapter(DatabaseAdapter):
    def execute(self, sql: str) -> Dict:
        # MySQL特定实现
        pass

# 使用时注入
db_adapter = PostgreSQLAdapter() if config.db_type == "postgres" else MySQLAdapter()
```

---

## 14. 安全考虑

### 14.1 SQL注入防护

```python
class SecurityValidator:
    """安全验证器"""
    
    BLOCKED_KEYWORDS = [
        "DROP", "DELETE", "TRUNCATE", "ALTER",
        "CREATE", "GRANT", "REVOKE", "EXEC",
        "EXECUTE", "xp_", "sp_"
    ]
    
    def validate_sql(self, sql: str) -> Tuple[bool, List[str]]:
        """验证SQL安全性"""
        errors = []
        sql_upper = sql.upper()
        
        # 检查危险关键字
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in sql_upper:
                errors.append(f"禁止使用 {keyword}")
        
        # 检查注释注入
        if "--" in sql or "/*" in sql:
            errors.append("SQL中不允许包含注释")
        
        # 检查多语句
        if ";" in sql and sql.count(";") > 1:
            errors.append("不允许执行多条SQL语句")
        
        return len(errors) == 0, errors
```

### 14.2 权限控制

```python
class PermissionManager:
    """权限管理"""
    
    def __init__(self, db):
        self.db = db
    
    def create_readonly_user(self):
        """创建只读用户"""
        self.db.execute("""
            CREATE USER nl2sql_readonly WITH PASSWORD 'secure_password';
            GRANT CONNECT ON DATABASE business_db TO nl2sql_readonly;
            GRANT USAGE ON SCHEMA public TO nl2sql_readonly;
            GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_readonly;
            
            -- 确保只读
            REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM nl2sql_readonly;
        """)
```

### 14.3 查询限制

```python
class QueryLimiter:
    """查询限制"""
    
    def __init__(self, max_rows=10000, timeout=30):
        self.max_rows = max_rows
        self.timeout = timeout
    
    def add_limits(self, sql: str) -> str:
        """自动添加LIMIT和超时"""
        
        # 添加LIMIT（如果没有）
        if "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {self.max_rows}"
        
        # 添加超时控制
        sql = f"SET statement_timeout = {self.timeout * 1000};\n{sql}"
        
        return sql
```

---

## 14. 技术栈详解

### 14.1 LangGraph v1.0+ 核心变更

**主要API变更**：

```python
# v1.0之前
workflow.set_entry_point("start_node")

# v1.0+
from langgraph.graph import START
workflow.add_edge(START, "start_node")

# 使用END常量
from langgraph.graph import END
workflow.add_edge("final_node", END)
```

**Checkpointer支持**：

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

# 内存checkpointer（开发环境）
checkpointer = MemorySaver()

# PostgreSQL checkpointer（生产环境）
checkpointer = PostgresSaver.from_conn_string(
    conn_string="postgresql://user:pass@localhost:5432/db"
)

# 编译时添加
graph = workflow.compile(checkpointer=checkpointer)

# 使用config指定thread_id实现会话管理
config = {"configurable": {"thread_id": "user-123-session-456"}}
result = graph.invoke(initial_state, config=config)
```

**流式输出**：

```python
# v1.0+ 支持多种流式模式
async for event in graph.astream(initial_state, stream_mode="updates"):
    # stream_mode选项：
    # - "values": 完整状态值
    # - "updates": 状态更新
    # - "debug": 调试信息
    print(event)
```

**MessagesState继承**：

```python
from langgraph.graph import MessagesState

class MyState(MessagesState):
    """继承MessagesState自动支持消息管理"""
    custom_field: str
    
# 自动包含messages字段和消息管理功能
```

### 14.2 pgvector 使用指南

**安装和初始化**：

```sql
-- 在PostgreSQL中启用扩展
CREATE EXTENSION vector;

-- 检查版本
SELECT * FROM pg_extension WHERE extname = 'vector';
```

**向量类型定义**：

```sql
-- 创建向量列
CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    embedding vector(1536)  -- 指定维度
);
```

**索引创建**：

```sql
-- HNSW索引（推荐，性能好）
CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops);

-- IVFFlat索引（内存占用小）
CREATE INDEX ON items USING ivfflat (embedding vector_l2_ops)
WITH (lists = 100);
```

**距离函数**：

```sql
-- 余弦距离（推荐用于文本嵌入）
SELECT * FROM items ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector LIMIT 5;

-- L2距离
SELECT * FROM items ORDER BY embedding <-> '[0.1, 0.2, ...]'::vector LIMIT 5;

-- 内积（需要归一化向量）
SELECT * FROM items ORDER BY embedding <#> '[0.1, 0.2, ...]'::vector LIMIT 5;
```

**Python客户端使用**：

```python
import psycopg
from pgvector.psycopg import register_vector

# 连接数据库
conn = psycopg.connect("postgresql://localhost/mydb")

# 注册vector类型
register_vector(conn)

# 插入向量
with conn.cursor() as cur:
    embedding = [0.1, 0.2, 0.3, ...]  # 1536维
    cur.execute(
        "INSERT INTO items (embedding) VALUES (%s)",
        (embedding,)
    )

# 查询相似向量
with conn.cursor() as cur:
    cur.execute("""
        SELECT id, embedding <=> %s as distance
        FROM items
        ORDER BY embedding <=> %s
        LIMIT 5
    """, (embedding, embedding))
    results = cur.fetchall()
```

**性能优化建议**：

```python
# 1. 批量插入
with conn.cursor() as cur:
    # 使用 executemany
    cur.executemany(
        "INSERT INTO items (embedding) VALUES (%s)",
        [(emb,) for emb in embeddings]
    )

# 2. 使用 COPY 命令（最快）
from io import StringIO
import csv

buf = StringIO()
writer = csv.writer(buf)
for emb in embeddings:
    writer.writerow([str(emb)])
buf.seek(0)

with conn.cursor() as cur:
    cur.copy_expert(
        "COPY items (embedding) FROM STDIN WITH CSV",
        buf
    )

# 3. 调整索引参数
# ef_construction: 构建时间 vs 召回率（默认64，可调至200）
# m: 每个节点的邻居数（默认16）
CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

# 4. 查询时调整ef_search
SET hnsw.ef_search = 100;  -- 默认40，增大提高召回率
```

### 14.3 国产大模型API使用

**通义千问（Qwen）**：

```python
from langchain_community.chat_models import ChatTongyi
from dashscope import Generation

# LangChain封装
llm = ChatTongyi(
    model="qwen-plus",  # 或 qwen-turbo, qwen-max
    dashscope_api_key="your-api-key",
    temperature=0,
    streaming=True  # 支持流式输出
)

# 原生SDK（更多控制）
response = Generation.call(
    model="qwen-plus",
    prompt="你好",
    api_key="your-api-key",
    result_format='message'
)
```

**DeepSeek**：

```python
from langchain_openai import ChatOpenAI

# DeepSeek使用OpenAI兼容接口
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key="your-deepseek-api-key",
    base_url="https://api.deepseek.com",
    temperature=0.7,
    max_tokens=2000
)

# 支持函数调用
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """获取城市天气"""
    return f"{city}的天气是晴天"

llm_with_tools = llm.bind_tools([get_weather])
response = llm_with_tools.invoke("北京天气怎么样？")
```

**嵌入模型**：

```python
from langchain_community.embeddings import DashScopeEmbeddings

# 通义千问嵌入
embeddings = DashScopeEmbeddings(
    model="text-embedding-v2",  # 1536维
    dashscope_api_key="your-api-key"
)

# 生成嵌入
text_embedding = embeddings.embed_query("这是一段文本")
docs_embeddings = embeddings.embed_documents([
    "文档1",
    "文档2",
    "文档3"
])
```

### 14.4 Python 3.12 新特性应用

**类型别名**：

```python
# Python 3.12+
type Point = tuple[float, float]
type Vector = list[float]
type QueryID = str

def calculate_distance(p1: Point, p2: Point) -> float:
    ...
```

**泛型语法简化**：

```python
# 旧语法
from typing import List, Dict, Optional
def process(items: List[Dict[str, Optional[int]]]) -> None:
    ...

# Python 3.12+ 简化语法
def process(items: list[dict[str, int | None]]) -> None:
    ...
```

**f-string增强**：

```python
# 支持表达式中的引号
name = "World"
print(f"Hello {name.upper()}")

# 支持反斜杠
print(f"Result: {calculate()}\n")
```

**性能改进**：

```python
# comprehension内联优化，比循环快30%
squares = [x**2 for x in range(1000)]

# 字典合并优化
d1 = {**d2, **d3}  # 更快的合并
```

---

## 15. 附录

### 15.1 依赖包清单

```txt
# requirements.txt

# Python 3.12.x required

# 核心框架
langgraph>=1.0.0
langchain>=0.3.0
langchain-core>=0.3.0
langchain-community>=0.3.0

# 国产LLM支持
dashscope>=1.14.0  # 阿里云通义千问（Qwen）
langchain-openai>=0.2.0  # DeepSeek使用OpenAI兼容接口

# 数据库
psycopg[binary]>=3.1.0  # PostgreSQL驱动（支持Python 3.12）
pgvector>=0.2.0  # pgvector Python客户端
sqlalchemy>=2.0.23
redis>=5.0.1

# 图数据库
neo4j>=5.15.0

# Web框架
fastapi>=0.104.1
uvicorn[standard]>=0.24.0
websockets>=12.0

# 工具
sqlparse>=0.4.4
duckduckgo-search>=4.1.0
pydantic>=2.5.2

# 监控
langsmith>=0.1.0

# 测试
pytest>=7.4.3
pytest-asyncio>=0.21.1
httpx>=0.25.0  # FastAPI测试客户端
```

### 15.2 配置文件示例

```yaml
# config.yaml

# 数据库配置
database:
  type: postgresql
  host: localhost
  port: 5432
  database: nl2sql
  user: nl2sql_readonly
  password: ${DB_PASSWORD}
  pool_size: 10
  max_overflow: 20
  # pgvector配置
  vector_extension: true
  vector_dimensions: 1536  # text-embedding-v2维度

# LLM配置
llm:
  # 通义千问（诊断、SQL生成、Summary）
  qwen:
    model: qwen-plus
    api_key: ${DASHSCOPE_API_KEY}
    temperature: 0
    max_tokens: 4000
  
  # DeepSeek（聊天Agent）
  deepseek:
    model: deepseek-chat
    api_key: ${DEEPSEEK_API_KEY}
    base_url: https://api.deepseek.com
    temperature: 0.7
    max_tokens: 2000

# 嵌入模型配置
embeddings:
  provider: dashscope  # 通义千问
  model: text-embedding-v2
  api_key: ${DASHSCOPE_API_KEY}
  dimensions: 1536

# 向量检索配置（pgvector）
vector:
  index_type: hnsw  # HNSW算法
  distance_metric: cosine
  ef_construction: 64
  m: 16

# 图数据库配置
neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: ${NEO4J_PASSWORD}
  database: nl2sql

# Redis配置
redis:
  host: localhost
  port: 6379
  db: 0
  password: ${REDIS_PASSWORD}

# 系统配置
system:
  max_retries: 3
  sql_timeout: 30
  max_parallel_queries: 5
  cache_ttl: 300
  
  # LangGraph v1.0+ 配置
  checkpointer_enabled: true
  stream_mode: updates  # values / updates / debug

# 监控配置
monitoring:
  langsmith_enabled: true
  langsmith_project: nl2sql-production
  langsmith_api_key: ${LANGSMITH_API_KEY}
  log_level: INFO
```

### 15.3 Prompt模板库

详见独立的 `prompts/` 目录，包含：
- `diagnose_agent.txt` - 诊断Agent的完整Prompt
- `sql_generation_agent.txt` - SQL生成Agent的完整Prompt
- `chat_agent.txt` - 聊天Agent的完整Prompt
- `summary_agent.txt` - Summary Agent的完整Prompt

---

## 16. 总结

本概要设计文档详细阐述了NL2SQL多步骤查询处理系统的架构设计，主要特点：

1. **统一架构**：所有查询走相同流程，普通查询是复杂查询的特例
2. **智能路由**：自动判断是否需要数据库，合理分配处理路径
3. **模块化设计**：Agent和Tool职责清晰，易于测试和扩展
4. **健壮容错**：多层降级和fallback机制，确保系统可用性
5. **性能优化**：并行执行、缓存策略、索引优化
6. **安全可控**：SQL注入防护、权限控制、查询限制

### 技术栈亮点

**LangGraph v1.0+**：
- 使用最新的状态管理API（`START`、`END`常量）
- 支持持久化checkpointer，可恢复执行
- 更好的流式输出支持
- 改进的子图机制

**国产大模型**：
- **Qwen-Plus**：用于诊断、SQL生成、Summary等核心任务，推理能力强
- **DeepSeek**：用于聊天Agent，性价比高，适合对话场景
- 支持国产算力，降低成本

**pgvector集成**：
- 无需独立向量数据库，降低运维复杂度
- 与业务数据库统一管理，事务一致性更好
- HNSW索引算法，查询性能优秀
- 支持多种距离度量（cosine、L2、inner product）

**Python 3.12**：
- 使用 `type` 语句定义类型别名
- 简化的泛型语法（`list[str]` 替代 `List[str]`）
- 更好的性能和内存优化

系统采用LangGraph作为编排框架，充分利用其状态管理、子图复用、并行执行等特性，结合国产大模型和pgvector，构建了一个可扩展、高性能、易维护的NL2SQL解决方案。

---

**文档版本**: v3.0  
**最后更新**: 2025-10-31  
**维护者**: 开发团队
