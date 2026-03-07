# 80 - FastAPI 与 Streamlit 架构设计

## 文档信息
- **创建日期**: 2026-03-06
- **版本**: v3.0
- **目标**: 将 NL2SQL 核心逻辑封装为 RESTful API 服务，并使用 Streamlit 构建现代化的 Web 对话界面。

---

## 一、 系统架构概览

本设计采用典型的前后端分离架构，确保核心逻辑的稳定性与前端展示的灵活性：

1. **核心业务层 (`nl2sql_father` / `sql_generation`)**：保持现有同步逻辑，不作任何侵入式修改。唯一的对外入口是 `run_nl2sql_query()`。
2. **后端 API 层 (FastAPI)**：通过同步路由函数安全地调用核心层（FastAPI 自动将 `def` 路由放入线程池执行），对外暴露 HTTP 接口。
3. **前端交互层 (Streamlit)**：纯 UI 呈现，负责状态管理、布局渲染与 API 通信。通过 `requests` 库调用 FastAPI 接口。

### 1.1 调用链路

```
用户浏览器 → Streamlit (8501) → requests → FastAPI (8000) → run_nl2sql_query() → LangGraph 父图
```

### 1.2 依赖说明

**已有依赖**（已在 `pyproject.toml` 主依赖中，无需新增）：
- `fastapi>=0.120.3`
- `uvicorn>=0.38.0`
- `pydantic>=2.5.2`

**需要新增的依赖**：在 `pyproject.toml` 中新增 `web` 可选依赖组（避免 CLI-only 用户安装不需要的包）：

```toml
[project.optional-dependencies]
web = [
    "streamlit>=1.55.0",
    "requests>=2.32.0",
]
```

安装方式：`uv pip install -e ".[web]"`

---

## 二、 FastAPI 后端设计

### 2.1 目录结构规划

在 `src/api/` 下构建标准的 FastAPI 目录：

```text
src/
  api/
    __init__.py
    main.py                 # FastAPI 应用入口（挂载路由、中间件、lifespan）
    routers/
      __init__.py
      query.py              # NL2SQL 查询路由
      history.py            # 历史会话路由
    schemas/
      __init__.py
      common.py             # 统一响应模型 (BaseResponse)
      query.py              # 查询相关的请求/响应模型
      history.py            # 历史相关的响应模型
    core/
      __init__.py
      config.py             # API 配置（CORS、端口等）
      logging.py            # API 独立日志配置
```

### 2.2 同步路由策略

`run_nl2sql_query()` 是纯同步函数，内部调用 `app.invoke()` 可能耗时数秒到数十秒。

**策略：所有业务路由使用 `def`（非 `async def`）**。FastAPI 会自动将 `def` 路由放入线程池执行，无需手动调用 `run_in_executor` 或 `asyncio.to_thread`。

```python
@router.post("/query")
def submit_query(req: QueryRequest) -> BaseResponse[QueryResponseData]:
    result = run_nl2sql_query(
        query=req.query,
        user_id=req.user_id,
        thread_id=req.thread_id,
    )
    ...
```

### 2.3 统一响应模板 (JSON)

所有**业务 API** 返回遵循统一的 JSON 模板结构。`trace_id` 直接复用核心层的 `query_id`，保持全链路追踪 ID 一致。唯一的例外是 `GET /health` 健康检查接口，它返回裸 JSON（不走 BaseResponse 包裹）。

```python
# src/api/schemas/common.py
from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T")

class BaseResponse(BaseModel, Generic[T]):
    code: int = 200                  # 业务状态码：200 成功，500 失败
    message: str = "success"         # 提示信息
    data: Optional[T] = None         # 核心业务数据
    trace_id: Optional[str] = None   # 请求追踪ID = query_id，用于排查日志
```

**请求模型示例：**

```python
# src/api/schemas/query.py
from typing import Optional
from pydantic import BaseModel, Field

class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)  # 用户自然语言问题，最大 1000 字符
    user_id: str = "guest"
    thread_id: Optional[str] = None
```

### 2.4 API 接口列表

> 以下所有接口均为 **FastAPI 后端 HTTP 接口**，Streamlit 前端通过 `requests` 库调用。Streamlit 本身不直接访问数据库或调用核心函数。

