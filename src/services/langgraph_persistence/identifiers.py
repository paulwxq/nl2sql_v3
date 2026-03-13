"""thread_id / user_id / query_id 标识符工具函数

提供标识符的生成、校验、解析功能。
"""

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from src.utils.logger import get_module_logger

logger = get_module_logger("persistence.identifiers")

# ==============================================================================
# user_id 相关
# ==============================================================================

# user_id 字符集约束：字母、数字、下划线、连字符（禁止 : 和 #）
USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_user_id(user_id: str) -> bool:
    """校验 user_id 是否符合规范

    Args:
        user_id: 用户标识

    Returns:
        True 如果合法，False 如果不合法
    """
    if not user_id or len(user_id) > 64:
        return False
    return bool(USER_ID_PATTERN.match(user_id))


def sanitize_user_id(user_id: str | None) -> str:
    """清理并返回合法的 user_id，不合法时返回 'guest'

    Args:
        user_id: 用户标识（可能为 None 或不合法）

    Returns:
        合法的 user_id，不合法时返回 'guest'
    """
    if user_id and validate_user_id(user_id):
        return user_id
    return "guest"


# ==============================================================================
# thread_id 相关
# ==============================================================================

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
    - user_id 符合 [a-zA-Z0-9_-]（长度 1-64）
    - timestamp 符合 YYYYMMDDTHHmmssSSS + Z（19位固定格式）

    Args:
        thread_id: 要校验的 thread_id

    Returns:
        True 如果合法，False 如果不合法
    """
    if not thread_id or "#" in thread_id:
        return False
    if not THREAD_ID_PATTERN.match(thread_id):
        return False
    # 额外校验 user_id 长度（正则中 + 不限制上限）
    user_id = thread_id.split(":", 1)[0]
    return len(user_id) <= 64


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


def parse_thread_id(thread_id: str) -> Tuple[str, str]:
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
    parts = thread_id.split(":", 1)
    return (parts[0], parts[1])


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


# ==============================================================================
# Store key 相关
# ==============================================================================


def parse_store_key(key: str) -> Tuple[str, str, str]:
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
    user_id, _ = thread_id.split(":", 1)  # 按 : 分割一次
    return thread_id, user_id, query_id


def parse_store_key_safe(key: str) -> Tuple[str, str, str] | None:
    """安全版本：解析失败时返回 None 而非抛异常

    Args:
        key: Store key

    Returns:
        (thread_id, user_id, query_id) 元组，或 None 如果解析失败
    """
    try:
        return parse_store_key(key)
    except ValueError:
        return None

