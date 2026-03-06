# 78 - CLI 启动时展示历史会话列表设计

> 日期：2026-03-06
> 前置文档：77_CLI界面Rich优化设计.md、75_对话历史功能优化与bug修复.md

---

## 1. 需求概述

在交互模式（`python scripts/nl2sql_father_cli.py`）启动时，展示最近 3 次对话会话，用户可选择继续历史会话或开始新会话。

### 1.1 功能要求

1. 启动 CLI 后，查询当前用户（默认 `guest`）的最近 3 个 thread（会话）
2. 按**会话创建时间**由近到远排列（创建时间从 thread_id 的 timestamp 部分解析）
3. 每个会话显示：创建时间（本地时区） + 该会话的**第一条用户问题**（截断 + 省略号）
4. 列表顶部为"新建会话"选项
5. 用户通过数字键选择（0=新会话，1/2/3=历史会话）
6. 使用 Rich Panel 将选项列表包裹在矩形框内；输入提示在 Panel 下方

### 1.2 设计决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| "最近"排序依据 | 会话**创建时间**（thread_id timestamp） | 需求明确要求从 thread_id 拆解创建时间 |
| 首问取哪条 | 该会话**最早一条**用户问题（按 `created_at ASC`） | 首问最能代表会话主题 |
| 是否过滤失败会话 | **不过滤**，展示所有会话 | 用户可能想回到失败会话重试 |
| 菜单与欢迎横幅顺序 | **菜单先出现**，选择完成后再显示欢迎信息 | 符合"启动先选会话"的交互预期 |
| 输入提示位置 | **Panel 外部** | Rich Panel 为一次性渲染对象，不支持内嵌 input |
| 数据库查询方式 | **原生 SQL** | LangGraph Store API 排序不可控，无法保证正确性（详见 3.2.3） |
| 数据库连接方式 | **`build_db_uri_from_config()` 直连** | 与 langgraph 持久化使用同一连接配置，避免依赖内部 API 或业务 DB 连接（详见 3.2.2） |

### 1.3 交互示意

```
┌─────────────── NL2SQL 交互式终端 ───────────────┐
│                                                   │
│  [0] 新建会话                                     │
│  [1] 2026-03-05 18:39  请问广州市的京东便利...     │
│  [2] 2026-03-04 10:22  查询2024年的销售总额...     │
│  [3] 2026-03-03 09:15  上海市的便利店有哪些...     │
│                                                   │
└───────────────────────────────────────────────────┘
请输入选项编号 (0-3):
```

---

## 2. 现状分析

### 2.1 Store 表结构

```sql
-- langgraph.store 表（schema 由配置项 langgraph_persistence.database.schema 决定）
CREATE TABLE langgraph.store (
    prefix      text NOT NULL,    -- 如: "chat_history.guest:20260305T183946997Z"
    key         text NOT NULL,    -- 如: "q_3990d76d"（query_id）
    value       jsonb NOT NULL,
    created_at  timestamp with time zone,
    updated_at  timestamp with time zone,
    PRIMARY KEY (prefix, key)
);
```

**写入逻辑**（`chat_history_writer.py`）：
```python
namespace = get_store_namespace()  # 从配置读取，默认 "chat_history"
store.put(namespace=(namespace, thread_id), key=query_id, value=value)
```

落库后 `prefix` = `{namespace}.{thread_id}`，如 `chat_history.guest:20260305T183946997Z`。

**prefix 的排序特性**：
- 同一用户的所有会话 prefix 共享前缀 `chat_history.{user_id}:`
- timestamp 部分为 ISO 8601 紧凑格式（`YYYYMMDDTHHmmssSSS`），天然**字典序 = 时间序**
- 因此 `ORDER BY prefix DESC` 可以直接拿到最新的会话，无需在 Python 层解析和排序

### 2.2 thread_id 格式

```
{user_id}:{timestamp}
```
- `user_id`：如 `guest`、`alice`（经过 `sanitize_user_id()` 校验）
- `timestamp`：`YYYYMMDDTHHmmssSSS` + `Z`（UTC 时间），如 `20260305T183946997Z`
- 完整示例：`guest:20260305T183946997Z`

### 2.3 现有代码现状

