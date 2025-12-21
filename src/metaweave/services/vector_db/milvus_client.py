"""兼容 shim：保持 MetaWeave 侧引用不断。

本文件已改为 re-export，实际实现位于 src.services.vector_db.milvus_client
"""

# ⚠️ 必须 re-export 所有被外部引用的符号
from src.services.vector_db.milvus_client import (  # noqa: F401
    MilvusClient,
    _lazy_import_milvus,
)

__all__ = ["MilvusClient", "_lazy_import_milvus"]
