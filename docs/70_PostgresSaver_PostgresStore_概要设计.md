# 70_PostgresSaver/PostgresStore 概要设计（Checkpoint + 历史对话写入）

> 目标：在**现有代码架构不推翻**的前提下，为父图（`nl2sql_father`，业务上称 `nl2sql_generation`）与子图（`sql_generation` subgraph）引入 `langgraph-checkpoint-postgres==3.0.2` 提供的：
>
> - `PostgresSaver`：用于 **LangGraph checkpoint 持久化**
> - `PostgresStore`：用于 **历史对话信息写入（仅写入，暂不读取）**
>
> 本文是基于当前仓库代码现状给出的**概要设计**，包含模块拆分、配置设计、关键接入点、数据模型与演进路线。

---

## 1. 背景与现状（代码事实）

### 1.1 Checkpoint（LangGraph checkpointer）

- 父图配置存在但**未被代码消费**：`src/modules/nl2sql_father/config/nl2sql_father_graph.yaml` 中 `observability.save_checkpoints: false`，但 `graph.py` 中没有任何代码读取和使用该配置（仅为占位预留）。
- 父图编译未传入 `checkpointer`：`src/modules/nl2sql_father/graph.py` 中 `app = graph.compile()`。
- 子图同样未传入 `checkpointer`：`src/modules/sql_generation/subgraph/create_subgraph.py` 中 `compiled = subgraph.compile()`。

结论：当前系统**没有启用** LangGraph 的 checkpoint 机制（无 MemorySaver/SqliteSaver/PostgresSaver）。

### 1.2 历史对话持久化（Long-term memory）

- 父图 `State` 并不包含 `messages`，也不继承 `MessagesState`：`src/modules/nl2sql_father/state.py`。
- 子图 `State` 继承 `MessagesState`，但仅用于单次子图执行期间：`src/modules/sql_generation/subgraph/state.py`。
- 子图运行完成后只做日志快照，并未持久化：`src/modules/sql_generation/subgraph/create_subgraph.py`（仅打印 messages_count）。

结论：当前系统**没有跨请求/跨会话**的对话历史持久化。

---

## 2. 需求与非需求

### 2.1 需求（本阶段）

1. 为父图与子图提供 Postgres checkpointer（`PostgresSaver`）的接入方案，用于保存 checkpoint。
2. 使用 `PostgresStore` **写入**历史对话信息（仅规划写入，不规划读取）。
3. 持久化失败时不影响主流程（降级为“只打日志”）。
4. 与现有 `query_id`/日志体系兼容，引入 `thread_id` 支持多轮会话。

### 2.2 非需求（明确不做）

- 不在本阶段实现"从 `PostgresStore` 读取历史对话并注入 prompt/state"的能力。
- 不要求落地到某个具体 API（例如 FastAPI route）上；以现有 `run_nl2sql_query()` / `run_sql_generation_subgraph()` 为主要接入点给出设计。
- 不强制变更父图 State 为 `MessagesState`（避免影响现有 reducer/字段语义）；历史对话写入采用"旁路写入"。

### 2.3 前置依赖（实施前必须添加）

本设计依赖 `langgraph-checkpoint-postgres` 库。**实施前请检查 `pyproject.toml`：如未添加该依赖则需添加；以仓库当前实际依赖为准**。

#### 2.3.1 需要添加的依赖

```toml
# pyproject.toml 需要新增
dependencies = [
    # ... 现有依赖
    "langgraph-checkpoint-postgres==3.0.2",  # Checkpoint 持久化核心库（建议锁定版本；如需允许升级可用 >=3.0.2,<4）
]
```

#### 2.3.2 版本兼容性说明

| LangGraph 版本 | langgraph-checkpoint-postgres 版本 | 兼容性 |
|----------------|-------------------------------------|--------|
| `>=1.0.0`      | `==3.0.2`                           | ✅ 本阶段锁定版本 |
| `<1.0.0`       | `==3.0.2`                           | ⚠️ 可能不兼容 |

> **版本策略**：本阶段锁定 `langgraph-checkpoint-postgres==3.0.2`，升级需单独验证兼容性后再修改版本约束。

#### 2.3.3 已有依赖确认

以下依赖已存在于项目中，无需额外添加：

| 依赖包 | 当前版本 | 用途 |
|--------|----------|------|
| `psycopg[binary]` | `>=3.1.0` | PostgreSQL 驱动（同步） |
| `psycopg-pool` | `>=3.2.7` | 连接池管理 |
| `langgraph` | `>=1.0.0` | LangGraph 核心 |

---

## 3. 总体方案概览

### 3.1 两类持久化的职责边界

| 组件 | 作用 | 触发时机 | 存储内容 | 读取计划 |
|---|---|---|---|---|
| `PostgresSaver`（checkpointer） | LangGraph 执行过程 checkpoint | 图执行过程中自动发生 | 图的中间状态/写入（由 LangGraph 定义） | 未来可用于 resume/time-travel |
| `PostgresStore`（store） | 历史对话写入（long-term memory） | 每次父图执行结束（或异常结束） | 用户问题/最终回答（可选：SQL、元数据） | 本阶段不做 |

### 3.2 会话标识（thread_id / query_id）

LangGraph checkpoint 通常需要一个稳定的 "thread" 维度来区分不同会话执行链路。

本项目当前只有 `query_id`（`q_xxxxxxxx`），语义更接近"单次请求 ID"，并非多轮会话 ID。

#### 3.2.1 thread_id 设计

**格式定义**：

```
thread_id = {user_id}:{timestamp}
```

| 组成部分 | 说明 | 示例 |
|----------|------|------|
| `user_id` | 用户标识，未登录时为 `guest` | `alice`、`guest` |
| `timestamp` | ISO 8601 紧凑格式，UTC 时间，精确到毫秒 | `20251219T163045123Z` |
| 分隔符 | 冒号 `:`（**在 thread_id 中仅出现一次**） | - |

**user_id 字符集约束**：

为保证 `thread_id` 可正确解析，`user_id` 必须满足以下约束：

| 约束 | 说明 |
|------|------|
| **禁止字符** | 冒号 `:`（thread_id 分隔符）、井号 `#`（Store key 分隔符） |
| **允许字符** | `[a-zA-Z0-9_-]`（字母、数字、下划线、连字符） |
| **正则表达式** | `^[a-zA-Z0-9_-]+$` |
| **长度限制** | 1-64 字符（建议） |

```python
import re

USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

def validate_user_id(user_id: str) -> bool:
    """校验 user_id 是否符合规范"""
    if not user_id or len(user_id) > 64:
        return False
    return bool(USER_ID_PATTERN.match(user_id))

def sanitize_user_id(user_id: str | None) -> str:
    """清理并返回合法的 user_id，不合法时返回 'guest'"""
    if user_id and validate_user_id(user_id):
        return user_id
    return "guest"
```

**时间戳格式说明**：

| 部分 | 位数 | 说明 | 示例 |
|------|------|------|------|
| `YYYYMMDD` | 8 位 | 日期（年月日） | `20251219` |
| `T` | 1 位 | 日期与时间的分隔符 | `T` |
| `HHmmssSSS` | **9 位连续数字**（无分隔） | 时间：HH(2)+mm(2)+ss(2)+SSS(3) | `163045123` |
| `Z` | 1 位 | UTC 时区标识 | `Z` |

> **注意**：`HHmmssSSS` 是 **9 位连续数字**，不含任何分隔符。例如 `163045123` 表示 `16:30:45.123`。

> **为什么使用 UTC**：统一时区避免跨地域部署时的时间混乱；`Z` 后缀明确表示 UTC，便于日志分析和排查。

**完整示例**：

```
guest:20251219T163045123Z      # 游客会话（UTC 时间 16:30:45.123）
alice:20251219T163045456Z      # 已登录用户 alice
bob:20251219T163045789Z        # 已登录用户 bob
```

#### 3.2.2 生成规则

| 场景 | thread_id | 说明 |
|------|-----------|------|
| 外部传入 | 使用传入值 | 支持多轮对话复用同一 thread_id |
| 未传入 + 有 user_id | 自动生成 `{user_id}:{timestamp}` | 新会话 |
| 未传入 + 无 user_id | 自动生成 `guest:{timestamp}` | 游客新会话 |