| 模块 | 文件 | 现状 |
|------|------|------|
| CLI 入口 | `scripts/nl2sql_father_cli.py` | `interactive_mode()` 先打印欢迎横幅（L479），再生成 thread_id（L505），无历史选择 |
| 历史读取 | `chat_history_reader.py` | 仅支持单 thread_id 内的轮次读取（`get_recent_turns()`），不支持跨 thread 列举 |
| 标识符解析 | `identifiers.py` | 已有 `parse_thread_id()`、`sanitize_user_id()`、`get_user_id_from_thread_id()` |
| Store 配置 | `postgres.py` | 已有 `get_store_namespace()`、`is_store_enabled()`、`build_db_uri_from_config()` |
| 业务 DB | `pg_connection.py` | `PGConnectionManager` 连接业务库（`database.*` 配置），与 langgraph schema 可能不在同一 DB |
| Rich 渲染 | `nl2sql_father_cli.py` | 已集成 Rich（Panel, Table, Console 等） |

### 2.4 数据库连接配置对比

| 连接方式 | 连接目标 | search_path |
|----------|----------|-------------|
| `PGConnectionManager`（`pg_connection.py`） | `database.*` 配置（业务库） | `public`（默认） |
| `build_db_uri_from_config()`（`postgres.py`） | `langgraph_persistence.database.*` 配置 | 由 URI 中 `-csearch_path=langgraph` 指定 |

> 当 `use_global_config: false` 时，两者可能指向不同的数据库实例。因此查询 `langgraph.store` 表时**必须使用 `build_db_uri_from_config()` 的连接**，不能使用 `PGConnectionManager`。

---

## 3. 设计方案

### 3.1 新增：thread_id 时间解析工具函数

**文件**：`src/services/langgraph_persistence/identifiers.py`

新增函数，从 thread_id 的 timestamp 部分解析出 UTC `datetime`：

```python
def parse_thread_id_datetime(thread_id: str) -> Optional[datetime]:
    """从 thread_id 解析会话创建时间。

    Args:
        thread_id: 格式为 {user_id}:{YYYYMMDDTHHmmssSSS}Z

    Returns:
        datetime 对象（UTC，带 tzinfo），解析失败返回 None
    """
    try:
        _, timestamp_str = parse_thread_id(thread_id)
        # "20260305T183946997Z" -> 前15位 "20260305T183946" + 毫秒 "997"
        dt = datetime.strptime(timestamp_str[:15], "%Y%m%dT%H%M%S")
        ms = int(timestamp_str[15:18])
        return dt.replace(microsecond=ms * 1000, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None
```

### 3.2 新增：会话列表读取函数

**文件**：`src/services/langgraph_persistence/chat_history_reader.py`

新增函数 `list_recent_sessions()`，用于列举指定用户的最近 N 个会话。

```python
def list_recent_sessions(
    *,
    user_id: str = "guest",
    max_sessions: int = 3,
    timeout_seconds: float = 5.0,
) -> List[Dict[str, Any]]:
    """列举用户最近的会话列表（新->旧）。

    Args:
        user_id: 用户标识（已经过 sanitize_user_id 处理）
        max_sessions: 最多返回的会话数
        timeout_seconds: 整体超时（秒）

    Returns:
        [
            {
                "thread_id": "guest:20260305T183946997Z",
                "created_at": datetime(2026, 3, 5, 18, 39, 46, 997000, tzinfo=UTC),
                "first_question": "请问广州市的京东便利店的总收入是多少",
            },
            ...
        ]
        按会话创建时间由近到远排列。Store 未启用、超时或异常时返回 []。
    """
```

#### 3.2.1 实现思路：单条合并 SQL

利用 prefix 的字典序特性（`chat_history.{user_id}:{timestamp}` 中 timestamp 为 ISO 格式，字典序 = 时间序），用一条 SQL 同时完成"找最近 3 个会话"和"取每个会话的首问"：

