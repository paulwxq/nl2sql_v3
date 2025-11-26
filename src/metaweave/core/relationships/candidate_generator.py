"""候选关系生成器

负责生成候选关系（复合键优先，单列其次），排除已存在的外键。
"""

import logging
from typing import Dict, List, Set, Any
from difflib import SequenceMatcher

logger = logging.getLogger("metaweave.relationships.candidate_generator")


class CandidateGenerator:
    """候选关系生成器

    生成顺序：
    1. 复合键候选（物理约束、逻辑键、动态同名）
    2. 单列候选（主动搜索、逻辑键匹配）
    """

    def __init__(self, config: dict, fk_signature_set: Set[str]):
        """初始化候选生成器

        Args:
            config: relationships配置
            fk_signature_set: 外键签名集合（用于去重）
        """
        self.config = config
        self.fk_signature_set = fk_signature_set

        # 单列配置
        single_config = config.get("single_column", {})
        self.active_search_enabled = single_config.get("active_search_same_name", True)
        self.important_constraints = set(single_config.get("important_constraints", [
            "single_field_primary_key",
            "single_field_unique_constraint",
            "single_field_index"
        ]))
        self.exclude_semantic_roles = set(single_config.get("exclude_semantic_roles", ["audit", "metric"]))
        self.logical_key_min_confidence = single_config.get("logical_key_min_confidence", 0.8)

        # 复合键配置
        composite_config = config.get("composite", {})
        self.max_columns = composite_config.get("max_columns", 3)
        self.target_sources = composite_config.get("target_sources", [
            "physical_constraints",
            "candidate_logical_keys",
            "dynamic_same_name"
        ])
        self.min_name_similarity = composite_config.get("min_name_similarity", 0.7)
        self.min_type_compatibility = composite_config.get("min_type_compatibility", 0.8)

        logger.info(f"候选生成器已初始化: max_columns={self.max_columns}, "
                    f"active_search={self.active_search_enabled}")

    def generate_candidates(self, tables: Dict[str, dict]) -> List[Dict[str, Any]]:
        """生成所有候选关系

        Args:
            tables: 表元数据字典 {full_name: json_data}

        Returns:
            候选列表，每个候选包含：
            - source/target: 表元数据
            - source_columns/target_columns: 列名列表
            - candidate_type: 候选类型
        """
        candidates = []

        # 1. 复合键候选（优先）
        composite_candidates = self._generate_composite_candidates(tables)
        candidates.extend(composite_candidates)
        logger.info(f"生成复合键候选: {len(composite_candidates)} 个")

        # 2. 单列候选
        single_candidates = self._generate_single_column_candidates(tables)
        candidates.extend(single_candidates)
        logger.info(f"生成单列候选: {len(single_candidates)} 个")

        logger.info(f"候选生成完成: 共 {len(candidates)} 个")
        return candidates

    def _generate_composite_candidates(self, tables: Dict[str, dict]) -> List[Dict[str, Any]]:
        """生成复合键候选

        来源：
        1. physical_constraints（PK/UK/Index组合）
        2. candidate_logical_keys（confidence >= 0.8）
        3. dynamic_same_name（精确同名 + 类型兼容）
        """
        candidates = []

        for source_name, source_table in tables.items():
            source_info = source_table.get("table_info", {})
            source_schema = source_info.get("schema_name")
            source_table_name = source_info.get("table_name")

            # 收集源表的复合键组合
            source_combinations = self._collect_source_combinations(source_table)

            # 对每个组合，在目标表中查找匹配
            for combo in source_combinations:
                source_columns = combo["columns"]
                combo_type = combo["type"]

                # 遍历所有目标表（排除自己）
                for target_name, target_table in tables.items():
                    if target_name == source_name:
                        continue

                    target_info = target_table.get("table_info", {})
                    target_schema = target_info.get("schema_name")
                    target_table_name = target_info.get("table_name")

                    # 检查FK去重
                    fk_sig = self._make_signature(
                        source_schema, source_table_name, source_columns,
                        target_schema, target_table_name, source_columns  # 临时用source_columns
                    )

                    # 根据target_sources查找目标列
                    target_columns = self._find_target_columns(
                        source_columns, source_table, target_table, combo_type
                    )

                    if not target_columns:
                        continue

                    # 更新FK签名（使用实际的target_columns）
                    fk_sig = self._make_signature(
                        source_schema, source_table_name, source_columns,
                        target_schema, target_table_name, target_columns
                    )

                    if fk_sig in self.fk_signature_set:
                        continue

                    # 创建候选
                    candidate = {
                        "source": source_table,
                        "target": target_table,
                        "source_columns": source_columns,
                        "target_columns": target_columns,
                        "candidate_type": f"composite_{combo_type}"
                    }
                    candidates.append(candidate)

        return candidates

    def _collect_source_combinations(self, table: dict) -> List[Dict[str, Any]]:
        """收集源表的复合键组合

        Returns:
            [{"columns": [...], "type": "physical|logical"}]
        """
        combinations = []
        table_profile = table.get("table_profile", {})

        # 1. 物理约束（PK/UK/Index）
        if "physical_constraints" in self.target_sources:
            physical = table_profile.get("physical_constraints", {})

            # 主键
            pk = physical.get("primary_key")
            if pk and pk.get("columns"):
                pk_cols = pk["columns"]
                if 2 <= len(pk_cols) <= self.max_columns:
                    combinations.append({"columns": pk_cols, "type": "physical"})

            # 唯一约束
            for uk in physical.get("unique_constraints", []):
                uk_cols = uk.get("columns", [])
                if 2 <= len(uk_cols) <= self.max_columns:
                    combinations.append({"columns": uk_cols, "type": "physical"})

            # 索引
            for idx in physical.get("indexes", []):
                idx_cols = idx.get("columns", [])
                if 2 <= len(idx_cols) <= self.max_columns:
                    combinations.append({"columns": idx_cols, "type": "physical"})

        # 2. 逻辑主键
        if "candidate_logical_keys" in self.target_sources:
            logical_keys = table_profile.get("logical_keys", {})
            for lk in logical_keys.get("candidate_primary_keys", []):
                lk_cols = lk.get("columns", [])
                lk_conf = lk.get("confidence_score", 0)
                if 2 <= len(lk_cols) <= self.max_columns and lk_conf >= self.logical_key_min_confidence:
                    combinations.append({"columns": lk_cols, "type": "logical"})

        return combinations

    def _find_target_columns(
            self,
            source_columns: List[str],
            source_table: dict,
            target_table: dict,
            combo_type: str
    ) -> List[str]:
        """在目标表中查找匹配的列组合

        Args:
            source_columns: 源列列表
            source_table: 源表元数据
            target_table: 目标表元数据
            combo_type: 组合类型（physical|logical）

        Returns:
            目标列列表（保持源列顺序），未找到返回None
        """
        target_profile = target_table.get("table_profile", {})

        # 1. 物理/逻辑约束匹配（使用名称相似度和类型兼容性）
        if combo_type in ["physical", "logical"]:
            target_combinations = self._collect_source_combinations(target_table)
            for target_combo in target_combinations:
                target_cols = target_combo["columns"]
                if len(target_cols) != len(source_columns):
                    continue

                # 检查名称相似度和类型兼容性
                if self._is_compatible_combination(
                        source_columns, target_cols,
                        source_table.get("column_profiles", {}),
                        target_table.get("column_profiles", {})
                ):
                    return target_cols

        # 2. 动态同名匹配（大小写不敏感 + 类型兼容）
        if "dynamic_same_name" in self.target_sources:
            matched = self._find_dynamic_same_name(source_columns, source_table, target_table)
            if matched:
                return matched

        return None

    def _is_compatible_combination(
            self,
            source_cols: List[str],
            target_cols: List[str],
            source_profiles: Dict[str, dict],
            target_profiles: Dict[str, dict]
    ) -> bool:
        """检查列组合是否兼容（名称相似度 + 类型兼容性）

        用于物理/逻辑约束匹配，需要同时满足：
        1. 平均名称相似度 >= min_name_similarity
        2. 所有列的类型兼容性 >= min_type_compatibility

        Args:
            source_cols: 源列列表
            target_cols: 目标列列表
            source_profiles: 源列画像
            target_profiles: 目标列画像

        Returns:
            True 如果兼容，False 否则
        """
        if len(source_cols) != len(target_cols):
            return False

        total_name_sim = 0
        for src_col, tgt_col in zip(source_cols, target_cols):
            # 1. 名称相似度检查
            name_sim = self._calculate_name_similarity(src_col, tgt_col)
            total_name_sim += name_sim

            # 2. 类型兼容性检查
            src_profile = source_profiles.get(src_col, {})
            tgt_profile = target_profiles.get(tgt_col, {})

            src_type = src_profile.get("data_type", "")
            tgt_type = tgt_profile.get("data_type", "")

            # 如果类型不兼容，直接返回 False
            if not self._is_type_compatible(src_type, tgt_type):
                return False

        # 检查平均名称相似度是否满足阈值
        avg_name_sim = total_name_sim / len(source_cols)
        return avg_name_sim >= self.min_name_similarity

    def _find_dynamic_same_name(
            self,
            source_columns: List[str],
            source_table: dict,
            target_table: dict
    ) -> List[str]:
        """动态同名匹配（大小写不敏感 + 类型兼容）

        Args:
            source_columns: 源列列表
            source_table: 源表元数据
            target_table: 目标表元数据

        Returns:
            目标列列表（保持源列顺序），未找到返回None
        """
        source_profiles = source_table.get("column_profiles", {})
        target_profiles = target_table.get("column_profiles", {})

        # 1. 构建大小写不敏感的映射（小写列名 -> 原始列名）
        target_column_map = {col_name.lower(): col_name for col_name in target_profiles.keys()}

        matched = []

        for src_col in source_columns:
            src_col_lower = src_col.lower()

            # 2. 大小写不敏感的同名检查
            if src_col_lower not in target_column_map:
                return None

            # 获取目标列的原始名称
            tgt_col = target_column_map[src_col_lower]

            # 3. 类型兼容性检查
            src_profile = source_profiles.get(src_col, {})
            tgt_profile = target_profiles.get(tgt_col, {})

            src_type = src_profile.get("data_type", "")
            tgt_type = tgt_profile.get("data_type", "")

            # 使用类型兼容性检查（复用 scorer 的逻辑）
            if not self._is_type_compatible(src_type, tgt_type):
                return None

            matched.append(tgt_col)

        return matched if len(matched) == len(source_columns) else None

    def _is_type_compatible(self, type1: str, type2: str) -> bool:
        """检查两个类型是否兼容

        复用 scorer 的类型兼容性逻辑，但返回布尔值（>= 0.5 视为兼容）

        Args:
            type1: 类型1
            type2: 类型2

        Returns:
            True 如果兼容，False 否则
        """
        # 标准化类型
        t1 = self._normalize_type(type1)
        t2 = self._normalize_type(type2)

        # 完全相同
        if t1 == t2:
            return True

        # 整数类型族
        int_types = {"integer", "int", "int4", "bigint", "int8", "smallint", "int2", "serial", "bigserial"}
        if t1 in int_types and t2 in int_types:
            return True

        # 字符串类型族
        str_types = {"varchar", "character varying", "char", "character", "text", "bpchar"}
        if t1 in str_types and t2 in str_types:
            return True  # 部分兼容（0.5）也视为兼容

        # 数值类型族
        num_types = {"numeric", "decimal", "real", "double precision", "float", "float4", "float8"}
        if t1 in num_types and t2 in num_types:
            return True  # 0.8 视为兼容

        # 整数与数值类型可以部分兼容
        if (t1 in int_types and t2 in num_types) or (t1 in num_types and t2 in int_types):
            return True  # 0.6 视为兼容

        # 日期/时间类型族
        date_types = {"date", "timestamp", "timestamp without time zone", "timestamp with time zone", "timestamptz"}
        if t1 in date_types and t2 in date_types:
            return True

        return False

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

    def _generate_single_column_candidates(self, tables: Dict[str, dict]) -> List[Dict[str, Any]]:
        """生成单列候选

        来源：
        1. active_search_same_name（重要约束列 -> 同名搜索）
        2. logical_key_matching（逻辑主键 -> identifier列）
        """
        candidates = []

        for source_name, source_table in tables.items():
            source_info = source_table.get("table_info", {})
            source_schema = source_info.get("schema_name")
            source_table_name = source_info.get("table_name")
            source_profiles = source_table.get("column_profiles", {})

            for col_name, col_profile in source_profiles.items():
                # 排除audit和metric角色
                semantic_role = col_profile.get("semantic_analysis", {}).get("semantic_role")
                if semantic_role in self.exclude_semantic_roles:
                    continue

                # 1. 主动搜索（重要约束列）
                if self.active_search_enabled and self._has_important_constraint(col_profile):
                    # 在所有目标表中搜索同名列（大小写不敏感）
                    for target_name, target_table in tables.items():
                        if target_name == source_name:
                            continue

                        target_info = target_table.get("table_info", {})
                        target_schema = target_info.get("schema_name")
                        target_table_name = target_info.get("table_name")
                        target_profiles = target_table.get("column_profiles", {})

                        # 构建大小写不敏感的映射（小写列名 -> 原始列名）
                        target_column_map = {col.lower(): col for col in target_profiles.keys()}
                        col_name_lower = col_name.lower()

                        if col_name_lower in target_column_map:
                            # 获取目标列的原始名称
                            target_col_name = target_column_map[col_name_lower]

                            # 检查FK去重
                            fk_sig = self._make_signature(
                                source_schema, source_table_name, [col_name],
                                target_schema, target_table_name, [target_col_name]
                            )
                            if fk_sig in self.fk_signature_set:
                                continue

                            candidate = {
                                "source": source_table,
                                "target": target_table,
                                "source_columns": [col_name],
                                "target_columns": [target_col_name],
                                "candidate_type": "single_active_search"
                            }
                            candidates.append(candidate)

                # 2. 逻辑主键匹配（源列是逻辑主键 -> 目标表符合约束的列）
                if self._is_logical_primary_key(col_name, source_table):
                    for target_name, target_table in tables.items():
                        if target_name == source_name:
                            continue

                        target_info = target_table.get("table_info", {})
                        target_schema = target_info.get("schema_name")
                        target_table_name = target_info.get("table_name")
                        target_profiles = target_table.get("column_profiles", {})

                        # 在目标表中查找满足约束条件的列
                        for target_col_name, target_col_profile in target_profiles.items():
                            # 1. 检查目标列是否满足约束条件（PK/UK/Index/逻辑主键）
                            if not self._is_qualified_target_column(target_col_name, target_col_profile, target_table):
                                continue

                            # 2. 检查语义角色（identifier优先，但不强制）
                            target_role = target_col_profile.get("semantic_analysis", {}).get("semantic_role")
                            if target_role != "identifier":
                                # 允许非identifier的列，但必须满足约束条件
                                pass

                            # 3. 检查名称相似度
                            name_sim = self._calculate_name_similarity(col_name, target_col_name)
                            if name_sim < 0.6:  # 最低相似度阈值
                                continue

                            # 4. 检查FK去重
                            fk_sig = self._make_signature(
                                source_schema, source_table_name, [col_name],
                                target_schema, target_table_name, [target_col_name]
                            )
                            if fk_sig in self.fk_signature_set:
                                continue

                            candidate = {
                                "source": source_table,
                                "target": target_table,
                                "source_columns": [col_name],
                                "target_columns": [target_col_name],
                                "candidate_type": "single_logical_key"
                            }
                            candidates.append(candidate)

        return candidates

    def _has_important_constraint(self, col_profile: dict) -> bool:
        """检查列是否有重要约束"""
        structure_flags = col_profile.get("structure_flags", {})

        # 检查单列主键
        if structure_flags.get("is_primary_key"):
            if "single_field_primary_key" in self.important_constraints:
                return True

        # 检查单列唯一约束
        if structure_flags.get("is_unique") or structure_flags.get("is_unique_constraint"):
            if "single_field_unique_constraint" in self.important_constraints:
                return True

        # 检查单列索引
        if structure_flags.get("is_indexed"):
            if "single_field_index" in self.important_constraints:
                return True

        return False

    def _is_logical_primary_key(self, col_name: str, table: dict) -> bool:
        """检查列是否为逻辑主键（单列）"""
        table_profile = table.get("table_profile", {})
        logical_keys = table_profile.get("logical_keys", {})

        for lk in logical_keys.get("candidate_primary_keys", []):
            lk_cols = lk.get("columns", [])
            lk_conf = lk.get("confidence_score", 0)

            # 单列逻辑主键且置信度足够
            if len(lk_cols) == 1 and lk_cols[0] == col_name and lk_conf >= self.logical_key_min_confidence:
                return True

        return False

    def _is_qualified_target_column(self, col_name: str, col_profile: dict, table: dict) -> bool:
        """检查目标列是否满足单列候选的约束条件

        按照文档要求，目标列必须满足以下条件之一：
        1. structure_flags.is_primary_key = true （物理主键）
        2. structure_flags.is_unique = true （唯一约束）
        3. structure_flags.is_indexed = true （有索引）
        4. 在 candidate_primary_keys 的任一候选组合中（单列且 confidence_score >= 0.8）

        Args:
            col_name: 列名
            col_profile: 列画像
            table: 表元数据

        Returns:
            True 如果满足条件，False 否则
        """
        structure_flags = col_profile.get("structure_flags", {})

        # 1. 检查物理主键
        if structure_flags.get("is_primary_key"):
            return True

        # 2. 检查唯一约束
        if structure_flags.get("is_unique") or structure_flags.get("is_unique_constraint"):
            return True

        # 3. 检查索引
        if structure_flags.get("is_indexed"):
            return True

        # 4. 检查是否为单列逻辑主键（confidence >= 0.8）
        if self._is_logical_primary_key(col_name, table):
            return True

        return False

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """计算列名相似度（0-1，大小写不敏感）"""
        if name1.lower() == name2.lower():
            return 1.0

        # 使用SequenceMatcher
        return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()

    def _make_signature(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str]
    ) -> str:
        """生成FK签名（用于去重）"""
        src_cols = sorted(source_columns)
        tgt_cols = sorted(target_columns)
        return (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
        )
