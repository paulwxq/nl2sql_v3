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
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.langgraph_persistence.postgres import (
    get_postgres_store,
    get_store_namespace,
    is_store_enabled,
)

logger = logging.getLogger(__name__)

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


def _truncate(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."
