"""关系评分器

为候选关系计算4维度评分（必须使用数据库采样）。
"""

from typing import Dict, List, Tuple, Any, Set
from difflib import SequenceMatcher

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.scorer")

# 默认评分权重（4维度评分体系）
DEFAULT_WEIGHTS = {
    "inclusion_rate": 0.55,       # 数据包含率（核心指标）
    "name_similarity": 0.20,      # 列名相似度（防止假阳性）
    "type_compatibility": 0.15,   # 类型兼容性（体现JOIN性能）
    "jaccard_index": 0.10,        # Jaccard相似度（辅助判断）
}


class RelationshipScorer:
    """关系评分器

    4个评分维度：
    1. inclusion_rate (55%)：源列值在目标列中的包含率（数据库采样）
    2. name_similarity (20%)：列名相似度（Levenshtein算法）
    3. type_compatibility (15%)：类型兼容性（体现JOIN性能）
    4. jaccard_index (10%)：Jaccard相似度（数据库采样，辅助判断）
    
    已删除的维度：
    - uniqueness：逻辑错误（外键关系中应评估源列而非目标列）
    - semantic_role_bonus：推断不严谨，权重过小，意义不大
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

        logger.info(f"关系评分器已初始化（4维度评分体系）:")
        logger.info(f"  - sample_size={self.sample_size}")
        logger.info(f"  - weights={self.weights}")
        logger.debug(f"  - weights总和={sum(self.weights.values()):.4f}")

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

                # 计算4个维度评分和基数
                score_details, cardinality = self._calculate_scores(
                    source_table, source_columns,
                    target_table, target_columns
                )

                # 防御性检查：验证 score_details 的键与 weights 的键是否一致
                score_keys = set(score_details.keys())
                weight_keys = set(self.weights.keys())

                if score_keys != weight_keys:
                    missing_in_weights = score_keys - weight_keys
                    missing_in_scores = weight_keys - score_keys
                    error_msg = (
                        f"评分维度与权重配置不匹配！\n"
                        f"  score_details 的维度: {sorted(score_keys)}\n"
                        f"  weights 的维度: {sorted(weight_keys)}\n"
                    )
                    if missing_in_weights:
                        error_msg += f"  score_details 中有但 weights 中缺失: {sorted(missing_in_weights)}\n"
                    if missing_in_scores:
                        error_msg += f"  weights 中有但 score_details 中缺失: {sorted(missing_in_scores)}\n"
                    error_msg += (
                        "\n请确保配置文件中的 weights 只包含以下4个维度：\n"
                        "  - inclusion_rate: 0.55\n"
                        "  - name_similarity: 0.20\n"
                        "  - type_compatibility: 0.15\n"
                        "  - jaccard_index: 0.10\n"
                        "\n如果您使用的是旧配置文件，请更新为新的4维度配置。"
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

                # 计算加权求和
                composite_score = sum(
                    score_details[dim] * self.weights[dim]
                    for dim in score_details
                )

                # 验证权重总和为1.0（允许浮点误差）
                weight_sum = sum(self.weights.values())
                if abs(weight_sum - 1.0) > 0.001:
                    logger.warning(
                        f"权重总和不为1.0: {weight_sum:.4f}，可能导致评分不准确。"
                        f"当前权重: {self.weights}"
                    )

                # 添加评分信息和基数到候选
                candidate["composite_score"] = composite_score
                candidate["score_details"] = score_details
                candidate["cardinality"] = cardinality

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
    ) -> Tuple[Dict[str, float], str]:
        """计算4个维度评分和关系基数
        
        维度说明：
        1. inclusion_rate (55%): 源列值在目标列中的包含率
        2. name_similarity (20%): 列名相似度
        3. type_compatibility (15%): 类型兼容性
        4. jaccard_index (10%): Jaccard相似度
        
        已删除的维度：
        - uniqueness: 逻辑错误（外键允许重复）
        - semantic_role_bonus: 推断不严谨，意义不大

        Args:
            source_table: 源表元数据
            source_columns: 源列列表
            target_table: 目标表元数据
            target_columns: 目标列列表

        Returns:
            (score_details, cardinality): 评分明细字典（4个维度）和基数类型
        """
        source_info = source_table.get("table_info", {})
        target_info = target_table.get("table_info", {})

        source_schema = source_info.get("schema_name")
        source_table_name = source_info.get("table_name")
        target_schema = target_info.get("schema_name")
        target_table_name = target_info.get("table_name")

        source_profiles = source_table.get("column_profiles", {})
        target_profiles = target_table.get("column_profiles", {})

        logger.debug(
            f"开始计算评分: {source_schema}.{source_table_name}{source_columns} -> "
            f"{target_schema}.{target_table_name}{target_columns}"
        )

        # 1 & 2: inclusion_rate, jaccard_index + 唯一性和JOIN倍率（用于基数计算）
        inclusion_rate, jaccard_index, source_uniqueness, target_uniqueness, join_multiplicity = \
            self._sample_and_calculate_inclusion(
                source_schema, source_table_name, source_columns,
                target_schema, target_table_name, target_columns
            )

        # 3: name_similarity（列名相似度）
        name_similarity = self._calculate_name_similarity(source_columns, target_columns)

        # 4: type_compatibility（类型兼容性）
        type_compatibility = self._calculate_type_compatibility(
            source_columns, source_profiles,
            target_columns, target_profiles
        )

        # 计算基数
        cardinality = self._calculate_cardinality(
            source_uniqueness, target_uniqueness, join_multiplicity
        )

        logger.debug(
            f"评分明细: inclusion_rate={inclusion_rate:.4f}, jaccard_index={jaccard_index:.4f}, "
            f"name_similarity={name_similarity:.4f}, type_compatibility={type_compatibility:.4f}"
        )
        logger.info(
            f"关系基数: {source_schema}.{source_table_name}{source_columns} -> "
            f"{target_schema}.{target_table_name}{target_columns} = {cardinality}"
        )

        return {
            "inclusion_rate": inclusion_rate,
            "jaccard_index": jaccard_index,
            "name_similarity": name_similarity,
            "type_compatibility": type_compatibility,
        }, cardinality

    def _sample_and_calculate_inclusion(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str]
    ) -> Tuple[float, float, float, float, float]:
        """从数据库采样并计算评分指标和基数计算所需的统计值

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表

        Returns:
            (inclusion_rate, jaccard_index, source_uniqueness, target_uniqueness, join_multiplicity)
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
                return 0.0, 0.0, 0.0, 0.0, 1.0

            # 提取值集合（组合多列为元组）- 返回值集合和有效行数
            source_values, source_valid_count = self._extract_value_set(source_rows, source_columns)
            target_values, target_valid_count = self._extract_value_set(target_rows, target_columns)

            if not source_values or not target_values:
                return 0.0, 0.0, 0.0, 0.0, 1.0

            # 计算交集
            intersection = source_values & target_values
            union = source_values | target_values

            # inclusion_rate = |source ∩ target| / |source|
            inclusion_rate = len(intersection) / len(source_values) if source_values else 0.0

            # jaccard_index = |source ∩ target| / |source ∪ target|
            jaccard_index = len(intersection) / len(union) if union else 0.0

            logger.debug(f"采样统计: source={len(source_values)}, target={len(target_values)}, "
                         f"intersection={len(intersection)}, inclusion={inclusion_rate:.3f}, jaccard={jaccard_index:.3f}")

            # 计算组合唯一性（使用有效行数作为分母，修复 NULL 值问题）
            source_uniqueness = len(source_values) / source_valid_count if source_valid_count > 0 else 0.0
            target_uniqueness = len(target_values) / target_valid_count if target_valid_count > 0 else 0.0

            # NULL 率过高时记录警告
            if source_valid_count < len(source_rows) * 0.5:
                logger.warning(
                    f"源列 NULL 率过高: {source_schema}.{source_table}{source_columns}, "
                    f"有效行数={source_valid_count}/{len(source_rows)}, 基数判断可能不准确"
                )
            if target_valid_count < len(target_rows) * 0.5:
                logger.warning(
                    f"目标列 NULL 率过高: {target_schema}.{target_table}{target_columns}, "
                    f"有效行数={target_valid_count}/{len(target_rows)}, 基数判断可能不准确"
                )

            # 执行 JOIN COUNT 获取精确倍率（传入 source_valid_count 作为分母）
            join_multiplicity = self._execute_join_count(
                source_schema, source_table, source_columns,
                target_schema, target_table, target_columns,
                source_valid_count
            )

            logger.debug(
                f"采样统计扩展: source_uniq={source_uniqueness:.3f} ({len(source_values)}/{source_valid_count}), "
                f"target_uniq={target_uniqueness:.3f} ({len(target_values)}/{target_valid_count}), "
                f"join_mult={join_multiplicity:.3f}, source_sample={len(source_rows)}, source_valid={source_valid_count}"
            )

            return inclusion_rate, jaccard_index, source_uniqueness, target_uniqueness, join_multiplicity

        except Exception as e:
            logger.error(f"数据库采样失败: {e}", exc_info=True)
            return 0.0, 0.0, 0.0, 0.0, 1.0

    def _execute_join_count(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str],
            source_valid_count: int
    ) -> float:
        """执行 JOIN COUNT 获取 JOIN 倍率

        在采样数据上执行真实 JOIN 查询，计算源表记录的扩散倍数。

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表
            source_valid_count: 源表有效行数（排除 NULL 后实际参与比较的行数）

        Returns:
            join_multiplicity: JOIN 倍率（join_count / source_valid_count）
        """
        try:
            # 构造列表达式
            source_col_expr = ", ".join([f'"{col}"' for col in source_columns])

            # 构造 JOIN ON 条件
            join_conditions = " AND ".join([
                f's."{src_col}" = t."{tgt_col}"'
                for src_col, tgt_col in zip(source_columns, target_columns)
            ])

            # JOIN COUNT SQL（在采样数据上执行）
            join_sql = f'''
                WITH source_sample AS (
                    SELECT {source_col_expr}
                    FROM "{source_schema}"."{source_table}"
                    LIMIT %s
                )
                SELECT COUNT(*) AS join_count
                FROM source_sample s
                INNER JOIN "{target_schema}"."{target_table}" t
                ON {join_conditions}
            '''

            result = self.connector.execute_query(join_sql, (self.sample_size,))
            join_count = result[0].get('join_count', 0) if result else 0

            # 计算倍率：使用传入的 source_valid_count 作为分母
            multiplicity = join_count / source_valid_count if source_valid_count > 0 else 0.0

            logger.debug(
                f"JOIN COUNT: {source_schema}.{source_table} → {target_schema}.{target_table}, "
                f"source_valid_count={source_valid_count}, join_count={join_count}, multiplicity={multiplicity:.3f}"
            )

            return multiplicity

        except Exception as e:
            logger.error(f"执行 JOIN COUNT 失败: {e}", exc_info=True)
            return 1.0  # 失败时返回 1.0（保守估计，避免误判为 M:N）

    def _calculate_cardinality(
            self,
            source_uniqueness: float,
            target_uniqueness: float,
            join_multiplicity: float
    ) -> str:
        """计算关系基数（静态+动态混合判断）

        三层判断策略：
        1. 静态预判（基于唯一性）：快速识别明确的 1:1、1:N、N:1
        2. 动态验证（基于 JOIN 倍率）：处理边界情况
        3. M:N 兜底：无法判断时统一返回 M:N

        Args:
            source_uniqueness: 源列组合唯一性（采样数据）
            target_uniqueness: 目标列组合唯一性（采样数据）
            join_multiplicity: JOIN 倍率（采样数据）

        Returns:
            基数类型: "1:1" | "1:N" | "N:1" | "M:N"
        """
        HIGH = 0.95  # 高唯一度阈值
        LOW = 0.80   # 低唯一度阈值

        logger.debug(
            f"基数判断输入: source_uniq={source_uniqueness:.3f}, "
            f"target_uniq={target_uniqueness:.3f}, join_mult={join_multiplicity:.3f}"
        )

        # === 第一层：静态预判（基于唯一性） ===

        # 1:1 - 双方都高度唯一
        if source_uniqueness >= HIGH and target_uniqueness >= HIGH:
            logger.debug("基数判断: 1:1（双方高唯一）")
            return "1:1"

        # 1:N - 源唯一，目标重复
        if source_uniqueness >= HIGH and target_uniqueness < LOW:
            logger.debug("基数判断: 1:N（源唯一，目标重复）")
            return "1:N"

        # N:1 - 源重复，目标唯一
        if source_uniqueness < LOW and target_uniqueness >= HIGH:
            logger.debug("基数判断: N:1（源重复，目标唯一）")
            return "N:1"

        # === 第二层：动态验证（边界情况） ===

        logger.debug(f"进入动态判断（唯一性在边界区间 [{LOW}, {HIGH})）")

        # 倍率接近 1 → 一对一或多对一
        if join_multiplicity <= 1.1:
            if source_uniqueness >= target_uniqueness:
                logger.debug("基数判断: 1:1（倍率≈1，源更唯一）")
                return "1:1"
            else:
                logger.debug("基数判断: N:1（倍率≈1，目标更唯一）")
                return "N:1"

        # 倍率显著 > 1 → 一对多或多对多
        if join_multiplicity > 1.5:
            if source_uniqueness >= 0.85:
                logger.debug("基数判断: 1:N（倍率>1.5，源较唯一）")
                return "1:N"
            else:
                logger.debug("基数判断: M:N（倍率>1.5，双方都不唯一）")
                return "M:N"

        # === 第三层：M:N 兜底 ===

        logger.debug("基数判断: M:N（兜底，无法明确判断）")
        return "M:N"

    def _extract_value_set(self, rows: List[Dict], columns: List[str]) -> Tuple[Set[Tuple], int]:
        """从查询结果中提取值集合

        Args:
            rows: 查询结果行列表
            columns: 列名列表

        Returns:
            (value_set, valid_count): 
            - value_set: 值元组集合（多列组合为元组，已排除含 NULL 的行）
            - valid_count: 有效行数（排除含 NULL 的行后实际参与比较的行数）
        """
        value_set = set()
        valid_count = 0

        for row in rows:
            # 提取各列的值组成元组
            values = tuple(row.get(col) for col in columns)

            # 跳过包含NULL的值
            if None not in values:
                value_set.add(values)
                valid_count += 1

        return value_set, valid_count

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
