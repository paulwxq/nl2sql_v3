"""Step 3: 关系发现模块

从Step 2生成的JSON元数据中发现表间关系（外键直通 + 推断关系）。
"""

from src.metaweave.core.relationships.models import (
    Relation,
    RelationshipDiscoveryResult,
)
from src.metaweave.core.relationships.pipeline import RelationshipDiscoveryPipeline

__all__ = [
    "Relation",
    "RelationshipDiscoveryResult",
    "RelationshipDiscoveryPipeline",
]
