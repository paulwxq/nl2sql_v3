"""
MetaWeave - 数据库元数据自动生成和增强平台

MetaWeave 是一个用于从 PostgreSQL 数据库中自动抽取元数据、
生成数据画像、发现表关系，并导出到图数据库和向量数据库的工具平台。
"""

__version__ = "0.1.0"
__author__ = "MetaWeave Team"

# 导出主要类供外部使用
from src.metaweave.core.metadata.generator import MetadataGenerator

__all__ = ["MetadataGenerator"]