#### 1) 健康检查（例外接口，不走 BaseResponse）
- **路径**: `GET /api/v1/health`
- **调用方**: Streamlit 前端，用于探测后端是否可用。
- **说明**: 此接口**不走** `BaseResponse` 包裹，直接返回裸 JSON。前端仅判断 HTTP 200 即可。
- **响应**:
  ```json
  { "status": "ok" }
  ```

#### 2) 提交 NL2SQL 查询（当前轮）
- **路径**: `POST /api/v1/query`
- **调用方**: Streamlit 前端，用户提交新问题时调用。
- **说明**: 接收用户自然语言问题，调用 `run_nl2sql_query()` 执行主图推理并返回结构化结果。返回的完整数据（含 SQL、执行结果、错误详情）**仅用于当前轮的展示**。
- **请求参数** (`QueryRequest`):
  ```json
  {
    "query": "广州市京东便利店的销售额是多少？",
    "user_id": "guest",
    "thread_id": "guest:20260305T183946997Z"
  }
  ```
  - `query`（必填）：用户自然语言问题，最大长度 1000 字符。超过时 API 返回 422 校验错误。（注：响应中的 `query_id` 由后端自动生成，格式为 `q_<8位hex>`，如 `q_a1b2c3d4`，不是 UUID。前端和日志中请以实际值为准。）
  - `user_id`（可选，默认 `"guest"`）：用户标识，仅允许 `[a-zA-Z0-9_-]`，不合法时降级为 `"guest"`。
  - `thread_id`（可选）：会话 ID，格式为 `{user_id}:{YYYYMMDDTHHmmssSSS}Z`。为空时后端自动生成新会话。

- **响应数据** (`data` 字段)：

  直接映射自 `extract_final_result()` 的输出，不做裁剪，前端按需取用。

  ```json
  {
    "user_query": "广州市京东便利店的销售额是多少？",
    "query_id": "q_a1b2c3d4",
    "thread_id": "guest:20260305T183946997Z",
    "user_id": "guest",
    "complexity": "simple",
    "path_taken": "fast",
    "summary": "广州市京东便利店的销售额为 12,345 元。",
    "error": null,
    "error_type": null,
    "failed_step": null,
    "sql": "SELECT SUM(amount) FROM sales WHERE city='广州' AND store='京东便利店'",
    "sub_queries": [
      {
        "sub_query_id": "q_a1b2c3d4_sq1",
        "query": "广州市京东便利店的销售额是多少？",
        "status": "completed",
        "validated_sql": "SELECT SUM(amount) FROM ...",
        "error": null,
        "error_type": null,
        "failed_step": null
      }
    ],
    "_note": "sub_queries 为精简示例，完整字段参见 SubQueryInfo 定义（state.py）",
    "execution_results": [
      {
        "sub_query_id": "q_a1b2c3d4_sq1",
        "sql": "SELECT SUM(amount) FROM ...",
        "success": true,
        "columns": ["total_sales"],
        "rows": [[12345]],
        "row_count": 1,
        "execution_time_ms": 85.3,
        "error": null
      }
    ],
    "metadata": {
      "total_execution_time_ms": 1250.0,
      "router_latency_ms": 320.5,
      "planner_latency_ms": null,
      "parallel_execution_count": null,
      "sub_query_count": 1
    }
  }
  ```

  > **`sql` 字段说明**：`sql` 是否有值取决于子查询数量，而非 `complexity`。核心逻辑为 `sql = sub_queries[0].validated_sql if len(sub_queries) == 1 else None`（见 `state.py` 的 `extract_final_result()`）。前端应**直接判断 `sql` 是否为 `null`** 来决定展示模式，不要根据 `complexity` 推断：
  > - `sql` 非 `null`：展示单条 SQL + 单个 DataFrame。
  > - `sql` 为 `null`：遍历 `sub_queries` 列表获取各子查询的 `validated_sql`，遍历 `execution_results` 展示多组结果表格。

- **错误场景**：当推理失败时，`error` 字段非空，`summary` 仍会包含 Summarizer 节点生成的友好错误提示。外层 `BaseResponse.code` 仍为 200（业务级错误通过 `data.error` 传递），仅当系统级异常（如服务不可用）时 `code` 为 500。

#### 3) 获取历史会话列表
- **路径**: `GET /api/v1/sessions`
- **调用方**: Streamlit 侧边栏，用于渲染历史会话列表。
- **说明**: 获取指定用户最近的对话会话列表。底层调用 `chat_history_reader.list_recent_sessions()`。
- **Query 参数**:
  - `user_id`（可选，默认 `"guest"`）
  - `limit`（可选，默认 10，范围 1-50）
