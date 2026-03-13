"""对话历史写入器

提供 append_turn() 函数，用于将对话记录写入 PostgresStore。
本阶段仅写入，不规划读取。
"""

import atexit
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.services.langgraph_persistence.postgres import (
    get_postgres_store,
    get_store_namespace,
    get_store_write_timeout,
    is_store_enabled,
)
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("persistence.history_writer")

# 线程池用于超时控制（多 worker 避免单点阻塞）
# 注意：
#   1. PostgresStore 使用 psycopg 连接池，是线程安全的
#   2. 如果遇到并发问题，可将 max_workers 改为 1
#   3. 线程池超时只是放弃等待，真正的硬超时依赖数据库层：
#      - connect_timeout: 连接超时（config.yaml 中配置）
#      - statement_timeout: SQL 执行超时（config.yaml 中配置）
_write_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def _get_write_executor() -> ThreadPoolExecutor:
    """获取或创建线程池（懒加载）"""
    global _write_executor
    if _write_executor is None:
        with _executor_lock:
            if _write_executor is None:
                _write_executor = ThreadPoolExecutor(
                    max_workers=3, thread_name_prefix="store_writer"
                )
    return _write_executor


def shutdown_write_executor():
    """关闭写入线程池（用于进程退出或手动清理）
    
    使用 wait=False 避免被卡住的线程阻塞进程退出。
    """
    global _write_executor
    if _write_executor is not None:
        with _executor_lock:
            if _write_executor is not None:
                logger.debug("正在关闭 Store 写入线程池...")
                _write_executor.shutdown(wait=False, cancel_futures=True)
                _write_executor = None


# 注册 atexit 钩子，确保进程退出时关闭线程池
atexit.register(shutdown_write_executor)

# 健康检查：连续超时次数 + 自动恢复
_consecutive_timeouts = 0
_disabled_at: Optional[float] = None  # 禁用时的时间戳（time.time()）
_timeout_lock = threading.Lock()
_MAX_CONSECUTIVE_TIMEOUTS = 5  # 连续超时 5 次后临时禁用
_COOLDOWN_SECONDS = 60.0  # 禁用后 60 秒自动尝试恢复


def append_turn(
    thread_id: str,
    query_id: str,
    user_text: str,
    assistant_text: str,
    *,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    success: Optional[bool] = None,
) -> bool:
    """追加一轮对话记录到 PostgresStore

    Args:
        thread_id: 会话 ID（格式：{user_id}:{timestamp}）
        query_id: 单次请求 ID
        user_text: 用户输入文本
        assistant_text: 助手回复文本
        user_id: 用户 ID（可选，如果不传则从 thread_id 解析）
        metadata: 额外元数据（如 complexity, path_taken 等）

    Returns:
        True 如果写入成功，False 如果失败或未启用
    """
    global _consecutive_timeouts, _disabled_at

    # 在函数入口处创建带 query_id 前缀的局部 logger，覆盖所有分支（含跳过/降级日志）
    qlog = with_query_id(logger, query_id)

    if not is_store_enabled():
        qlog.debug("Store 未启用，跳过对话历史写入")
        return False

    # 健康检查：连续超时过多时临时禁用，但有冷却期自动恢复
    with _timeout_lock:
        if _consecutive_timeouts >= _MAX_CONSECUTIVE_TIMEOUTS:
            # 检查是否已过冷却期
            if _disabled_at is not None:
                elapsed = time.time() - _disabled_at
                if elapsed >= _COOLDOWN_SECONDS:
                    # 冷却期已过，自动恢复尝试一次
                    qlog.info(f"Store 写入冷却期已过（{elapsed:.1f}s），尝试恢复...")
                    _consecutive_timeouts = 0
                    _disabled_at = None
                else:
                    qlog.debug(
                        f"Store 写入已临时禁用（连续超时 {_consecutive_timeouts} 次），"
                        f"剩余冷却 {_COOLDOWN_SECONDS - elapsed:.1f}s"
                    )
                    return False
            else:
                # 首次达到阈值但未设置禁用时间（不应该发生，防御性处理）
                qlog.debug(f"Store 写入已临时禁用（连续超时 {_consecutive_timeouts} 次）")
                return False

    store = get_postgres_store()
    if store is None:
        qlog.warning("PostgresStore 实例获取失败，跳过对话历史写入")
        return False

    # key 仅使用 query_id（thread_id 已下钻到 namespace/prefix）
    key = query_id

    # 从 thread_id 解析 user_id（如果未传入）
    if user_id is None:
        from src.services.langgraph_persistence.identifiers import (
            get_user_id_from_thread_id,
        )
        user_id = get_user_id_from_thread_id(thread_id)

    # 构建 value
    value = {
        "thread_id": thread_id,
        "user_id": user_id,
        "query_id": query_id,
        "success": success,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user": {"role": "user", "content": _truncate_text(user_text, 10000)},
        "assistant": {"role": "assistant", "content": _truncate_text(assistant_text, 10000)},
        "metadata": metadata or {},
    }

    # 获取 namespace 和超时配置
    namespace = get_store_namespace()
    write_timeout = get_store_write_timeout()

    def _do_write():
        """实际写入操作（在线程池中执行）"""
        store.put(namespace=(namespace, thread_id), key=key, value=value)

    try:
        # 使用线程池实现超时控制
        executor = _get_write_executor()
        future = executor.submit(_do_write)
        future.result(timeout=write_timeout)
        
        # 写入成功，重置超时计数和禁用状态
        with _timeout_lock:
            _consecutive_timeouts = 0
            _disabled_at = None
        
        qlog.debug(f"对话历史写入成功: key={key}")
        return True

    except FuturesTimeoutError:
        # 记录连续超时
        with _timeout_lock:
            _consecutive_timeouts += 1
            if _consecutive_timeouts >= _MAX_CONSECUTIVE_TIMEOUTS:
                _disabled_at = time.time()  # 记录禁用时间
                qlog.error(
                    f"对话历史写入连续超时 {_consecutive_timeouts} 次，已临时禁用 {_COOLDOWN_SECONDS}s。"
                    "可能是数据库连接问题，请检查。"
                )
        qlog.warning(f"对话历史写入超时（{write_timeout}s），已跳过: key={key}")
        return False

    except Exception as e:
        qlog.warning(f"对话历史写入失败（已跳过）: {e}, key={key}")
        return False


def reset_write_health():
    """重置写入健康状态（用于测试或手动恢复）"""
    global _consecutive_timeouts, _disabled_at
    with _timeout_lock:
        _consecutive_timeouts = 0
        _disabled_at = None
    logger.info("Store 写入健康状态已重置")


def _truncate_text(text: str, max_length: int) -> str:
    """截断文本到指定长度

    Args:
        text: 原始文本
        max_length: 最大长度

    Returns:
        截断后的文本（如超长则添加 ... 后缀）
    """
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
