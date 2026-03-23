# NL2SQL v3

基于 LangGraph 多智能体编排的生产级**自然语言转 SQL** 系统。用户用中文提问，系统自动路由查询、通过 RAG 检索相关 Schema、生成并验证 SQL、在 PostgreSQL 上执行，最终返回自然语言摘要。

---

## 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [RAG 数据依赖：MetaWeave](#rag-数据依赖metaweave)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [启动服务](#启动服务)
- [API 文档](#api-文档)
- [项目结构](#项目结构)
- [测试](#测试)
- [开发路线图](#开发路线图)

---

## 项目概述

NL2SQL v3 将自然语言业务问题转换为 SQL 查询并返回易于理解的答案，核心能力如下：

- **复杂度路由** — 基于 LLM 的分类器判断问题是否可用单条 SQL 完成（Fast Path）或需要多条依赖 SQL（Complex Path）。
- **RAG 辅助 Schema 检索** — 向量检索（pgvector 或 Milvus）+ 图数据库遍历（Neo4j），找到相关表、字段、JOIN 路径和历史 SQL 示例。
- **迭代式 SQL 生成与验证** — LLM 生成 SQL，多层验证器（语法、安全、语义 EXPLAIN）最多自动重试 3 次。
- **自然语言总结** — 最终结果由 LLM 以自然语言解释并返回给用户。
- **多轮对话** — 基于 PostgreSQL 的会话管理，支持按用户隔离的对话历史。
- **多 LLM 支持** — DashScope（通义千问）、OpenAI、OpenRouter、DeepSeek 以及任何 OpenAI 兼容接口。

---

## 系统架构

### 整体流程

```
用户问题
    |
    v
[ Router 路由节点 ]  -----(complex)-----> [ Complex Planner ] (Phase 2 开发中)
    |
 (simple)
    |
    v
[ Simple Planner 简单规划节点 ]
    |
    v
[ SQL 生成子图 ] <------ 验证失败自动重试（最多 3 次）------+
  |-- 问题解析（实体、时间、维度、指标提取 + 指代消解）       |
  |-- Schema 检索（向量检索 + 图检索 + 维度值匹配）          |
  |-- SQL 生成（LLM）                                      |
  +-- 验证（语法 / 安全 / 语义 EXPLAIN）  ----------------+
      |
      v（验证通过的 SQL）
[ SQL 执行节点 ]（PostgreSQL）
      |
      v
[ Summarizer 总结节点 ]（LLM）
      |
      v
  自然语言答案
```

### 父图（Father Graph）

顶层 LangGraph 编排器，包含以下节点：

| 节点 | 职责 |
|---|---|
| **Router** | 调用轻量 LLM，将问题分类为 `simple` 或 `complex` |
| **Simple Planner** | 为 Fast Path 准备子查询参数（纯函数，<1 ms） |
| **SQL Gen Wrapper** | 调用 SQL 生成子图，将输出映射回父图 State |
| **SQL Execution** | 在 PostgreSQL 上执行验证通过的 SQL |
| **Summarizer** | 将执行结果（或错误）转换为用户友好的自然语言回答 |

### SQL 生成子图

每个子查询独立调用的 LangGraph 子图：

| 节点 | 职责 |
|---|---|
| **Question Parsing** | 结构化提取时间范围、维度、指标等信息，并做指代消解 |
| **Schema Retrieval** | 向量检索相关表/列，Neo4j 生成 JOIN 计划，模糊匹配维度值 |
| **SQL Generation** | 基于结构化上下文由 LLM 生成 SQL |
| **Validation** | 多层校验：语法（sqlparse）、安全（关键词白名单）、语义（PostgreSQL `EXPLAIN`） |

### 执行路径

- **Fast Path**（Phase 1，当前版本）：单条 SQL 查询，端到端约 1–3 秒。
- **Complex Path**（Phase 2，开发中）：多条依赖 SQL 查询，支持依赖解析和并行执行。

---

## 技术栈

| 层次 | 技术 |
|---|---|
| 开发语言 | Python 3.12+ |
| 智能体编排 | LangGraph 1.0+，LangChain 1.0+ |
| API 服务 | FastAPI + Uvicorn |
| 查询数据库 | PostgreSQL（psycopg3） |
| 向量数据库 | pgvector **或** Milvus（通过配置切换） |
| 图数据库 | Neo4j 5.x（JOIN 路径规划） |
| LLM 提供商 | DashScope（通义千问）、OpenAI、OpenRouter、DeepSeek |
| 向量模型 | DashScope `text-embedding-v3`（1024 维） |
| SQL 解析 | sqlparse |
| 数据校验 | Pydantic v2 |
| 会话持久化 | LangGraph PostgresSaver |
| 包管理器 | uv |
| 测试框架 | pytest |

---

## RAG 数据依赖：MetaWeave

NL2SQL v3 依赖预先构建好的 RAG 数据来理解业务数据库的 Schema。这些数据由配套项目 **[MetaWeave](https://github.com/your-org/metaweave)**（链接待更新）生成。

MetaWeave 分析源表的结构与关联关系，并生成以下 RAG 数据：

| 向量集合 / 表 | 内容 |
|---|---|
| `table_schema_embeddings` | 每张表及每个字段的描述文本，嵌入为 1024 维向量，存入 pgvector 或 Milvus |
| `dim_value_embeddings` | 维度列的枚举值嵌入，用于模糊值匹配（例如将"肯德基"映射到 `brand_id=42`） |
| `sql_example_embeddings` | 历史验证通过的 SQL 示例嵌入，用于少样本检索 |
| Neo4j 图数据库 | 表关系图，供 JOIN 规划器通过 APOC Dijkstra 算法查找多跳 JOIN 路径 |

**在运行 NL2SQL v3 之前，必须先运行 MetaWeave 填充上述数据。** 若数据缺失，Schema 检索将返回空结果，SQL 生成将失败。

---

## 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) 包管理器
- PostgreSQL 14+（pgvector 模式下需安装 `pgvector` 扩展）
- Neo4j 5.x
- Milvus 2.x（可选，使用 Milvus 模式时需要）
- 至少一个 LLM 提供商的 API Key

---

## 安装

```bash
# 克隆仓库
git clone https://github.com/your-org/nl2sql-v3.git
cd nl2sql-v3

# 创建虚拟环境并安装依赖
uv venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows

uv pip install -e .

# 安装开发依赖（可选）
uv pip install -e ".[dev]"
```

---

## 配置

所有配置集中在 `src/configs/config.yaml`，最小配置示例如下：

```yaml
# LLM 提供商（填写 API Key）
llm_providers:
  dashscope:
    api_key: "sk-..."
  openai:
    api_key: "sk-..."
    base_url: "https://api.openai.com/v1"

# 各节点使用的 LLM 画像
llm_profiles:
  router_llm:
    provider: dashscope
    model: qwen-turbo       # 路由分类，使用轻量模型
    temperature: 0
  generation_llm:
    provider: dashscope
    model: qwen-max         # SQL 生成，使用高能力模型
    temperature: 0
  summarizer_llm:
    provider: dashscope
    model: qwen-plus        # 结果总结
    temperature: 0.3

# 向量数据库（二选一）
vector_database:
  active: pgvector          # 或 "milvus"
  pgvector:
    host: localhost
    port: 5432
    dbname: nl2sql
    user: postgres
    password: "..."
  milvus:
    host: localhost
    port: 19530
    db_name: nl2sql

# PostgreSQL（业务数据库，用于执行 SQL）
postgresql:
  host: localhost
  port: 5432
  dbname: your_business_db
  user: postgres
  password: "..."

# Neo4j（用于 JOIN 路径规划）
neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: "..."

# LangGraph 持久化（对话历史）
langgraph_persistence:
  enabled: true
  checkpoint:
    father_enabled: true
    subgraph_enabled: false
```

各节点的详细配置（模型选择、重试次数、超时时间等）位于：

- `src/modules/nl2sql_father/config/nl2sql_father_graph.yaml` — Router、SQL 执行、Summarizer
- `src/modules/sql_generation/config/sql_generation_subgraph.yaml` — 问题解析、Schema 检索、SQL 生成、验证

---

## 启动服务

### 启动 API 服务

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 快速验证

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查询2024年各月的销售额", "user_id": "demo"}'
```

### Python 直接调用

```python
from src.modules.nl2sql_father.graph import run_nl2sql_query

result = run_nl2sql_query(
    query="查询2024年各月的销售额",
    user_id="alice",
)

print(result["summary"])            # 自然语言答案
print(result["sql"])                # 执行的 SQL
print(result["execution_results"])  # 原始行列数据
```

---

## API 文档

### POST `/api/v1/query`

提交自然语言查询。

**请求体：**

```json
{
  "query": "查询2024年各月的销售额",
  "user_id": "alice",
  "thread_id": "alice:1700000000000"
}
```

**响应：**

```json
{
  "code": 200,
  "message": "success",
  "trace_id": "q_a1b2c3d4",
  "data": {
    "user_query": "查询2024年各月的销售额",
    "query_id": "q_a1b2c3d4",
    "thread_id": "alice:1700000000000",
    "complexity": "simple",
    "path_taken": "fast",
    "summary": "2024年各月销售额如下：1月 12万元，2月 9.5万元，……",
    "sql": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(amount) AS total FROM orders WHERE ...",
    "sub_queries": [...],
    "execution_results": [
      {
        "success": true,
        "columns": ["month", "total_amount"],
        "rows": [["2024-01-01", 120000.0], "..."],
        "row_count": 12,
        "execution_time_ms": 48.3
      }
    ],
    "metadata": {
      "total_execution_time_ms": 1823.5,
      "router_latency_ms": 145.2
    }
  }
}
```

### GET `/api/v1/health`

健康检查接口，返回 `{"status": "ok"}`。

### GET `/api/v1/history`

获取指定会话的对话历史（需开启持久化）。

---

## 项目结构

```
nl2sql-v3/
├── src/
│   ├── api/                              # FastAPI 应用
│   │   ├── main.py                       # 应用入口，生命周期钩子
│   │   ├── routers/                      # query.py, history.py
│   │   └── schemas/                      # Pydantic 请求/响应模型
│   │
│   ├── modules/
│   │   ├── nl2sql_father/                # 父图（顶层编排器）
│   │   │   ├── graph.py                  # 图编译与 run_nl2sql_query()
│   │   │   ├── state.py                  # NL2SQLFatherState 定义
│   │   │   ├── nodes/                    # router, simple_planner, sql_execution, summarizer ...
│   │   │   └── config/                   # nl2sql_father_graph.yaml
│   │   │
│   │   └── sql_generation/               # SQL 生成子图
│   │       └── subgraph/
│   │           ├── create_subgraph.py    # 子图编译
│   │           ├── state.py              # SQLGenerationState 定义
│   │           └── nodes/               # question_parsing, schema_retrieval, sql_generation, validation
│   │
│   ├── services/
│   │   ├── llm_factory.py               # 多提供商 LLM 工厂（DashScope / OpenAI / DeepSeek）
│   │   ├── config_loader.py             # YAML 配置加载器（支持环境变量插值）
│   │   ├── embedding/                   # 向量嵌入客户端
│   │   ├── vector_adapter/              # pgvector / Milvus 适配器（工厂模式，可切换）
│   │   ├── db/                          # PostgreSQL 客户端，Neo4j 客户端
│   │   └── langgraph_persistence/       # PostgresSaver 检查点，对话历史读写
│   │
│   ├── tools/
│   │   ├── schema_retrieval/
│   │   │   ├── retriever.py             # SchemaRetriever 协调器
│   │   │   ├── join_planner.py          # 基于 Neo4j 的 JOIN 路径规划
│   │   │   └── value_matcher.py         # 维度值模糊匹配
│   │   └── validation/
│   │       └── sql_validation.py        # 多层 SQL 验证器
│   │
│   ├── prompts/                         # LLM 提示词模板
│   └── configs/                         # 全局 config.yaml
│
├── tests/                               # 测试工具与调试脚本
├── docs/                                # 设计文档
├── configs/                             # 额外配置文件
├── pyproject.toml
└── README.md
```

---

## 测试

```bash
# 运行所有单元测试
uv run pytest src/tests/unit/ -v

# 运行父图单元测试
uv run pytest src/tests/unit/nl2sql_father/ -v

# 运行集成测试（需要真实数据库连接）
uv run pytest src/tests/integration/ -v

# 生成覆盖率报告
uv run pytest src/tests/unit/ --cov=src --cov-report=term-missing
```

---

## 开发路线图

- [x] **Phase 1 — Fast Path**：完整 RAG 流水线，支持单条 SQL 查询
- [x] 多 LLM 提供商支持（DashScope、OpenAI、DeepSeek、OpenRouter）
- [x] 向量数据库后端可切换（pgvector / Milvus）
- [x] 基于 PostgreSQL 的对话历史持久化
- [x] 多层 SQL 验证 + 自动重试
- [x] **Phase 2 — Complex Path**：多步依赖 SQL 查询，支持并行执行
- [ ] 流式 API 响应
- [x] Web 界面（Streamlit）
- [ ] LangSmith 可观测性集成

---

## 许可证

内部项目，许可证待定。