- **响应数据** (`data` 字段):
  ```json
  [
    {
      "thread_id": "guest:20260305T183946997Z",
      "created_at": "2026-03-05T18:39:46.997Z",
      "first_question": "请问广州市的京东便利店..."
    }
  ]
  ```
  > 注：`list_recent_sessions()` 返回的 `created_at` 是 `datetime` 对象，由 Pydantic 自动序列化为 ISO 8601 字符串。

#### 4) 恢复历史会话的对话上下文
- **路径**: `GET /api/v1/sessions/turns`
- **调用方**: Streamlit 前端，用户点击历史会话时调用。
- **说明**: **仅用于恢复历史问答上下文**，只返回 `question` 和 `answer` 文本。**不返回** SQL、执行结果、错误详情等技术数据。底层调用 `chat_history_reader.get_recent_turns()`。
- **Query 参数**:
  - `thread_id`（必填）：会话 ID。使用 Query 参数而非 Path 参数，因为 `thread_id` 包含 `:` 字符（如 `guest:20260305T183946997Z`），放在 URL 路径中可能被反向代理或 WAF 截断。
  - `limit`（可选，默认 50）：最多返回的对话轮数。
- **实现说明**: `get_recent_turns()` 需要 `history_max_turns` 和 `max_history_content_length` 两个必需参数。API 层处理方式：
  - `history_max_turns` = 请求的 `limit` 参数
  - `max_history_content_length` = 10000（对话恢复场景不截断，硬编码一个足够大的值）
- **响应数据** (`data` 字段):
  ```json
  [
    {
      "question": "广州的销售额",
      "answer": "广州的销售额是..."
    }
  ]
  ```
  > 注意：此处只有纯文本问答。前端加载历史后，这些消息**没有技术详情折叠面板**，仅展示问答文本。

### 2.5 应用生命周期（Lifespan）

使用 FastAPI 的 `lifespan` 上下文管理器处理启动和关闭逻辑：

```python
# src/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动阶段 ----
    from src.api.core.logging import init_api_logging
    logger = init_api_logging()

    from src.modules.nl2sql_father.graph import get_compiled_father_graph
    get_compiled_father_graph()
    logger.info("LangGraph 父图预编译完成")
    yield
    # ---- 关闭阶段 ----
    from src.services.langgraph_persistence.chat_history_reader import shutdown_read_executor
    from src.services.langgraph_persistence.chat_history_writer import shutdown_write_executor
    from src.services.langgraph_persistence.postgres import close_persistence
    shutdown_read_executor()
    shutdown_write_executor()
    close_persistence()
    logger.info("资源已释放（读写线程池 + 持久化连接）")

app = FastAPI(title="NL2SQL API", version="0.1.0", lifespan=lifespan)

# CORS 中间件（允许 Streamlit 跨域调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发阶段允许所有来源，生产环境应限制
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
from src.api.routers import query, history
app.include_router(query.router, prefix="/api/v1")
app.include_router(history.router, prefix="/api/v1")
```

### 2.6 并发安全说明

FastAPI 使用线程池执行 `def` 路由，多个用户同时发起查询时需注意：

- **图编译缓存**（`_compiled_graph` 等模块级变量）：首次访问时存在竞态条件，但 `lifespan` 启动阶段已调用 `get_compiled_father_graph()` 预热，因此正常运行时不会触发竞态。
- **配置缓存**（`_father_graph_config_cache`、`_summarizer_config_cache` 等）：首次加载时存在理论上的竞态，但 Python GIL 保证了字典赋值的原子性，最坏情况是重复加载一次配置文件，不会导致错误。
- **`run_nl2sql_query()` 本身是无状态的**：每次调用都会创建独立的 `initial_state`，不共享可变数据，因此多线程并发调用是安全的。

### 2.7 日志设计

FastAPI 入口需要完成**两步**日志初始化，与现有 CLI 入口（`nl2sql_father_cli.py`）保持一致的模式：

**第一步：初始化全局日志体系**。调用 `setup_logging_from_yaml()`，加载 `src/configs/logging.yaml`，确保核心模块（`nl2sql.*`）的日志正常输出到控制台和 `logs/sql_subgraph.log` 等文件。这一步保证了 FastAPI 调用核心函数时，核心模块的日志行为与 CLI 模式完全一致。

