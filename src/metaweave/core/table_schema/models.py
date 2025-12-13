from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


class ObjectType(str, enum.Enum):
    TABLE = "table"
    COLUMN = "column"


class TableCategory(str, enum.Enum):
    DIM = "dim"
    FACT = "fact"
    BRIDGE = "bridge"
    OTHER = "other"


@dataclass
class SchemaObject:
    object_type: ObjectType
    object_id: str
    parent_id: str
    object_desc: str
    time_col_hint: Optional[str] = None
    table_category: Optional[str] = None
    updated_at: int = 0

    def to_milvus_dict(self, embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        """转换为 Milvus upsert/insert 所需的字典。"""
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "parent_id": self.parent_id,
            "object_desc": self.object_desc,
            "embedding": embedding,
            "time_col_hint": self.time_col_hint or "",
            "table_category": self.table_category or "",
            "updated_at": self.updated_at,
        }


@dataclass
class LoaderOptions:
    batch_size: int = 50
    max_tables: int = 0  # 0 表示不限制
    include_columns: bool = True
    skip_empty_desc: bool = True

    @classmethod
    def from_dict(cls, options: Dict[str, Any]) -> "LoaderOptions":
        return cls(
            batch_size=options.get("batch_size", 50),
            max_tables=options.get("max_tables", 0),
            include_columns=options.get("include_columns", True),
            skip_empty_desc=options.get("skip_empty_desc", True),
        )


__all__ = ["ObjectType", "TableCategory", "SchemaObject", "LoaderOptions"]

