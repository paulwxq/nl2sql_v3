"""数据模型定义

定义元数据生成过程中使用的所有数据结构。
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any
import json


@dataclass
class ColumnInfo:
    """字段信息"""
    column_name: str
    ordinal_position: int
    data_type: str
    character_maximum_length: Optional[int] = None
    numeric_precision: Optional[int] = None
    numeric_scale: Optional[int] = None
    is_nullable: bool = True
    column_default: Optional[str] = None
    comment: str = ""
    comment_source: str = "db"  # 'db' or 'llm_generated'
    statistics: Optional[Dict[str, Any]] = None  # 列统计信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class PrimaryKey:
    """主键约束"""
    constraint_name: str
    columns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class ForeignKey:
    """外键约束"""
    constraint_name: str
    source_columns: List[str] = field(default_factory=list)
    target_schema: str = ""
    target_table: str = ""
    target_columns: List[str] = field(default_factory=list)
    on_delete: str = "NO ACTION"
    on_update: str = "NO ACTION"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class UniqueConstraint:
    """唯一约束"""
    constraint_name: str
    columns: List[str] = field(default_factory=list)
    is_partial: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class IndexInfo:
    """索引信息"""
    index_name: str
    index_type: str = "btree"  # btree, hash, gist, gin, etc.
    columns: List[str] = field(default_factory=list)
    is_unique: bool = False
    is_primary: bool = False
    condition: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class LogicalKey:
    """逻辑主键"""
    columns: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    uniqueness: float = 0.0
    null_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class TableMetadata:
    """表元数据"""
    schema_name: str
    table_name: str
    table_type: str = "table"  # table, view, materialized_view
    comment: str = ""
    comment_source: str = "db"  # 'db' or 'llm_generated'
    row_count: int = 0
    columns: List[ColumnInfo] = field(default_factory=list)
    primary_keys: List[PrimaryKey] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    unique_constraints: List[UniqueConstraint] = field(default_factory=list)
    indexes: List[IndexInfo] = field(default_factory=list)
    candidate_logical_primary_keys: List[LogicalKey] = field(default_factory=list)
    sample_records: List[Dict[str, Any]] = field(default_factory=list)
    column_profiles: Dict[str, "ColumnProfile"] = field(default_factory=dict)
    table_profile: Optional["TableProfile"] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化 v2.0 格式）"""
        # 合并 columns 信息到 column_profiles
        merged_column_profiles = {}
        
        # 先创建 columns 的字典映射
        columns_dict = {col.column_name: col.to_dict() for col in self.columns}
        
        # 合并到 column_profiles
        for name, profile in self.column_profiles.items():
            profile_dict = profile.to_dict()
            # 如果该列在 columns 中存在，将基础信息合并进去
            if name in columns_dict:
                col_info = columns_dict[name]
                # 将列的基础信息添加到 profile 的开头
                merged_profile = {
                    "column_name": col_info["column_name"],
                    "ordinal_position": col_info["ordinal_position"],
                    "data_type": col_info["data_type"],
                    "character_maximum_length": col_info.get("character_maximum_length"),
                    "numeric_precision": col_info.get("numeric_precision"),
                    "numeric_scale": col_info.get("numeric_scale"),
                    "is_nullable": col_info["is_nullable"],
                    "column_default": col_info.get("column_default"),
                    "comment": col_info.get("comment", ""),
                    "comment_source": col_info.get("comment_source", ""),
                    "statistics": col_info.get("statistics"),
                }
                # 合并 profile 的语义信息（已经重组为 semantic_analysis 和 role_specific_info）
                merged_profile.update(profile_dict)
                merged_column_profiles[name] = merged_profile
            else:
                # 如果没有对应的 column 信息，只使用 profile
                merged_column_profiles[name] = profile_dict
        
        # 构建 v2.0 格式的 JSON
        data = {
            "metadata_version": "2.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            
            "table_info": {
                "schema_name": self.schema_name,
                "table_name": self.table_name,
                "table_type": self.table_type,
                "comment": self.comment,
                "comment_source": self.comment_source,
                "total_rows": self.row_count,
                "total_columns": len(self.columns),
            },
            
            "column_profiles": merged_column_profiles,
            
            "table_profile": self.table_profile.to_dict(self) if self.table_profile else None,
            
            # 注意：sample_records 将在 formatter 中从 DDL 或 sample_data 提取后添加
        }
        return data

    def to_json(self, indent: int = 2) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @property
    def full_name(self) -> str:
        """获取完整表名"""
        return f"{self.schema_name}.{self.table_name}"


@dataclass
class CommentTask:
    """LLM 注释生成任务"""
    task_type: str  # 'table' or 'column'
    schema_name: str
    table_name: str
    column_name: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    
    def get_cache_key(self) -> str:
        """获取缓存键"""
        if self.task_type == "table":
            return f"table:{self.schema_name}.{self.table_name}"
        else:
            return f"column:{self.schema_name}.{self.table_name}.{self.column_name}"


@dataclass
class GenerationResult:
    """元数据生成结果"""
    success: bool
    processed_tables: int = 0
    failed_tables: int = 0
    generated_comments: int = 0
    logical_keys_found: int = 0
    output_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def add_error(self, error: str):
        """添加错误信息"""
        self.errors.append(error)
    
    def add_output_file(self, file_path: str):
        """添加输出文件"""
        self.output_files.append(file_path)


@dataclass
class SampleData:
    """样本数据"""
    schema_name: str
    table_name: str
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
        }


# ---------------------------------------------------------------------------
# Profiling-related data structures
# ---------------------------------------------------------------------------


