"""关系发现数据模型

定义表间关系和发现结果的数据结构。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any


@dataclass
class Relation:
    """表间关系对象（单列或复合列）

    Attributes:
        relationship_id: 确定性ID（格式: rel_ + MD5[:12]）
        source_schema: 源表schema
        source_table: 源表名
        source_columns: 源列名列表（可以是1个或多个）
        target_schema: 目标表schema
        target_table: 目标表名
        target_columns: 目标列名列表
        relationship_type: 关系类型（foreign_key | inferred）
        cardinality: 基数（1:1 | 1:N | N:1 | M:N）
        composite_score: 综合评分（仅推断关系有值，0-1）
        score_details: 评分明细（6个维度）
        inference_method: 推断方法（如single_active_search, composite_physical等）
    """
    relationship_id: str
    source_schema: str
    source_table: str
    source_columns: List[str]
    target_schema: str
    target_table: str
    target_columns: List[str]
    relationship_type: str  # foreign_key | inferred
    cardinality: str = "N:1"  # 默认多对一
    composite_score: Optional[float] = None
    score_details: Optional[Dict[str, float]] = None
    inference_method: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于JSON序列化）"""
        data = asdict(self)
        # 确保空值字段也被包含
        if self.composite_score is None and self.relationship_type == "foreign_key":
            data.pop("composite_score", None)
            data.pop("score_details", None)
            data.pop("inference_method", None)
        return data

    @property
    def is_single_column(self) -> bool:
        """是否为单列关系"""
        return len(self.source_columns) == 1

    @property
    def is_composite(self) -> bool:
        """是否为复合列关系"""
        return len(self.source_columns) > 1

    @property
    def source_full_name(self) -> str:
        """源表全名"""
        return f"{self.source_schema}.{self.source_table}"

    @property
    def target_full_name(self) -> str:
        """目标表全名"""
        return f"{self.target_schema}.{self.target_table}"

    @property
    def table_pair(self) -> str:
        """表对标识（用于抑制规则）"""
        return f"{self.source_full_name}->{self.target_full_name}"


@dataclass
class RelationshipDiscoveryResult:
    """关系发现结果

    Attributes:
        success: 是否成功
        total_relations: 总关系数
        foreign_key_relations: 外键直通关系数
        inferred_relations: 推断关系数
        high_confidence_count: 高置信度关系数（≥0.90）
        medium_confidence_count: 中置信度关系数（0.80-0.90）
        suppressed_count: 被抑制的关系数
        output_files: 输出文件路径列表
        errors: 错误信息列表
    """
    success: bool = True
    total_relations: int = 0
    foreign_key_relations: int = 0
    inferred_relations: int = 0
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    suppressed_count: int = 0
    output_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def add_error(self, error: str):
        """添加错误信息"""
        self.errors.append(error)
        self.success = False

    def add_output_file(self, file_path: str):
        """添加输出文件"""
        self.output_files.append(file_path)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
