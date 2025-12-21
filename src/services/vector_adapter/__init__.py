"""向量检索适配器模块。

提供统一的向量检索接口，支持 PgVector 和 Milvus 两种后端。
"""

from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.services.vector_adapter.factory import create_vector_search_adapter
from src.services.vector_adapter.milvus_adapter import MilvusSearchAdapter
from src.services.vector_adapter.pgvector_adapter import PgVectorSearchAdapter

__all__ = [
    "BaseVectorSearchAdapter",
    "create_vector_search_adapter",
    "MilvusSearchAdapter",
    "PgVectorSearchAdapter",
]