**第二步：追加 API 专属日志**。在全局日志基础上，为 API 层额外创建一个独立的 logger，输出到 `logs/fastapi.log`，不与核心算法日志混用。

```python
# src/api/core/logging.py
import logging
from pathlib import Path
from src.utils.logger import setup_logging_from_yaml, setup_module_logger

def init_api_logging():
    """初始化 API 日志（全局 + API 专属）

    对标 CLI 入口 nl2sql_father_cli.py 的做法：
    - 先 setup_logging_from_yaml() 初始化全局日志体系
    - 再 setup_module_logger() 追加 API 专属日志
    """
    project_root = Path(__file__).parent.parent.parent.parent
    yaml_path = str(project_root / "src" / "configs" / "logging.yaml")
    setup_logging_from_yaml(yaml_path)

    return setup_module_logger(
        "fastapi",
        log_file="logs/fastapi.log",
        level=logging.INFO,
        console=True,
    )
```

- **API 专属日志文件**: `logs/fastapi.log`
- **轮转策略**: `RotatingFileHandler`（按文件大小轮转，与项目其他模块一致）
- **记录内容**: HTTP 请求路径、客户端 IP、请求耗时、`query_id`（trace_id）、未捕获异常

---

## 三、 Streamlit 前端定制化设计

### 3.1 目录结构规划

在项目根目录下新建前端模块：

```text
frontend/
  app.py                 # Streamlit 主入口程序
  api_client.py          # 封装对 FastAPI 的 requests 调用
  logger.py              # 前端独立日志配置
  .streamlit/
    config.toml          # 全局主题和样式定制
```

### 3.2 Session State 管理

Streamlit 每次用户交互都会重新执行整个脚本，因此所有跨交互的状态必须显式存储在 `st.session_state` 中。

**核心状态字段定义：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `user_id` | `str` | `"guest"` | 当前用户标识 |
| `thread_id` | `Optional[str]` | `None` | 当前会话 ID，`None` 表示新会话 |
| `messages` | `list[dict]` | `[]` | 当前对话消息列表（见下方两种结构） |

**`messages` 列表中的消息分为两类：**

1. **历史消息**（从 `/turns` 接口加载，仅包含问答文本）：
   ```python
   {"role": "user", "content": "广州的销售额"}
   {"role": "assistant", "content": "广州的销售额是..."}
   ```

2. **当前轮消息**（从 `/query` 接口返回，包含技术详情）：
   ```python
   {"role": "user", "content": "广州的销售额"}
   {"role": "assistant", "content": "广州的销售额是...", "detail": {
       "sql": "SELECT ...",
       "sub_queries": [...],
       "execution_results": [...],
       "error": None
   }}
   ```

> **核心规则**：`detail` 字段**仅在当前轮查询**时由 `/query` 接口的返回数据填充。历史消息**没有** `detail` 字段。前端渲染时，有 `detail` 的消息展示技术详情折叠面板，无 `detail` 的消息只展示纯文本。

**状态初始化逻辑（在 `app.py` 顶部执行）：**

```python
if "user_id" not in st.session_state:
    st.session_state.user_id = "guest"
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
```

**关键状态流转：**

- **新建对话**：重置 `thread_id = None`，清空 `messages = []`。
- **点击历史会话**：设置 `thread_id = 选中的会话 ID`，调用 `GET /api/v1/sessions/turns?thread_id=...` 加载历史问答，转换为 `{"role", "content"}` 格式（无 `detail`）填充到 `messages`。
- **发送查询后**：`api_client.submit_query()` 返回的是已解包的业务数据（即 `BaseResponse.data`），直接从中取 `data["thread_id"]` 回写到 `st.session_state.thread_id`（首次查询时后端自动生成的 ID），同时将用户消息和带 `detail` 的 assistant 消息追加到 `messages`。

### 3.3 UI 界面元素编排设计

整个界面采用经典的"左右分栏"结构，最大化利用屏幕空间，同时保持对话的专注度。

#### 1) 左侧边栏 (`st.sidebar`)：会话管理与身份
- **用户身份区**:
  - `st.text_input("当前用户", value="guest")`：允许快速切换用户身份。
- **新建对话按钮**:
  - 放置一个醒目的 `st.button("+ 新建对话", type="primary")`，点击后清空 `st.session_state.thread_id` 和 `st.session_state.messages`。