```sql
WITH recent_sessions AS (
    -- Step 1：按 prefix DESC 取该用户最近 N 个不同的会话
    SELECT DISTINCT prefix
    FROM {schema}.store
    WHERE prefix LIKE %(prefix_pattern)s
    ORDER BY prefix DESC
    LIMIT %(max_sessions)s
),
first_questions AS (
    -- Step 2：每个会话取最早一条记录（首问）
    SELECT DISTINCT ON (s.prefix)
        s.prefix,
        s.value->'user'->>'content' AS first_question
    FROM {schema}.store s
    INNER JOIN recent_sessions rs ON s.prefix = rs.prefix
    ORDER BY s.prefix, s.created_at ASC
)
SELECT prefix, first_question
FROM first_questions
ORDER BY prefix DESC
```

**参数说明**：
- `{schema}`：从 `_get_persistence_config()["database"]["schema"]` 读取（默认 `langgraph`），在 SQL 拼接时使用
- `%(prefix_pattern)s`：值为 `{namespace}.{user_id}:%`，如 `chat_history.guest:%`
- `%(max_sessions)s`：值为 `3`

**查询结果**：

| prefix | first_question |
|--------|---------------|
| `chat_history.guest:20260305T183946997Z` | `请问广州市的京东便利店的总收入是多少` |
| `chat_history.guest:20260304T102200123Z` | `查询2024年的销售总额` |
| `chat_history.guest:20260303T091500456Z` | `上海市的便利店有哪些` |

**Python 后处理**：
```python
from src.services.langgraph_persistence.identifiers import (
    parse_thread_id_datetime,
    get_user_id_from_thread_id,
)

sessions = []
for row in rows:
    prefix = row["prefix"]
    # 从 prefix 中提取 thread_id：去掉 "{namespace}." 前缀
    # prefix = "chat_history.guest:20260305T183946997Z"
    # thread_id = "guest:20260305T183946997Z"
    tid = prefix[len(namespace) + 1:]  # +1 跳过 "." 分隔符

    created_at = parse_thread_id_datetime(tid)
    if created_at is None:
        continue

    sessions.append({
        "thread_id": tid,
        "created_at": created_at,
        "first_question": (row.get("first_question") or "").strip(),
    })
```

#### 3.2.2 数据库连接方式

使用 `build_db_uri_from_config()`（`postgres.py` 中的公开函数）创建 psycopg 直连，确保连接到 langgraph 数据库：

```python
import psycopg
from psycopg.rows import dict_row
from src.services.langgraph_persistence.postgres import build_db_uri_from_config

def _query_recent_sessions(prefix_pattern: str, schema: str, max_sessions: int):
    """执行原生 SQL 查询最近会话。"""
    db_uri = build_db_uri_from_config()

    sql = f"""
        WITH recent_sessions AS (
            SELECT DISTINCT prefix
            FROM {schema}.store
            WHERE prefix LIKE %(prefix_pattern)s
            ORDER BY prefix DESC
            LIMIT %(max_sessions)s
        ),
        first_questions AS (
            SELECT DISTINCT ON (s.prefix)
                s.prefix,
                s.value->'user'->>'content' AS first_question
            FROM {schema}.store s
            INNER JOIN recent_sessions rs ON s.prefix = rs.prefix
            ORDER BY s.prefix, s.created_at ASC
        )
        SELECT prefix, first_question
        FROM first_questions
        ORDER BY prefix DESC
    """

    with psycopg.connect(db_uri, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "prefix_pattern": prefix_pattern,
                "max_sessions": max_sessions,
            })
            return cur.fetchall()
```

> **为什么不用 `PGConnectionManager`？**
> `PGConnectionManager` 连接的是业务库（`database.*` 配置），当 `langgraph_persistence.database.use_global_config: false` 时可能指向不同的数据库。使用 `build_db_uri_from_config()` 保证始终连接到 langgraph 数据库。

> **为什么不用 `store._cursor()`？**
> `_cursor()` 是 `PostgresStore` 的内部私有方法（下划线前缀），后续 LangGraph 版本可能变更或移除。`build_db_uri_from_config()` 是本项目自有的公开函数，不依赖第三方库的内部 API。

> **Schema 限定**：SQL 中使用 `{schema}.store` 显式限定 schema（从配置读取，默认 `langgraph`），不依赖连接的 `search_path`，避免 `relation "store" does not exist` 问题。

#### 3.2.3 被否决的方案

