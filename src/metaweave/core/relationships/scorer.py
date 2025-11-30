"""关系评分器

为候选关系计算6维度评分（必须使用数据库采样）。
"""

from typing import Dict, List, Tuple, Any, Set
from difflib import SequenceMatcher

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.scorer")

# 默认评分权重
DEFAULT_WEIGHTS = {
    "inclusion_rate": 0.30,
    "jaccard_index": 0.15,
    "uniqueness": 0.10,
    "name_similarity": 0.20,
    "type_compatibility": 0.20,
    "semantic_role_bonus": 0.05,
}


class RelationshipScorer:
    """关系评分器

    6个评分维度：
    1. inclusion_rate：源列值在目标列中的包含率（数据库采样）
    2. jaccard_index：Jaccard相似度（数据库采样）
    3. uniqueness：目标列唯一性（JSON statistics）
    4. name_similarity：列名相似度（Levenshtein）
    5. type_compatibility：类型兼容性
    6. semantic_role_bonus：语义角色加分
    """

    def __init__(self, config: dict, connector: DatabaseConnector):
        """初始化评分器

        Args:
            config: relationships配置
            connector: 数据库连接器（必需）
        """
        self.config = config
        self.connector = connector
        self.weights = config.get("weights", DEFAULT_WEIGHTS)

        # 采样配置
        sampling_config = config.get("sampling", {})
        self.sample_size = sampling_config.get("sample_size", 1000)

        logger.info(f"关系评分器已初始化: sample_size={self.sample_size}")

    def score_candidates(
            self,
            candidates: List[Dict[str, Any]],
            tables: Dict[str, dict]
    ) -> List[Dict[str, Any]]:
        """为候选关系计算评分

        Args:
            candidates: 候选列表
            tables: 表元数据字典

        Returns:
            评分后的候选列表（添加composite_score和score_details字段）
        """
        scored_candidates = []

        for i, candidate in enumerate(candidates):
            try:
                source_table = candidate["source"]
                target_table = candidate["target"]
                source_columns = candidate["source_columns"]
                target_columns = candidate["target_columns"]

                # 计算6个维度评分
                score_details = self._calculate_scores(
                    source_table, source_columns,
                    target_table, target_columns
                )

                # 加权求和
                composite_score = sum(
                    score_details[dim] * self.weights[dim]
                    for dim in score_details
                )

                # 添加评分信息到候选
                candidate["composite_score"] = composite_score
                candidate["score_details"] = score_details

                source_info = source_table.get("table_info", {})
                target_info = target_table.get("table_info", {})
                relation_label = (
                    f"{source_info.get('schema_name')}.{source_info.get('table_name')}"
                    f"[{', '.join(source_columns)}] -> "
                    f"{target_info.get('schema_name')}.{target_info.get('table_name')}"
                    f"[{', '.join(target_columns)}]"
                )
                logger.debug(
                    "评分完成 %s: %s, composite=%.4f",
                    relation_label,
                    score_details,
                    composite_score,
                )

                scored_candidates.append(candidate)

                if (i + 1) % 10 == 0:
                    logger.info(f"已评分: {i + 1}/{len(candidates)} 个候选")

            except Exception as e:
                logger.error(f"候选评分失败: {e}", exc_info=True)

        logger.info(f"候选评分完成: {len(scored_candidates)} 个")
        return scored_candidates

    def _calculate_scores(
            self,
            source_table: dict,
            source_columns: List[str],
            target_table: dict,
            target_columns: List[str]
    ) -> Dict[str, float]:
        """计算6个维度评分

        Args:
            source_table: 源表元数据
            source_columns: 源列列表
            target_table: 目标表元数据
            target_columns: 目标列列表

        Returns:
            评分明细字典
        """
        source_info = source_table.get("table_info", {})
        target_info = target_table.get("table_info", {})

        source_schema = source_info.get("schema_name")
        source_table_name = source_info.get("table_name")
        target_schema = target_info.get("schema_name")
        target_table_name = target_info.get("table_name")

        source_profiles = source_table.get("column_profiles", {})
        target_profiles = target_table.get("column_profiles", {})

        # 1 & 2: inclusion_rate 和 jaccard_index（数据库采样）
        inclusion_rate, jaccard_index = self._sample_and_calculate_inclusion(
            source_schema, source_table_name, source_columns,
            target_schema, target_table_name, target_columns
        )

        # 3: uniqueness（从JSON获取，平均值）
        uniqueness = self._calculate_avg_uniqueness(target_columns, target_profiles)

        # 4: name_similarity（列名相似度）
        name_similarity = self._calculate_name_similarity(source_columns, target_columns)

        # 5: type_compatibility（类型兼容性）
        type_compatibility = self._calculate_type_compatibility(
            source_columns, source_profiles,
            target_columns, target_profiles
        )

        # 6: semantic_role_bonus（语义角色加分）
        semantic_role_bonus = self._calculate_semantic_role_bonus(
            target_columns, target_profiles
        )

        return {
            "inclusion_rate": inclusion_rate,
            "jaccard_index": jaccard_index,
            "uniqueness": uniqueness,
            "name_similarity": name_similarity,
            "type_compatibility": type_compatibility,
            "semantic_role_bonus": semantic_role_bonus,
        }

    def _sample_and_calculate_inclusion(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str]
    ) -> Tuple[float, float]:
        """从数据库采样并计算inclusion_rate和jaccard_index

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表

        Returns:
            (inclusion_rate, jaccard_index)
        """
        try:
            # 采样源表（只取需要的列）
            source_col_expr = ", ".join([f'"{col}"' for col in source_columns])
            source_sql = f'''
                SELECT {source_col_expr}
                FROM "{source_schema}"."{source_table}"
                LIMIT %s
            '''
            source_rows = self.connector.execute_query(source_sql, (self.sample_size,))

            # 采样目标表
            target_col_expr = ", ".join([f'"{col}"' for col in target_columns])
            target_sql = f'''
                SELECT {target_col_expr}
                FROM "{target_schema}"."{target_table}"
                LIMIT %s
            '''
            target_rows = self.connector.execute_query(target_sql, (self.sample_size,))

            if not source_rows or not target_rows:
                logger.warning(f"采样数据为空: {source_schema}.{source_table} 或 {target_schema}.{target_table}")
                return 0.0, 0.0

            # 提取值集合（组合多列为元组）
            source_values = self._extract_value_set(source_rows, source_columns)
            target_values = self._extract_value_set(target_rows, target_columns)

            if not source_values or not target_values:
                return 0.0, 0.0

            # 计算交集
            intersection = source_values & target_values
            union = source_values | target_values

            # inclusion_rate = |source ∩ target| / |source|
            inclusion_rate = len(intersection) / len(source_values) if source_values else 0.0

            # jaccard_index = |source ∩ target| / |source ∪ target|
            jaccard_index = len(intersection) / len(union) if union else 0.0

            logger.debug(f"采样统计: source={len(source_values)}, target={len(target_values)}, "
                         f"intersection={len(intersection)}, inclusion={inclusion_rate:.3f}, jaccard={jaccard_index:.3f}")

            return inclusion_rate, jaccard_index

        except Exception as e:
            logger.error(f"数据库采样失败: {e}", exc_info=True)
            return 0.0, 0.0

    def _extract_value_set(self, rows: List[Dict], columns: List[str]) -> Set[Tuple]:
        """从查询结果中提取值集合

        Args:
            rows: 查询结果行列表
            columns: 列名列表

        Returns:
            值元组集合（多列组合为元组）
        """
        value_set = set()

        for row in rows:
            # 提取各列的值组成元组
            values = tuple(row.get(col) for col in columns)

            # 跳过包含NULL的值
            if None not in values:
                value_set.add(values)

        return value_set

    def _calculate_avg_uniqueness(
            self,
            columns: List[str],
            profiles: Dict[str, dict]
    ) -> float:
        """计算平均唯一性

        Args:
            columns: 列名列表
            profiles: 列画像字典

        Returns:
            平均唯一性（0-1）
        """
        total_uniqueness = 0
        count = 0

        for col in columns:
            profile = profiles.get(col, {})
            stats = profile.get("statistics", {})
            uniqueness = stats.get("uniqueness", 0.5)  # 默认0.5
            total_uniqueness += uniqueness
            count += 1

        return total_uniqueness / count if count > 0 else 0.5

    def _calculate_name_similarity(
            self,
            source_columns: List[str],
            target_columns: List[str]
    ) -> float:
        """计算列名相似度（平均值）

        Args:
            source_columns: 源列列表
            target_columns: 目标列列表

        Returns:
            平均名称相似度（0-1）
        """
        if len(source_columns) != len(target_columns):
            return 0.0

        total_sim = 0
        for src_col, tgt_col in zip(source_columns, target_columns):
            if src_col == tgt_col:
                sim = 1.0
            else:
                sim = SequenceMatcher(None, src_col.lower(), tgt_col.lower()).ratio()
            total_sim += sim

        return total_sim / len(source_columns)

    def _calculate_type_compatibility(
            self,
            source_columns: List[str],
            source_profiles: Dict[str, dict],
            target_columns: List[str],
            target_profiles: Dict[str, dict]
    ) -> float:
        """计算类型兼容性（平均值）

        Args:
            source_columns: 源列列表
            source_profiles: 源列画像
            target_columns: 目标列列表
            target_profiles: 目标列画像

        Returns:
            平均类型兼容性（0-1）
        """
        if len(source_columns) != len(target_columns):
            return 0.0

        total_compat = 0
        for src_col, tgt_col in zip(source_columns, target_columns):
            src_profile = source_profiles.get(src_col, {})
            tgt_profile = target_profiles.get(tgt_col, {})

            src_type = src_profile.get("data_type", "")
            tgt_type = tgt_profile.get("data_type", "")

            compat = self._get_type_compatibility(src_type, tgt_type)
            total_compat += compat

        return total_compat / len(source_columns)

    def _get_type_compatibility(self, type1: str, type2: str) -> float:
        """计算两个类型的兼容性

        Returns:
            1.0 (完全兼容) | 0.5 (部分兼容) | 0.0 (不兼容)
        """
        # 标准化类型
        t1 = self._normalize_type(type1)
        t2 = self._normalize_type(type2)

        # 完全相同
        if t1 == t2:
            return 1.0

        # 整数类型族
        int_types = {"integer", "int", "int4", "bigint", "int8", "smallint", "int2", "serial", "bigserial"}
        if t1 in int_types and t2 in int_types:
            return 1.0

        # 字符串类型族
        str_types = {"varchar", "character varying", "char", "character", "text", "bpchar"}
        if t1 in str_types and t2 in str_types:
            return 0.5  # 部分兼容（长度可能不同）

        # 数值类型族
        num_types = {"numeric", "decimal", "real", "double precision", "float", "float4", "float8"}
        if t1 in num_types and t2 in num_types:
            return 0.8

        # 整数与数值类型可以部分兼容
        if (t1 in int_types and t2 in num_types) or (t1 in num_types and t2 in int_types):
            return 0.6

        return 0.0

    def _normalize_type(self, data_type: str) -> str:
        """标准化数据类型"""
        if not data_type:
            return ""

        # 转小写并去除空格
        normalized = data_type.lower().strip()

        # 移除precision/scale（如 numeric(10,2) -> numeric）
        if "(" in normalized:
            normalized = normalized.split("(")[0].strip()

        return normalized

    def _calculate_semantic_role_bonus(
            self,
            columns: List[str],
            profiles: Dict[str, dict]
    ) -> float:
        """计算语义角色加分

        识别为identifier的列给予加分

        Args:
            columns: 列名列表
            profiles: 列画像字典

        Returns:
            语义角色加分（0-1）
        """
        identifier_count = 0

        for col in columns:
            profile = profiles.get(col, {})
            semantic_analysis = profile.get("semantic_analysis", {})
            semantic_role = semantic_analysis.get("semantic_role")

            if semantic_role == "identifier":
                identifier_count += 1

        # 全部是identifier -> 1.0，部分是identifier -> 按比例，都不是 -> 0.0
        return identifier_count / len(columns) if columns else 0.0
