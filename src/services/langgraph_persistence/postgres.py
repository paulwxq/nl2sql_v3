"""PostgresSaver / PostgresStore 核心工厂函数

提供 checkpointer 和 store 的单例管理、URI 构建、初始化等功能。
"""

import logging
from typing import Optional
from urllib.parse import quote, quote_plus, urlencode

from src.services.config_loader import get_config

logger = logging.getLogger(__name__)

# ==============================================================================
# 单例缓存
# ==============================================================================

_postgres_saver_father: Optional["PostgresSaver"] = None
_postgres_saver_subgraph: Optional["PostgresSaver"] = None
_postgres_store: Optional["PostgresStore"] = None
_persistence_initialized: bool = False

# 保存上下文管理器引用，防止被 GC（连接会关闭）
_context_managers: dict = {}


# ==============================================================================
# 配置读取与开关判断
# ==============================================================================


def _get_persistence_config() -> dict:
    """获取 langgraph_persistence 配置块"""
    config = get_config()
    return config.get("langgraph_persistence", {})


def is_persistence_enabled() -> bool:
    """检查持久化总开关是否启用"""
    return _get_persistence_config().get("enabled", False)


def is_checkpoint_enabled() -> bool:
    """检查 checkpoint 是否启用（总开关 + checkpoint 开关）"""
    persistence_config = _get_persistence_config()
    return (
        persistence_config.get("enabled", False)
        and persistence_config.get("checkpoint", {}).get("enabled", False)
    )


def is_store_enabled() -> bool:
    """检查 store 是否启用（总开关 + store 开关）"""
    persistence_config = _get_persistence_config()
    return (
        persistence_config.get("enabled", False)
        and persistence_config.get("store", {}).get("enabled", False)
    )


def get_checkpoint_namespace(kind: str = "father") -> str:
    """获取 checkpoint namespace

    Args:
        kind: "father" 或 "subgraph"

    Returns:
        namespace 字符串
    """
    persistence_config = _get_persistence_config()
    checkpoint_config = persistence_config.get("checkpoint", {})
    if kind == "father":
        return checkpoint_config.get("father_namespace", "nl2sql_father")
    else:
        return checkpoint_config.get("subgraph_namespace", "sql_generation")


def get_store_namespace() -> str:
    """获取 store namespace"""
    persistence_config = _get_persistence_config()
    return persistence_config.get("store", {}).get("namespace", "chat_history")


def get_store_write_timeout() -> float:
    """获取 store 写入超时（秒）"""
    persistence_config = _get_persistence_config()
    return persistence_config.get("store", {}).get("write_timeout", 2.0)


# ==============================================================================
# URI 构建
# ==============================================================================