@dataclass
class StructureFlags:
    is_primary_key: bool = False
    is_composite_primary_key_member: bool = False
    is_foreign_key: bool = False
    is_composite_foreign_key_member: bool = False
    is_unique: bool = False
    is_composite_unique_member: bool = False
    is_unique_constraint: bool = False
    is_composite_unique_constraint_member: bool = False
    is_indexed: bool = False
    is_composite_indexed_member: bool = False
    is_nullable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdentifierInfo:
    naming_pattern: str
    is_surrogate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MetricInfo:
    metric_category: str
    suggested_aggregations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DateTimeInfo:
    datetime_type: str
    datetime_grain: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnumInfo:
    cardinality: int
    cardinality_level: str
    values: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditInfo:
    """审计字段信息"""
    audit_type: str  # timestamp, actor, flag, version, etl
    description: str  # 字段用途描述

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PrimaryKeyProfileInfo:
    source: str  # constraint | logical
    confidence: Optional[float] = None
    is_single_column: bool = True
    composite_columns: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ForeignKeyProfileInfo:
    target_schema: str
    target_table: str
    target_columns: List[str]
    on_delete: str
    on_update: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IndexProfileInfo:
    index_name: str
    index_type: str
    is_unique: bool
    position: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ColumnProfile:
    column_name: str
    semantic_role: str
    semantic_confidence: float
    structure_flags: StructureFlags
    identifier_info: Optional[IdentifierInfo] = None
    metric_info: Optional[MetricInfo] = None
    datetime_info: Optional[DateTimeInfo] = None
    enum_info: Optional[EnumInfo] = None
    audit_info: Optional["AuditInfo"] = None
    primary_key_info: Optional[PrimaryKeyProfileInfo] = None
    foreign_key_info: Optional[ForeignKeyProfileInfo] = None
    index_info: Optional[IndexProfileInfo] = None
    inference_basis: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        # 基础字段
        result = {
            "column_name": self.column_name,
        }
        
        # 添加 semantic_analysis 分组
        result["semantic_analysis"] = {
            "semantic_role": self.semantic_role,
            "semantic_confidence": self.semantic_confidence,
            "inference_basis": self.inference_basis,
        }
        
        result["structure_flags"] = self.structure_flags.to_dict()
        
        # 将所有 *_info 字段归类到 role_specific_info 下
        role_specific_info = {}
        if self.identifier_info:
            role_specific_info["identifier_info"] = self.identifier_info.to_dict()
        if self.metric_info:
            role_specific_info["metric_info"] = self.metric_info.to_dict()
        if self.datetime_info:
            role_specific_info["datetime_info"] = self.datetime_info.to_dict()
        if self.enum_info:
            role_specific_info["enum_info"] = self.enum_info.to_dict()
        if self.audit_info:
            role_specific_info["audit_info"] = self.audit_info.to_dict()
        if self.primary_key_info:
            role_specific_info["primary_key_info"] = self.primary_key_info.to_dict()
        if self.foreign_key_info:
            role_specific_info["foreign_key_info"] = self.foreign_key_info.to_dict()
        if self.index_info:
            role_specific_info["index_info"] = self.index_info.to_dict()
        
        result["role_specific_info"] = role_specific_info
        
        return result


@dataclass
class ColumnStatisticsSummary:
    total_columns: int
    identifier_count: int
    metric_count: int
    datetime_count: int
    enum_count: int
    audit_count: int
    attribute_count: int
    primary_key_count: int
    foreign_key_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KeyColumnsSummary:
    primary_keys: List[str] = field(default_factory=list)
    logical_primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FactTableInfo:
    grain: List[str]
    metrics: List[str]
    dimensions: List[str]
    time_dimension: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DimTableInfo:
    natural_key: Optional[str]
    surrogate_key: Optional[str]
    attributes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeTableInfo:
    foreign_key_pairs: List[List[str]]
    weight_columns: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TableProfile:
    table_category: str
    confidence: float
    column_statistics: ColumnStatisticsSummary
    key_columns: KeyColumnsSummary
    fact_table_info: Optional[FactTableInfo] = None
    dim_table_info: Optional[DimTableInfo] = None
    bridge_table_info: Optional[BridgeTableInfo] = None
    inference_basis: List[str] = field(default_factory=list)
    candidate_logical_primary_keys: List["LogicalKey"] = field(default_factory=list)

    def to_dict(self, metadata: Optional['TableMetadata'] = None) -> Dict[str, Any]:
        result = {
            "table_category": self.table_category,
            "confidence": self.confidence,
            "inference_basis": self.inference_basis,
        }
        
        # 添加 physical_constraints（从 metadata 获取）
        if metadata:
            result["physical_constraints"] = {
                "primary_key": metadata.primary_keys[0].to_dict() if metadata.primary_keys else None,
                "foreign_keys": [fk.to_dict() for fk in metadata.foreign_keys],
                "unique_constraints": [uc.to_dict() for uc in metadata.unique_constraints],
                "indexes": [idx.to_dict() for idx in metadata.indexes],
            }
        
        # column_statistics
        result["column_statistics"] = self.column_statistics.to_dict()
        
        # logical_keys（包装 candidate_logical_primary_keys）
        if self.candidate_logical_primary_keys:
            result["logical_keys"] = {
                "candidate_primary_keys": [lk.to_dict() for lk in self.candidate_logical_primary_keys]
            }
        
        # 表类型特定信息
        if self.fact_table_info:
            result["fact_table_info"] = self.fact_table_info.to_dict()
        if self.dim_table_info:
            result["dim_table_info"] = self.dim_table_info.to_dict()
        if self.bridge_table_info:
            result["bridge_table_info"] = self.bridge_table_info.to_dict()
        
        return result

