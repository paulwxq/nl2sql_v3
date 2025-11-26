"""Profiling utilities for Step 2 JSON generation.

This module analyzes TableMetadata + sampled data to produce column-level and
table-level profiles as described in docs/gen_rag/3.1.数据画像模块改造说明.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.metaweave.core.metadata.models import (
    AuditInfo,
    BridgeTableInfo,
    ColumnInfo,
    ColumnProfile,
    ColumnStatisticsSummary,
    DateTimeInfo,
    DimTableInfo,
    EnumInfo,
    FactTableInfo,
    ForeignKeyProfileInfo,
    IdentifierInfo,
    IndexInfo,
    IndexProfileInfo,
    KeyColumnsSummary,
    MetricInfo,
    PrimaryKeyProfileInfo,
    StructureFlags,
    TableMetadata,
    TableProfile,
)
from src.metaweave.utils.data_utils import get_column_statistics


@dataclass
class ProfilingResult:
    column_profiles: Dict[str, ColumnProfile]
    table_profile: Optional[TableProfile]


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _default_metric_patterns() -> List[str]:
    return [
        r"amount",
        r"total",
        r"sum",
        r"count",
        r"qty",
        r"quantity",
        r"price",
        r"cost",
        r"revenue",
        r"sales",
        r"profit",
        r"num",
        r"number",
        r"volume",
        r"rate",
        r"ratio",
        r"percent",
    ]


def _default_identifier_patterns() -> List[str]:
    return [
        r"_id$",
        r"_key$",
        r"_code$",
        r"_no$",
        r"_number$",
        r"^id$",
        r"^key$",
    ]


def _default_datetime_types() -> List[str]:
    return ["date", "datetime", "timestamp", "timestamptz", "time"]


def _default_allowed_identifier_types() -> List[str]:
    """默认允许识别为 identifier 的数据类型（白名单）
    
    使用白名单而非黑名单，确保：
    1. 安全性：只有明确允许的类型才会被识别为 identifier
    2. 可预测性：不会因为新数据库类型产生意外行为
    3. 简洁性：identifier 适用的类型本来就有限
    """
    return [
        # 整数类型
        "integer", "int", "int4",
        "bigint", "int8",
        "smallint", "int2",
        "serial", "bigserial", "smallserial",
        # 字符串类型
        "varchar", "character varying",
        "char", "character",
        "bpchar",  # blank-padded char
        # UUID类型
        "uuid",
        # 数值类型（需要额外检查 scale=0）
        "numeric", "decimal"
    ]


def _default_audit_patterns() -> List[str]:
    """审计字段的命名模式"""
    return [
        # 时间戳相关
        r"_ts$", r"_time$", r"_date$", r"_dt$", r"timestamp",
        # 创建
        r"^created_", r"^create_", r"^insert_", r"^inserted_", r"^add_", r"^added_",
        # 更新
        r"^updated_", r"^update_", r"^modified_", r"^modify_", r"^changed_", r"^change_",
        r"last_modified", r"last_updated", r"last_changed",
        # 删除
        r"^deleted_", r"^delete_", r"^removed_", r"^remove_",
        # 操作人
        r"_by$", r"_user$", r"creator", r"updater", r"modifier", r"operator",
        # 软删除
        r"is_deleted", r"is_active", r"is_valid", r"del_flag", r"delete_flag",
        # 版本
        r"version", r"_ver$", r"revision",
        # ETL
        r"^etl_", r"^load_", r"^batch_", r"^source_", r"^dw_", r"^dwh_",
        r"^effective_", r"^expiration_", r"valid_from", r"valid_to",
        # 其他
        r"^sync_", r"^import_", r"^process_", r"^refresh_", r"^snapshot_", r"^audit_",
    ]


@dataclass
class FactTableRules:
    min_metric_columns: int = 1
    min_dimension_columns: int = 2
    require_datetime: bool = True
    naming_patterns: List[str] = field(default_factory=lambda: [r"^fact_", r"_fact$", r"^agg_", r"^sum_"])
    comment_keywords: List[str] = field(default_factory=lambda: ["事实表", "流水", "明细", "汇总"])


@dataclass
class DimTableRules:
    require_primary_key: bool = True
    max_metric_columns: int = 0
    naming_patterns: List[str] = field(default_factory=lambda: [r"^dim_", r"_dim$", r"^d_"])
    comment_keywords: List[str] = field(default_factory=lambda: ["维表", "维度", "字典"])


@dataclass
class BridgeTableRules:
    min_foreign_keys: int = 2
    max_columns: int = 5
    max_metric_columns: int = 1
    naming_patterns: List[str] = field(default_factory=lambda: [r"^bridge_", r"_bridge$"])


@dataclass
class ProfilingConfig:
    enum_threshold: int = 10
    metric_patterns: List[str] = field(default_factory=_default_metric_patterns)
    identifier_patterns: List[str] = field(default_factory=_default_identifier_patterns)
    audit_patterns: List[str] = field(default_factory=_default_audit_patterns)
    datetime_types: List[str] = field(default_factory=_default_datetime_types)
    allowed_identifier_types: List[str] = field(default_factory=_default_allowed_identifier_types)
    fact_rules: FactTableRules = field(default_factory=FactTableRules)
    dim_rules: DimTableRules = field(default_factory=DimTableRules)
    bridge_rules: BridgeTableRules = field(default_factory=BridgeTableRules)

    @classmethod
    def from_dict(cls, config: Optional[Dict]) -> "ProfilingConfig":
        if not config:
            return cls()
        enum_threshold = config.get("column_profiling", {}).get("enum_threshold", cls.enum_threshold)
        metric_patterns = config.get("column_profiling", {}).get("metric_patterns", _default_metric_patterns())
        identifier_patterns = config.get("column_profiling", {}).get(
            "identifier_patterns",
            _default_identifier_patterns(),
        )
        datetime_types = config.get("column_profiling", {}).get(
            "datetime_types",
            _default_datetime_types(),
        )
        audit_patterns = config.get("column_profiling", {}).get(
            "audit_patterns",
            _default_audit_patterns(),
        )
        # 读取 identifier 数据类型白名单
        allowed_identifier_types = config.get("sampling", {}).get("identifier_detection", {}).get(
            "allowed_data_types",
            _default_allowed_identifier_types(),
        )

        fact_cfg = config.get("table_profiling", {}).get("fact_table", {})
        dim_cfg = config.get("table_profiling", {}).get("dim_table", {})
        bridge_cfg = config.get("table_profiling", {}).get("bridge_table", {})

        return cls(
            enum_threshold=enum_threshold,
            metric_patterns=metric_patterns,
            identifier_patterns=identifier_patterns,
            audit_patterns=audit_patterns,
            datetime_types=[dt.lower() for dt in datetime_types],
            allowed_identifier_types=[dt.lower() for dt in allowed_identifier_types],
            fact_rules=FactTableRules(
                min_metric_columns=fact_cfg.get("min_metric_columns", FactTableRules.min_metric_columns),
                min_dimension_columns=fact_cfg.get(
                    "min_dimension_columns", FactTableRules.min_dimension_columns
                ),
                require_datetime=fact_cfg.get("require_datetime", FactTableRules.require_datetime),
                naming_patterns=fact_cfg.get("naming_patterns", FactTableRules().naming_patterns),
                comment_keywords=fact_cfg.get("comment_keywords", FactTableRules().comment_keywords),
            ),
            dim_rules=DimTableRules(
                require_primary_key=dim_cfg.get("require_primary_key", DimTableRules.require_primary_key),
                max_metric_columns=dim_cfg.get("max_metric_columns", DimTableRules.max_metric_columns),
                naming_patterns=dim_cfg.get("naming_patterns", DimTableRules().naming_patterns),
                comment_keywords=dim_cfg.get("comment_keywords", DimTableRules().comment_keywords),
            ),
            bridge_rules=BridgeTableRules(
                min_foreign_keys=bridge_cfg.get("min_foreign_keys", BridgeTableRules.min_foreign_keys),
                max_columns=bridge_cfg.get("max_columns", BridgeTableRules.max_columns),
                max_metric_columns=bridge_cfg.get("max_metric_columns", BridgeTableRules.max_metric_columns),
                naming_patterns=bridge_cfg.get("naming_patterns", BridgeTableRules().naming_patterns),
            ),
        )


# ---------------------------------------------------------------------------
# Profiling logic
# ---------------------------------------------------------------------------


class MetadataProfiler:
    """High-level profiler orchestrating column/table analysis."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = ProfilingConfig.from_dict(config)
        self._compiled_identifier_patterns = [re.compile(pat, re.IGNORECASE) for pat in self.config.identifier_patterns]
        self._compiled_metric_patterns = [re.compile(pat, re.IGNORECASE) for pat in self.config.metric_patterns]
        self._compiled_audit_patterns = [re.compile(pat, re.IGNORECASE) for pat in self.config.audit_patterns]
        self._compiled_fact_patterns = [re.compile(pat, re.IGNORECASE) for pat in self.config.fact_rules.naming_patterns]
        self._compiled_dim_patterns = [re.compile(pat, re.IGNORECASE) for pat in self.config.dim_rules.naming_patterns]
        self._compiled_bridge_patterns = [
            re.compile(pat, re.IGNORECASE) for pat in self.config.bridge_rules.naming_patterns
        ]

    def profile(
        self,
        metadata: TableMetadata,
        sample_df: Optional[pd.DataFrame] = None,
    ) -> ProfilingResult:
        column_profiles = self._profile_columns(metadata, sample_df)
        table_profile = self._profile_table(metadata, column_profiles)
        return ProfilingResult(column_profiles=column_profiles, table_profile=table_profile)

    # ----------------------- Column profiling ---------------------------------

    def _profile_columns(
        self,
        metadata: TableMetadata,
        sample_df: Optional[pd.DataFrame],
    ) -> Dict[str, ColumnProfile]:
        pk_columns = self._collect_pk_columns(metadata)
        unique_constraint_columns = self._collect_unique_constraint_columns(metadata)
        fk_info = self._collect_foreign_key_map(metadata)
        index_info = self._collect_index_map(metadata)
        logical_map = self._collect_logical_key_map(metadata)

        profiles: Dict[str, ColumnProfile] = {}
        for column in metadata.columns:
            stats = self._ensure_statistics(column, sample_df)
            struct_flags = StructureFlags(
                is_primary_key=column.column_name.lower() in pk_columns,
                is_foreign_key=column.column_name.lower() in fk_info,
                is_unique=self._is_unique(stats),
                is_unique_constraint=column.column_name.lower() in unique_constraint_columns,
                is_indexed=column.column_name.lower() in index_info,
                is_nullable=column.is_nullable,
            )
            (
                semantic_role,
                semantic_confidence,
                identifier_info,
                metric_info,
                datetime_info,
                enum_info,
                audit_info,
                inference_basis,
            ) = self._classify_semantics(column, stats, struct_flags)

            pk_info = None
            if struct_flags.is_primary_key:
                pk_info = PrimaryKeyProfileInfo(
                    source="constraint",
                    confidence=None,
                    is_single_column=len(pk_columns) <= 1,
                    composite_columns=list(pk_columns) if len(pk_columns) > 1 else None,
                )
            elif not metadata.primary_keys and logical_map:
                logical_details = logical_map.get(column.column_name.lower())
                if logical_details:
                    pk_info = PrimaryKeyProfileInfo(
                        source="logical",
                        confidence=logical_details.get("confidence"),
                        is_single_column=len(logical_details.get("columns", [])) <= 1,
                        composite_columns=logical_details.get("columns"),
                    )

            fk_profile = None
            if struct_flags.is_foreign_key:
                fk_entry = fk_info[column.column_name.lower()][0]
                fk_profile = ForeignKeyProfileInfo(
                    target_schema=fk_entry["target_schema"],
                    target_table=fk_entry["target_table"],
                    target_columns=fk_entry["target_columns"],
                    on_delete=fk_entry["on_delete"],
                    on_update=fk_entry["on_update"],
                )

            idx_profile = None
            if struct_flags.is_indexed:
                idx = index_info[column.column_name.lower()][0]
                idx_profile = IndexProfileInfo(
                    index_name=idx.index_name,
                    index_type=idx.index_type,
                    is_unique=idx.is_unique,
                    position=idx.columns.index(column.column_name) + 1 if column.column_name in idx.columns else 1,
                )

            profiles[column.column_name] = ColumnProfile(
                column_name=column.column_name,
                semantic_role=semantic_role,
                semantic_confidence=semantic_confidence,
                structure_flags=struct_flags,
                identifier_info=identifier_info,
                metric_info=metric_info,
                datetime_info=datetime_info,
                enum_info=enum_info,
                audit_info=audit_info,
                primary_key_info=pk_info,
                foreign_key_info=fk_profile,
                index_info=idx_profile,
                inference_basis=inference_basis,
            )
        return profiles

    # ----------------------- Table profiling -----------------------------------

    def _profile_table(
        self,
        metadata: TableMetadata,
        column_profiles: Dict[str, ColumnProfile],
    ) -> Optional[TableProfile]:
        if not column_profiles:
            return None

        stats_summary = self._calculate_column_summary(column_profiles)
        key_summary = self._build_key_summary(metadata, column_profiles)

        metric_columns = [name for name, profile in column_profiles.items() if profile.semantic_role == "metric"]
        identifier_columns = [
            name for name, profile in column_profiles.items() if profile.semantic_role == "identifier"
        ]
        datetime_columns = [name for name, profile in column_profiles.items() if profile.semantic_role == "datetime"]
        # enum_columns = [name for name, profile in column_profiles.items() if profile.semantic_role == "enum"]  # 已删除

        table_category, confidence, inference_basis = self._classify_table(
            metadata,
            stats_summary,
            metric_columns,
            identifier_columns,
            datetime_columns,
            [],  # enum_columns - 已删除 enum 类型
        )

        fact_info = None
        dim_info = None
        bridge_info = None

        if table_category == "fact":
            grain = key_summary.primary_keys or key_summary.logical_primary_keys or identifier_columns
            fact_info = FactTableInfo(
                grain=grain,
                metrics=metric_columns,
                dimensions=identifier_columns + datetime_columns,
                time_dimension=datetime_columns[0] if datetime_columns else None,
            )
        elif table_category == "dim":
            surrogate = key_summary.primary_keys[0] if key_summary.primary_keys else None
            natural = key_summary.logical_primary_keys[0] if key_summary.logical_primary_keys else None
            attributes = [name for name, profile in column_profiles.items() if profile.semantic_role == "attribute"]
            dim_info = DimTableInfo(
                natural_key=natural,
                surrogate_key=surrogate,
                attributes=attributes,
            )
        elif table_category == "bridge":
            fk_pairs = self._pair_foreign_keys(key_summary.foreign_keys)
            bridge_info = BridgeTableInfo(
                foreign_key_pairs=[[pair[0], pair[1]] for pair in fk_pairs],
                weight_columns=metric_columns,
            )

        return TableProfile(
            table_category=table_category,
            confidence=confidence,
            column_statistics=stats_summary,
            key_columns=key_summary,
            fact_table_info=fact_info,
            dim_table_info=dim_info,
            bridge_table_info=bridge_info,
            inference_basis=inference_basis,
            candidate_logical_primary_keys=metadata.candidate_logical_primary_keys,
        )

    # -----------------------------------------------------------------------
    # Helper utilities
    # -----------------------------------------------------------------------

    def _collect_pk_columns(self, metadata: TableMetadata) -> List[str]:
        cols: List[str] = []
        for pk in metadata.primary_keys:
            cols.extend([c.lower() for c in pk.columns])
        return cols

    def _collect_unique_constraint_columns(self, metadata: TableMetadata) -> List[str]:
        cols: List[str] = []
        for uc in metadata.unique_constraints:
            cols.extend([c.lower() for c in uc.columns])
        return cols

    def _collect_foreign_key_map(self, metadata: TableMetadata) -> Dict[str, List[Dict]]:
        mapping: Dict[str, List[Dict]] = {}
        for fk in metadata.foreign_keys:
            for column in fk.source_columns:
                mapping.setdefault(column.lower(), []).append(
                    {
                        "target_schema": fk.target_schema,
                        "target_table": fk.target_table,
                        "target_columns": fk.target_columns,
                        "on_delete": fk.on_delete,
                        "on_update": fk.on_update,
                    }
                )
        return mapping

    def _collect_index_map(self, metadata: TableMetadata) -> Dict[str, List[IndexInfo]]:
        mapping: Dict[str, List[IndexInfo]] = {}
        for index in metadata.indexes:
            for column in index.columns:
                mapping.setdefault(column.lower(), []).append(index)
        return mapping

    def _collect_logical_key_map(self, metadata: TableMetadata) -> Dict[str, Dict]:
        mapping: Dict[str, Dict] = {}
        for logical in metadata.candidate_logical_primary_keys:
            for column in logical.columns:
                mapping[column.lower()] = {
                    "columns": logical.columns,
                    "confidence": logical.confidence_score,
                }
        return mapping

    def _ensure_statistics(
        self,
        column: ColumnInfo,
        sample_df: Optional[pd.DataFrame],
    ) -> Optional[Dict]:
        if column.statistics:
            return column.statistics
        if sample_df is None or sample_df.empty or column.column_name not in sample_df.columns:
            return None
        stats = get_column_statistics(
            sample_df,
            column.column_name,
            value_distribution_threshold=self.config.enum_threshold,
        )
        column.statistics = stats
        return stats

    def _is_unique(self, stats: Optional[Dict]) -> bool:
        if not stats:
            return False
        uniqueness = stats.get("uniqueness")
        if uniqueness is None:
            return False
        try:
            return float(uniqueness) == 1.0
        except (TypeError, ValueError):
            return False

    def _classify_semantics(
        self,
        column: ColumnInfo,
        stats: Optional[Dict],
        struct_flags: StructureFlags,
    ) -> Tuple[
        str,
        float,
        Optional[IdentifierInfo],
        Optional[MetricInfo],
        Optional[DateTimeInfo],
        Optional[EnumInfo],
        Optional[AuditInfo],
        List[str],
    ]:
        column_name = column.column_name
        lower_name = column_name.lower()
        inference_basis: List[str] = []

        # audit detection - 最高优先级
        audit_pattern = self._match_pattern(self._compiled_audit_patterns, lower_name)
        if audit_pattern:
            inference_basis.append(f"audit_pattern:{audit_pattern.pattern}")
            audit_type, description = self._determine_audit_type(lower_name, column.data_type)
            return (
                "audit",
                0.95,
                None,
                None,
                None,
                None,
                AuditInfo(audit_type=audit_type, description=description),
                inference_basis,
            )

        # datetime detection
        if column.data_type.lower() in self.config.datetime_types or self._matches_datetime_name(lower_name):
            inference_basis.append("datetime_type_match" if column.data_type.lower() in self.config.datetime_types else "datetime_name_match")
            confidence = 1.0 if column.data_type.lower() in self.config.datetime_types else 0.85
            grain = self._infer_datetime_grain(lower_name)
            return (
                "datetime",
                confidence,
                None,
                None,
                DateTimeInfo(datetime_type=column.data_type.lower(), datetime_grain=grain),
                None,
                None,
                inference_basis,
            )

        # identifier detection (新规则体系)
        is_id, id_confidence, matched_pattern, id_basis = self._is_identifier(column, stats, struct_flags)
        if is_id:
            inference_basis.extend(id_basis)
            # 使用匹配的模式或关键词作为命名模式
            naming_pattern = matched_pattern if matched_pattern else "unknown"
            return (
                "identifier",
                id_confidence,
                IdentifierInfo(naming_pattern=naming_pattern, is_surrogate=not struct_flags.is_foreign_key),
                None,
                None,
                None,
                None,
                inference_basis,
            )

        # enum detection (简单两值情况)
        if self._is_simple_two_value_enum(column, stats, struct_flags):
            inference_basis.append("simple_two_value_enum")
            cardinality = stats.get("unique_count", 0)
            values = list(stats.get("value_distribution", {}).keys()) if stats else []
            return (
                "enum",
                0.85,
                None,
                None,
                None,
                EnumInfo(cardinality=cardinality, cardinality_level="low", values=values),
                None,
                inference_basis,
            )

        # metric detection
        numeric_type = column.data_type.lower() in {
            "numeric",
            "decimal",
            "number",
            "int",
            "integer",
            "bigint",
            "smallint",
            "double precision",
            "real",
            "float",
        }
        metric_pattern = self._match_pattern(self._compiled_metric_patterns, lower_name)
        if numeric_type:
            inference_basis.append("numeric_type")
        if metric_pattern:
            inference_basis.append(f"metric_pattern:{metric_pattern.pattern}")
        if numeric_type or metric_pattern:
            confidence = 0.95 if numeric_type and metric_pattern else (0.7 if numeric_type else 0.6)
            category = self._determine_metric_category(lower_name)
            aggregations = self._suggest_metric_aggregations(category)
            return (
                "metric",
                confidence,
                None,
                MetricInfo(metric_category=category, suggested_aggregations=aggregations),
                None,
                None,
                None,
                inference_basis,
            )

        # default attribute
        inference_basis.append("fallback_attribute")
        return ("attribute", 0.7, None, None, None, None, None, inference_basis)

    def _is_simple_two_value_enum(
        self,
        column: ColumnInfo,
        stats: Optional[Dict],
        struct_flags: StructureFlags,
    ) -> bool:
        """判断是否为简单的两值枚举
        
        条件：
        0. 命名排除规则（描述性字段不应该是枚举）
        1. 唯一值数量恰好为 2
        2. 数据类型为字符串或小整数
        3. 非主键、非外键、非唯一约束
        4. 非空比例较低
        5. 每个值至少出现2次
        6. 字符串值长度较短
        """
        if not stats:
            return False
        
        # 条件0: 命名排除规则 - 描述性字段不应该是枚举
        lower_name = column.column_name.lower()
        exclude_keywords = ["name", "nm", "desc", "description", "remark", "comment", "details", "memo", "summary"]
        for keyword in exclude_keywords:
            if keyword in lower_name:
                return False
        
        # 条件1: 唯一值数量必须恰好为 2
        unique_count = stats.get("unique_count")
        if unique_count != 2:
            return False
        
        # 条件2: 数据类型检查
        data_type_lower = column.data_type.lower()
        is_string_type = data_type_lower in {
            "character varying", "varchar", "text", "char", "character"
        }
        is_small_int = data_type_lower in {"integer", "smallint", "boolean"}
        
        if not (is_string_type or is_small_int):
            return False
        
        # 条件3: 非主键、非外键、非唯一约束
        if (struct_flags.is_primary_key or 
            struct_flags.is_foreign_key or 
            struct_flags.is_unique):
            return False
        
        # 条件4: 非空比例较低
        null_rate = stats.get("null_rate", 0)
        if null_rate >= 0.3:
            return False
        
        # 条件5: 每个值至少出现2次（避免数据稀疏）
        value_distribution = stats.get("value_distribution", {})
        if not value_distribution or len(value_distribution) != 2:
            return False
        
        for count in value_distribution.values():
            if count < 2:
                return False
        
        # 条件6: 字符串值长度检查
        if is_string_type:
            for value in value_distribution.keys():
                if value and len(str(value)) > 20:
                    return False
        
        return True

    def _is_identifier_type(self, column: ColumnInfo) -> bool:
        """规则0：数据类型白名单检查（配置驱动）
        
        从配置文件读取 allowed_data_types 白名单。
        
        允许的类型（默认）：
        - 整数类型：integer, bigint, smallint, serial 等
        - 字符串类型：varchar, char 等
        - UUID类型：uuid
        - 数值类型（无小数）：numeric(scale=0), decimal(scale=0)
        
        排除的类型（所有不在白名单中的）：
        - boolean, text, float, timestamp, json, jsonb, array, bytea
        - geometry, geography, hstore, xml, inet, cidr, macaddr
        - 范围类型、位串类型等
        """
        data_type_lower = column.data_type.lower()
        
        # 从配置获取白名单
        allowed_types = set(self.config.allowed_identifier_types)
        
        # 检查是否在白名单中
        if data_type_lower not in allowed_types:
            return False
        
        # numeric/decimal 类型：需要额外检查 scale=0（无小数位）
        if data_type_lower in {"numeric", "decimal"}:
            scale = column.numeric_scale
            # 有 scale 信息且 scale > 0，排除
            if scale is not None and scale > 0:
                return False
            # scale=0 或无 scale 信息，允许
            return True
        
        # 其他在白名单中的类型，直接允许
        return True

    def _has_physical_constraint(self, struct_flags: StructureFlags) -> Tuple[bool, float, str]:
        """规则1：物理约束检查
        
        检查字段是否有 PRIMARY KEY、FOREIGN KEY 或 UNIQUE 约束
        
        返回: (是否有约束, 置信度, 约束类型)
        """
        if struct_flags.is_primary_key:
            return (True, 1.0, "primary_key")
        if struct_flags.is_foreign_key:
            return (True, 1.0, "foreign_key")
        if struct_flags.is_unique_constraint:  # 只检查物理约束，不检查统计唯一性
            return (True, 1.0, "unique_constraint")
        return (False, 0.0, "")

    def _has_high_uniqueness(self, stats: Optional[Dict]) -> Tuple[bool, float, str]:
        """规则2：统计特征检查
        
        条件：唯一性 > 0.95 AND 非空率 > 0.80
        
        返回: (是否满足, 置信度, 原因)
        """
        if not stats:
            return (False, 0.0, "")
        
        uniqueness = stats.get("uniqueness")
        null_rate = stats.get("null_rate", 0)
        
        if uniqueness is None:
            return (False, 0.0, "")
        
        try:
            uniqueness_val = float(uniqueness)
            null_rate_val = float(null_rate)
            non_null_rate = 1.0 - null_rate_val
            
            if uniqueness_val > 0.95 and non_null_rate > 0.80:
                return (True, 0.95, "high_uniqueness")
        except (TypeError, ValueError):
            pass
        
        return (False, 0.0, "")

    def _has_identifier_naming(
        self, 
        column_name: str, 
        stats: Optional[Dict]
    ) -> Tuple[bool, float, str, str]:
        """规则3：命名特征检查
        
        条件：字段名包含标识关键词 AND 唯一性 > 0.05
        
        返回: (是否满足, 置信度, 匹配的关键词, 原因)
        """
        lower_name = column_name.lower()
        
        # 8大类关键词
        identifier_keywords = [
            # ID类
            "id", "uid",
            # Code类
            "code",
            # Key类
            "key", "pk", "fk",
            # Number类
            "no", "num", "number",
            # 序列类
            "sn", "serial", "seq",
            # UUID类
            "uuid", "guid",
            # 引用类
            "ref", "reference",
            # 标识类
            "identifier",
        ]
        
        # 查找匹配的关键词
        matched_keyword = None
        for keyword in identifier_keywords:
            if keyword in lower_name:
                matched_keyword = keyword
                break
        
        if not matched_keyword:
            return (False, 0.0, "", "")
        
        # 检查唯一性 > 0.05（排除枚举）
        if stats:
            uniqueness = stats.get("uniqueness")
            if uniqueness is not None:
                try:
                    uniqueness_val = float(uniqueness)
                    if uniqueness_val > 0.05:
                        return (True, 0.85, matched_keyword, "naming_with_uniqueness")
                except (TypeError, ValueError):
                    pass
        
        # 如果没有统计数据，仅基于命名判断（降低置信度）
        return (True, 0.75, matched_keyword, "naming_only")

    def _is_identifier(
        self,
        column: ColumnInfo,
        stats: Optional[Dict],
        struct_flags: StructureFlags,
    ) -> Tuple[bool, float, Optional[str], List[str]]:
        """综合判断是否为 identifier
        
        按优先级依次检查：
        0. 命名排除规则（name/desc 等描述性字段）
        1. 数据类型白名单（前置过滤）
        2. 物理约束（PK/FK/UNIQUE）
        3. 统计特征（唯一性>0.95 + 非空率>0.80）
        4. 命名特征（关键词 + 唯一性>0.05）
        
        返回: (是否identifier, 置信度, 匹配的模式/关键词, 推断依据列表)
        """
        inference_basis = []
        
        # 规则0a：命名排除规则 - 描述性字段不应该是 identifier
        # 即使它们唯一，也应该是 attribute
        lower_name = column.column_name.lower()
        exclude_keywords = ["name", "nm", "desc", "description", "remark", "comment", "details", "memo", "summary"]
        for keyword in exclude_keywords:
            if keyword in lower_name:
                return (False, 0.0, None, [])
        
        # 规则0b：类型白名单检查（前置过滤）
        if not self._is_identifier_type(column):
            return (False, 0.0, None, [])
        
        inference_basis.append("type_whitelist_passed")
        
        # 规则1：物理约束检查（最高优先级，100%确定）
        has_constraint, constraint_conf, constraint_type = self._has_physical_constraint(struct_flags)
        if has_constraint:
            inference_basis.append(f"physical_constraint:{constraint_type}")
            return (True, constraint_conf, constraint_type, inference_basis)
        
        # 规则2：统计特征检查（逻辑主键候选）
        has_high_uniq, uniq_conf, uniq_reason = self._has_high_uniqueness(stats)
        if has_high_uniq:
            inference_basis.append(uniq_reason)
            return (True, uniq_conf, "logical_primary_key", inference_basis)
        
        # 规则3：命名特征检查（逻辑外键候选或命名规范的标识字段）
        has_naming, naming_conf, matched_kw, naming_reason = self._has_identifier_naming(column.column_name, stats)
        if has_naming:
            inference_basis.append(naming_reason)
            return (True, naming_conf, matched_kw, inference_basis)
        
        # 都不满足
        return (False, 0.0, None, [])

    def _matches_datetime_name(self, column_name: str) -> bool:
        datetime_keywords = [
            "_date",
            "_day",
            "_month",
            "_year",
            "_hour",
            "_minute",
            "_time",
            "_dt",
        ]
        return any(column_name.endswith(keyword) for keyword in datetime_keywords)

    def _infer_datetime_grain(self, column_name: str) -> Optional[str]:
        mapping = {
            "_year": "year",
            "_quarter": "quarter",
            "_month": "month",
            "_week": "week",
            "_day": "day",
            "_date": "day",
            "_hour": "hour",
            "_minute": "minute",
        }
        for suffix, grain in mapping.items():
            if column_name.endswith(suffix):
                return grain
        return None

    def _match_pattern(self, patterns: List[re.Pattern], text: str) -> Optional[re.Pattern]:
        for pattern in patterns:
            if pattern.search(text):
                return pattern
        return None

    def _determine_metric_category(self, column_name: str) -> str:
        if re.search(r"(amount|price|cost|revenue|sales|profit)", column_name):
            return "amount"
        if re.search(r"(count|qty|quantity|num|number)", column_name):
            return "count"
        if re.search(r"(rate|ratio|percent|percentage)", column_name):
            return "ratio"
        return "metric"

    def _suggest_metric_aggregations(self, category: str) -> List[str]:
        if category == "count":
            return ["SUM"]
        if category == "ratio":
            return ["AVG"]
        return ["SUM", "AVG", "MIN", "MAX"]

    def _determine_audit_type(self, column_name: str, data_type: str) -> Tuple[str, str]:
        """判断审计字段的类型和用途"""
        lower_name = column_name.lower()
        
        # 时间戳类型
        if any(keyword in lower_name for keyword in ["created_at", "create_time", "insert_time", "added_at"]):
            return ("timestamp", "记录创建时间")
        if any(keyword in lower_name for keyword in ["updated_at", "update_time", "modified_at", "changed_at", "last_modified", "last_updated"]):
            return ("timestamp", "记录更新时间")
        if any(keyword in lower_name for keyword in ["deleted_at", "delete_time", "removed_at"]):
            return ("timestamp", "记录删除时间")
        if any(keyword in lower_name for keyword in ["etl_", "load_", "batch_", "effective_", "valid_from", "valid_to"]):
            return ("etl", "ETL时间戳")
        
        # 操作人类型
        if any(keyword in lower_name for keyword in ["_by", "_user", "creator", "updater", "modifier", "operator"]):
            return ("actor", "操作人标识")
        
        # 软删除标志
        if any(keyword in lower_name for keyword in ["is_deleted", "is_active", "is_valid", "del_flag", "delete_flag"]):
            return ("flag", "软删除标志")
        
        # 版本控制
        if any(keyword in lower_name for keyword in ["version", "_ver", "revision"]):
            return ("version", "版本号")
        
        # 默认
        return ("timestamp", "审计时间戳")

    def _calculate_column_summary(self, column_profiles: Dict[str, ColumnProfile]) -> ColumnStatisticsSummary:
        identifier_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "identifier")
        metric_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "metric")
        datetime_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "datetime")
        audit_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "audit")
        # enum_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "enum")  # 已删除
        attribute_count = sum(1 for profile in column_profiles.values() if profile.semantic_role == "attribute")
        primary_key_count = sum(1 for profile in column_profiles.values() if profile.structure_flags.is_primary_key)
        foreign_key_count = sum(1 for profile in column_profiles.values() if profile.structure_flags.is_foreign_key)

        return ColumnStatisticsSummary(
            total_columns=len(column_profiles),
            identifier_count=identifier_count,
            metric_count=metric_count,
            datetime_count=datetime_count,
            enum_count=0,  # enum 类型已删除
            audit_count=audit_count,
            attribute_count=attribute_count,
            primary_key_count=primary_key_count,
            foreign_key_count=foreign_key_count,
        )

    def _build_key_summary(
        self,
        metadata: TableMetadata,
        column_profiles: Dict[str, ColumnProfile],
    ) -> KeyColumnsSummary:
        primary_keys = metadata.primary_keys[0].columns if metadata.primary_keys else []
        logical_primary_keys = metadata.candidate_logical_primary_keys[0].columns if metadata.candidate_logical_primary_keys else []
        foreign_keys = sorted(
            {name for name, profile in column_profiles.items() if profile.structure_flags.is_foreign_key}
        )
        return KeyColumnsSummary(
            primary_keys=primary_keys,
            logical_primary_keys=logical_primary_keys,
            foreign_keys=foreign_keys,
        )

    def _classify_table(
        self,
        metadata: TableMetadata,
        stats_summary: ColumnStatisticsSummary,
        metric_columns: List[str],
        identifier_columns: List[str],
        datetime_columns: List[str],
        enum_columns: List[str],
    ) -> Tuple[str, float, List[str]]:
        inference_basis: List[str] = []
        total_cols = stats_summary.total_columns
        fk_count = stats_summary.foreign_key_count

        # Bridge detection
        if (
            fk_count >= self.config.bridge_rules.min_foreign_keys
            and total_cols <= self.config.bridge_rules.max_columns
            and len(metric_columns) <= self.config.bridge_rules.max_metric_columns
        ):
            inference_basis.append("bridge_fk_threshold")
            return ("bridge", 0.85, inference_basis)

        # Fact detection
        conditions_met = 0
        if len(metric_columns) >= self.config.fact_rules.min_metric_columns:
            conditions_met += 1
            inference_basis.append("fact_has_metric")
        if len(identifier_columns) >= self.config.fact_rules.min_dimension_columns:
            conditions_met += 1
            inference_basis.append("fact_dimension_columns")
        if not self.config.fact_rules.require_datetime or datetime_columns:
            conditions_met += 1
            if datetime_columns:
                inference_basis.append("fact_datetime")
        if conditions_met >= 2:
            confidence = 0.6
            confidence += 0.15 if len(metric_columns) >= self.config.fact_rules.min_metric_columns else 0
            confidence += 0.1 if len(identifier_columns) >= self.config.fact_rules.min_dimension_columns else 0
            confidence += 0.1 if datetime_columns else 0
            if self._matches_table_pattern(metadata.table_name, self._compiled_fact_patterns):
                confidence += 0.05
                inference_basis.append("fact_name_pattern")
            if self._matches_comment_keyword(metadata.comment, self.config.fact_rules.comment_keywords):
                confidence += 0.05
                inference_basis.append("fact_comment_keyword")
            return ("fact", min(confidence, 0.98), inference_basis)

        # Dimension detection
        if (
            (metadata.primary_keys or metadata.candidate_logical_primary_keys or not self.config.dim_rules.require_primary_key)
            and len(metric_columns) <= self.config.dim_rules.max_metric_columns
            and identifier_columns
        ):
            inference_basis.append("dim_identifier_columns")
            confidence = 0.7
            if metadata.primary_keys or metadata.candidate_logical_primary_keys:
                confidence += 0.15
                inference_basis.append("dim_has_primary_key")
            if not metric_columns:
                confidence += 0.1
            if self._matches_table_pattern(metadata.table_name, self._compiled_dim_patterns):
                confidence += 0.05
                inference_basis.append("dim_name_pattern")
            if self._matches_comment_keyword(metadata.comment, self.config.dim_rules.comment_keywords):
                confidence += 0.05
                inference_basis.append("dim_comment_keyword")
            return ("dim", min(confidence, 0.95), inference_basis)

        # Unknown
        return ("unknown", 0.5, inference_basis)

    def _matches_table_pattern(self, table_name: str, patterns: List[re.Pattern]) -> bool:
        return any(pattern.search(table_name) for pattern in patterns)

    def _matches_comment_keyword(self, comment: str, keywords: List[str]) -> bool:
        if not comment:
            return False
        return any(keyword in comment for keyword in keywords)

    def _pair_foreign_keys(self, foreign_keys: List[str]) -> List[Tuple[str, str]]:
        if len(foreign_keys) < 2:
            return []
        pairs = []
        for idx in range(0, len(foreign_keys) - 1, 2):
            pairs.append((foreign_keys[idx], foreign_keys[idx + 1]))
        return pairs


