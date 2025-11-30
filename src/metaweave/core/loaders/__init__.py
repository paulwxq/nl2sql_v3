"""MetaWeave 数据加载器模块

提供统一的加载器接口，支持不同类型的数据加载到不同的目标数据库。
"""

from src.metaweave.core.loaders.base import BaseLoader
from src.metaweave.core.loaders.cql_loader import CQLLoader
from src.metaweave.core.loaders.factory import LoaderFactory

__all__ = [
    "BaseLoader",
    "CQLLoader",
    "LoaderFactory",
]
