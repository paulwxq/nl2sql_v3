"""关系输出器

负责输出关系发现结果（JSON + Markdown），符合 v3.2 文档规范。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

from src.metaweave.core.relationships.models import Relation
from src.metaweave.utils.file_utils import ensure_dir
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.writer")


class RelationshipWriter:
    """关系输出器

    输出文件（当前版本仅支持 global 粒度）：
    - relationships_{granularity}.json（所有关系，v3.2格式）
    - relationships_{granularity}.md（可读报告）

    注意：Phase 1 仅支持 rel_granularity='global'，schema 粒度将在后续版本实现。
    """

    def __init__(self, config: dict):
        """初始化输出器

        Args:
            config: top-level 配置
        """
        output_config = config.get("output", {})

        self.rel_dir = Path(output_config.get("rel_directory", "output/metaweave/metadata/rel"))
        self.rel_granularity = output_config.get("rel_granularity", "global")

        # 验证粒度配置（Phase 1 仅支持 global）
        if self.rel_granularity != "global":
            logger.warning(
                f"当前版本仅支持 rel_granularity='global'，配置值 '{self.rel_granularity}' 将被忽略。"
                f"Schema 粒度输出功能计划在后续版本实现。"
            )
            self.rel_granularity = "global"  # 强制使用 global

        # 决策阈值（用于置信度分类）
        decision_config = config.get("decision", {})
        self.high_confidence_threshold = decision_config.get("high_confidence_threshold", 0.90)
        self.medium_confidence_threshold = decision_config.get("medium_confidence_threshold", 0.80)

        # 确保输出目录存在
        ensure_dir(self.rel_dir)

        logger.info(f"关系输出器已初始化: {self.rel_dir}")

    def write_results(
            self,
            relations: List[Relation],
            suppressed: List[Dict[str, Any]],
            config: Dict[str, Any],
            tables: Optional[Dict[str, dict]] = None
    ) -> List[str]:
        """输出关系发现结果（v3.2格式）

        Args:
            relations: 接受的关系列表（外键+推断）
            suppressed: 被抑制的候选列表
            config: 完整配置
            tables: 表元数据字典（用于获取列的约束信息）

        Returns:
            输出文件路径列表
        """
        # 保存 tables 供后续使用
        self.tables = tables or {}
        
        output_files = []

        # 1. 输出JSON（v3.2格式）
        json_file = self._write_json_v32(relations, suppressed, config)
        if json_file:
            output_files.append(str(json_file))

        # 2. 输出Markdown
        md_file = self._write_markdown(relations)
        if md_file:
            output_files.append(str(md_file))

        logger.info(f"输出完成: {len(output_files)} 个文件")
        return output_files

    def _write_json_v32(
            self,
            relations: List[Relation],
            suppressed: List[Dict],
            config: Dict[str, Any]
    ) -> Path:
        """输出JSON文件（v3.2格式）

        Args:
            relations: 关系列表
            suppressed: 被抑制的候选
            config: 配置

        Returns:
            输出文件路径
        """
        # 将被抑制的单列关系按表对分组
        suppressed_by_table_pair = self._group_suppressed_by_table_pair(suppressed)

        logger.debug(
            "开始转换 JSON，关系=%d，被抑制=%d",
            len(relations),
            len(suppressed),
        )

        # 转换关系为v3.2格式，并嵌入被抑制的单列
        relationships_v32 = []
        for rel in relations:
            rel_dict = self._convert_to_v32_format(rel)

            # 如果是复合键关系，嵌入被抑制的单列
            if rel.is_composite:
                table_pair = rel.table_pair
                if table_pair in suppressed_by_table_pair:
                    rel_dict["suppressed_single_relations"] = suppressed_by_table_pair[table_pair]

            relationships_v32.append(rel_dict)

        if relationships_v32:
            sample_ids = [rel.get("relationship_id") for rel in relationships_v32[:3]]
            logger.debug("JSON 样例关系ID: %s", sample_ids)

        # 计算统计数据（v3.2口径）
        stats = self._calculate_statistics_v32(relations, suppressed)

        # 构建JSON数据（v3.2格式）
        data = {
            "metadata_source": "json_files",
            "json_metadata_version": "2.0",
            "json_files_loaded": stats.get("json_files_loaded", 0),
            "database_queries_executed": stats.get("database_queries_executed", 0),
            "analysis_timestamp": datetime.utcnow().isoformat() + "Z",

            "statistics": {
                "total_relationships_found": stats["total_relationships_found"],
                "foreign_key_relationships": stats["foreign_key_relationships"],
                "composite_key_relationships": stats["composite_key_relationships"],
                "single_column_relationships": stats["single_column_relationships"],
                "total_suppressed_single_relations": stats["total_suppressed_single_relations"],
                "active_search_discoveries": stats["active_search_discoveries"],
                "dynamic_composite_discoveries": stats["dynamic_composite_discoveries"],
            },

            "relationships": relationships_v32
        }

        # 写入文件（使用配置的粒度，当前仅支持 global）
        json_file = self.rel_dir / f"relationships_{self.rel_granularity}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"JSON已输出: {json_file}")
        return json_file

    def _group_suppressed_by_table_pair(
            self,
            suppressed: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """按表对分组被抑制的单列关系

        Args:
            suppressed: 被抑制的候选列表

        Returns:
            {table_pair: [suppressed_relation_dict, ...]}
        """
        grouped = defaultdict(list)

        for candidate in suppressed:
            # 只处理单列关系
            if len(candidate.get("source_columns", [])) > 1:
                continue

            source_info = candidate["source"].get("table_info", {})
            target_info = candidate["target"].get("table_info", {})

            table_pair = (
                f"{source_info.get('schema_name')}.{source_info.get('table_name')}->"
                f"{target_info.get('schema_name')}.{target_info.get('table_name')}"
            )

            # 转换为v3.2格式
            suppressed_rel = {
                "from_column": candidate["source_columns"][0],
                "to_column": candidate["target_columns"][0],
                "original_score": candidate.get("composite_score", 0.0),
                "suppression_reason": "在复合键中，无独立约束",
                "could_have_been_accepted": candidate.get("composite_score", 0.0) >= 0.80
            }

            grouped[table_pair].append(suppressed_rel)

        return dict(grouped)

    def _convert_to_v32_format(self, rel: Relation) -> Dict[str, Any]:
        """转换关系对象为v3.2 JSON格式

        Args:
            rel: 关系对象

        Returns:
            v3.2格式的字典
        """
        # 确定关系类型
        if rel.is_composite:
            rel_type = "composite"
        else:
            rel_type = "single_column"

        # 确定置信度级别
        if rel.composite_score is None:
            confidence_level = None
        elif rel.composite_score >= self.high_confidence_threshold:
            confidence_level = "high"
        elif rel.composite_score >= self.medium_confidence_threshold:
            confidence_level = "medium"
        else:
            confidence_level = "low"

        # 基础字段
        result = {
            "relationship_id": rel.relationship_id,
            "type": rel_type,
            "from_table": {
                "schema": rel.source_schema,
                "table": rel.source_table
            },
            "to_table": {
                "schema": rel.target_schema,
                "table": rel.target_table
            },
        }

        # 列名（单列用 from_column，复合用 from_columns）
        if rel.is_single_column:
            result["from_column"] = rel.source_columns[0]
            result["to_column"] = rel.target_columns[0]
        else:
            result["from_columns"] = rel.source_columns
            result["to_columns"] = rel.target_columns

        # 发现方法、来源类型、约束类型（规范化映射）
        if rel.relationship_type == "foreign_key":
            result["discovery_method"] = "foreign_key_constraint"
            result["target_source_type"] = "foreign_key"
            result["source_constraint"] = None
        else:
            # 从 inference_method (candidate_type) 拆分为规范字段
            discovery_info = self._parse_discovery_info(rel.inference_method, rel)
            result["discovery_method"] = discovery_info["discovery_method"]
            result["target_source_type"] = discovery_info.get("target_source_type")
            result["source_constraint"] = discovery_info.get("source_constraint")

        # 评分相关字段（仅推断关系有）
        if rel.composite_score is not None:
            result["composite_score"] = rel.composite_score
            result["confidence_level"] = confidence_level
            result["metrics"] = rel.score_details or {}

        # 关系基数（所有关系都有）
        result["cardinality"] = rel.cardinality

        return result

    def _parse_discovery_info(
            self,
            inference_method: Optional[str],
            rel: Relation
    ) -> Dict[str, Optional[str]]:
        """解析 inference_method 为 discovery_method, target_source_type, source_constraint

        映射规则（基于v3.2文档）：
        
        单列关系：
        - single_defined_constraint_and_logical_pk -> active_search (源有约束+逻辑键，目标动态检测)
        - single_defined_constraint -> active_search (源有约束，目标动态检测)
        - single_logical_key -> logical_key_matching (源是逻辑键，目标是逻辑键)
        - single_active_search -> active_search (向后兼容，已废弃)
        
        复合键关系：
        - composite_physical -> physical_constraint_matching
        - composite_logical -> logical_key_matching
        - composite_dynamic_same_name -> dynamic_same_name
        
        其他：
        - 未知类型 -> standard_matching

        Args:
            inference_method: 推断方法字符串（如 single_defined_constraint）
            rel: 关系对象

        Returns:
            包含 discovery_method, target_source_type, source_constraint 的字典
        """
        if not inference_method:
            return {
                "discovery_method": "standard_matching",
                "target_source_type": None,
                "source_constraint": None
            }

        # 单列定义约束（既有约束又是逻辑键）
        if inference_method == "single_defined_constraint_and_logical_pk":
            source_constraint = self._get_source_constraint(rel)
            target_type = self._get_target_source_type(rel)
            return {
                "discovery_method": "active_search",
                "target_source_type": target_type,
                "source_constraint": source_constraint
            }

        # 单列定义约束（只有约束，非逻辑键）
        if inference_method == "single_defined_constraint":
            source_constraint = self._get_source_constraint(rel)
            target_type = self._get_target_source_type(rel)
            return {
                "discovery_method": "active_search",
                "target_source_type": target_type,
                "source_constraint": source_constraint
            }

        # 单列主动搜索（保留用于向后兼容）
        if inference_method == "single_active_search":
            # 检查源列的实际约束类型
            constraint = self._get_source_constraint(rel)
            return {
                "discovery_method": "active_search",
                "target_source_type": None,
                "source_constraint": constraint
            }

        # 单列逻辑主键匹配
        if inference_method == "single_logical_key":
            return {
                "discovery_method": "logical_key_matching",
                "target_source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 复合键物理约束匹配
        if inference_method == "composite_physical":
            return {
                "discovery_method": "physical_constraint_matching",
                "target_source_type": "physical_constraints",  # 简化版，实际可能是 primary_key/unique_constraint/index
                "source_constraint": None
            }

        # 复合键逻辑主键匹配
        if inference_method == "composite_logical":
            return {
                "discovery_method": "logical_key_matching",
                "target_source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 复合键动态同名匹配
        if inference_method == "composite_dynamic_same_name":
            return {
                "discovery_method": "dynamic_same_name",
                "target_source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 其他未知类型，使用标准匹配
        logger.warning(f"未知的 inference_method: {inference_method}，使用 standard_matching")
        return {
            "discovery_method": "standard_matching",
            "target_source_type": None,
            "source_constraint": None
        }

    def _get_source_constraint(self, rel: Relation) -> Optional[str]:
        """获取源列的实际约束类型
        
        Args:
            rel: 关系对象
            
        Returns:
            约束类型字符串，可能的值：
            - "single_field_primary_key": 单列主键
            - "single_field_unique_constraint": 单列唯一约束
            - "single_field_index": 单列索引
            - None: 没有物理约束（只是数据唯一或逻辑主键）
        """
        if not hasattr(self, 'tables') or not self.tables or not rel.is_single_column:
            return None
        
        # 构建源表的完整名称
        source_table_key = f"{rel.source_schema}.{rel.source_table}"
        source_table = self.tables.get(source_table_key)
        
        if not source_table:
            logger.debug(f"未找到源表元数据: {source_table_key}")
            return None
        
        # 获取源列的 profile
        column_profiles = source_table.get("column_profiles", {})
        source_column = rel.source_columns[0]
        col_profile = column_profiles.get(source_column)
        
        if not col_profile:
            logger.debug(f"未找到源列元数据: {source_table_key}.{source_column}")
            return None
        
        # 检查 structure_flags
        structure_flags = col_profile.get("structure_flags", {})
        
        # 按优先级检查约束类型
        if structure_flags.get("is_primary_key"):
            return "single_field_primary_key"
        elif structure_flags.get("is_unique_constraint"):
            return "single_field_unique_constraint"
        elif structure_flags.get("is_indexed"):
            return "single_field_index"
        else:
            # 没有物理约束（可能只是数据唯一或逻辑主键）
            return None

    def _get_target_source_type(self, rel: Relation) -> Optional[str]:
        """获取目标列的实际来源类型
        
        Args:
            rel: 关系对象
            
        Returns:
            目标列类型字符串，可能的值：
            - "primary_key": 物理主键
            - "unique_constraint": 唯一约束
            - "index": 索引
            - "candidate_logical_key": 逻辑主键
            - None: 无法确定
        """
        if not hasattr(self, 'tables') or not self.tables or not rel.is_single_column:
            return None
        
        # 构建目标表的完整名称
        target_table_key = f"{rel.target_schema}.{rel.target_table}"
        target_table = self.tables.get(target_table_key)
        
        if not target_table:
            logger.debug(f"未找到目标表元数据: {target_table_key}")
            return None
        
        # 获取目标列的 profile
        column_profiles = target_table.get("column_profiles", {})
        target_column = rel.target_columns[0]
        col_profile = column_profiles.get(target_column)
        
        if not col_profile:
            logger.debug(f"未找到目标列元数据: {target_table_key}.{target_column}")
            return None
        
        # 检查 structure_flags（按优先级：PK > UK > Index）
        structure_flags = col_profile.get("structure_flags", {})
        
        if structure_flags.get("is_primary_key"):
            return "primary_key"
        
        if structure_flags.get("is_unique") or structure_flags.get("is_unique_constraint"):
            return "unique_constraint"
        
        if structure_flags.get("is_indexed"):
            return "index"
        
        # 检查是否为逻辑主键
        table_profile = target_table.get("table_profile", {})
        logical_keys = table_profile.get("logical_keys", {})
        
        for lk in logical_keys.get("candidate_primary_keys", []):
            lk_cols = lk.get("columns", [])
            lk_conf = lk.get("confidence_score", 0)
            
            # 单列逻辑主键且置信度 >= 0.8
            if (len(lk_cols) == 1 and 
                lk_cols[0] == target_column and 
                lk_conf >= 0.8):
                return "candidate_logical_key"
        
        return None

    def _calculate_statistics_v32(
            self,
            relations: List[Relation],
            suppressed: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """计算统计数据（v3.2口径）

        按照开发指南 2.10 节要求，统计字段包括：
        - total_relationships_found: 总关系数
        - foreign_key_relationships: 外键直通关系数
        - composite_key_relationships: 复合键关系数
        - single_column_relationships: 单列关系数
        - total_suppressed_single_relations: 被抑制的单列关系数
        - active_search_discoveries: 主动搜索发现数
        - dynamic_composite_discoveries: 动态同名复合键发现数

        Args:
            relations: 关系列表
            suppressed: 被抑制的候选

        Returns:
            统计字典
        """
        # 基础统计
        total = len(relations)

        # 外键直通关系数（relationship_type == "foreign_key"）
        foreign_key_count = len([r for r in relations if r.relationship_type == "foreign_key"])

        composite_count = len([r for r in relations if r.is_composite])
        single_count = len([r for r in relations if r.is_single_column])

        # 被抑制的单列关系数量
        suppressed_single_count = len([
            s for s in suppressed
            if len(s.get("source_columns", [])) == 1
        ])

        # active_search 发现数
        active_search_count = len([
            r for r in relations
            if r.inference_method and "active_search" in r.inference_method
        ])

        # dynamic_composite 发现数
        dynamic_composite_count = len([
            r for r in relations
            if r.inference_method and "dynamic_same_name" in r.inference_method and r.is_composite
        ])

        # TODO: 从 JSON 文件计数（暂时使用占位符）
        json_files_loaded = 0
        database_queries_executed = 0

        return {
            "total_relationships_found": total,
            "foreign_key_relationships": foreign_key_count,
            "composite_key_relationships": composite_count,
            "single_column_relationships": single_count,
            "total_suppressed_single_relations": suppressed_single_count,
            "active_search_discoveries": active_search_count,
            "dynamic_composite_discoveries": dynamic_composite_count,
            "json_files_loaded": json_files_loaded,
            "database_queries_executed": database_queries_executed,
        }

    def _write_markdown(self, relations: List[Relation]) -> Path:
        """输出Markdown报告

        Args:
            relations: 关系列表

        Returns:
            输出文件路径
        """
        lines = []

        # 标题
        lines.append("# 表间关系发现报告\n")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"关系总数: {len(relations)}\n")

        # 统计摘要
        lines.append("## 统计摘要\n")
        composite_count = len([r for r in relations if r.is_composite])
        single_count = len([r for r in relations if r.is_single_column])
        foreign_key_count = len([r for r in relations if r.relationship_type == "foreign_key"])
        inferred_count = len([r for r in relations if r.relationship_type == "inferred"])

        high_conf = len([r for r in relations
                         if r.composite_score and r.composite_score >= self.high_confidence_threshold])
        medium_conf = len([r for r in relations
                           if r.composite_score and
                           self.medium_confidence_threshold <= r.composite_score < self.high_confidence_threshold])

        lines.append(f"- 外键直通: {foreign_key_count}")
        lines.append(f"- 推断关系: {inferred_count}")
        lines.append(f"- 复合键关系: {composite_count}")
        lines.append(f"- 单列关系: {single_count}")
        lines.append(f"- 高置信度 (≥{self.high_confidence_threshold}): {high_conf}")
        lines.append(f"- 中置信度 ({self.medium_confidence_threshold}-{self.high_confidence_threshold}): {medium_conf}\n")

        # 关系详情
        lines.append("## 关系详情\n")

        for i, rel in enumerate(relations, 1):
            lines.append(f"### {i}. {rel.source_full_name_with_columns} → {rel.target_full_name_with_columns}\n")

            # 类型
            rel_type = "复合键" if rel.is_composite else "单列"
            lines.append(f"- **类型**: {rel_type}")

            # 列名
            if rel.is_single_column:
                lines.append(f"- **源列**: `{rel.source_columns[0]}`")
                lines.append(f"- **目标列**: `{rel.target_columns[0]}`")
            else:
                lines.append(f"- **源列**: `{', '.join(rel.source_columns)}`")
                lines.append(f"- **目标列**: `{', '.join(rel.target_columns)}`")

            # 关系类型
            lines.append(f"- **关系类型**: {rel.relationship_type}")

            if rel.composite_score is not None:
                # 置信度分类
                if rel.composite_score >= self.high_confidence_threshold:
                    conf_label = "高"
                elif rel.composite_score >= self.medium_confidence_threshold:
                    conf_label = "中"
                else:
                    conf_label = "低"

                lines.append(f"- **置信度**: {rel.composite_score:.3f} ({conf_label})")

                # 评分明细
                if rel.score_details:
                    lines.append("- **评分明细**:")
                    for dim, score in rel.score_details.items():
                        lines.append(f"  - {dim}: {score:.3f}")

                # 推断方法
                if rel.inference_method:
                    lines.append(f"- **推断方法**: {rel.inference_method}")

            lines.append("")  # 空行

        # 写入文件（使用配置的粒度，当前仅支持 global）
        md_file = self.rel_dir / f"relationships_{self.rel_granularity}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Markdown已输出: {md_file}")
        return md_file
