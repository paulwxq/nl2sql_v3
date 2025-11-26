"""元数据生成模块

负责从 PostgreSQL 数据库中抽取和增强元数据信息。
"""

from src.metaweave.core.metadata.generator import MetadataGenerator
from src.metaweave.core.metadata.models import TableMetadata, ColumnInfo
from src.metaweave.core.metadata.ddl_loader import DDLLoader

__all__ = ["MetadataGenerator", "TableMetadata", "ColumnInfo", "DDLLoader"]

