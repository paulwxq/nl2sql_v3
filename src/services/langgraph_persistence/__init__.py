"""LangGraph 持久化服务模块

提供 PostgresSaver（Checkpoint）和 PostgresStore（历史对话）的统一接入。
"""

from src.services.langgraph_persistence.identifiers import (
    USER_ID_PATTERN,
    THREAD_ID_PATTERN,
    validate_user_id,
    sanitize_user_id,
    validate_thread_id,
    get_or_generate_thread_id,
    parse_thread_id,
    get_user_id_from_thread_id,
    parse_store_key,
    parse_store_key_safe,
)
from src.services.langgraph_persistence.postgres import (
    build_db_uri_from_config,
    get_postgres_saver,
    get_postgres_store,
    setup_persistence,
    close_persistence,
    is_checkpoint_enabled,
    is_store_enabled,
)
from src.services.langgraph_persistence.chat_history_writer import (
    append_turn,
    reset_write_health,
    shutdown_write_executor,
)
from src.services.langgraph_persistence.chat_history_reader import (
    get_recent_turns,
    shutdown_read_executor,
)

__all__ = [
    # identifiers
    "USER_ID_PATTERN",
    "THREAD_ID_PATTERN",
    "validate_user_id",
    "sanitize_user_id",
    "validate_thread_id",
    "get_or_generate_thread_id",
    "parse_thread_id",
    "get_user_id_from_thread_id",
    "parse_store_key",
    "parse_store_key_safe",
    # postgres
    "build_db_uri_from_config",
    "get_postgres_saver",
    "get_postgres_store",
    "setup_persistence",
    "close_persistence",
    "is_checkpoint_enabled",
    "is_store_enabled",
    # chat_history_writer
    "append_turn",
    "reset_write_health",
    "shutdown_write_executor",
    # chat_history_reader
    "get_recent_turns",
    "shutdown_read_executor",
]