def build_db_uri_from_config() -> str:
    """从配置构建 PostgreSQL URI

    Returns:
        URI 格式连接串，如 postgresql://user:pass@host:port/dbname?sslmode=disable&options=...

    Raises:
        ValueError: 配置缺失或不合法
    """
    config = get_config()
    persistence_config = config.get("langgraph_persistence", {})
    db_config = persistence_config.get("database", {})

    if not db_config.get("use_global_config", True):
        # 直接使用配置的 db_uri
        # 注意：此模式下 schema/sslmode 配置项不生效，需直接写入 db_uri 的 query 参数中
        db_uri = db_config.get("db_uri")
        if not db_uri:
            raise ValueError(
                "langgraph_persistence.database.db_uri is required when use_global_config=false"
            )
        return db_uri

    # 从 database.* 组装 URI
    global_db = config.get("database", {})
    host = global_db.get("host", "localhost")
    port = global_db.get("port", 5432)
    database = global_db.get("database", "postgres")
    user = global_db.get("user", "postgres")
    password = quote_plus(str(global_db.get("password", "")))  # URL 编码密码

    # 构建 query 参数
    query_params = {}

    # sslmode（可选，来自 langgraph_persistence.database.sslmode）
    sslmode = db_config.get("sslmode")
    if sslmode:
        query_params["sslmode"] = sslmode

    # 连接超时（防止连接阶段卡死）
    connect_timeout = db_config.get("connect_timeout", 5)
    query_params["connect_timeout"] = str(connect_timeout)

    # schema 作为 search_path（来自 langgraph_persistence.database.schema）
    # 同时设置 statement_timeout（防止 SQL 执行卡死，单位：毫秒）
    schema = db_config.get("schema", "langgraph")
    statement_timeout_ms = db_config.get("statement_timeout_ms", 5000)  # 默认 5 秒
    options_parts = []
    if schema:
        options_parts.append(f"-csearch_path={schema}")
    options_parts.append(f"-cstatement_timeout={statement_timeout_ms}")
    # 注意：多个 -c 选项用空格分隔，这里不预编码，让 urlencode 处理
    # 但 urlencode 的 quote_via 默认用 quote_plus（空格→+），PostgreSQL 需要 %20
    query_params["options"] = " ".join(options_parts)

    # 组装 query string
    # 使用 quote_via=quote 确保空格编码为 %20（而非 +），PostgreSQL options 需要这种格式
    query_string = f"?{urlencode(query_params, quote_via=quote)}" if query_params else ""

    return f"postgresql://{user}:{password}@{host}:{port}/{database}{query_string}"


# ==============================================================================
# PostgresSaver 工厂函数
# ==============================================================================


def get_postgres_saver(kind: str = "father") -> Optional["PostgresSaver"]:
    """获取 PostgresSaver 实例（单例）

    Args:
        kind: "father" 或 "subgraph"

    Returns:
        PostgresSaver 实例，或 None 如果未启用或创建失败

    注意：
        返回的实例需要在应用退出时关闭（调用 close_persistence）
    """
    global _postgres_saver_father, _postgres_saver_subgraph, _context_managers

    if not is_checkpoint_enabled():
        return None

    # 检查缓存
    if kind == "father" and _postgres_saver_father is not None:
        return _postgres_saver_father
    if kind == "subgraph" and _postgres_saver_subgraph is not None:
        return _postgres_saver_subgraph

    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        db_uri = build_db_uri_from_config()
        # from_conn_string 返回上下文管理器，需进入上下文获取实际实例
        context_manager = PostgresSaver.from_conn_string(db_uri)
        saver = context_manager.__enter__()
        
        # 保存上下文管理器引用，防止被 GC（否则连接会关闭）
        _context_managers[f"saver_{kind}"] = context_manager

        # 首次创建时自动调用 setup()
        try:
            saver.setup()
            logger.info(f"PostgresSaver ({kind}) setup 完成")
        except Exception as setup_err:
            # setup 失败可能是严重问题（权限不足、schema 不存在等）
            # 提升到 warning 级别，但仍继续（表可能已存在）
            logger.warning(f"PostgresSaver ({kind}) setup 异常: {setup_err}")
            logger.warning("如果是首次运行且表不存在，checkpoint 功能可能无法正常工作")

        if kind == "father":
            _postgres_saver_father = saver
        else:
            _postgres_saver_subgraph = saver

        logger.info(f"PostgresSaver ({kind}) 创建成功")
        return saver

    except Exception as e:
        logger.warning(f"PostgresSaver ({kind}) 创建失败: {e}")
        return None


# ==============================================================================
# PostgresStore 工厂函数
# ==============================================================================


