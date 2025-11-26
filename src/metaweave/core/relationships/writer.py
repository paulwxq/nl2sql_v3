"""关系输出器

负责输出关系发现结果（JSON + Markdown），符合 v3.2 文档规范。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

from src.metaweave.core.relationships.models import Relation
from src.metaweave.utils.file_utils import ensure_dir

logger = logging.getLogger("metaweave.relationships.writer")


class RelationshipWriter:
    """关系输出器

    输出文件：
    - relationships_global.json（所有关系，v3.2格式）
    - relationships_global.md（可读报告）
    """

    def __init__(self, config: dict):
        """初始化输出器

        Args:
            config: top-level 配置
        """
        output_config = config.get("output", {})

        self.rel_dir = Path(output_config.get("rel_directory", "output/metaweave/metadata/rel"))
        self.rel_granularity = output_config.get("rel_granularity", "global")

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
            config: Dict[str, Any]
    ) -> List[str]:
        """输出关系发现结果（v3.2格式）

        Args:
            relations: 接受的关系列表（外键+推断）
            suppressed: 被抑制的候选列表
            config: 完整配置

        Returns:
            输出文件路径列表
        """
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

        # 写入文件
        json_file = self.rel_dir / "relationships_global.json"
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
            result["source_type"] = "foreign_key"
            result["source_constraint"] = None
        else:
            # 从 inference_method (candidate_type) 拆分为规范字段
            discovery_info = self._parse_discovery_info(rel.inference_method, rel)
            result["discovery_method"] = discovery_info["discovery_method"]
            result["source_type"] = discovery_info.get("source_type")
            result["source_constraint"] = discovery_info.get("source_constraint")

        # 评分相关字段（仅推断关系有）
        if rel.composite_score is not None:
            result["composite_score"] = rel.composite_score
            result["confidence_level"] = confidence_level
            result["metrics"] = rel.score_details or {}

        return result

    def _parse_discovery_info(
            self,
            inference_method: Optional[str],
            rel: Relation
    ) -> Dict[str, Optional[str]]:
        """解析 inference_method 为 discovery_method, source_type, source_constraint

        映射规则（基于v3.2文档）：
        - single_active_search -> discovery_method: "active_search", source_constraint: "single_field_index"
        - single_logical_key -> discovery_method: "logical_key_matching", source_type: "candidate_logical_key"
        - composite_physical -> discovery_method: "physical_constraint_matching", source_type: "physical_constraints"
        - composite_logical -> discovery_method: "logical_key_matching", source_type: "candidate_logical_key"
        - composite_dynamic_same_name -> discovery_method: "dynamic_same_name", source_type: "candidate_logical_key"
        - 其他 -> discovery_method: "standard_matching"

        Args:
            inference_method: 推断方法字符串（如 single_active_search）
            rel: 关系对象

        Returns:
            包含 discovery_method, source_type, source_constraint 的字典
        """
        if not inference_method:
            return {
                "discovery_method": "standard_matching",
                "source_type": None,
                "source_constraint": None
            }

        # 单列主动搜索
        if inference_method == "single_active_search":
            return {
                "discovery_method": "active_search",
                "source_type": None,
                "source_constraint": "single_field_index"  # 简化版，实际可能是其他约束
            }

        # 单列逻辑主键匹配
        if inference_method == "single_logical_key":
            return {
                "discovery_method": "logical_key_matching",
                "source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 复合键物理约束匹配
        if inference_method == "composite_physical":
            return {
                "discovery_method": "physical_constraint_matching",
                "source_type": "physical_constraints",  # 简化版，实际可能是 primary_key/unique_constraint/index
                "source_constraint": None
            }

        # 复合键逻辑主键匹配
        if inference_method == "composite_logical":
            return {
                "discovery_method": "logical_key_matching",
                "source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 复合键动态同名匹配
        if inference_method == "composite_dynamic_same_name":
            return {
                "discovery_method": "dynamic_same_name",
                "source_type": "candidate_logical_key",
                "source_constraint": None
            }

        # 其他未知类型，使用标准匹配
        logger.warning(f"未知的 inference_method: {inference_method}，使用 standard_matching")
        return {
            "discovery_method": "standard_matching",
            "source_type": None,
            "source_constraint": None
        }

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
            lines.append(f"### {i}. {rel.source_full_name} → {rel.target_full_name}\n")

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

        # 写入文件
        md_file = self.rel_dir / "relationships_global.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Markdown已输出: {md_file}")
        return md_file
