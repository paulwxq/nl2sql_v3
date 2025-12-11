"""Milvus 向量数据库客户端封装。"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.metaweave.services.vector_db.base import BaseVectorClient

logger = logging.getLogger(__name__)


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


class MilvusClient(BaseVectorClient):
    """Milvus 客户端封装。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.alias = config.get("alias", "default")
        self.connected = False

    def connect(self) -> None:
        connections, db, *_, utility = _lazy_import_milvus()
        if self.connected:
            return

        connections.connect(
            alias=self.alias,
            host=self.config.get("host", "localhost"),
            port=str(self.config.get("port", "19530")),
            user=self.config.get("user"),
            password=self.config.get("password"),
            timeout=self.config.get("timeout", 30),
        )
        self.connected = True

        db_name = self.config.get("database")
        if db_name:
            if db_name not in db.list_database():
                db.create_database(db_name)
            db.using_database(db_name)

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

    def ensure_collection(
        self,
        collection_name: str,
        schema: Any,
        index_params: Dict[str, Any],
        clean: bool = False,
    ) -> Any:
        connections, db, FieldSchema, CollectionSchema, Collection, _, utility = _lazy_import_milvus()
        self.connect()

        db_name = self.config.get("database")
        if db_name:
            if db_name not in db.list_database():
                db.create_database(db_name)
            db.using_database(db_name)

        # 使用 utility.list_collections() 替代 db.list_collections()
        existing_collections = utility.list_collections(using=self.alias)
        
        if clean and collection_name in existing_collections:
            Collection(collection_name, using=self.alias).drop()

        if collection_name not in utility.list_collections(using=self.alias):
            collection = Collection(
                name=collection_name,
                schema=schema,
                shards_num=self.config.get("shards_num", 2),
                using=self.alias,  # 明确指定使用的连接别名
            )
        else:
            collection = Collection(collection_name, using=self.alias)

        # 创建向量索引（若不存在）
        if not collection.indexes:
            collection.create_index(
                field_name="embedding",
                index_params=index_params,
            )

        collection.load()
        return collection

    def insert_batch(
        self,
        collection_name: str,
        data: List[Dict[str, Any]],
    ) -> int:
        *_, Collection, _, _ = _lazy_import_milvus()
        if not data:
            return 0

        collection = Collection(collection_name, using=self.alias)
        # 将字典列表转换为列式数据
        fields = ["table_name", "col_name", "col_value", "embedding", "update_ts"]
        columns: Dict[str, List[Any]] = {f: [] for f in fields}
        for row in data:
            for f in fields:
                columns[f].append(row[f])

        entities = [columns[f] for f in fields]
        mr = collection.insert(entities)
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