def get_postgres_store() -> Optional["PostgresStore"]:
    """获取 PostgresStore 实例（单例）

    Returns:
        PostgresStore 实例，或 None 如果未启用或创建失败

    注意：
        返回的实例需要在应用退出时关闭（调用 close_persistence）
    """
    global _postgres_store, _context_managers

    if not is_store_enabled():
        return None

    if _postgres_store is not None:
        return _postgres_store

    try:
        from langgraph.store.postgres import PostgresStore

        db_uri = build_db_uri_from_config()
        # from_conn_string 返回上下文管理器，需进入上下文获取实际实例
        context_manager = PostgresStore.from_conn_string(db_uri)
        store = context_manager.__enter__()
        
        # 保存上下文管理器引用，防止被 GC
        _context_managers["store"] = context_manager
        
        # 首次创建时自动调用 setup()
        try:
            store.setup()
            logger.info("PostgresStore setup 完成")
        except Exception as setup_err:
            # setup 失败可能是严重问题（权限不足、schema 不存在等）
            # 提升到 warning 级别，但仍继续（表可能已存在）
            logger.warning(f"PostgresStore setup 异常: {setup_err}")
            logger.warning("如果是首次运行且表不存在，Store 功能可能无法正常工作")
        
        _postgres_store = store

        logger.info("PostgresStore 创建成功")
        return store

    except Exception as e:
        logger.warning(f"PostgresStore 创建失败: {e}")
        return None


# ==============================================================================
# 初始化（建表）
# ==============================================================================


def setup_persistence() -> bool:
    """初始化 LangGraph 持久化：创建表 + 跑迁移（幂等）

    应在应用启动时调用一次。此函数会触发单例创建，
    单例创建时自动调用 setup()。

    Returns:
        True 如果初始化成功（实例创建成功），False 如果失败或未启用

    注意：
        即使返回 True，也可能存在 setup 异常（表已存在时的幂等情况）。
        建议检查日志中的 warning 信息确认 setup 是否真正成功。
    """
    global _persistence_initialized

    if _persistence_initialized:
        logger.debug("LangGraph 持久化已初始化，跳过")
        return True

    if not is_persistence_enabled():
        logger.debug("LangGraph 持久化未启用，跳过初始化")
        return False

    success = True
    
    try:
        # 通过获取单例来触发创建和 setup（单例创建时自动调用 setup）
        if is_checkpoint_enabled():
            saver = get_postgres_saver("father")
            if saver:
                logger.info("PostgresSaver 实例创建成功")
            else:
                logger.error("PostgresSaver 实例创建失败")
                success = False

        if is_store_enabled():
            store = get_postgres_store()
            if store:
                logger.info("PostgresStore 实例创建成功")
            else:
                logger.error("PostgresStore 实例创建失败")
                success = False

        if success:
            _persistence_initialized = True
            logger.info("LangGraph 持久化初始化完成")
        else:
            logger.error("LangGraph 持久化初始化部分失败，请检查上述错误")
        
        return success

    except Exception as e:
        logger.error(f"LangGraph 持久化初始化失败: {e}")
        return False


# ==============================================================================
# 资源清理
# ==============================================================================


def close_persistence():
    """关闭所有持久化连接

    应在应用退出时调用。此函数会：
    1. 关闭所有上下文管理器（释放数据库连接）
    2. 清空单例缓存

    线程安全：此函数非线程安全，应在所有业务操作完成后调用。
    """
    global _postgres_saver_father, _postgres_saver_subgraph, _postgres_store, _persistence_initialized, _context_managers

    # 关闭所有上下文管理器
    for key, cm in list(_context_managers.items()):
        try:
            cm.__exit__(None, None, None)
            logger.debug(f"关闭持久化连接: {key}")
        except Exception as e:
            logger.warning(f"关闭持久化连接失败 ({key}): {e}")

    _context_managers.clear()
    _postgres_saver_father = None
    _postgres_saver_subgraph = None
    _postgres_store = None
    _persistence_initialized = False

    logger.info("LangGraph 持久化连接已关闭")


def reset_persistence_cache():
    """重置单例缓存（仅用于测试，close_persistence 的别名）"""
    close_persistence()


# 注册进程退出时的清理钩子
import atexit

def _atexit_close_persistence():
    """atexit 钩子：静默关闭连接"""
    global _context_managers
    for key, cm in list(_context_managers.items()):
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass
    _context_managers.clear()

atexit.register(_atexit_close_persistence)