- **历史记录列表**:
  - 调用 `GET /api/v1/sessions` 接口。
  - 使用 `st.radio` 或自定义样式的按钮列表展示（如：`2026-03-05 广州市销售额...`）。
  - 用户点击列表项时，更新 `st.session_state.thread_id`，并调用 `/turns` 接口拉取历史记录填充到 `st.session_state.messages`。

#### 2) 右侧主区域：对话窗口
- **欢迎横幅 / 状态展示**:
  - 顶部显示当前会话的 `thread_id`（仅作提示，可调暗颜色）。
- **消息滚动区 (`st.chat_message`)**:
  - **用户消息**: 右侧头像，显示用户输入。
  - **AI 消息**: 左侧机器人头像。渲染逻辑根据消息是否有 `detail` 字段区分两种模式：

  **模式 A — 历史消息（无 `detail`）**：仅显示 `content` 纯文本，不展示技术详情面板。

  **模式 B — 当前轮消息（有 `detail`）**：展示分为两层：
    1. **自然语言总结**: 顶层直接显示 `content`（即 `summary`，清晰易读）。
    2. **技术详情折叠面板 (`st.expander`)**:
       - 标题为"查看执行的 SQL 与明细数据"。
       - `detail.sql` 非 `null`（单子查询）：展示单条 SQL + 单个 DataFrame。
       - `detail.sql` 为 `null`（多子查询）：遍历 `detail.sub_queries` 列表，为每个子查询展示其 `validated_sql` 和对应的执行结果 DataFrame。
       - SQL 使用 `st.code(sql, language="sql")` 语法高亮。
       - 表格使用 `st.dataframe(df, use_container_width=True)`。
    3. **错误提示**：当 `detail.error` 非空时，在 expander 内使用 `st.warning()` 展示错误详情。

  > **显示规则总结**：当前轮可看技术详情（SQL、结果表、错误），历史轮只看问答文本。这是因为历史数据（`/turns` 接口）仅存储了 question/answer，不存储 SQL 和执行结果。

- **输入停靠区 (`st.chat_input`)**:
  - 永远固定在屏幕底部，提示词如："请输入您的数据查询需求..."。
  - 发送查询时显示 `st.spinner("正在分析您的问题...")`。

### 3.4 API Client 封装

`frontend/api_client.py` 封装所有 FastAPI 调用，统一处理超时和异常。

**解包约定**：所有业务接口（`/query`、`/sessions`、`/turns`）的返回都包裹在 `BaseResponse` 中，`api_client` 内部统一解包 `resp.json()["data"]`，调用方拿到的直接是业务数据，无需再关心外层信封。`health_check` 是例外接口（见 2.4 第 1 条），只判断 HTTP 状态码。

```python
# frontend/api_client.py
import os
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8008/api/v1")
DEFAULT_TIMEOUT = 120  # 秒，NL2SQL 查询可能较慢

class NL2SQLApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url

    def _unwrap(self, resp: requests.Response) -> dict | list | None:
        """统一解包 BaseResponse，返回 data 字段"""
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 200:
            raise RuntimeError(f"API 业务错误: {body.get('message')}")
        return body.get("data")

    def health_check(self) -> bool:
        """检查后端是否可用（例外接口，不走 BaseResponse）"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def submit_query(self, query: str, user_id: str = "guest",
                     thread_id: str | None = None) -> dict:
        """提交 NL2SQL 查询，返回解包后的业务数据（即 extract_final_result 的输出）"""
        payload = {"query": query, "user_id": user_id}
        if thread_id:
            payload["thread_id"] = thread_id
        resp = requests.post(
            f"{self.base_url}/query",
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._unwrap(resp)

    def list_sessions(self, user_id: str = "guest", limit: int = 10) -> list:
        """获取历史会话列表，返回解包后的会话列表"""
        resp = requests.get(
            f"{self.base_url}/sessions",
            params={"user_id": user_id, "limit": limit},
            timeout=10,
        )
        return self._unwrap(resp)

    def get_turns(self, thread_id: str, limit: int = 50) -> list:
        """获取会话对话明细，返回解包后的问答列表"""
        resp = requests.get(
            f"{self.base_url}/sessions/turns",
            params={"thread_id": thread_id, "limit": limit},
            timeout=10,
        )
        return self._unwrap(resp)
```

### 3.5 主题与定制化 (`.streamlit/config.toml`)

采用偏向商业 BI 系统的配色风格：

