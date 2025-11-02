# 项目目录规划（建议稿）

## 目标与依据
- 目标：在保证可维护性与扩展性的前提下，明确 NL2SQL 项目（v3）目录组织，支撑后续快速开发与协作。
- 依据：
  - `docs/项目总体需求.md`（五大模块：SQL 生成、SQL 执行、结果总结返回、日志记录、数据准备）
  - `docs/nl2sql_design_document_updated.md`（整体架构、Agent & Tool 划分、主流程）
  - `docs/nl2sql_pipeline_v3_integrated.html`（整合流程与路由/降级）
  - `docs/sql_generation_subgraph_design.md`（SQL 生成子图详细设计）

## 顶层目录结构（推荐）
```text
nl2sql_v3/
├─ src/                               # 业务代码根目录
│  ├─ api/                             # FastAPI 对外服务层
│  │  ├─ main.py                       # 应用入口（注册路由/中间件）
│  │  ├─ routers/
│  │  │  ├─ query.py                   # /api/v1/query → 调用 orchestrator
│  │  │  └─ health.py                  # /health 心跳
│  │  ├─ deps/
│  │  │  ├─ config.py                  # 配置依赖（加载 config.yaml）
│  │  │  └─ graph.py                   # 主流程/子图单例依赖
│  │  ├─ schemas/
│  │  │  └─ query.py                   # Pydantic 请求/响应模型
│  │  ├─ middleware/
│  │  │  └─ request_logging.py         # 请求日志/trace-id（避免与标准库 logging 同名冲突）
│  │  ├─ exceptions/                   # （可选）异常处理器
│  │  └─ core/                         # （可选）核心配置（CORS/安全等）
│  ├─ orchestrator/                   # 主流程编排（LangGraph主图）
│  │  ├─ agents/                      # 主流程级Agent（诊断/聊天等）
│  │  │  ├─ diagnose_agent.py         # Agent 1: 诊断和拆解
│  │  │  └─ chat_agent.py             # Agent 4: 聊天Agent
│  │  ├─ main_graph.py
│  │  ├─ state.py
│  │  └─ routing.py
│  │
│  ├─ modules/                        # 五大业务模块（按职责边界拆分）
│  │  ├─ sql_generation/              # 模块1：SQL 生成
│  │  │  ├─ subgraph/                 # 子图（LangGraph子图，聚合节点/状态/条件边）
│  │  │  │  ├─ state.py
│  │  │  │  ├─ nodes/
│  │  │  │  │  ├─ schema_retrieval.py
│  │  │  │  │  ├─ sql_generation.py
│  │  │  │  │  └─ validation.py
│  │  │  │  └─ create_subgraph.py
│  │  │  └─ config/                   # 子图配置（与设计文档一致）
│  │  │     └─ sql_generation_subgraph.yaml
│  │  │
│  │  ├─ sql_execution/               # 模块2：SQL 执行（只读）
│  │  │  ├─ executor.py               # 执行器入口（对外API）
│  │  │  ├─ query_limiter.py          # 查询限制（LIMIT/超时）
│  │  │  ├─ result_formatter.py       # 结果格式化
│  │  │  └─ adapters/                 # 执行适配（未来支持多数据库）
│  │  │     ├─ base.py
│  │  │     └─ postgres_adapter.py
│  │  │
│  │  ├─ result_summary/              # 模块3：结果总结返回（Summary Agent）
│  │  │  └─ summary_agent.py          # Agent 5: Summary Agent
│  │  │
│  │  ├─ logging_center/              # 模块4：日志记录
│  │  │  ├─ logger.py                 # 统一logger封装
│  │  │  └─ handlers.py               # 格式/落盘/级别等
│  │  │
│  │  └─ data_preparation/            # 模块5：数据准备（下个版本）
│  │     ├─ README.md                 # 说明：计划于v4.0开发
│  │     └─ .gitkeep
│  │
│  ├─ tools/                          # 纯函数工具（确定性），跨模块复用
│  │  ├─ schema_retrieval/
│  │  │  ├─ retriever.py              # 协调 services，拼装Schema上下文
│  │  │  ├─ value_matcher.py          # 维度值匹配逻辑（纯函数）
│  │  │  └─ join_planner.py           # JOIN路径规划算法（纯函数）
│  │  ├─ validation/
│  │  │  └─ sql_validation.py         # 三层验证（语法/安全/语义）
│  │  ├─ aggregation/
│  │  │  └─ aggregator.py
│  │  └─ common/
│  │     ├─ sql_utils.py
│  │     ├─ text_normalize.py
│  │     └─ time_window.py
│  │
│  ├─ services/                       # 基础设施适配层（连接/客户端/缓存/监控）
│  │  ├─ db/
│  │  │  ├─ pg_connection.py          # PostgreSQL 连接/池管理
│  │  │  ├─ pg_client.py              # PG业务客户端（sem_object_vec / dim_value_index / sql_embedding）
│  │  │  ├─ neo4j_connection.py       # Neo4j 连接管理
│  │  │  ├─ neo4j_client.py           # Neo4j业务客户端（JOIN_ON路径检索）
│  │  │  └─ migrations/
│  │  │     └─ pgvector.sql           # 运行版（与 docs/pgvector.sql 对齐）
│  │  ├─ embedding/
│  │  │  └─ embedding_client.py       # 嵌入服务适配（Qwen Embedding）
│  │  ├─ cache/
│  │  │  └─ redis_client.py
│  │  ├─ monitoring/
│  │  │  └─ langsmith.py
│  │  └─ config_loader.py             # 统一配置加载/校验
│  │
│  ├─ utils/                          # 轻量工具（非业务、非连接），尽量保持通用性
│  │  ├─ env.py
│  │  └─ hashing.py
│  │
│  ├─ configs/
│  │  └─ config.yaml                  # 系统级配置（引用子图配置路径）
│  │
│  ├─ prompts/                        # 统一提示词集中管理（方便版本化）
│  │  ├─ orchestrator/
│  │  │  ├─ diagnose_agent.txt
│  │  │  └─ chat_agent.txt
│  │  ├─ sql_generation/
│  │  │  ├─ generator_prompt.txt
│  │  │  └─ validation_feedback.txt
│  │  └─ summary/
│  │     └─ summary_agent.txt
│  │
│  └─ tests/                          # 测试目录
│     ├─ unit/
│     │  ├─ tools/
│     │  ├─ modules/
│     │  └─ services/                 # 新增：services 层单测
│     ├─ integration/
│     │  ├─ api/                       # 新增：API 集成测试
│     │  ├─ sql_generation_subgraph/
│     │  ├─ orchestrator/
│     │  └─ database/                 # 新增：数据库集成测试
│     ├─ e2e/
│     ├─ fixtures/                    # 新增：测试数据
│     │  ├─ sample_queries.json
│     │  └─ mock_schemas.json
│     └─ mocks/                       # 新增：Mock对象
│        ├─ mock_llm.py
│        └─ mock_db.py
│
├─ scripts/                           # 运维/初始化/数据灌库脚本
│  ├─ init_db.ps1
│  ├─ init_db.sh
│  └─ load_dim_value_index.sql
│
├─ docs/                              # 文档
│  ├─ project_directory_plan.md       # 本文档
│  ├─ sql_generation_subgraph_design.md
│  ├─ PG_Neo4j取数与提示词拼接说明.md
│  ├─ pgvector.sql
│  ├─ nl2sql_design_document_updated.md
│  └─ nl2sql_pipeline_v3_integrated.html
│
├─ logs/
│  └─ .gitkeep
│
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 设计说明（关键点）
- 五大业务模块独立目录（`src/modules/*`），便于团队并行开发与领域内聚：
  - `sql_generation/`：仅负责“单个子查询 SQL 生成”，子图放入 `subgraph/`（状态/节点/条件分层）。
  - `sql_execution/`：统一执行模块（执行器入口/查询限制/结果格式化/多DB适配）。
  - `result_summary/`：Summary Agent 独立，便于多终端输出（文本/图表）。
  - `logging_center/`：统一日志策略封装（格式、级别、落盘、打点）。
  - `data_preparation/`：以 README 占位，后续逐步补齐（向量/图/索引/维度值索引）。

- Agent 放置规则：
  - 主流程级（诊断、聊天）→ `orchestrator/agents/`。
  - 子图内（SQL生成）→ `modules/sql_generation/subgraph/nodes/`。
  - 模块专属（Summary）→ `modules/result_summary/`。

- 工具与服务分层：
  - `services/`：外部依赖封装（连接/客户端/缓存/监控/嵌入）。
  - `tools/`：纯函数与协调器（如 retriever 组合 services、join_planner/value_matcher 算法）。
  - 依赖方向：`tools → services → 外部系统`。

- 提示词与配置：
  - `prompts/` 统一管理，按功能域分目录（orchestrator/sql_generation/summary）。
  - `configs/config.yaml` 为系统级配置，引用各子图配置路径。
  - 子图配置放在对应模块内（如 `modules/sql_generation/config/`），保持子图独立性，便于未来抽离为独立包。
  - `services/config_loader.py` 统一加载与校验。

- 数据库脚本与迁移：
  - `services/db/migrations/pgvector.sql` 为可执行版本；`docs/pgvector.sql` 为规范定义版本。

- 测试：
  - 单元：tools/modules/services 分层；
  - 集成：子图、编排、数据库；
  - e2e：端到端；
  - fixtures/mocks：测试数据与 Mock 统一管理。

### FastAPI 接口层（推荐）
- 责任：对外暴露 HTTP API，仅做请求校验、依赖注入与调用 orchestrator，不承载业务逻辑。
- 目录：`src/api/{main.py, routers/, deps/, schemas/, middleware/, exceptions/, core/}`。
  - `routers/`：路由处理器
  - `deps/`：依赖注入（配置、图实例等）
  - `schemas/`：Pydantic 请求/响应模型
  - `middleware/`：中间件（日志、trace-id 等）
  - `exceptions/`（可选）：异常处理器
  - `core/`（可选）：核心配置（CORS、安全策略等）
- 运行：`uvicorn src.api.main:app --reload`。
- 测试：在 `src/tests/integration/api/` 添加接口集成用例。

## 先行落地（启动子图开发建议）
优先创建以下最小集，确保可运行：
- `src/modules/sql_generation/subgraph/`：`state.py`、`nodes/{schema_retrieval,sql_generation,validation}.py`、`create_subgraph.py`
- `src/modules/sql_generation/config/sql_generation_subgraph.yaml`
- `src/tools/schema_retrieval/`：`retriever.py`、`value_matcher.py`、`join_planner.py`
- `src/tools/validation/sql_validation.py`
- `src/services/db/`：`pg_connection.py`、`pg_client.py`、`neo4j_connection.py`、`neo4j_client.py`、`migrations/pgvector.sql`
- `src/services/embedding/embedding_client.py`
- `src/configs/config.yaml`（包含引用子图配置的路径）
- `src/prompts/sql_generation/generator_prompt.txt`

随后接入主流程：
- `src/orchestrator/{main_graph.py,state.py,routing.py}` 装配 `create_subgraph()`；
- `src/orchestrator/agents/diagnose_agent.py` 接入路由决策；
- 通过 `services/config_loader.py` 注入依赖。

## 命名与约定（摘）
- 目录/文件命名使用下划线或中划线，避免驼峰；Python 模块使用下划线。
- 模块内“对外入口”文件命名为 `create_xxx.py` 或 `agent.py`，便于主流程引用。
- 纯函数工具放入 `tools/`，避免引入外部副作用；连接/依赖放入 `services/`。
- 不在通用工具中塞入特例参数，遵循“单一职责”和“可替换性”。

---

## 常见问题 (FAQ)

### Q1: 如何添加新的 Agent？
根据 Agent 的职责，放入对应位置：
- **主流程级 Agent**（如诊断、聊天）→ `orchestrator/agents/`
- **模块专属 Agent**（如 Summary Agent）→ `modules/xxx/`
- **子图节点 Agent**（如 SQL 生成 Agent）→ `modules/xxx/subgraph/nodes/`

示例：添加一个新的"解释 Agent"用于解释 SQL：
```python
# src/modules/sql_generation/sql_explainer_agent.py
def create_sql_explainer_agent():
    """创建 SQL 解释 Agent"""
    ...
```

### Q2: 配置文件应该放在哪里？
- **系统级配置** → `src/configs/config.yaml`
  - 包含数据库连接、LLM API密钥、系统参数等
  - 通过环境变量引用敏感信息：`${DB_PASSWORD}`

- **子图配置** → `src/modules/xxx/config/xxx_subgraph.yaml`
  - 子图专属配置（如重试次数、超时时间、提示词参数）
  - 保持子图独立性，便于抽离为独立包

- **配置加载示例**：
```yaml
# src/configs/config.yaml
sql_generation:
  subgraph_config_path: ../modules/sql_generation/config/sql_generation_subgraph.yaml
  enabled: true
```

```python
# 在代码中加载（推荐以项目根为基准构建绝对路径，避免相对路径脆弱）
from services.config_loader import ConfigLoader
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]  # 指向仓库根
config_path = project_root / "src" / "configs" / "config.yaml"
config = ConfigLoader.load(str(config_path))

subgraph_cfg_rel = config["sql_generation"]["subgraph_config_path"]  # 如 ../modules/sql_generation/config/sql_generation_subgraph.yaml
subgraph_cfg_path = (project_root / "src" / subgraph_cfg_rel).resolve()
subgraph_config = ConfigLoader.load(str(subgraph_cfg_path))
```

### Q3: 如何区分 tools 和 services？
**原则**：
- **tools**: 纯函数，无外部依赖，高度可测试
- **services**: 封装外部系统（DB/Redis/LLM/API）

**判断标准**：
| 特征 | tools | services |
|-----|-------|----------|
| 外部连接 | ❌ 无 | ✅ 有（DB/Redis/API） |
| 状态管理 | ❌ 无状态 | ✅ 有状态（连接池、缓存） |
| 可测试性 | ✅ 直接单测 | ⚠️ 需要 Mock/集成测试 |
| 依赖注入 | ❌ 不需要 | ✅ 需要（通过构造函数） |

**示例**：
```python
# ✅ tools/validation/sql_validation.py
def validate_sql_syntax(sql: str) -> List[str]:
    """纯函数：验证 SQL 语法"""
    errors = []
    if not sql.strip():
        errors.append("SQL 不能为空")
    return errors

# ✅ services/db/pg_client.py
class PGClient:
    """服务：封装 PostgreSQL 连接"""
    def __init__(self, connection_pool):
        self.pool = connection_pool  # 有状态

    def query_schema(self, table_name: str):
        with self.pool.connection() as conn:  # 外部依赖
            ...
```

**依赖方向**：`tools` → `services` → `外部系统`

### Q4: 如何扩展支持新的数据库（如 MySQL）？
采用适配器模式，新增适配器即可：

1. **定义适配器接口**：
```python
# src/modules/sql_execution/adapters/base.py
from abc import ABC, abstractmethod

class DatabaseAdapter(ABC):
    @abstractmethod
    def execute(self, sql: str, timeout: int) -> dict:
        """执行 SQL 并返回结果"""
        pass

    @abstractmethod
    def explain(self, sql: str) -> dict:
        """获取查询计划"""
        pass
```

2. **实现 MySQL 适配器**：
```python
# src/modules/sql_execution/adapters/mysql_adapter.py
from .base import DatabaseAdapter

class MySQLAdapter(DatabaseAdapter):
    def execute(self, sql: str, timeout: int) -> dict:
        # MySQL 特定实现
        ...
```

3. **在配置中切换**：
```yaml
# src/configs/config.yaml
database:
  type: mysql  # 或 postgres
  adapter: modules.sql_execution.adapters.mysql_adapter.MySQLAdapter
```

### Q5: 子图如何抽离为独立 Python 包？
如需将子图抽离为独立 Python 包（供其他工程复用）：

1. **在子图目录添加包结构**：
```
src/modules/sql_generation/subgraph/
├─ __init__.py              # 导出公共接口
├─ pyproject.toml           # 包配置
├─ state.py
├─ nodes/
│  ├─ __init__.py
│  ├─ schema_retrieval.py
│  ├─ sql_generation.py
│  └─ validation.py
└─ create_subgraph.py
```

2. **定义公共接口**：
```python
# src/modules/sql_generation/subgraph/__init__.py
from .create_subgraph import create_sql_generation_subgraph
from .state import SQLGenerationState

__all__ = ["create_sql_generation_subgraph", "SQLGenerationState"]
```

3. **配置包元信息**：
```toml
# src/modules/sql_generation/subgraph/pyproject.toml
[project]
name = "nl2sql-sql-generation-subgraph"
version = "1.0.0"
dependencies = [
    "langgraph>=1.0.0",
    "langchain>=0.3.0"
]
```

4. **在主工程中使用**：
```python
# 本地引用
from src.modules.sql_generation.subgraph import create_sql_generation_subgraph

# 或作为独立包安装后
from nl2sql_sql_generation_subgraph import create_sql_generation_subgraph
```

### Q6: 如何组织和管理提示词版本？
推荐使用 Git + 提示词模板变量：

1. **提示词模板化**：
```text
# src/prompts/sql_generation/generator_prompt.txt
你是一个 SQL 生成专家。

【数据库类型】：{{database_type}}
【Schema 上下文】：
{{schema_context}}

【历史成功案例】：
{{history_examples}}

【要求】：
1. 生成 {{database_type}} 语法的 SQL
2. 考虑性能优化
...
```

2. **版本管理**：
```bash
# 使用 Git 标签管理提示词版本
git tag -a prompts-v1.0 -m "初始提示词版本"
git tag -a prompts-v1.1 -m "优化 SQL 生成提示词"
```

3. **A/B 测试**：
```python
# src/services/config_loader.py
def load_prompt(name: str, version: str = "latest") -> str:
    """加载指定版本的提示词"""
    if version == "latest":
        path = f"prompts/{name}.txt"
    else:
        path = f"prompts/versions/{version}/{name}.txt"
    return read_file(path)
```

---

## 附录：快速启动命令

创建项目目录结构：
```bash
# 创建主要目录
mkdir -p src/{orchestrator/agents,modules,tools,services,utils,configs,prompts,tests}

# 创建 FastAPI API 层
mkdir -p src/api/{routers,deps,schemas,middleware,exceptions,core}

# 创建五大模块
mkdir -p src/modules/{sql_generation/subgraph/nodes,sql_generation/config,sql_execution/adapters,result_summary,logging_center,data_preparation}

# 创建 tools
mkdir -p src/tools/{schema_retrieval,validation,aggregation,common}

# 创建 services
mkdir -p src/services/{db/migrations,embedding,cache,monitoring}

# 创建 prompts
mkdir -p src/prompts/{orchestrator,sql_generation,summary}

# 创建 tests
mkdir -p src/tests/{unit/{tools,modules,services},integration/{api,sql_generation_subgraph,orchestrator,database},e2e,fixtures,mocks}

# 创建其他目录
mkdir -p {scripts,docs,logs}

# 创建占位文件
touch src/api/main.py
touch src/api/routers/{query.py,health.py}
touch src/api/deps/{config.py,graph.py}
touch src/api/schemas/query.py
touch src/api/middleware/request_logging.py
touch src/api/exceptions/.gitkeep
touch src/api/core/.gitkeep
touch src/modules/data_preparation/{README.md,.gitkeep}
touch src/modules/sql_generation/config/sql_generation_subgraph.yaml
touch logs/.gitkeep

echo "✅ 项目目录结构创建完成！"
```


