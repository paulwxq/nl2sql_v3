"""Neo4j 图数据库连接管理"""

from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

from neo4j import GraphDatabase, Session
from neo4j.exceptions import Neo4jError

from src.services.config_loader import get_config


class Neo4jConnectionManager:
    """Neo4j 连接管理器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化连接管理器

        Args:
            config: Neo4j 配置，如果为 None 则从全局配置加载
        """
        if config is None:
            main_config = get_config()
            config = main_config["neo4j"]

        self.config = config
        self._driver = None

    def initialize(self) -> None:
        """
        初始化 Neo4j 驱动

        Raises:
            Neo4jError: 连接失败
        """
        if self._driver is not None:
            return

        self._driver = GraphDatabase.driver(
            self.config["uri"],
            auth=(self.config["user"], self.config["password"]),
            max_connection_lifetime=self.config.get("max_connection_lifetime", 3600),
            max_connection_pool_size=self.config.get("max_connection_pool_size", 50),
            connection_timeout=self.config.get("connection_timeout", 30),
        )

        print(f"✅ Neo4j 驱动已初始化: {self.config['uri']}")

    def close(self) -> None:
        """关闭 Neo4j 驱动"""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            print("✅ Neo4j 驱动已关闭")

    @contextmanager
    def get_session(self, database: Optional[str] = None) -> Generator[Session, None, None]:
        """
        获取 Neo4j 会话（上下文管理器）

        Args:
            database: 数据库名称，如果为 None 则使用配置中的默认数据库

        Yields:
            neo4j.Session 实例

        Example:
            >>> with neo4j_manager.get_session() as session:
            >>>     result = session.run("MATCH (n) RETURN n LIMIT 1")
        """
        if self._driver is None:
            self.initialize()

        if database is None:
            database = self.config.get("database", "neo4j")

        session = self._driver.session(database=database)
        try:
            yield session
        finally:
            session.close()

    def test_connection(self) -> bool:
        """
        测试 Neo4j 连接

        Returns:
            连接成功返回 True，失败返回 False
        """
        try:
            with self.get_session() as session:
                result = session.run("RETURN 1 AS test")
                record = result.single()
                assert record["test"] == 1

            print("✅ Neo4j 连接测试成功")
            return True

        except Exception as e:
            print(f"❌ Neo4j 连接测试失败: {e}")
            return False

    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> list:
        """
        执行 Cypher 查询

        Args:
            query: Cypher 查询语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            查询结果列表

        Raises:
            Neo4jError: 查询失败
        """
        with self.get_session(database) as session:
            result = session.run(query, parameters or {})
            return list(result)

    def execute_write_transaction(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> Any:
        """
        执行写事务

        Args:
            query: Cypher 写操作语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            事务结果
        """
        def work(tx):
            return tx.run(query, parameters or {})

        with self.get_session(database) as session:
            result = session.execute_write(work)
            return result

    def execute_read_transaction(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> list:
        """
        执行读事务

        Args:
            query: Cypher 查询语句
            parameters: 查询参数
            database: 数据库名称

        Returns:
            查询结果列表
        """
        def work(tx):
            result = tx.run(query, parameters or {})
            return list(result)

        with self.get_session(database) as session:
            return session.execute_read(work)

    def check_apoc_available(self) -> bool:
        """
        检查 APOC 插件是否可用

        Returns:
            可用返回 True，否则返回 False
        """
        try:
            with self.get_session() as session:
                result = session.run("RETURN apoc.version() AS version")
                record = result.single()

                if record:
                    version = record["version"]
                    print(f"✅ APOC 插件已安装: {version}")
                    return True
                else:
                    print("❌ APOC 插件未安装")
                    return False

        except Neo4jError as e:
            print(f"❌ APOC 插件不可用: {e}")
            return False

    def get_database_info(self) -> Dict[str, Any]:
        """
        获取数据库信息

        Returns:
            数据库信息字典
        """
        try:
            with self.get_session() as session:
                # 获取节点和关系数量
                result = session.run(
                    """
                    CALL apoc.meta.stats()
                    YIELD nodeCount, relCount, labelCount, relTypeCount
                    RETURN nodeCount, relCount, labelCount, relTypeCount
                    """
                )
                record = result.single()

                if record:
                    return {
                        "node_count": record["nodeCount"],
                        "relationship_count": record["relCount"],
                        "label_count": record["labelCount"],
                        "relationship_type_count": record["relTypeCount"],
                    }
                else:
                    # 如果 APOC 不可用，返回基本信息
                    return {"status": "connected", "apoc_available": False}

        except Exception as e:
            print(f"⚠️ 无法获取数据库信息: {e}")
            return {"status": "connected", "details_unavailable": True}

    def verify_driver(self) -> bool:
        """
        验证驱动是否正常

        Returns:
            正常返回 True，否则返回 False
        """
        if self._driver is None:
            return False

        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False


# 全局 Neo4j 管理器实例（单例）
_global_neo4j_manager: Optional[Neo4jConnectionManager] = None


def get_neo4j_manager() -> Neo4jConnectionManager:
    """
    获取全局 Neo4j 连接管理器（单例）

    Returns:
        Neo4jConnectionManager 实例
    """
    global _global_neo4j_manager

    if _global_neo4j_manager is None:
        _global_neo4j_manager = Neo4jConnectionManager()
        _global_neo4j_manager.initialize()

    return _global_neo4j_manager


def close_neo4j_manager() -> None:
    """关闭全局 Neo4j 管理器"""
    global _global_neo4j_manager

    if _global_neo4j_manager is not None:
        _global_neo4j_manager.close()
        _global_neo4j_manager = None
