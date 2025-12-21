"""PostgreSQL 连接池管理 - 支持 pgvector 扩展"""

import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.services.config_loader import get_config


class PGConnectionManager:
    """PostgreSQL 连接池管理器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化连接池管理器

        Args:
            config: 数据库配置，如果为 None 则从全局配置加载
        """
        if config is None:
            main_config = get_config()
            config = main_config["database"]

        self.config = config
        self._pool: Optional[ConnectionPool] = None

    def _build_connection_string(self) -> str:
        """
        构建 PostgreSQL 连接字符串

        Returns:
            连接字符串
        """
        return (
            f"host={self.config['host']} "
            f"port={self.config['port']} "
            f"dbname={self.config['database']} "
            f"user={self.config['user']} "
            f"password={self.config['password']}"
        )

    def initialize(self) -> None:
        """
        初始化连接池

        Raises:
            psycopg.OperationalError: 连接失败
        """
        if self._pool is not None:
            return

        conninfo = self._build_connection_string()

        # 创建连接池
        self._pool = ConnectionPool(
            conninfo=conninfo,
            min_size=self.config.get("pool_min_size", 5),
            max_size=self.config.get("pool_max_size", 20),
            timeout=self.config.get("pool_timeout", 30),
            kwargs={
                "row_factory": dict_row,  # 返回字典格式的行
            },
        )

        # ✅ 条件注册 pgvector 扩展（仅 PgVector 模式需要）
        main_config = get_config()
        vector_db_config = main_config.get("vector_database", {})
        active_vector_db = vector_db_config.get("active")

        # ⚠️ 配置缺失时明确失败（与工厂函数保持一致）
        if not active_vector_db:
            raise ValueError(
                "缺少 vector_database.active 配置。\n"
                "请在 config.yaml 中设置 vector_database.active 为 'pgvector' 或 'milvus'。\n"
                "这是必需配置，不提供默认值以避免掩盖配置错误。"
            )

        if active_vector_db == "pgvector":
            with self._pool.connection() as conn:
                register_vector(conn)
            print(f"✅ PostgreSQL 连接池已初始化（已注册 pgvector 扩展）: {self.config['host']}:{self.config['port']}/{self.config['database']}")
        else:
            print(f"✅ PostgreSQL 连接池已初始化（{active_vector_db} 模式，跳过 pgvector 注册）: {self.config['host']}:{self.config['port']}/{self.config['database']}")

    def close(self) -> None:
        """关闭连接池"""
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            print("✅ PostgreSQL 连接池已关闭")

    @contextmanager
    def get_connection(self) -> Generator[psycopg.Connection, None, None]:
        """
        获取数据库连接（上下文管理器）

        Yields:
            psycopg.Connection 实例

        Example:
            >>> with pg_manager.get_connection() as conn:
            >>>     with conn.cursor() as cur:
            >>>         cur.execute("SELECT * FROM table")
        """
        if self._pool is None:
            self.initialize()

        with self._pool.connection() as conn:
            yield conn

    def test_connection(self) -> bool:
        """
        测试数据库连接

        Returns:
            连接成功返回 True，失败返回 False
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS test")
                    result = cur.fetchone()
                    assert result["test"] == 1

            print("✅ PostgreSQL 连接测试成功")
            return True

        except Exception as e:
            print(f"❌ PostgreSQL 连接测试失败: {e}")
            return False

    def execute_with_retry(
        self,
        query: str,
        params: Optional[tuple] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> Any:
        """
        执行查询并支持重试

        Args:
            query: SQL 查询语句
            params: 查询参数
            max_retries: 最大重试次数（默认从配置读取）
            retry_delay: 重试延迟（秒，默认从配置读取）

        Returns:
            查询结果

        Raises:
            Exception: 重试后仍然失败
        """
        if max_retries is None:
            max_retries = self.config.get("max_retries", 3)
        if retry_delay is None:
            retry_delay = self.config.get("retry_delay", 1)

        last_exception = None

        for attempt in range(max_retries):
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(query, params)
                        return cur.fetchall()

            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    print(f"⚠️ 查询失败（尝试 {attempt + 1}/{max_retries}），{retry_delay}秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    print(f"❌ 查询失败（已重试 {max_retries} 次）: {e}")

        raise last_exception

    def check_pgvector_extension(self) -> bool:
        """
        检查 pgvector 扩展是否已安装

        Returns:
            已安装返回 True，否则返回 False
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    )
                    result = cur.fetchone()

            if result:
                print("✅ pgvector 扩展已安装")
                return True
            else:
                print("❌ pgvector 扩展未安装，请先安装：CREATE EXTENSION vector;")
                return False

        except Exception as e:
            print(f"❌ 检查 pgvector 扩展失败: {e}")
            return False

    def get_pool_status(self) -> Dict[str, Any]:
        """
        获取连接池状态

        Returns:
            连接池状态信息
        """
        if self._pool is None:
            return {"initialized": False}

        return {
            "initialized": True,
            "min_size": self._pool.min_size,
            "max_size": self._pool.max_size,
            "name": self._pool.name,
        }


# 全局连接池管理器实例（单例）
_global_pg_manager: Optional[PGConnectionManager] = None


def get_pg_manager() -> PGConnectionManager:
    """
    获取全局 PostgreSQL 连接池管理器（单例）

    Returns:
        PGConnectionManager 实例
    """
    global _global_pg_manager

    if _global_pg_manager is None:
        _global_pg_manager = PGConnectionManager()
        _global_pg_manager.initialize()

    return _global_pg_manager


def close_pg_manager() -> None:
    """关闭全局连接池"""
    global _global_pg_manager

    if _global_pg_manager is not None:
        _global_pg_manager.close()
        _global_pg_manager = None
