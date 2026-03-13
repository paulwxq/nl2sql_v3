"""对话历史读取器（原生 PostgresStore）

读取策略（与 docs/75_对话历史功能优化与bug修复.md 对齐）：
- namespace 下钻：写入为 namespace=(chat_history, thread_id)，key=query_id
- 读取：store.search((chat_history, thread_id), limit=history_max_turns*2)
- 过滤：success 必须存在且为 true；question/answer 非空；排除 exclude_query_id
- 排序：代码层按 item.updated_at 排序，输出旧→新
- 超时：10 秒；fail-open：异常/超时返回 []
"""

from __future__ import annotations

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.langgraph_persistence.postgres import (
    build_db_uri_from_config,
    get_postgres_store,
    get_store_namespace,
    is_store_enabled,
    _get_persistence_config,
)
from src.utils.logger import get_module_logger

logger = get_module_logger("persistence.history_reader")

_DEFAULT_READ_TIMEOUT_SECONDS = 10.0
_DEFAULT_FETCH_MULTIPLIER = 2

_read_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def _get_read_executor() -> ThreadPoolExecutor:
    global _read_executor
    if _read_executor is None:
        with _executor_lock:
            if _read_executor is None:
                _read_executor = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="store_reader"
                )
    return _read_executor


def shutdown_read_executor():
    global _read_executor
    if _read_executor is not None:
        with _executor_lock:
            if _read_executor is not None:
                logger.debug("正在关闭 Store 读取线程池...")
                _read_executor.shutdown(wait=False, cancel_futures=True)
                _read_executor = None


atexit.register(shutdown_read_executor)


def get_recent_turns(
    *,
    thread_id: str,
    history_max_turns: int,
    max_history_content_length: int,
    exclude_query_id: Optional[str] = None,
    timeout_seconds: float = _DEFAULT_READ_TIMEOUT_SECONDS,
) -> List[Dict[str, str]]:
    """读取最近对话历史（旧→新）。

    Args:
        thread_id: 会话 ID
        history_max_turns: 最多返回的轮数（Q/A 为一轮）
        max_history_content_length: 每条 question/answer 的最大字符数（仅截断 history）
        exclude_query_id: 排除的 query_id（防御性：避免把当前轮次也注入）
        timeout_seconds: 读取超时（秒），默认 10 秒

    Returns:
        [{"question": "...", "answer": "..."}, ...]（旧→新）
    """
    if not thread_id:
        return []
    if history_max_turns <= 0:
        return []

    if not is_store_enabled():
        return []

    store = get_postgres_store()
    if store is None:
        return []

    namespace = get_store_namespace()
    limit = max(1, int(history_max_turns) * _DEFAULT_FETCH_MULTIPLIER)

    def _do_read() -> List[Any]:
        # PostgresStore.search(namespace_prefix, *, limit, offset, filter, query, ...)
        return store.search((namespace, thread_id), limit=limit, offset=0)

    try:
        executor = _get_read_executor()
        future = executor.submit(_do_read)
        items = future.result(timeout=float(timeout_seconds))
    except FuturesTimeoutError:
        logger.warning(
            "读取对话历史超时（%ss，已跳过）：thread_id=%s",
            timeout_seconds,
            thread_id,
        )
        return []
    except Exception as e:
        logger.warning("读取对话历史失败（已跳过）：%s", e)
        return []

    # 防御性排序：按 updated_at 升序（旧→新）
    try:
        items_sorted = sorted(
            items,
            key=lambda x: getattr(x, "updated_at", None) or datetime.min,
        )
    except Exception:
        items_sorted = list(items)

    turns: List[Dict[str, str]] = []

    for item in items_sorted:
        try:
            key = getattr(item, "key", None)
            value = getattr(item, "value", None) or {}
            if not isinstance(value, dict):
                continue

            # 排除当前 query_id（防御性）
            if exclude_query_id:
                if key == exclude_query_id or value.get("query_id") == exclude_query_id:
                    continue

            # success 必须存在且为 true
            if value.get("success") is not True:
                continue

            user = value.get("user") or {}
            assistant = value.get("assistant") or {}
            question = (user.get("content") or "").strip()
            answer = (assistant.get("content") or "").strip()

            if not question:
                continue
            if not answer:
                continue

            turns.append(
                {
                    "question": _truncate(question, max_history_content_length),
                    "answer": _truncate(answer, max_history_content_length),
                }
            )
        except Exception:
            continue

    if len(turns) <= history_max_turns:
        return turns
    return turns[-history_max_turns:]