| 方案 | 问题 |
|------|------|
| `store.list_namespaces(limit=1000)` + Python 排序 | 底层 `ORDER BY truncated_prefix ASC`（字典序正序 = 时间正序），limit 截断的恰好是**最新**会话；用户会话数超限时永远看不到最近的会话 |
| `store.search(("chat_history",), limit=30)` | 返回"最近 30 条记录"而非"最近 30 个会话"；高频会话轮次多时旧会话被挤出 |
| `store.search((ns, tid), limit=10)` + Python 排序取首问 | `search` 底层固定 `ORDER BY updated_at DESC`，会话超 10 轮时首问不在返回结果中 |
| `store._cursor()` 执行原生 SQL | 依赖 LangGraph 内部私有方法，升级后可能不可用 |
| `PGConnectionManager` 执行原生 SQL | 连接业务库，当 langgraph 配置指向不同 DB 时无法查到 store 表 |

#### 3.2.4 超时与异常处理

- 整体使用线程池 + Future 实现超时（复用 `_get_read_executor()` 的模式）
- 超时或任何异常时返回 `[]`（fail-open，不阻塞 CLI 启动）
- 日志记录异常信息，便于排查

### 3.3 修改：CLI 交互模式入口

**文件**：`scripts/nl2sql_father_cli.py`

#### 3.3.1 新增会话选择渲染函数

```python
def _render_session_menu(sessions: List[Dict[str, Any]]) -> Panel:
    """渲染会话选择菜单（Rich Panel）。

    Args:
        sessions: list_recent_sessions() 返回的会话列表（新->旧）

    Returns:
        Rich Panel 对象（仅包含选项列表，不含输入提示）
    """
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("idx", style="bold cyan", no_wrap=True, width=4)
    table.add_column("info")

    # 第一行：新建会话
    table.add_row("[0]", "[bold green]新建会话[/bold green]")

    # 历史会话
    for i, session in enumerate(sessions, 1):
        created_at = session["created_at"]
        # UTC -> 本地时区显示
        local_time = created_at.astimezone()
        time_str = local_time.strftime("%Y-%m-%d %H:%M")

        # 首问展示（兜底空值）
        question = session.get("first_question") or "（无对话内容）"
        max_q_len = 36
        if len(question) > max_q_len:
            question = question[:max_q_len] + "..."

        table.add_row(f"[{i}]", f"{time_str}  {question}")

    return Panel(
        table,
        title="[bold blue]NL2SQL 交互式终端[/bold blue]",
        border_style="blue",
        expand=False,
        padding=(1, 2),
    )
```

#### 3.3.2 新增会话选择逻辑函数

```python
def _select_session(
    user_id: str,
    use_rich: bool,
) -> Optional[str]:
    """展示会话列表并等待用户选择，返回 thread_id。

    Args:
        user_id: 用户标识（已经过 sanitize_user_id 处理）
        use_rich: 是否使用 Rich 渲染

    Returns:
        - 选中的历史 thread_id（继续对话）
        - None（新建会话，由调用方生成 thread_id）
    """
    from src.services.langgraph_persistence.chat_history_reader import (
        list_recent_sessions,
    )

    # 查询最近会话
    sessions = list_recent_sessions(user_id=user_id, max_sessions=3)

    if not sessions:
        # 无历史会话，直接新建
        return None

    # 渲染菜单
    if use_rich:
        panel = _render_session_menu(sessions)
        console.print(panel)
    else:
        # 纯文本降级
        print("=" * 50)
        print("  [0] 新建会话")
        for i, s in enumerate(sessions, 1):
            local_time = s["created_at"].astimezone()
            time_str = local_time.strftime("%Y-%m-%d %H:%M")
            q = s.get("first_question") or "（无对话内容）"
            if len(q) > 36:
                q = q[:36] + "..."
            print(f"  [{i}] {time_str}  {q}")
        print("=" * 50)

    # 等待用户输入（输入提示在 Panel 外部）
    max_idx = len(sessions)
    while True:
        if use_rich:
            choice = console.input(
                f"[bold]请输入选项编号 (0-{max_idx}): [/bold]"
            ).strip()
        else:
            choice = input(f"请输入选项编号 (0-{max_idx}): ").strip()

        if choice == "0" or choice == "":
            return None  # 新建会话

        try:
            idx = int(choice)
            if 1 <= idx <= max_idx:
                return sessions[idx - 1]["thread_id"]
        except ValueError:
            pass

        # 输入无效，提示重试
        if use_rich:
            console.print(f"[red]请输入 0 到 {max_idx} 之间的数字[/red]")
        else:
            print(f"请输入 0 到 {max_idx} 之间的数字")
```