```python
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# thread_id 格式正则：{user_id}:{timestamp}
# - user_id: [a-zA-Z0-9_-] 重复 1-64 次（不含 : 和 #）
# - timestamp: YYYYMMDD + T + HHmmssSSS + Z（8位日期 + T + 9位时间 + Z = 19位）
THREAD_ID_PATTERN = re.compile(
    r"^[a-zA-Z0-9_-]+"           # user_id（1-64 字符，后续用 len 校验上限）
    r":"                          # 分隔符
    r"\d\d\d\d\d\d\d\d"           # YYYYMMDD（8 位日期）
    r"T"                          # 日期时间分隔符
    r"\d\d\d\d\d\d\d\d\d"         # HHmmssSSS（9 位时间，含毫秒）
    r"Z$"                         # UTC 时区标识
)

def validate_thread_id(thread_id: str) -> bool:
    """校验 thread_id 格式是否合法
    
    合法格式：{user_id}:{timestamp}
    - 恰好一个 `:` 分隔符
    - 不含 `#`（Store key 分隔符）
    - user_id 符合 [a-zA-Z0-9_-]{1,64}（长度 1-64）
    - timestamp 符合 YYYYMMDDTHHmmssSSS + Z（19位固定格式）
    """
    if not thread_id or "#" in thread_id:
        return False
    return bool(THREAD_ID_PATTERN.match(thread_id))

def get_or_generate_thread_id(thread_id: str | None, user_id: str | None) -> str:
    """获取或自动生成 thread_id
    
    Args:
        thread_id: 外部传入的会话 ID（多轮对话时复用）
        user_id: 用户标识（未登录时为 None，不合法时回退为 guest）
    
    Returns:
        thread_id，格式：{user_id}:{timestamp}
        示例：guest:20251219T163045123Z
    
    行为：
        - 传入合法 thread_id → 直接使用
        - 传入非法 thread_id → 降级为自动生成（记录 warning）
        - 未传入 thread_id → 自动生成
    """
    if thread_id:
        if validate_thread_id(thread_id):
            return thread_id  # 合法，直接用
        else:
            # 非法 thread_id，降级为自动生成
            logger.warning(f"Invalid thread_id format: {thread_id}, will generate new one")
            # 继续走自动生成逻辑
    
    # 自动生成（使用 UTC 时间）
    user = sanitize_user_id(user_id)  # 校验 user_id，不合法则回退为 guest
    now = datetime.now(timezone.utc)
    # 格式：YYYYMMDDTHHmmssSSS + Z（ISO 8601 紧凑格式，UTC）
    timestamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
    return f"{user}:{timestamp}"

def parse_thread_id(thread_id: str) -> tuple[str, str]:
    """解析 thread_id，提取 user_id 和 timestamp
    
    Args:
        thread_id: 格式为 {user_id}:{timestamp}
    
    Returns:
        (user_id, timestamp) 元组
    
    Raises:
        ValueError: 格式不正确
    """
    if not validate_thread_id(thread_id):
        raise ValueError(f"Invalid thread_id format: {thread_id}")
    return thread_id.split(":", 1)

def get_user_id_from_thread_id(thread_id: str) -> str:
    """从 thread_id 反推 user_id
    
    Args:
        thread_id: 格式为 {user_id}:{timestamp}
    
    Returns:
        user_id（如解析失败返回 'guest'）
    """
    try:
        user_id, _ = parse_thread_id(thread_id)
        return user_id
    except ValueError:
        return "guest"
```

#### 3.2.3 与 query_id 的关系

> **术语说明**：`query_id` 即对话系统中的 `turn_id`（一轮对话的标识）。本项目统一使用 `query_id`，与现有代码字段保持一致。

| 标识 | 语义 | 生命周期 | 示例 |
|------|------|----------|------|
| `thread_id` | 会话标识（多轮共享） | 整个会话 | `alice:20251219T163045123Z` |
| `query_id` | 单次请求标识（即 turn_id） | 单次请求 | `q_abc123` |

同一会话的多轮对话：

```
第 1 轮：thread_id = "alice:20251219T163045123Z", query_id = "q_001"
第 2 轮：thread_id = "alice:20251219T163045123Z", query_id = "q_002"  ← 同一 thread_id
第 3 轮：thread_id = "alice:20251219T163045123Z", query_id = "q_003"  ← 同一 thread_id
```

具体接入方式见 6.3。

### 3.3 父/子图 State 兼容性与现有 wrapper 设计合理性

当前父图与子图的 State **不兼容（不共享同一套 schema）**，这是现状也是合理的分层：

- 父图 `NL2SQLFatherState` 是编排/执行态：包含 `sub_queries`、`execution_results`、`dependency_graph` 等业务编排字段，但**不维护** `messages`。
- 子图 `SQLGenerationState` 继承 `MessagesState`：承载 LLM 交互所需的 `messages`、以及 `schema_context`、`validation_history` 等子图内部属性。
- 现有实现通过父图 wrapper（`sql_gen_wrapper`/`sql_gen_batch_wrapper`）做“**显式入参映射 + 显式出参映射**”，只把必要字段在父子图之间传递（例如 `query_id`、`user_query`、`dependencies_results`），避免父图被子图内部大字段污染。

该设计对本阶段的持久化规划是正向的：

- **PostgresSaver/checkpoint**：各图保存各自 state；父图不含 `messages` 只意味着父图 checkpoint 不包含对话消息，不影响启用 checkpoint。
- **PostgresStore/历史对话（仅写）**：本阶段只保存“用户可见对话”（`user_query` + `summary` + 少量元数据），放在父图执行结束处旁路写入即可；子图内部 `messages` 不应默认进入长期记忆（体积/敏感性更高）。

重要澄清：在当前“父图 wrapper 直接调用 `subgraph.invoke(initial_state)`”的模式下，子图**不会自动继承**父图里同名字段；子图能看到的仅是 wrapper 显式传入的 `initial_state` 键。若未来希望“同名字段自动流转”，需要把子图作为 LangGraph 子图节点集成到父图并做 state/schema 对齐或显式映射（属于后续演进，不是本阶段必需）。

---

## 4. 配置设计（建议）

### 4.1 系统级（`src/configs/config.yaml`）增加 langgraph_persistence 配置块

建议新增（示例），并尽量与现有配置风格保持一致（例如 `vector_database.providers.pgvector.use_global_config` 的命名习惯）：

```yaml
langgraph_persistence:
  enabled: false  # 总开关

  # 数据库连接（复用 database.* 或独立配置）
  database:
    use_global_config: true  # true: 从 database.* 组装 URI；false: 使用 db_uri
    db_uri: ${LANGGRAPH_DB_URI:}  # 仅当 use_global_config=false 时生效（URI 格式）
    schema: ${LANGGRAPH_SCHEMA:langgraph}  # 独立 schema，避免与业务表混用
    sslmode: ${LANGGRAPH_DB_SSLMODE:}  # 可选：disable/require/verify-ca 等，留空则不设置

  # Checkpoint 配置
  checkpoint:
    enabled: false
    father_namespace: nl2sql_father      # 父图 checkpoint_ns，代码中通过配置读取
    subgraph_namespace: sql_generation   # 子图 checkpoint_ns 前缀，代码中通过配置读取

  # Store 配置（本阶段仅写入历史对话，不规划读取）
  store:
    enabled: false  # 默认关闭，Phase B 时开启
    namespace: chat_history
    retention_days: 90  # 预留：后续清理策略
```

说明：
- `enabled` 为总开关；`checkpoint.enabled` 与 `store.enabled` 分开控制，便于分阶段上线。
- **本项目持久化统一使用 URI 格式**（如 `postgresql://user:pass@host:port/dbname?sslmode=disable`）
- 连接方式通过 `database.use_global_config` 明确"二选一"：
  - `true`：从现有 `database.*` 配置组装 URI（见下方 `build_db_uri_from_config()` 示例）
  - `false`：直接使用 `database.db_uri`
- `database.schema` 建议默认 `langgraph`，与业务表/向量表隔离。

**Checkpoint 类说明**：

本阶段使用 `PostgresSaver`（完整 checkpoint，保存全量 state）。

```python
from langgraph.checkpoint.postgres import PostgresSaver
```

> **未来优化**：如遇 state 体积过大导致 checkpoint 表膨胀或写入延迟问题，可考虑引入 `ShallowPostgresSaver`（浅层 checkpoint，仅保存 metadata），届时需另行评估并更新设计。

### 4.2 图级开关（保持现有配置习惯）

父图目前已存在：`nl2sql_father_graph.yaml -> observability.save_checkpoints`。

建议：
- 保留现有字段作为"图级开关"，最终生效条件为：系统级与图级同时启用。
- 子图配置（`sql_generation_subgraph.yaml`）可新增类似字段（如 `observability.save_checkpoints` 或 `observability.persist_messages`），用于控制是否对子图启用 checkpointer。

**开关生效条件公式**：

```python
# Checkpoint 生效条件（父图）
father_checkpoint_enabled = (
    langgraph_persistence.enabled                     # 系统总开关
    and langgraph_persistence.checkpoint.enabled      # checkpoint 组件开关
    and nl2sql_father_graph.observability.save_checkpoints  # 图级开关
)

# Checkpoint 生效条件（子图）
subgraph_checkpoint_enabled = (
    langgraph_persistence.enabled
    and langgraph_persistence.checkpoint.enabled
    and sql_generation_subgraph.observability.save_checkpoints  # 子图级开关（新增）
)

# Store 生效条件
store_enabled = (
    langgraph_persistence.enabled                     # 系统总开关
    and langgraph_persistence.store.enabled           # store 组件开关
)
```

> **注意**：实现时需统一使用上述公式，避免各模块对开关判断逻辑不一致。

---

## 5. 模块拆分（建议新增的代码模块形态）

> 本节描述“建议新增哪些模块与接口”，**用于后续实现**；本设计文档不要求立刻改动现有业务节点逻辑。

### 5.1 新增服务层模块（统一工厂 + 单例）

建议新增目录（示例）：

- `src/services/langgraph_persistence/postgres.py`
  - `get_postgres_saver(kind: Literal["father", "subgraph"]) -> PostgresSaver`
  - `get_postgres_store() -> PostgresStore`
  - `build_db_uri_from_config() -> str`（组装 URI 格式连接串）
  - `setup_persistence()`（启动时调用，内部调用 `checkpointer.setup()` 和 `store.setup()`；见 5.1.1/5.1.2 的 API 确认）
- `src/services/langgraph_persistence/safe_checkpointer.py`（可选：若实施 6.1.1 的 fail-open 策略）
  - `SafeCheckpointer`
    - 包装真实 checkpointer（如 `PostgresSaver`），捕获数据库异常/超时
    - 失败时记录 warning，并以 no-op 语义让主流程继续
    - 依赖前提：LangGraph 允许注入自定义 checkpointer（接口形态以实际版本为准）

设计要点：
- 当前代码路径均为同步执行，优先使用 `PostgresSaver` / `PostgresStore`（同步版）；异步版留到 FastAPI/async 场景再引入。
- 连接信息应与现有 `src/services/db/pg_connection.py` 的配置来源保持一致（统一从 `ConfigLoader/get_config()` 读）。
- 允许"失败降级"：创建 saver/store 失败时返回 `None`，上层逻辑仅记录 warning，不中断主流程。

**`build_db_uri_from_config()` 构建规则**（与 4.1 的"二选一"保持一致）：

- 若 `langgraph_persistence.database.use_global_config == false`：
  - 必须提供 `langgraph_persistence.database.db_uri`（非空），直接使用
- 若 `langgraph_persistence.database.use_global_config == true`：
  - 从现有 `database.host/port/database/user/password` 组装 URI 格式

**连接串格式：统一使用 URI 格式**

```
postgresql://user:password@host:port/dbname[?query_params]
```

> **Query 参数说明**：
> - `sslmode=disable`：可选，禁用 SSL（内网环境常用）
> - `options=-csearch_path=schema_name`：可选，设置默认 schema
> - 多个参数使用 `&` 连接，例如 `?sslmode=disable&options=...`

示例实现：

```python
from urllib.parse import quote_plus, urlencode

def build_db_uri_from_config() -> str:
    """从配置构建 PostgreSQL URI
    
    Returns:
        URI 格式连接串，如 postgresql://user:pass@host:port/dbname?sslmode=disable&options=...
    """
    config = get_config()
    persistence_config = config.get("langgraph_persistence", {})
    db_config = persistence_config.get("database", {})
    
    if not db_config.get("use_global_config", True):
        # 直接使用配置的 db_uri
        # 注意：此模式下 schema/sslmode 配置项不生效，需直接写入 db_uri 的 query 参数中
        # 例如：postgresql://user:pass@host:5432/dbname?sslmode=disable&options=-csearch_path=langgraph
        db_uri = db_config.get("db_uri")
        if not db_uri:
            raise ValueError("langgraph_persistence.database.db_uri is required when use_global_config=false")
        return db_uri
    
    # 从 database.* 组装 URI
    global_db = config.get("database", {})
    host = global_db.get("host", "localhost")
    port = global_db.get("port", 5432)
    database = global_db.get("database", "postgres")
    user = global_db.get("user", "postgres")
    password = quote_plus(global_db.get("password", ""))  # URL 编码密码
    
    # 构建 query 参数
    query_params = {}
    
    # sslmode（可选，来自 langgraph_persistence.database.sslmode）
    sslmode = db_config.get("sslmode")
    if sslmode:
        query_params["sslmode"] = sslmode
    
    # schema 作为 search_path（来自 langgraph_persistence.database.schema）
    schema = db_config.get("schema", "langgraph")
    if schema:
        # options 参数值需要特殊编码
        query_params["options"] = f"-csearch_path={schema}"
    
    # 组装 query string（urlencode 会正确处理多参数和特殊字符）
    query_string = f"?{urlencode(query_params)}" if query_params else ""
    
    return f"postgresql://{user}:{password}@{host}:{port}/{database}{query_string}"
```

> **注意**：
> - 现有 `PGConnectionManager._build_connection_string()` 返回的是 psycopg 格式（`host=... port=...`），但 `PostgresSaver.from_conn_string()` 接受 URI 格式，因此需要单独实现 `build_db_uri_from_config()`。
> - 使用 `urlencode()` 统一处理多个 query 参数，自动处理 `&` 连接和特殊字符编码。
> - 建议 schema 名仅使用 `[a-zA-Z0-9_]`，避免需要转义的字符。

#### 5.1.1 API 与 Import 路径验证（实施前必查）

`langgraph-checkpoint-postgres` 包**同时提供同步和异步版本**：
- 同步版：`PostgresSaver` / `PostgresStore`（本项目使用）
- 异步版：`AsyncPostgresSaver` / `AsyncPostgresStore`（FastAPI/async 场景用）

当前项目主流程为**同步执行**（使用 `psycopg` 和 `psycopg_pool`），应使用同步版类。

实施前需确认以下细节（避免 API 假设错误导致返工）：

| 验证项 | 说明 |
|--------|------|
| **Import 路径** | `from langgraph.checkpoint.postgres import PostgresSaver`（同步版）<br>`from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`（异步版） |
| **初始化方法** | 使用 `PostgresSaver.from_conn_string(LANGGRAPH_DB_URI)` 工厂方法（推荐） |
| **表初始化** | **首次使用前必须调用 `.setup()` 创建表**（幂等，可重复调用） |
| **连接参数格式** | 接受 URI 格式：`postgresql://user:pass@host:port/dbname?sslmode=disable` |
| **方法签名** | `put`/`get`/`list` 等方法的参数与返回类型见官方文档 |

**官方文档示例的初始化流程**（实施前需验证 import/运行无误）：

```python
import os
from langgraph.checkpoint.postgres import PostgresSaver

# 从环境变量或配置获取（与 langgraph_persistence.database.db_uri 对应）
LANGGRAPH_DB_URI = os.getenv("LANGGRAPH_DB_URI", "postgresql://user:password@host:5432/dbname?sslmode=disable")

# 同步版：使用 with 上下文管理器
with PostgresSaver.from_conn_string(LANGGRAPH_DB_URI) as checkpointer:
    checkpointer.setup()  # ✅ 首次使用：创建表 + 跑迁移（幂等）
    # ... 后续操作
```

```python
import os
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

LANGGRAPH_DB_URI = os.getenv("LANGGRAPH_DB_URI")

# 异步版
async with AsyncPostgresSaver.from_conn_string(LANGGRAPH_DB_URI) as checkpointer:
    await checkpointer.setup()  # ✅ 首次使用：创建表 + 跑迁移（幂等）
    # ... 后续操作
```

#### 5.1.2 PostgresStore API 验证（实施前必查）

本设计文档在 5.2/8 中使用了"`append_turn(...)` 写入一条对话记录"的抽象，底层调用 `PostgresStore` 的实际 API。

**官方文档示例的初始化流程**（实施前需验证 import/运行无误）：

```python
import os
from langgraph.store.postgres import PostgresStore

# 从环境变量或配置获取（与 langgraph_persistence.database.db_uri 对应）
LANGGRAPH_DB_URI = os.getenv("LANGGRAPH_DB_URI", "postgresql://user:password@host:5432/dbname?sslmode=disable")

# 同步版：使用 with 上下文管理器
with PostgresStore.from_conn_string(LANGGRAPH_DB_URI) as store:
    store.setup()  # ✅ 首次使用：创建表 + 跑迁移（幂等）
    # ... 后续操作（put/get/search 等）
```

```python
import os
from langgraph.store.postgres.aio import AsyncPostgresStore

LANGGRAPH_DB_URI = os.getenv("LANGGRAPH_DB_URI")

# 异步版
async with AsyncPostgresStore.from_conn_string(LANGGRAPH_DB_URI) as store:
    await store.setup()  # ✅ 首次使用：创建表 + 跑迁移（幂等）
    # ... 后续操作
```

**API 要点**：

| 项目 | 说明 |
|------|------|
| 初始化 | `PostgresStore.from_conn_string(LANGGRAPH_DB_URI)`（推荐） |
| 表初始化 | **首次使用前必须调用 `.setup()` 创建表**（幂等） |
| 写入 API | `store.put(namespace, key, value)` |
| 读取 API | `store.get(namespace, key)` / `store.search(namespace, query)` |

> **官方文档参考**：`PostgresStore.setup()` 方法在官方文档中有示例，与 `PostgresSaver.setup()` 行为一致（幂等，创建表+迁移）。**实施时需验证当前安装版本确实支持该方法**；若未来版本移除，需改用迁移脚本保障表结构。

**实施策略**：

- 在 `src/services/langgraph_persistence/chat_history_writer.py` 中保持 `append_turn(...)` 作为**项目内部 API**（稳定），底层调用 `store.put(...)` 方法。
- `namespace/key/value` 的类型要求与限制以官方文档为准。

#### 5.1.3 SafeCheckpointer 接口定义（可选实现）

若需实现 6.1.1 中的 fail-open 策略，`SafeCheckpointer` 应包装真实 checkpointer 并实现相同接口：

```python
import logging

logger = logging.getLogger(__name__)

class SafeCheckpointer:
    """Fail-open 适配层：捕获异常，失败时记录日志并返回空结果"""
    
    def __init__(self, real_checkpointer: PostgresSaver, timeout_seconds: float = 5.0):
        self._real = real_checkpointer
        self._timeout = timeout_seconds
    
    def put(self, config, checkpoint, metadata) -> None:
        """写入 checkpoint，失败时记录 warning 并跳过"""
        try:
            # 带超时的写入（实际实现方式依赖库接口）
            self._real.put(config, checkpoint, metadata)
        except Exception as e:
            logger.warning(f"Checkpoint 写入失败（已跳过）: {e}")
    
    def get(self, config) -> "Checkpoint | None":
        """读取 checkpoint，失败时返回 None"""
        try:
            return self._real.get(config)
        except Exception as e:
            logger.warning(f"Checkpoint 读取失败（返回 None）: {e}")
            return None
    
    # ... 其他接口方法（list, get_tuple 等）
```

> 注：接口签名以 LangGraph checkpointer 实际定义为准，上述仅为示意。

### 5.2 新增对话历史写入器（旁路写入）

建议新增：

- `src/services/langgraph_persistence/chat_history_writer.py`
  - `append_turn(thread_id, query_id, user_text, assistant_text, *, metadata: dict)`（项目内部抽象）
    - 函数名 `append_turn` 表示"追加一轮对话"，参数 `query_id` 即本轮的请求标识
  - 内部通过适配层调用 `PostgresStore` 的实际写入 API（仅写；具体方法以 3.0.2 实际接口为准）

写入触发点建议放在**父图调用结束后**（`run_nl2sql_query()`），因为父图能拿到最终 summary 与路径信息，且父图 State 当前不维护 `messages`。

### 5.3 模块目录结构

建议新增以下目录结构：

```
src/services/langgraph_persistence/
├── __init__.py                    # 模块导出
├── postgres.py                    # 核心工厂函数
│   ├── get_postgres_saver()       # 获取 PostgresSaver 实例（单例）
│   ├── get_postgres_store()       # 获取 PostgresStore 实例（单例）
│   ├── build_db_uri_from_config()  # 从配置构建 URI 格式连接串
│   └── setup_persistence()        # 启动时调用 .setup() 建表（幂等）
├── chat_history_writer.py         # 对话历史写入器
│   └── append_turn()              # 追加一轮对话记录
└── safe_checkpointer.py           # SafeCheckpointer（可选，fail-open 适配层）
    └── SafeCheckpointer           # 包装类
```

与现有服务层结构的关系：

```
src/services/
├── config_loader.py               # 现有：配置加载
├── db/
│   ├── pg_connection.py           # 现有：PostgreSQL 连接池
│   ├── pg_client.py               # 现有：PostgreSQL 客户端
│   └── migrations/                # 现有：迁移脚本（可选存放 DDL 备份）
├── embedding/                     # 现有：Embedding 服务
├── vector_adapter/                # 现有：向量数据库适配器
└── langgraph_persistence/         # 【新增】LangGraph 持久化服务
    └── ...
```

> **迁移策略说明**：
> - **推荐方式**：使用 `checkpointer.setup()` / `store.setup()` 自动建表（见 5.1.1/5.1.2），无需手动维护迁移脚本。
> - **显式迁移方式**（DBA 管理场景）：由 DBA 从官方文档获取最新 DDL 并执行；本项目不维护独立的 `langgraph.sql` 文件，避免与库版本升级产生不一致。

---

## 6. 父图接入设计（nl2sql_father / nl2sql_generation）

### 6.1 Checkpoint（PostgresSaver）

接入点：

1. 编译时传入 `checkpointer`
   - 现状：`src/modules/nl2sql_father/graph.py` 使用 `graph.compile()`。
   - 设计：当开关开启时改为 `graph.compile(checkpointer=postgres_saver, ...)`。

2. 调用时传入 thread_id 和 checkpoint_ns
   - 现状：`app.invoke(initial_state)` 没有配置项。
   - 设计：`app.invoke(initial_state, config={"configurable": {"thread_id": thread_id, "checkpoint_ns": father_namespace}})`
   - `checkpoint_ns` 取值来自配置 `langgraph_persistence.checkpoint.father_namespace`（默认 `"nl2sql_father"`）
   
   **thread_id 与 user_id 获取逻辑**（优先级从高到低）：
   
   | 优先级 | 条件 | thread_id 来源 | user_id 来源 |
   |--------|------|----------------|--------------|
   | 1 | 调用方传入 `thread_id` | 直接使用（多轮对话复用） | **从 thread_id 解析**（`get_user_id_from_thread_id()`） |
   | 2 | 仅传入 `user_id` | 自动生成 `{user_id}:{timestamp}` | 使用传入值（经 `sanitize_user_id()` 校验） |
   | 3 | 都未传入 | 自动生成 `guest:{timestamp}` | `guest` |
   
   ```python
   def run_nl2sql_query(
       query: str,
       query_id: str = None,
       thread_id: str = None,
       user_id: str = None,
   ) -> Dict[str, Any]:
       # 1. query_id 自动生成
       actual_query_id = query_id or f"q_{uuid.uuid4().hex[:8]}"
       
       # 2. thread_id 和 user_id 一致性处理（见 3.2.2 的函数定义）
       #    - 传入 thread_id → 从中解析 user_id
       #    - 仅传入 user_id → 自动生成 thread_id
       #    - 都未传入 → user_id=guest，自动生成 thread_id
       if thread_id and validate_thread_id(thread_id):
           actual_thread_id = thread_id
           actual_user_id = get_user_id_from_thread_id(thread_id)  # ← 从 thread_id 解析
       else:
           actual_user_id = sanitize_user_id(user_id)  # 校验或回退为 guest
           actual_thread_id = get_or_generate_thread_id(None, actual_user_id)
       
       # 3. 构建初始状态（create_initial_state 内部也有相同逻辑，见 6.3）
       initial_state = create_initial_state(
           user_query=query,
           query_id=actual_query_id,
           thread_id=actual_thread_id,
           user_id=actual_user_id,
       )
       
       # 4. 获取编译后的图
       app = get_compiled_father_graph()
       
       # 5. 获取 checkpoint_ns（从配置读取）
       persistence_config = get_config().get("langgraph_persistence", {})
       father_namespace = persistence_config.get("checkpoint", {}).get("father_namespace", "nl2sql_father")
       
       # 6. 调用图（传入 thread_id 和 checkpoint_ns 用于 checkpoint）
       final_state = app.invoke(
           initial_state,
           config={"configurable": {
               "thread_id": actual_thread_id,
               "checkpoint_ns": father_namespace,  # 从配置读取
           }},
       )
       # ...
   ```
   
   > **重要**：`user_id` 的来源规则与 `thread_id` 关联，详见 6.3 节 `create_initial_state()` 的一致性规则表。

3. 子图调用的 namespace 隔离（必须项，见 7.2）
   - Complex Path 会在同一 `thread_id` 下多次调用 SQL 生成子图；为避免 checkpoint "最新状态"相互覆盖、并提升可观测性，需要对子查询维度做 namespace 隔离（`sub_query_id`）。

**编译与 Checkpointer 生命周期**：

当前实现中，每次调用 `run_nl2sql_query()` 都会执行 `create_nl2sql_father_graph()`（即每次都编译图）。若传入 checkpointer，需考虑生命周期管理：

```python
# 现有实现（每次编译）
def run_nl2sql_query(query: str, query_id: str = None) -> Dict[str, Any]:
    app = create_nl2sql_father_graph()  # 每次调用都编译
    final_state = app.invoke(initial_state)
    ...
```

建议的优化方案：

1. **Checkpointer 单例**：通过 `get_postgres_saver()` 返回单例，避免每次请求创建连接
2. **编译图缓存**：将编译后的图缓存为模块级变量（首次调用时编译并缓存）

示例实现：

```python
# 模块级缓存
_compiled_graph: Optional[CompiledGraph] = None
_checkpointer: Optional[PostgresSaver] = None

def get_compiled_father_graph() -> CompiledGraph:
    global _compiled_graph, _checkpointer
    if _compiled_graph is None:
        # 获取 checkpointer（单例）
        _checkpointer = get_postgres_saver("father") if is_checkpoint_enabled() else None
        # 编译并缓存
        graph = StateGraph(NL2SQLFatherState)
        # ... 添加节点和边
        _compiled_graph = graph.compile(checkpointer=_checkpointer)
    return _compiled_graph
```

> **热更新注意事项**：若需支持运行时开关切换（不重启进程），需额外处理缓存失效逻辑：
> - 将 `_compiled_graph` 缓存与 `checkpoint.enabled` 配置值绑定（例如缓存 key 包含开关状态的 hash）
> - 开关变化时清空缓存，下次调用重新编译
> - 避免出现"开关已切换但仍使用旧编译图"的不一致状态
>
> 如无热更新需求（重启生效即可），可忽略此复杂度。

#### 6.1.1 Checkpoint 写入失败的"降级"策略（必须明确）

与 6.2 的“尾部写一次 store”不同，checkpoint 写入发生在图执行过程中；**若 checkpointer 在运行时抛异常，LangGraph 可能直接中断本次图执行**。因此需要在实施时明确“fail-open（继续跑）还是 fail-closed（失败即中断）”的策略。

本项目建议目标为：**fail-open（checkpoint best-effort，不影响主流程返回）**，但实现上需要以 LangGraph/checkpointer 的扩展点能力为准（实施前必查）。

建议的落地路径（按优先级）：

1. **预防为主（强烈建议）**：启用 checkpoint 前做 preflight
   - 启动时（或首次调用时）验证：数据库可连通、schema/表存在、权限足够、写入延迟在可接受范围
   - 为 checkpoint 专用连接设置 `statement_timeout`，避免单次写入长时间卡住
2. **可行则实现 fail-open（推荐）**：SafeCheckpointer 适配层
   - 若 LangGraph 允许注入自定义 checkpointer 并由其实现标准接口（例如 `put/get/list` 等），可在外层包一层 `SafeCheckpointer`：
     - 捕获所有数据库异常与超时
     - 记录 warning
     - 返回“未保存/无 checkpoint”的语义，让图继续跑（等价于 no-op）
3. **若无法 fail-open（保底）**：运维级降级
   - 保持 `checkpoint.enabled` 默认关闭，仅在验证稳定后逐步开启
   - 一旦发现 checkpointer 导致链路失败，第一时间通过配置关闭 checkpoint（恢复为当前版本行为）

> 注：`thread_id/checkpoint_ns` 的具体 key 名称以 LangGraph 1.0.x / checkpoint 3.x 的接口为准；设计上需要“可配置的 thread 维度”与“图 namespace 维度”。

### 6.2 历史对话写入（PostgresStore，仅写）

接入点：`src/modules/nl2sql_father/graph.py: run_nl2sql_query()`

写入时机：
- `final_state = app.invoke(...)` 之后
- `result = extract_final_result(final_state)` 之后（拿到 summary/metadata）

写入内容（建议最小可用）：

- `thread_id`（会话标识，格式：`{user_id}:{timestamp}`）
- `user_id`（用户标识，从 thread_id 解析或独立存储）
- `query_id`（单次请求标识）
- `user_query`
- `assistant_summary`（`result["summary"]`）
- `metadata`（复杂度、路径、耗时、子查询数量）

写入策略：
- 写入失败不影响返回（try/except + warn log）
- **只写追加**（append-only），避免覆盖导致并发丢失

#### 6.2.1 写入阻塞与用户耗时（必须考虑）

由于当前主流程为同步执行，任何 PostgreSQL 写入都会增加用户感知的响应时间；尤其是 checkpoint（图执行过程中多次写入）与对话历史（父图结束时写入）都可能在高峰期出现几十到几百毫秒的延迟。

建议按阶段优化写入策略：

- **写入策略 A（MVP）**：同步写入 + 严格超时控制（优先保证主流程返回）
  - 应用侧：对 `append_turn(...)` 设置总超时（建议 2–5 秒，默认 2 秒），超时直接跳过并记录 warning
  - 数据库侧：为该连接设置 `statement_timeout`（或等价机制），避免卡住线程
- **写入策略 B（优化）**：异步写入（后台线程/队列）
  - 将 `append_turn(...)` 放入后台线程（daemon）或进程内队列，由单独 worker 消费
  - 失败可丢弃（best-effort）或落盘缓冲（按运维要求决定）

> 注：本节的"写入策略 A/B"指 Store 写入方式的演进，与第 11 节"分阶段落地计划 Phase A/B/C"是不同维度的概念。

说明：
- `PostgresSaver` 写入发生在图执行期间，难以完全"异步化"；若对延迟敏感，优先通过开关控制、缩小 state（docs/20）来降低写入负担。

### 6.3 接口签名与入口接入（thread_id）

现状：父图便捷函数签名仅支持 `query_id`，无法从调用入口传入"多轮会话"的 `thread_id`。

建议：在不破坏现有调用方式的前提下，给 `run_nl2sql_query()` 增加可选参数 `thread_id` 和 `user_id`。

**父图便捷函数签名（建议变更）**

- 当前：`src/modules/nl2sql_father/graph.py` 中 `run_nl2sql_query(query: str, query_id: str = None)`
- 建议：
  - `run_nl2sql_query(query: str, query_id: str = None, thread_id: str = None, user_id: str = None)`
  - thread_id 生成逻辑：见 3.2.2

```python
def run_nl2sql_query(
    query: str,
    query_id: str = None,
    thread_id: str = None,   # 【新增】多轮会话 ID
    user_id: str = None,     # 【新增】用户标识
) -> Dict[str, Any]:
    # query_id 自动生成
    actual_query_id = query_id or f"q_{uuid.uuid4().hex[:8]}"
    
    # thread_id 自动生成（若未传入）
    actual_thread_id = get_or_generate_thread_id(thread_id, user_id)
    
    # ... 后续逻辑
```

**父图 State 变更**

在 `NL2SQLFatherState` 中新增字段：

```python
# src/modules/nl2sql_father/state.py
class NL2SQLFatherState(TypedDict):
    # ========== 输入与标识 ==========
    user_query: str
    query_id: str
    thread_id: str      # 【新增】会话 ID（格式：{user_id}:{timestamp}）
    user_id: str        # 【新增】用户标识（未登录时为 "guest"）

    # ... 其他字段
```

同步更新 `create_initial_state()`：

```python
import logging

logger = logging.getLogger(__name__)

def create_initial_state(
    user_query: str,
    query_id: str | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
) -> NL2SQLFatherState:
    # query_id 自动生成
    if query_id is None:
        query_id = f"q_{uuid.uuid4().hex[:8]}"
    
    # thread_id 和 user_id 一致性处理
    if thread_id and validate_thread_id(thread_id):
        # 传入了合法 thread_id → 从中反推 user_id
        actual_thread_id = thread_id
        thread_user_id = get_user_id_from_thread_id(thread_id)
        
        if user_id and user_id != thread_user_id:
            # 两者都传入但不一致 → 以 thread_id 为准，记录 warning
            logger.warning(
                f"user_id '{user_id}' != thread_id prefix '{thread_user_id}', "
                f"using '{thread_user_id}' from thread_id"
            )
        actual_user_id = thread_user_id
    else:
        # 未传入 thread_id 或格式非法 → 自动生成
        actual_user_id = sanitize_user_id(user_id)  # 校验 user_id，不合法则回退为 guest
        actual_thread_id = get_or_generate_thread_id(None, actual_user_id)
    
    return NL2SQLFatherState(
        user_query=user_query,
        query_id=query_id,
        thread_id=actual_thread_id,
        user_id=actual_user_id,
        # ... 其他字段初始化
    )
```

**thread_id 与 user_id 一致性规则**：

| 传入参数 | 行为 |
|----------|------|
| 只传 `thread_id` | 从 thread_id 反推 user_id |
| 只传 `user_id` | 自动生成 thread_id |
| 都传入且一致 | 直接使用 |
| 都传入但不一致 | 以 thread_id 为准，记录 warning |
| 都不传 | user_id=guest，自动生成 thread_id |

**CLI 接入（建议）**

当前 CLI：`scripts/nl2sql_father_cli.py` 仅支持 `--query-id`，建议新增：

- `--thread-id`：指定会话 ID（多轮对话复用）
- `--user-id`：指定用户标识（默认 `guest`）

交互模式下建议固定一个 thread_id（启动时生成一次），后续每轮只变化 `query_id`。

**CLI 交互模式变更示例**：

```python
from datetime import datetime, timezone

def interactive_mode(thread_id: str = None, user_id: str = None):
    """交互对话模式"""
    # user_id 默认为 guest
    actual_user_id = user_id or "guest"
    
    # 启动时生成一次 thread_id（固定整个交互会话，使用 UTC 时间）
    if thread_id is None:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
        thread_id = f"{actual_user_id}:{timestamp}"
    
    print(f"🆔 会话 ID: {thread_id}")
    print(f"👤 用户: {actual_user_id}")
    
    while True:
        question = input("👤 您的问题: ").strip()
        if question.lower() in ["exit", "quit"]:
            break
        
        # 每轮生成新的 query_id，thread_id 保持不变
        result = run_nl2sql_query(
            query=question,
            query_id=None,       # 自动生成
            thread_id=thread_id, # 固定（整个交互会话共享）
            user_id=actual_user_id,
        )
        print_result(result)
```

**（可选）API 接入（若后续接入 FastAPI/HTTP）**

- 请求体/参数增加 `thread_id`（可选）和 `user_id`（可选）
- 服务端将参数透传到 `run_nl2sql_query(..., thread_id=..., user_id=...)`

---

## 7. 子图接入设计（sql_generation subgraph）

### 7.1 为什么子图也需要 checkpointer

子图内部存在 retry（validation 失败回到 generation），且 `MessagesState` 会累积消息；若启用 checkpoint，可用于：
- 调试：复现某次生成失败的中间状态
- 未来能力：在同一会话中“继续生成/重试”而不是从零开始

### 7.2 接入点与隔离方式

子图目前被父图 wrapper 通过便捷函数**独立 invoke**：
- 父图：`sql_gen_wrapper()` / `sql_gen_batch_wrapper()` 调用 `run_sql_generation_subgraph(...)`
- 子图：`create_sql_generation_subgraph()` 内部 `subgraph.compile()`

设计建议：

1. 子图编译时按开关传入 `checkpointer`
   - `compiled = subgraph.compile(checkpointer=postgres_saver, ...)`

2. 子图 invoke 时传入同一 `thread_id`
   - 从父图 State 获取 `thread_id`（与父图一致，保证同一会话下可关联）

3. 子图 namespace 隔离（设计决策：采用方案 A，必须传 `sub_query_id`）
   - 选择原因：
     - `query_id` 是会话/轮次级（turn）ID，在 Complex Path 下会对应多个子查询；仅使用 `query_id` 会导致子图多次执行在同一 namespace 下滚动覆盖“最新 checkpoint”，难以定位到具体子查询。
     - `sub_query_id` 在现有父图 State 中已存在，且格式建议为 `{query_id}_sqN`（天然唯一且可读）。
   - 实现方式（后续落地时）：
     - 在父图 wrapper 层将 `sub_query_id` 下传给子图（Fast Path 用 `current_sub_query_id`；Complex Path 循环变量即 `sub_query_id`）。
     - 子图 invoke 使用：`checkpoint_ns = f"{subgraph_namespace}:{sub_query_id}"`，其中 `subgraph_namespace` 取自配置 `langgraph_persistence.checkpoint.subgraph_namespace`（默认 `"sql_generation"`）。
     - 兼容兜底：若 `sub_query_id` 缺失（例如外部直接调用子图），可回退为 `{subgraph_namespace}:{query_id}`，但不作为主路径设计。

不采用方案 B（`query` hash）的原因（仅保留为最后兜底手段）：
- `query` 文本可能在清洗/重写/重试中变化，hash 不稳定且难以人工排查
- 不如 `sub_query_id` 与父图 `sub_queries`/日志上下文天然对齐

#### 7.2.1 子图便捷函数签名变更（对应父图 6.3）

为支持 `checkpoint_ns = f"{subgraph_namespace}:{sub_query_id}"` 的隔离策略（`subgraph_namespace` 从配置读取），并与父图统一 `thread_id`，需要对现有子图便捷函数 `run_sql_generation_subgraph()` 做向后兼容的签名扩展。

**当前签名**（`src/modules/sql_generation/subgraph/create_subgraph.py`）：

```python
def run_sql_generation_subgraph(
    query: str,
    query_id: str,
    user_query: str,
    dependencies_results: dict = None,
    parse_hints: dict = None,
) -> dict:
    ...
```

**建议签名**（新增可选参数，保证老调用不受影响）：

```python
def run_sql_generation_subgraph(
    query: str,
    query_id: str,
    user_query: str,
    dependencies_results: dict = None,
    parse_hints: dict = None,
    *,
    sub_query_id: str | None = None,   # 新增：用于 checkpoint_ns 隔离
    thread_id: str | None = None,      # 新增：会话 ID（从父图透传）
) -> dict:
    """
    Args:
        sub_query_id:
            - Fast Path: 传 `state["current_sub_query_id"]`
            - Complex Path: 传循环变量 `sub_query_id`
            - 不传：兜底回退为 `query_id`（不建议作为主路径）
        thread_id:
            - 透传父图的 thread_id
            - 不传：兜底回退为 `query_id`（单轮模式）
    """
```

类型注解风格说明：本项目 `pyproject.toml` 设定 `requires-python = ">=3.12"`，因此文档示例使用 `str | None`（PEP 604）语法；如团队代码风格更偏好 `Optional[str]`，可在实现时统一替换，两者在语义上等价。

**invoke 配置构造（示例）**

- `subgraph_namespace` 从配置 `langgraph_persistence.checkpoint.subgraph_namespace` 读取（默认 `"sql_generation"`）
- `checkpoint_ns = f"{subgraph_namespace}:{sub_query_id or query_id}"`
- `thread_id` 从父图 State 获取（或回退为 query_id）
- 当且仅当启用 checkpoint 时传入（避免无谓地影响现有调用路径）：

```python
# 从配置读取 subgraph_namespace
persistence_config = get_config().get("langgraph_persistence", {})
subgraph_namespace = persistence_config.get("checkpoint", {}).get("subgraph_namespace", "sql_generation")

# 构造 checkpoint_ns
checkpoint_ns = f"{subgraph_namespace}:{sub_query_id or query_id}"

final_state = subgraph.invoke(
    initial_state,
    config={"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}},
)
```

> 注：`thread_id/checkpoint_ns` 的 key 名称以 LangGraph 版本为准；本节仅表达"必须能传入 thread_id 与 namespace"的设计要求。

**父图 wrapper 调用示例（设计意图）**

- Fast Path（`sql_gen_wrapper`）：
  - `sub_query_id = state["current_sub_query_id"]`
  - `thread_id = state["thread_id"]`
- Complex Path（`sql_gen_batch_wrapper`）：
  - `sub_query_id = sub_query_id`（循环变量）
  - `thread_id = state["thread_id"]`

#### 7.2.2 父图 Wrapper 代码变更（具体实现）

以下给出父图 wrapper 需要做的具体代码变更，以支持新参数传递。

**Fast Path wrapper（`sql_gen_wrapper`）变更**：

```python
# src/modules/nl2sql_father/graph.py

def sql_gen_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    from src.modules.sql_generation.subgraph.create_subgraph import (
        run_sql_generation_subgraph,
    )
    
    # ... 现有逻辑获取 current_sub_query_id 和 current_sub_query
    
    try:
        subgraph_output = run_sql_generation_subgraph(
            query=current_sub_query["query"],
            query_id=state["query_id"],
            user_query=state["user_query"],
            dependencies_results={},
            parse_hints=None,
            # 【新增参数】
            sub_query_id=state["current_sub_query_id"],
            thread_id=state["thread_id"],
        )
        # ... 后续处理
```

**Complex Path wrapper（`sql_gen_batch_wrapper`）变更**：

```python
def sql_gen_batch_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    from src.modules.sql_generation.subgraph.create_subgraph import (
        run_sql_generation_subgraph,
    )
    
    # ... 现有逻辑
    
    for sub_query_id in current_batch_ids:
        sub_query = next((sq for sq in sub_queries if sq["sub_query_id"] == sub_query_id), None)
        if not sub_query:
            continue
        
        try:
            subgraph_output = run_sql_generation_subgraph(
                query=sub_query["query"],
                query_id=state["query_id"],
                user_query=state["user_query"],
                dependencies_results=sub_query.get("dependencies_results", {}),
                parse_hints=None,
                # 【新增参数】
                sub_query_id=sub_query_id,  # 循环变量
                thread_id=state["thread_id"],
            )
            # ... 后续处理
```

---

## 8. PostgresStore 的数据模型（仅写阶段）

> 目标是“先可用、可排查、可演进”，不追求一次到位的检索体验。

实现前置条件：本节的 key/value 结构是"期望的数据形态"，落地时需要以 `langgraph-checkpoint-postgres==3.0.2` 的 `PostgresStore` 实际 API 与约束为准（见 5.1.2，以及 5.1.1 的 import/初始化验证）。

### 8.1 建议的 key 设计

为了 append-only 与后续可检索（即便本阶段不读），建议使用"每轮一条记录"的粒度：

- `namespace = "chat_history"`
- `key = f"{thread_id}#{query_id}"`（使用 `#` 分隔 thread_id 和 query_id，避免与 thread_id 内部的 `:` 混淆）

示例：`guest:20251219T163045123Z#q_abc123`

**key 格式说明**：

| 分隔符 | 用途 | 说明 |
|--------|------|------|
| `:` | 分隔 user_id 和 timestamp（thread_id 内部） | `guest:20251219T163045123Z` |
| `#` | 分隔 thread_id 和 query_id（key 层级） | `{thread_id}#{query_id}` |

```python
def parse_store_key(key: str) -> tuple[str, str, str]:
    """解析 Store key，提取 thread_id、user_id、query_id
    
    Args:
        key: 格式为 {thread_id}#{query_id}，其中 thread_id = {user_id}:{timestamp}
    
    Returns:
        (thread_id, user_id, query_id) 元组
    
    Raises:
        ValueError: key 格式不正确（缺少 # 分隔符、thread_id 格式非法等）
    """
    # 1. 校验 # 分隔符
    if "#" not in key:
        raise ValueError(f"Invalid store key format: missing '#' separator in '{key}'")
    
    thread_id, query_id = key.split("#", 1)  # 按 # 分割一次
    
    # 2. 校验 thread_id 完整格式（调用 validate_thread_id 作为额外防线）
    if not validate_thread_id(thread_id):
        raise ValueError(f"Invalid thread_id format in store key: '{thread_id}'")
    
    # 3. 提取 user_id
    user_id, _ = thread_id.split(":", 1)     # 按 : 分割一次
    return thread_id, user_id, query_id


def parse_store_key_safe(key: str) -> tuple[str, str, str] | None:
    """安全版本：解析失败时返回 None 而非抛异常"""
    try:
        return parse_store_key(key)
    except ValueError:
        return None
```

### 8.2 建议的 value（JSON）

```json
{
  "thread_id": "guest:20251219T163045123Z",
  "user_id": "guest",
  "query_id": "q_abc123",
  "created_at": "2025-12-19T16:30:45.123Z",
  "user": { "role": "user", "content": "查询2024年销售额" },
  "assistant": { "role": "assistant", "content": "2024年销售总额为..." },
  "metadata": {
    "complexity": "simple",
    "path_taken": "fast",
    "total_execution_time_ms": 1234,
    "sub_query_count": 1
  }
}
```

可选扩展（调试/审计需求时再加）：
- `validated_sql`（单子查询时）
- `sub_queries`/`execution_results`（注意体积与敏感数据）

建议的落地约束（与 store 具体实现无关的通用建议）：
- `value` 只写入可 JSON 序列化字段；遇到复杂对象（如消息对象）先转换为纯 dict/list/str
- 对 `assistant`/`user` 文本设置最大长度并做截断，避免单条记录过大
- key 采用短且稳定的 `thread_id#query_id`，避免包含长 query 文本
- `user_id` 可以从 `thread_id` 解析（冒号前的部分），也可以独立存储便于查询

### 8.3 子图 messages 是否写入 store（建议默认不写）

子图 `messages` 多为“系统 prompt + 中间推理上下文 + 工具调用信息”，体积与敏感性较高。

建议：
- 本阶段 store **只保存用户可见**对话（user_query + summary）
- 子图 messages 若确有需求，优先依赖 checkpointer（用于调试），或单独开关写入到 `namespace = "sql_generation_messages"` 并做脱敏/截断

---

## 9. 数据库与运维建议

### 9.1 Schema 与权限

- 建议使用独立 schema：`langgraph`
- 最小权限：仅允许应用账号对该 schema 下的表进行 DDL/CRUD（是否允许 DDL 取决于“库是否自动建表”策略）

### 9.2 建表/迁移策略

**官方推荐方式：调用 `.setup()` 方法自动建表**

`langgraph-checkpoint-postgres` 包提供了 `.setup()` 方法，用于自动创建所需的表并执行迁移。该方法是**幂等**的，可以安全地重复调用。

**初始化流程**：

```python
# 应用启动时执行一次（建议放在启动脚本或首次调用时）
def init_langgraph_persistence():
    """初始化 LangGraph 持久化：创建表 + 跑迁移（幂等）"""
    # 从配置获取 URI
    db_uri = build_db_uri_from_config()
    
    # PostgresSaver（Checkpoint）
    with PostgresSaver.from_conn_string(db_uri) as checkpointer:
        checkpointer.setup()  # ✅ 创建 checkpoint 相关表
    
    # PostgresStore（历史对话）
    with PostgresStore.from_conn_string(db_uri) as store:
        store.setup()  # ✅ 创建 store 相关表
```

**两种部署策略**：

| 策略 | 实现方式 | 优点 | 缺点 | 适用场景 |
|------|----------|------|------|----------|
| **自动建表** | 应用启动时调用 `.setup()` | 简单、无需维护 DDL、自动迁移 | 需要 CREATE TABLE 权限 | 开发/测试/小规模生产 |
| **显式迁移** | DBA 预先执行建表 SQL | 权限分离、可审计 | 需跟踪库版本的 schema 变化 | 大规模生产/严格权限控制 |

**建议**：

- **开发/测试环境**：使用自动建表（`.setup()`），简化流程
- **生产环境**：可选择自动建表（确保账号有 DDL 权限），或显式迁移（DBA 预先执行）

**前置条件**（无论哪种策略）：

- 数据库已创建
- Schema 已创建（如使用独立 schema）：`CREATE SCHEMA IF NOT EXISTS <schema>;`（`<schema>` 取配置 `langgraph_persistence.database.schema` 的值，默认 `langgraph`）
- 应用账号拥有必要权限：
  - 自动建表：`CREATE TABLE`、`CREATE INDEX`
  - 显式迁移：仅需 `SELECT`/`INSERT`/`UPDATE`/`DELETE`

### 9.2.1 表结构参考（仅供运维评估）

以下仅为"预期表形态"的参考，便于 DBA/运维评估容量与索引策略。**实际表结构由 `.setup()` 自动创建，无需手工执行**。

**示例（仅供参考，非最终结构）**

> **注意**：以下 SQL 中的 `<schema>` 为占位符，执行前需替换为配置的 `langgraph_persistence.database.schema` 值（默认 `langgraph`）。**请勿直接复制执行**。

```sql
-- 独立 schema（<schema> 替换为配置值，如 langgraph）
CREATE SCHEMA IF NOT EXISTS <schema>;

-- Checkpoint 表（示例：用于 PostgresSaver）
-- 注意：真实实现可能拆分为 checkpoints / blobs / writes 等多表，或主键结构不同。
CREATE TABLE IF NOT EXISTS <schema>.checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- Store 表（示例：用于 PostgresStore）
-- 注意：真实实现可能包含 value 的序列化字段、版本号、TTL/过期字段等。
CREATE TABLE IF NOT EXISTS <schema>.store (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, key)
);

-- 索引（示例：按写入时间检索/清理）
CREATE INDEX IF NOT EXISTS idx_<schema>_checkpoints_created_at
    ON <schema>.checkpoints (created_at);

CREATE INDEX IF NOT EXISTS idx_<schema>_store_created_at
    ON <schema>.store (created_at);
```

手动迁移执行方式（示例）：

- 使用 `psql`/Flyway/liquibase 等工具执行迁移文件
- 确保应用账号拥有配置的 schema（默认 `langgraph`）的必要权限（DDL/CRUD 取决于是否需要自动建表）

### 9.3 体积与保留策略

checkpoint 与对话历史都会增长，建议预留：
- checkpoint 保留天数（例如 7/30 天）
- 对话历史保留天数（例如 30/90 天）
- 定期清理 job（cron/平台任务）

### 9.4 数据清理 SQL 示例

以下 SQL 仅供参考，实际表名/字段以 `langgraph-checkpoint-postgres==3.0.2` 的建表结果为准。

**清理过期 checkpoint**：

> **占位符说明**：`<schema>` 替换为 `langgraph_persistence.database.schema` 配置值（默认 `langgraph`）。**请勿直接复制执行**。

```sql
-- 清理 7 天前的 checkpoint
DELETE FROM <schema>.checkpoints
WHERE created_at < NOW() - INTERVAL '7 days';

-- 可选：先查询待清理数量
SELECT COUNT(*) AS to_delete
FROM <schema>.checkpoints
WHERE created_at < NOW() - INTERVAL '7 days';
```

**清理过期对话历史**：

> **占位符说明**：
> - `<schema>` 替换为 `langgraph_persistence.database.schema` 配置值（默认 `langgraph`）
> - `<store_namespace>` 替换为 `langgraph_persistence.store.namespace` 配置值（默认 `chat_history`）
>
> **请勿直接复制执行**。

```sql
-- 清理 90 天前的对话历史
DELETE FROM <schema>.store
WHERE namespace = '<store_namespace>'
  AND created_at < NOW() - INTERVAL '90 days';

-- 可选：按 thread_id 清理（保留最近 N 轮）
-- 需根据业务需求定制
```

**定期清理任务建议**：

| 方式 | 适用场景 | 说明 |
|------|----------|------|
| `pg_cron` 扩展 | PostgreSQL 内置调度 | 需安装扩展，适合 DBA 管理 |
| 外部调度器（cron/K8s CronJob） | 独立于数据库 | 通过 `psql` 执行 SQL 脚本 |
| 应用层定时任务 | 与应用集成 | 在 Python 进程中调度（如 APScheduler） |

建议优先使用 `pg_cron` 或外部 cron，避免应用层实现增加代码复杂度。

---

## 10. 风险与对策

1. **State 体积过大导致 checkpoint 表膨胀**
   - 对策：按 docs/20 的思路继续"State 瘦身"；未来可考虑引入 `ShallowPostgresSaver`（浅层 checkpoint）。
2. **保存失败影响主流程**
   - 对策：所有持久化写入必须 try/except，失败只打日志；并支持总开关快速关闭。
3. **并发写入与覆盖**
   - 对策：store 采用 append-only key（每轮唯一），避免覆盖；checkpoint 依赖库内部并发控制。
4. **敏感信息合规**
   - 对策：对写入字段做白名单；默认不写执行结果 rows；必要时做脱敏与截断。
5. **数据库写入阻塞主流程（延长响应时间）**
   - 现象：PostgreSQL 写入慢、连接池耗尽或锁等待导致 `run_nl2sql_query()` 响应变慢（store 写入在尾部阻塞；checkpoint 写入在执行中放大延迟）
   - 对策：
     - store：设置应用侧超时（2–5 秒）+ 数据库 statement_timeout；必要时后台线程/队列异步写入（best-effort）
     - checkpoint：默认关闭；启用时优先 state 瘦身（docs/20）；必要时拆分独立连接池/独立数据库实例

6. **与现有代码风格/架构不一致**
   - 现象：新增模块命名、配置结构与现有代码不一致，增加维护成本
   - 对策：
     - 模块命名遵循现有 `src/services/` 下的风格（如 `pg_connection.py`、`config_loader.py`）
     - 配置命名与现有习惯保持一致（如 `vector_database.providers.pgvector.use_global_config`）
     - 单例管理方式参考 `get_pg_manager()`、`get_config()` 的实现模式

7. **库 API 假设错误导致返工**
   - 现象：设计文档假设的 API（如 `PostgresStore.put()`）与实际不符
   - 对策：
     - 实施前完成 5.1.1/5.1.2 的验证项
     - 保持项目内部 API 稳定（如 `append_turn()`），底层适配实际库接口

---

## 11. 分阶段落地计划（建议）

### Phase A：只启用父图 checkpoint

- 接入父图 `PostgresSaver`
- `invoke` 传 `thread_id`
- 不启用 store

### Phase B：父图写入历史对话（store，仅写）

- 在 `run_nl2sql_query()` 末尾写入 `PostgresStore`
- 不读取、不注入 prompt

### Phase C：子图 checkpoint（可选）

- 子图 compile + invoke 增加 checkpointer
- 引入 `checkpoint_ns` 隔离（至少区分 father/subgraph）

---

## 12. 验收标准（面向实现时）

> 说明：本节给出“可执行”的验收步骤。由于 9.2.1 的表结构为示例，实际 SQL 需要以 `langgraph-checkpoint-postgres==3.0.2` 的最终建表结果为准。

### 12.1 前置检查

1. 开启开关（`langgraph_persistence.enabled=true`，并分别开启 `checkpoint.enabled` / `store.enabled`）。
2. 执行一次查询（父图入口）。
3. 确认配置的 schema 下实际表名（示例，需将 `'langgraph'` 替换为配置的 `langgraph_persistence.database.schema` 值）：

> **占位符说明**：`<schema>` 替换为 `langgraph_persistence.database.schema` 配置值（默认 `langgraph`）。**请勿直接复制执行**。

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = '<schema>'
ORDER BY table_name;
```

### 12.2 Checkpoint 验收

1. 开启 checkpoint 后执行一次查询。
2. 查询 checkpoint 记录（以下以 9.2.1 的示例表为例；如实际表不同请替换）：

> **占位符说明**：`<schema>` 替换为 `langgraph_persistence.database.schema` 配置值（默认 `langgraph`）。**请勿直接复制执行**。

```sql
SELECT thread_id, checkpoint_ns, checkpoint_id, created_at
FROM <schema>.checkpoints
ORDER BY created_at DESC
LIMIT 5;
```

3. 预期：
- 至少看到 1 条父图记录，`checkpoint_ns` 值为配置的 `father_namespace`（默认 `'nl2sql_father'`）
- Complex Path 下可看到多个子图 namespace，格式为 `{subgraph_namespace}:{sub_query_id}`（默认前缀 `'sql_generation'`）

> 注：`father_namespace` 和 `subgraph_namespace` 取自配置 `langgraph_persistence.checkpoint.*`，验收时需以实际配置值为准。

### 12.3 Store（历史对话写入）验收

1. 开启 store 后执行一次查询。
2. 查询 store 记录（以下以 9.2.1 的示例表为例；如实际表不同请替换）：

> **占位符说明**：
> - `<schema>` 替换为 `langgraph_persistence.database.schema` 配置值（默认 `langgraph`）
> - `<store_namespace>` 替换为 `langgraph_persistence.store.namespace` 配置值（默认 `chat_history`）
>
> **请勿直接复制执行**。

```sql
SELECT
  namespace,
  key,
  value->'user'->>'content'      AS user_content,
  value->'assistant'->>'content' AS assistant_content,
  created_at
FROM <schema>.store
WHERE namespace = '<store_namespace>'
ORDER BY created_at DESC
LIMIT 5;
```

3. 预期：
- 至少看到 1 条记录
- `key` 格式为 `thread_id#query_id`（如 `guest:20251219T163045123Z#q_abc123`）
- `user_content` 与本次输入一致；`assistant_content` 为本次输出 summary

### 12.4 降级验收（数据库不可用）

目的：验证“持久化 best-effort，不影响主流程返回”。

步骤（任选其一）：
- 停止 PostgreSQL 服务，或将 `langgraph_persistence.database.db_uri`（或 `database.*`）配置为错误连接
- 触发一次查询

预期：
- 查询仍然成功返回 NL2SQL 结果（主流程不中断）
- 日志中出现 WARNING（或可控 ERROR）级别的持久化失败日志
- 进程不崩溃；不出现未捕获异常导致的请求失败

> 注：降级验收的预期行为取决于 6.1.1 的实现方式（实施者需先确认采用哪种方案）：
> - **若实现了 SafeCheckpointer（fail-open）**：数据库不可用时，查询仍成功返回，日志出现 WARNING，且不会因为 checkpoint 写入异常导致本次执行失败（本次可能无新增 checkpoint 记录）。
> - **若未实现 SafeCheckpointer（运维级降级）**：数据库不可用时，应由 preflight 检测失败并自动关闭 checkpoint（或人工关闭 `checkpoint.enabled`），使主流程以“无 checkpoint”模式运行并成功返回；验收时应分别验证：
>   - 关闭 checkpoint 后主流程正常
>   - preflight 能识别不可用并阻止开启 checkpoint（避免中途因 checkpointer 抛错导致失败）

### 12.5 性能/阻塞验收（写入超时）

1. 人为制造慢写（例如数据库侧降低性能或注入延迟）。
2. 执行一次查询。
3. 预期：
- store 写入不会无限阻塞：在 6.2.1 约定的超时（如 2 秒）后跳过写入并返回结果
- 日志记录"写入超时/跳过"信息，便于排查

---

## 13. 测试策略

### 13.1 单元测试

| 测试目标 | 测试方式 | 覆盖场景 |
|----------|----------|----------|
| `build_db_uri_from_config()` | Mock 配置 | 使用全局配置、使用独立 db_uri、缺失配置报错 |
| `get_postgres_saver()` / `get_postgres_store()` | Mock 连接 | 正常创建、创建失败返回 None |
| `append_turn()` | Mock store | 正常写入、写入失败记录日志、超时跳过 |
| `SafeCheckpointer`（若实现） | Mock 真实 checkpointer | 正常透传、异常捕获、超时处理 |

### 13.2 集成测试

使用真实 PostgreSQL（可用 Docker 容器），验证端到端流程：

```bash
# 启动测试用 PostgreSQL
docker run -d --name langgraph-pg-test \
  -e POSTGRES_PASSWORD=test \
  -p 5433:5432 \
  postgres:15
```

| 测试场景 | 验证点 |
|----------|--------|
| 正常写入 checkpoint | 执行查询后，checkpoint 表有记录 |
| 正常写入 store | 执行查询后，store 表有记录 |
| 数据库不可用时降级 | 主流程正常返回，日志有 WARNING |
| 写入超时场景 | 超时后跳过写入，主流程正常返回 |

### 13.3 回归测试

确保关闭 checkpoint/store 开关时，现有功能不受影响：

| 测试场景 | 验证点 |
|----------|--------|
| `checkpoint.enabled=false` | 图编译不传入 checkpointer，checkpoint 表无新记录 |
| `store.enabled=false` | `run_nl2sql_query()` 结束后不调用 `append_turn()` |
| `langgraph_persistence.enabled=false` | 所有持久化功能关闭，行为与当前版本一致 |

### 13.4 回滚验证

验证快速回滚能力：

1. 模拟上线后发现 checkpoint 导致问题
2. 修改配置 `checkpoint.enabled=false`
3. 重启服务（或热更新配置，若支持）
4. 验证主流程恢复正常

---

## 14. 监控与告警（建议）

### 14.1 监控指标

| 指标名称 | 类型 | 说明 | 建议阈值 |
|----------|------|------|----------|
| `checkpoint_write_latency_ms` | Histogram | Checkpoint 写入延迟 | P99 < 500ms |
| `checkpoint_write_failure_total` | Counter | Checkpoint 写入失败次数 | 增长率 < 1/min |
| `store_write_latency_ms` | Histogram | Store 写入延迟 | P99 < 200ms |
| `store_write_failure_total` | Counter | Store 写入失败次数 | 增长率 < 1/min |
| `langgraph_table_size_bytes` | Gauge | 表空间大小 | < 10GB（按保留策略） |

### 14.2 告警规则（参考）

```yaml
# Prometheus AlertManager 规则示例
groups:
  - name: langgraph-persistence
    rules:
      - alert: CheckpointWriteHighLatency
        expr: histogram_quantile(0.99, checkpoint_write_latency_ms) > 500
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Checkpoint 写入延迟过高"

      - alert: StoreWriteFailureRateHigh
        expr: rate(store_write_failure_total[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Store 写入失败率过高"
```

### 14.3 与现有 LangSmith 监控的关系

| 组件 | 职责 | 数据存储 |
|------|------|----------|
| LangSmith（现有） | 链路追踪、LLM 调用可观测性 | SaaS（LangChain 托管） |
| PostgresSaver（新增） | 图执行 checkpoint，用于 resume/time-travel | 本地 PostgreSQL |
| PostgresStore（新增） | 历史对话归档，用于审计/分析 | 本地 PostgreSQL |

三者互补，不冲突：
- LangSmith 关注"执行过程可观测性"
- PostgresSaver 关注"状态持久化与恢复"
- PostgresStore 关注"业务数据归档"