def list_recent_sessions(
    *,
    user_id: str = "guest",
    max_sessions: int = 3,
    timeout_seconds: float = 5.0,
) -> List[Dict[str, Any]]:
    """列举用户最近的会话列表（新->旧）。

    通过原生 SQL 查询 langgraph store 表，利用 prefix 字典序 = 时间序的特性，
    一次查询同时获取最近 N 个会话及其首问。

    Args:
        user_id: 用户标识（已经过 sanitize_user_id 处理）
        max_sessions: 最多返回的会话数
        timeout_seconds: 整体超时（秒）

    Returns:
        [
            {
                "thread_id": "guest:20260305T183946997Z",
                "created_at": datetime(..., tzinfo=UTC),
                "first_question": "请问广州市的京东便利店的总收入是多少",
            },
            ...
        ]
        按会话创建时间由近到远排列。Store 未启用、超时或异常时返回 []。
    """
    if not is_store_enabled():
        return []

    namespace = get_store_namespace()
    persistence_config = _get_persistence_config()
    schema = persistence_config.get("database", {}).get("schema") or "public"
    prefix_pattern = f"{namespace}.{user_id}:%"

    def _do_query() -> List[Dict[str, Any]]:
        rows = _query_recent_sessions(
            prefix_pattern=prefix_pattern,
            schema=schema,
            namespace=namespace,
            max_sessions=max_sessions,
        )
        return rows

    try:
        executor = _get_read_executor()
        future = executor.submit(_do_query)
        rows = future.result(timeout=float(timeout_seconds))
    except FuturesTimeoutError:
        logger.warning(
            "读取历史会话列表超时（%ss，降级为新建会话）",
            timeout_seconds,
        )
        return []
    except Exception as e:
        logger.warning("读取历史会话列表失败（降级为新建会话）：%s", e)
        return []

    # 后处理：从 prefix 提取 thread_id 并解析创建时间
    from src.services.langgraph_persistence.identifiers import parse_thread_id_datetime

    sessions: List[Dict[str, Any]] = []
    expected_prefix = f"{namespace}."
    for row in rows:
        prefix = row.get("prefix", "")
        # prefix = "chat_history.guest:20260305T183946997Z"
        # thread_id = "guest:20260305T183946997Z"
        if not prefix.startswith(expected_prefix):
            continue
        tid = prefix[len(expected_prefix):]

        created_at = parse_thread_id_datetime(tid)
        if created_at is None:
            continue

        sessions.append({
            "thread_id": tid,
            "created_at": created_at,
            "first_question": (row.get("first_question") or "").strip(),
        })

    return sessions


def _query_recent_sessions(
    *,
    prefix_pattern: str,
    schema: str,
    namespace: str,
    max_sessions: int,
) -> List[Dict[str, Any]]:
    """执行原生 SQL 查询最近会话及首问。

    使用 build_db_uri_from_config() 获取 langgraph 数据库连接，
    不依赖 PostgresStore 内部 API，也不依赖业务 DB 连接。

    Args:
        prefix_pattern: LIKE 模式，如 "chat_history.guest:%"
        schema: 数据库 schema，如 "langgraph"
        namespace: store namespace，如 "chat_history"
        max_sessions: 最多返回的会话数

    Returns:
        [{"prefix": "...", "first_question": "..."}, ...]
        按 prefix DESC 排列（新->旧）。
    """
    import psycopg
    from psycopg.rows import dict_row

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


def _truncate(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."
