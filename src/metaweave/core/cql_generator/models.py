"""Step 4 数据模型定义

定义 Table、Column、Relationship 等 Neo4j 图数据模型。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class ForeignKeyConstraint:
    """外键约束"""
    constraint_name: str
    source_columns: List[str]
    target_schema: str
    target_table: str
    target_columns: List[str]


@dataclass
class TableNode:
    """Table 节点模型

    对应 Neo4j 中的 Table 节点，包含表的所有属性。
    """
    # 必需属性
    full_name: str  # schema.table（唯一键）
    schema: str
    name: str

    # 可选属性
    comment: Optional[str] = None

    # 约束和索引
    pk: List[str] = field(default_factory=list)  # 物理主键
    uk: List[List[str]] = field(default_factory=list)  # 物理唯一约束
    fk: List[List[str]] = field(default_factory=list)  # 物理外键（只保留源列名）
    logic_pk: List[List[str]] = field(default_factory=list)  # 候选逻辑主键
    logic_fk: List[List[str]] = field(default_factory=list)  # 逻辑外键
    logic_uk: List[List[str]] = field(default_factory=list)  # 逻辑唯一
    indexes: List[List[str]] = field(default_factory=list)  # 索引

    @property
    def id(self) -> str:
        """兼容属性：与 full_name 相同"""
        return self.full_name

    def to_cypher_dict(self) -> Dict[str, Any]:
        """转换为 Cypher 参数字典"""
        return {
            "full_name": self.full_name,
            "schema": self.schema,
            "name": self.name,
            "comment": self.comment or "",
            "pk": self.pk,
            "uk": self.uk,
            "fk": self.fk,
            "logic_pk": self.logic_pk,
            "logic_fk": self.logic_fk,
            "logic_uk": self.logic_uk,
            "indexes": self.indexes
        }


@dataclass
class ColumnNode:
    """Column 节点模型

    对应 Neo4j 中的 Column 节点，包含列的所有属性。
    """
    # 必需属性
    full_name: str  # schema.table.column（唯一键）
    schema: str
    table: str
    name: str
    data_type: str

    # 可选属性
    comment: Optional[str] = None
    semantic_role: Optional[str] = None

    # 标志位
    is_pk: bool = False
    is_uk: bool = False
    is_fk: bool = False
    is_time: bool = False
    is_measure: bool = False

    # 位置和统计
    pk_position: int = 0
    uniqueness: float = 0.0
    null_rate: float = 0.0

    def to_cypher_dict(self) -> Dict[str, Any]:
        """转换为 Cypher 参数字典"""
        return {
            "full_name": self.full_name,
            "schema": self.schema,
            "table": self.table,
            "name": self.name,
            "comment": self.comment or "",
            "data_type": self.data_type,
            "semantic_role": self.semantic_role or "",
            "is_pk": self.is_pk,
            "is_uk": self.is_uk,
            "is_fk": self.is_fk,
            "is_time": self.is_time,
            "is_measure": self.is_measure,
            "pk_position": self.pk_position,
            "uniqueness": self.uniqueness,
            "null_rate": self.null_rate
        }


@dataclass
class HASColumnRelation:
    """HAS_COLUMN 关系模型

    表示 Table -> Column 的包含关系。
    """
    table_full_name: str
    column_full_name: str

    def to_cypher_dict(self) -> Dict[str, Any]:
        """转换为 Cypher 参数字典"""
        return {
            "table_full_name": self.table_full_name,
            "column_full_name": self.column_full_name
        }


@dataclass
class JOINOnRelation:
    """JOIN_ON 关系模型

    表示 Table -> Table 的关联关系。
    """
    # 源表和目标表
    src_full_name: str
    dst_full_name: str

    # 关系属性
    cardinality: str  # N:1, 1:N, 1:1, M:N
    join_type: str = "INNER JOIN"
    on: str = ""  # 连接表达式

    # 列信息
    source_columns: List[str] = field(default_factory=list)
    target_columns: List[str] = field(default_factory=list)

    # 可选
    constraint_name: Optional[str] = None

    def to_cypher_dict(self) -> Dict[str, Any]:
        """转换为 Cypher 参数字典"""
        return {
            "src_full_name": self.src_full_name,
            "dst_full_name": self.dst_full_name,
            "cardinality": self.cardinality,
            "constraint_name": self.constraint_name,
            "join_type": self.join_type,
            "on": self.on,
            "source_columns": self.source_columns,
            "target_columns": self.target_columns
        }


@dataclass
class CQLGenerationResult:
    """CQL 生成结果"""
    success: bool
    output_files: List[str] = field(default_factory=list)
    tables_count: int = 0
    columns_count: int = 0
    relationships_count: int = 0
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "成功" if self.success else "失败"
        return (
            f"CQL生成结果: {status}\n"
            f"  - 表节点: {self.tables_count}\n"
            f"  - 列节点: {self.columns_count}\n"
            f"  - 关系: {self.relationships_count}\n"
            f"  - 输出文件: {len(self.output_files)}\n"
            f"  - 错误: {len(self.errors)}"
        )
