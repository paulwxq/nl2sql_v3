"""PgVector 客户端占位实现（未来扩展）。"""

from typing import Any, Dict, List

from src.metaweave.services.vector_db.base import BaseVectorClient


class PgVectorClient(BaseVectorClient):  # pragma: no cover - 预留占位
    """暂未实现的 PgVector 客户端。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def connect(self) -> None:
        raise NotImplementedError("PgVectorClient 尚未实现")

    def test_connection(self) -> bool:
        raise NotImplementedError("PgVectorClient 尚未实现")

    def ensure_collection(self, collection_name: str, schema: Any, index_params: Dict[str, Any], clean: bool = False) -> Any:
        raise NotImplementedError("PgVectorClient 尚未实现")

    def insert_batch(self, collection_name: str, data: List[Dict[str, Any]]) -> int:
        raise NotImplementedError("PgVectorClient 尚未实现")

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        raise NotImplementedError("PgVectorClient 尚未实现")

    def close(self) -> None:
        raise NotImplementedError("PgVectorClient 尚未实现")

