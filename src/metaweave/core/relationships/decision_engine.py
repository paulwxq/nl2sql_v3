"""决策引擎

应用决策规则和抑制逻辑，过滤候选关系。
"""

from typing import List, Dict, Tuple, Any

from src.metaweave.core.relationships.models import Relation
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.decision_engine")


class DecisionEngine:
    """决策引擎

    职责：
    1. 阈值过滤：composite_score < accept_threshold -> 丢弃
    2. 抑制规则：复合关系存在时抑制同表对的单列关系（除非有独立约束）
    """

    def __init__(self, config: dict):
        """初始化决策引擎

        Args:
            config: relationships配置
        """
        decision_config = config.get("decision", {})
        output_config = config.get("output", {})

        self.accept_threshold = decision_config.get("accept_threshold", 0.80)
        self.high_confidence_threshold = decision_config.get("high_confidence_threshold", 0.90)
        self.medium_confidence_threshold = decision_config.get("medium_confidence_threshold", 0.80)
        self.suppress_single_if_composite = decision_config.get("suppress_single_if_composite", True)

        # 读取 rel_id_salt 配置（与 Repository 保持一致）
        self.rel_id_salt = output_config.get("rel_id_salt", "")

        logger.info(f"决策引擎已初始化: accept_threshold={self.accept_threshold}, "
                    f"suppress_single={self.suppress_single_if_composite}")

    def filter_and_suppress(
            self,
            scored_candidates: List[Dict[str, Any]]
    ) -> Tuple[List[Relation], List[Dict[str, Any]]]:
        """过滤和抑制候选关系

        Args:
            scored_candidates: 评分后的候选列表

        Returns:
            (accepted_relations, suppressed_candidates)
            - accepted_relations: 接受的推断关系列表
            - suppressed_candidates: 被抑制的候选列表
        """
        # 1. 阈值过滤
        above_threshold = []
        below_threshold = []

        for candidate in scored_candidates:
            composite_score = candidate.get("composite_score", 0)
            if composite_score >= self.accept_threshold:
                above_threshold.append(candidate)
                logger.debug(
                    "通过阈值 %.2f: %s (score=%.4f)",
                    self.accept_threshold,
                    self._format_candidate(candidate),
                    composite_score,
                )
            else:
                below_threshold.append(candidate)
                logger.debug(
                    "低于阈值 %.2f: %s (score=%.4f)",
                    self.accept_threshold,
                    self._format_candidate(candidate),
                    composite_score,
                )

        logger.info(f"阈值过滤: {len(above_threshold)} 个通过，{len(below_threshold)} 个未达标")

        # 2. 应用抑制规则
        if self.suppress_single_if_composite:
            accepted, suppressed = self._apply_suppression(above_threshold)
        else:
            accepted = above_threshold
            suppressed = []

        # 3. 转换为Relation对象
        accepted_relations = []
        for candidate in accepted:
            relation = self._candidate_to_relation(candidate)
            accepted_relations.append(relation)

        logger.info(f"抑制规则: {len(accepted_relations)} 个接受，{len(suppressed)} 个抑制")

        # 合并所有未接受的候选（用于调试）
        all_suppressed = below_threshold + suppressed

        return accepted_relations, all_suppressed

    def _apply_suppression(
            self,
            candidates: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """应用抑制规则

        规则：
        - 如果存在accepted的复合关系(A->B)，抑制同表对的单列关系
        - 除非单列关系的源列有独立约束（PK/UK/单列Index）

        Args:
            candidates: 候选列表

        Returns:
            (accepted, suppressed)
        """
        # 按表对分组
        table_pair_groups: Dict[str, List[Dict]] = {}

        for candidate in candidates:
            source_info = candidate["source"].get("table_info", {})
            target_info = candidate["target"].get("table_info", {})

            source_full = f"{source_info.get('schema_name')}.{source_info.get('table_name')}"
            target_full = f"{target_info.get('schema_name')}.{target_info.get('table_name')}"

            table_pair = f"{source_full}->{target_full}"

            if table_pair not in table_pair_groups:
                table_pair_groups[table_pair] = []

            table_pair_groups[table_pair].append(candidate)

        # 对每个表对应用抑制规则
        accepted = []
        suppressed = []

        for table_pair, group in table_pair_groups.items():
            # 检查是否有复合关系
            composite_relations = [c for c in group if len(c["source_columns"]) > 1]
            single_relations = [c for c in group if len(c["source_columns"]) == 1]

            if composite_relations:
                # 有复合关系，保留复合关系
                accepted.extend(composite_relations)
                for rel in composite_relations:
                    logger.debug(
                        "保留复合关系: %s",
                        self._format_candidate(rel),
                    )

                # 检查单列关系是否有独立约束
                for single_rel in single_relations:
                    if self._has_independent_constraint(single_rel):
                        # 有独立约束，保留
                        accepted.append(single_rel)
                        logger.debug(
                            "保留单列关系（独立约束）: %s",
                            self._format_candidate(single_rel),
                        )
                    else:
                        # 无独立约束，抑制
                        suppressed.append(single_rel)
                        logger.debug(
                            "抑制单列关系（存在复合关系）: %s",
                            self._format_candidate(single_rel),
                        )
            else:
                # 没有复合关系，保留所有单列关系
                accepted.extend(single_relations)
                for rel in single_relations:
                    logger.debug(
                        "保留单列关系: %s",
                        self._format_candidate(rel),
                    )

        return accepted, suppressed

    def _has_independent_constraint(self, candidate: Dict[str, Any]) -> bool:
        """检查源列是否有独立约束（PK/UK/单列Index）

        Args:
            candidate: 候选关系

        Returns:
            是否有独立约束
        """
        source_table = candidate["source"]
        source_columns = candidate["source_columns"]

        if len(source_columns) != 1:
            return False

        source_col_name = source_columns[0]
        source_profiles = source_table.get("column_profiles", {})
        source_profile = source_profiles.get(source_col_name, {})

        structure_flags = source_profile.get("structure_flags", {})

        # 检查单列主键
        if structure_flags.get("is_primary_key"):
            return True

        # 检查单列唯一约束
        if structure_flags.get("is_unique") or structure_flags.get("is_unique_constraint"):
            return True

        # 检查单列索引
        if structure_flags.get("is_indexed"):
            # 需要确认是否为单列索引（而非复合索引的一部分）
            # Phase 1简化实现：有索引就算
            return True

        return False

    def _candidate_to_relation(self, candidate: Dict[str, Any]) -> Relation:
        """将候选转换为Relation对象

        Args:
            candidate: 候选关系

        Returns:
            Relation对象
        """
        source_info = candidate["source"].get("table_info", {})
        target_info = candidate["target"].get("table_info", {})

        # 提取表和列信息
        source_schema = source_info.get("schema_name")
        source_table = source_info.get("table_name")
        target_schema = target_info.get("schema_name")
        target_table = target_info.get("table_name")
        source_columns = candidate["source_columns"]
        target_columns = candidate["target_columns"]

        # 使用 Repository 的静态方法生成 relationship_id（统一逻辑）
        relationship_id = MetadataRepository.compute_relationship_id(
            source_schema=source_schema,
            source_table=source_table,
            source_columns=source_columns,
            target_schema=target_schema,
            target_table=target_table,
            target_columns=target_columns,
            rel_id_salt=self.rel_id_salt
        )

        # 从评分结果获取基数（由 scorer 计算）
        cardinality = candidate.get("cardinality", "N:1")

        # 推断方法
        inference_method = candidate.get("candidate_type", "unknown")

        return Relation(
            relationship_id=relationship_id,
            source_schema=source_schema,
            source_table=source_table,
            source_columns=source_columns,
            target_schema=target_schema,
            target_table=target_table,
            target_columns=target_columns,
            relationship_type="inferred",
            cardinality=cardinality,
            composite_score=candidate.get("composite_score"),
            score_details=candidate.get("score_details"),
            inference_method=inference_method
        )

    def _format_candidate(self, candidate: Dict[str, Any]) -> str:
        """格式化候选信息用于日志"""

        def _fmt(table_meta: Dict[str, Any]) -> str:
            info = table_meta.get("table_info", {})
            return f"{info.get('schema_name')}.{info.get('table_name')}"

        source = _fmt(candidate["source"])
        target = _fmt(candidate["target"])
        src_cols = ",".join(candidate.get("source_columns", []))
        tgt_cols = ",".join(candidate.get("target_columns", []))
        cand_type = candidate.get("candidate_type")
        return f"{source}[{src_cols}] -> {target}[{tgt_cols}] ({cand_type})"