```toml
[theme]
primaryColor = "#2563eb"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f8fafc"
textColor = "#1e293b"
font = "sans serif"

[server]
maxUploadSize = 50
```

### 3.6 前端独立日志设计
- **文件位置**: `logs/streamlit.log`
- **设计策略**:
  - Streamlit 进程**不需要**调用 `setup_logging_from_yaml()` 初始化核心模块日志（它不会直接调用核心函数，核心逻辑在 FastAPI 进程中执行）。
  - 只需使用 `setup_module_logger()` 创建前端专属日志即可。
  - 轮转策略：`RotatingFileHandler`（按文件大小轮转，与项目其他模块一致）。
  - 记录内容：Session State 状态切换（新建会话、切换历史记录）、调用 FastAPI 接口的网络延迟与 HTTP 状态码。
  - 异常捕获：如果 FastAPI 服务不可用，Streamlit 捕获 `requests.RequestException` 并通过 `logger.error` 写入前端日志，同时在 UI 上使用 `st.error("后端服务未启动，请检查 FastAPI 是否运行中。")` 优雅提示用户。

```python
# frontend/logger.py
from src.utils.logger import setup_module_logger

streamlit_logger = setup_module_logger(
    "streamlit",
    log_file="logs/streamlit.log",
)
```

> **导入前提**：Streamlit 必须从项目根目录启动（`streamlit run frontend/app.py`），确保 `src` 包在 Python 路径中。如果使用 `uv pip install -e ".[web]"` 安装了项目，则无需额外设置 `PYTHONPATH`。

---

## 四、 启动方式

### 4.1 开发环境

需要**两个终端**分别启动后端和前端：

```bash
# 终端 1：启动 FastAPI 后端
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：启动 Streamlit 前端
streamlit run frontend/app.py --server.port 8501
```

### 4.2 API Base URL 配置

Streamlit 前端访问 FastAPI 的地址通过环境变量配置（`.env` 中新增）：

```bash
# .env 新增
API_BASE_URL=http://localhost:8008/api/v1   # FastAPI 后端地址
```

`api_client.py` 中通过 `os.getenv("API_BASE_URL", "http://localhost:8008/api/v1")` 读取。

> **`.env` 加载注意**：项目的 `.env` 自动加载依赖 `src/utils/env.py` 模块被导入时触发（模块底部的 `load_env()` 调用）。FastAPI 进程会在加载核心模块时自动触发此链路。但 **Streamlit 进程不会自动导入核心模块**，因此需要在 `frontend/app.py` 启动时显式加载：
> ```python
> from dotenv import load_dotenv
> load_dotenv()  # 加载项目根目录的 .env
> ```
> 或者在启动 Streamlit 之前通过 shell 手动 export 环境变量，不依赖 `.env` 自动加载。

### 4.3 与现有 CLI 的兼容性

FastAPI + Streamlit 模块与现有 CLI 完全独立，互不影响：

- **CLI 路径**: `scripts/nl2sql_father_cli.py` → 直接调用 `run_nl2sql_query()`
- **API 路径**: `src/api/main.py` → FastAPI 路由 → 同样调用 `run_nl2sql_query()`

两者共享同一个核心函数、同一份配置（`config.yaml`）、同一套持久化存储（checkpoint + store）。

**日志差异说明**：CLI 和 API 都会先加载全局 `logging.yaml`，因此核心模块（`nl2sql.*`）的日志在两种模式下行为一致，都输出到控制台和 `logs/sql_subgraph.log`（由 `logging.yaml` 配置决定）。API 模式额外拥有 `logs/fastapi.log`，记录 HTTP 请求级别的日志。

---

## 五、 实施步骤建议

1. **第一阶段：跑通 FastAPI 核心骨架**
   - 搭建 `src/api/` 目录结构，配置日志和 CORS。
   - 实现 `GET /health` 和 `POST /query`，使用 Postman/curl 测试通过。
2. **第二阶段：完善历史接口**
   - 实现 `GET /sessions` 和 `GET /sessions/turns`。
   - 补充 Pydantic 请求/响应 Schema。
3. **第三阶段：Streamlit 基础对话**
   - 编写 `frontend/api_client.py` 联调后端。
   - 实现单轮对话：输入 → Spinner → 输出解析 → Summary + SQL + DataFrame 渲染。
4. **第四阶段：会话管理与美化**
   - 接入侧边栏历史列表和会话切换。
   - 应用 `config.toml` 主题，配置 `logs/streamlit.log`。
