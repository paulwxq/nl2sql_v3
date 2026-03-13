"""Milvus 向量数据库客户端封装（公共层）。

本模块提供 NL2SQL 模块与 Milvus 向量数据库之间的基础连接和操作能力。
不继承任何基类，仅提供连接、数据插入/更新等基础功能。
"""

from typing import Any, Dict, List, Optional, Tuple

from src.utils.logger import get_module_logger

logger = get_module_logger("milvus_client")


def _lazy_import_milvus() -> Tuple[Any, ...]:
    """延迟导入 pymilvus，避免在未安装时立刻失败。"""

    try:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            connections,
            db,
            utility,
        )
    except ImportError as exc:  # pragma: no cover - 在未安装 pymilvus 时用于友好提示
        raise ImportError("pymilvus 未安装，请安装后再使用 MilvusClient") from exc

    return connections, db, FieldSchema, CollectionSchema, Collection, DataType, utility


class MilvusClient:
    """Milvus 客户端封装（公共层）。

    提供连接管理、批量插入、Upsert 等基础操作。
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.alias = config.get("alias", "default")
        self.connected = False

    def connect(self) -> None:
        connections, db, *_, utility = _lazy_import_milvus()
        if self.connected:
            return

        # 建立连接
        connections.connect(
            alias=self.alias,
            host=self.config.get("host", "localhost"),
            port=str(self.config.get("port", "19530")),
            user=self.config.get("user"),
            password=self.config.get("password"),
            timeout=self.config.get("timeout", 30),
        )

        # ⚠️ 在设置 connected=True 之前先验证 database（避免状态污染）
        db_name = self.config.get("database")
        if db_name:
            # 检查 database 是否存在（不自动创建，遵循"清晰失败"原则）
            # ⚠️ 传递 using=self.alias 以操作正确的连接
            existing_databases = db.list_database(using=self.alias)
            if db_name not in existing_databases:
                raise ValueError(
                    f"Milvus database '{db_name}' 不存在。\n"
                    f"可用的 databases: {existing_databases}\n"
                    f"请确保已预先创建好数据库和 Collection，然后再启动 NL2SQL 模块。"
                )
            # ⚠️ 传递 using=self.alias 以操作正确的连接
            db.using_database(db_name, using=self.alias)

        # ✅ 所有验证通过后才设置 connected=True（避免状态污染）
        self.connected = True
        logger.info("✅ 已连接 Milvus: %s:%s/%s", self.config.get("host"), self.config.get("port"), db_name)

    def test_connection(self) -> bool:
        try:
            self.connect()
            *_, utility = _lazy_import_milvus()
            # 使用 utility.list_collections() 来测试连接
            utility.list_collections(using=self.alias)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Milvus 连接测试失败: %s", exc)
            return False

    def insert_batch(
        self,
        collection_name: str,
        data: List[Dict[str, Any]],
    ) -> int:
        *_, Collection, _, _ = _lazy_import_milvus()
        if not data:
            return 0

        collection = Collection(collection_name, using=self.alias)
        # 按 schema 顺序构建列式数据，通用实现
        field_names = [f.name for f in collection.schema.fields]
        columns: Dict[str, List[Any]] = {f: [] for f in field_names}
        for row in data:
            for f in field_names:
                columns[f].append(row.get(f))

        entities = [columns[f] for f in field_names]
        mr = collection.insert(entities)
        collection.flush()
        return len(mr.primary_keys) if mr and getattr(mr, "primary_keys", None) else len(data)

    def upsert_batch(
        self,
        collection_name: str,
        data: List[Dict[str, Any]],
    ) -> int:
        """批量 Upsert 数据到 Milvus Collection。

        适用于 object_id 作为主键、auto_id=False 的场景。
        """
        *_, Collection, _, _ = _lazy_import_milvus()
        if not data:
            return 0

        collection = Collection(collection_name, using=self.alias)

        # 按 Collection 的 schema 顺序构建列式数据，避免字段顺序不一致
        field_names = [f.name for f in collection.schema.fields]
        columns: Dict[str, List[Any]] = {f: [] for f in field_names}

        for row in data:
            for f in field_names:
                columns[f].append(row.get(f))

        entities = [columns[f] for f in field_names]
        mr = collection.upsert(entities)
        collection.flush()
        return len(mr.primary_keys) if mr and getattr(mr, "primary_keys", None) else len(data)

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        *_, Collection, _, _ = _lazy_import_milvus()
        collection = Collection(collection_name, using=self.alias)
        return collection.describe()

    def close(self) -> None:
        connections, *_ = _lazy_import_milvus()
        try:
            connections.disconnect(alias=self.alias)
        except Exception:
            pass
        self.connected = False