#### 3.3.3 修改 `interactive_mode()` 函数

核心变化：**会话选择菜单先于欢迎横幅出现**。将原来"先欢迎横幅 -> 再生成 thread_id"的顺序调整为"先会话选择 -> 再欢迎横幅"。

```python
def interactive_mode(
    thread_id: str = None,
    user_id: str = None,
    use_rich: bool = True,
):
    from datetime import datetime, timezone
    from src.services.langgraph_persistence.identifiers import sanitize_user_id

    # 用户标识（使用项目已有的 sanitize_user_id）
    actual_user_id = sanitize_user_id(user_id)

    # ====== 会话选择（在欢迎横幅之前） ======
    is_resumed = False
    if thread_id is None:
        # 未通过 --thread-id 指定，展示会话选择菜单
        selected = _select_session(
            user_id=actual_user_id,
            use_rich=use_rich,
        )
        if selected is not None:
            thread_id = selected
            is_resumed = True
        else:
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
            thread_id = f"{actual_user_id}:{timestamp}"

    # ====== 欢迎横幅（在会话选择之后） ======
    if use_rich:
        if is_resumed:
            console.print(f"\n[cyan]已恢复历史会话[/cyan]: {thread_id}")
        console.print(Panel(
            "欢迎使用！...",  # 原有欢迎文本
            title="[bold blue]NL2SQL 交互式测试终端[/bold blue]",
            border_style="blue",
            expand=False,
        ))
    else:
        if is_resumed:
            print(f"\n已恢复历史会话: {thread_id}")
        # 原有纯文本欢迎 ...

    # 后续会话信息显示和对话循环保持不变 ...
```

**关键变化**：
- `actual_user_id` 改用 `sanitize_user_id(user_id)` 替代 `user_id or "guest"`
- 会话选择在欢迎横幅**之前**执行
- `is_resumed` 在会话选择分支内部赋值，不依赖可能未定义的 `selected_thread_id`
- 当 `--thread-id` 已指定时，跳过会话选择，`is_resumed = False`

---

## 4. 数据流

```
CLI 启动（交互模式，无 --thread-id）
    |
    +-- sanitize_user_id(user_id)
    |
    +-- _select_session(user_id, use_rich)
    |     |
    |     +-- list_recent_sessions(user_id, max_sessions=3)
    |     |     |
    |     |     +-- is_store_enabled() 检查
    |     |     |
    |     |     +-- build_db_uri_from_config() 获取连接 URI
    |     |     |
    |     |     +-- 单条合并 SQL（线程池 + 超时控制）
    |     |     |     +-- CTE recent_sessions: DISTINCT prefix ... ORDER BY prefix DESC LIMIT 3
    |     |     |     +-- CTE first_questions: DISTINCT ON (prefix) ... ORDER BY created_at ASC
    |     |     |     +-- 返回: [(prefix, first_question), ...]
    |     |     |
    |     |     +-- Python 后处理
    |     |           +-- 从 prefix 提取 thread_id
    |     |           +-- parse_thread_id_datetime() 解析创建时间
    |     |           +-- 空值兜底: first_question or ""
    |     |
    |     +-- 渲染 Rich Panel 菜单（Panel 外部显示输入提示）
    |     |
    |     +-- 用户输入选择
    |           +-- 0 / 回车 -> None（新建）
    |           +-- 1/2/3   -> 对应 thread_id
    |
    +-- thread_id 确定
    |
    +-- 欢迎横幅（如 is_resumed 则额外提示"已恢复历史会话"）
    |
    +-- 对话循环（不变）
```

---

## 5. 文件变更清单

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| 修改 | `src/services/langgraph_persistence/identifiers.py` | 新增 `parse_thread_id_datetime()` |
| 修改 | `src/services/langgraph_persistence/chat_history_reader.py` | 新增 `list_recent_sessions()`、`_query_recent_sessions()` |
| 修改 | `scripts/nl2sql_father_cli.py` | 新增 `_render_session_menu()`、`_select_session()`；修改 `interactive_mode()` 顺序 |
| 修改 | `src/tests/unit/services/test_chat_history_reader.py` | 新增 `list_recent_sessions()` 单元测试 |
| 新增 | `src/tests/unit/services/test_identifiers.py` | 新增 `parse_thread_id_datetime()` 单元测试 |

---

## 6. 测试计划

### 6.1 单元测试

**文件**：`src/tests/unit/services/test_chat_history_reader.py`（扩展现有测试文件）

| 测试项 | 说明 |
|--------|------|
| `test_list_recent_sessions_empty` | Store 无数据时返回 `[]` |
| `test_list_recent_sessions_filters_by_user` | 仅返回指定 user_id 的会话，不混入其他用户 |
| `test_list_recent_sessions_order` | 按创建时间倒序（新->旧） |
| `test_list_recent_sessions_max_sessions` | 超过 max_sessions 时只返回前 N 条 |
| `test_list_recent_sessions_first_question` | 首问取的是该会话最早一条，而非最新一条 |
| `test_list_recent_sessions_includes_failed` | 包含 `success=false` 的会话（不过滤失败） |
| `test_list_recent_sessions_timeout` | 超时时返回 `[]` |
| `test_list_recent_sessions_store_disabled` | Store 未启用时返回 `[]` |
| `test_list_recent_sessions_empty_first_question` | 首问为空时返回空字符串（不报错） |

**文件**：`src/tests/unit/services/test_identifiers.py`（新增）

| 测试项 | 说明 |
|--------|------|
| `test_parse_thread_id_datetime_valid` | 合法 thread_id 返回正确的 UTC datetime（带 tzinfo） |
| `test_parse_thread_id_datetime_invalid` | 非法格式返回 `None` |
| `test_parse_thread_id_datetime_milliseconds` | 毫秒部分正确解析为 microsecond |

---

## 7. 注意事项

### 7.1 性能

- 单条 SQL 通过 CTE + `DISTINCT ON` 完成"找会话 + 取首问"，仅一次数据库往返
- `ORDER BY prefix DESC LIMIT 3` 利用主键索引，无全表扫描
- `DISTINCT ON (prefix) ... ORDER BY created_at ASC` 走 `(prefix, created_at)` 索引
- 此函数仅在 CLI 启动时调用一次，非热路径

### 7.2 Store 未启用时的降级

- 如果 Store 未启用（`is_store_enabled()` 返回 False）或连接失败，`list_recent_sessions()` 返回 `[]`
- `_select_session()` 发现无历史时，直接返回 None，静默进入新建会话流程，用户无感知

### 7.3 `--thread-id` 参数优先

- 如果用户通过 `--thread-id` 参数指定了 thread_id，`interactive_mode()` 跳过会话选择菜单
- `is_resumed` 保持 `False`，欢迎横幅不显示"已恢复"提示

### 7.4 `--no-rich` 降级

- 非 Rich 模式下，使用纯文本渲染菜单（无 Panel/Table，仅 print）
- 时间显示和输入交互逻辑不变

### 7.5 时区处理

- thread_id 中的 timestamp 为 UTC 时间
- `parse_thread_id_datetime()` 返回的 datetime 带 `tzinfo=timezone.utc`
- 显示时通过 `datetime.astimezone()` 转换为系统本地时区
- 不硬编码任何时区，依赖 Python 自动获取系统设置

### 7.6 配置依赖

- namespace 通过 `get_store_namespace()` 从配置读取（默认 `"chat_history"`），不硬编码
- schema 通过 `_get_persistence_config()["database"]["schema"]` 读取（默认 `"langgraph"`），SQL 中显式限定
- Store 可用性通过 `is_store_enabled()` 判断，不直接引用配置字段
- 数据库连接通过 `build_db_uri_from_config()` 获取，与 langgraph 持久化使用同一配置

### 7.7 展示容错

- `first_question` 为空时（脏数据、写入异常等），显示 `"（无对话内容）"` 兜底文案
- `parse_thread_id_datetime()` 解析失败时跳过该会话，不中断整体流程
- 时间显示异常时由 `astimezone()` 的内置容错处理
