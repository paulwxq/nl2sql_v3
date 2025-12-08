"""候选关系生成器

负责生成候选关系（复合键优先，单列其次），排除已存在的外键。
"""

from typing import Dict, List, Set, Any, Optional, Tuple
from difflib import SequenceMatcher
from itertools import permutations

from src.metaweave.core.relationships.name_similarity import NameSimilarityService
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.candidate_generator")


class CandidateGenerator:
    """候选关系生成器

    生成顺序：
    1. 复合键候选（物理约束、逻辑键、动态同名）
    2. 单列候选（主动搜索、逻辑键匹配）
    """

    def __init__(
            self,
            config: dict,
            fk_signature_set: Set[str],
            name_similarity_service: Optional[NameSimilarityService] = None,
    ):
        """初始化候选生成器

        Args:
            config: relationships配置（要求完整配置，不设默认值以暴露配置问题）
            fk_signature_set: 外键签名集合（用于去重）
        """
        self.config = config
        self.fk_signature_set = fk_signature_set
        self.name_similarity_service = name_similarity_service

        # 单列配置（single_column 节点）
        single_config = config["single_column"]
        self.important_constraints = set(single_config["important_constraints"])
        self.exclude_semantic_roles = set(single_config["exclude_semantic_roles"])
        self.single_logical_key_min_confidence = single_config["logical_key_min_confidence"]
        self.single_min_type_compatibility = single_config["min_type_compatibility"]
        self.single_name_similarity_important_target = single_config["name_similarity_important_target"]
        self.name_similarity_normal_target = single_config["name_similarity_normal_target"]

        # 复合键配置（composite 节点）
        composite_config = config["composite"]
        self.max_columns = composite_config["max_columns"]
        # 防御性处理：如果 target_sources 为 None 或缺失，默认为空列表
        self.target_sources = composite_config.get("target_sources") or []
        self.composite_min_type_compatibility = composite_config["min_type_compatibility"]
        self.composite_logical_key_min_confidence = composite_config["logical_key_min_confidence"]
        self.composite_name_similarity_important_target = composite_config["name_similarity_important_target"]

        # 复合键排除的语义角色（从配置读取，默认只排除 metric）
        # ⚠️ 关键：这个配置必须与 LogicalKeyDetector 中的 composite_exclude_roles 来自相同的 YAML 配置
        # 默认值保守策略：只排除明确不适合的 metric，description 等其他角色由用户根据实际情况选择
        self.composite_exclude_semantic_roles = set(
            composite_config.get("exclude_semantic_roles", ["metric"])
        )

        logger.info(f"候选生成器已初始化:")
        logger.info(f"  单列配置: important_target_sim={self.single_name_similarity_important_target}, "
                    f"normal_target_sim={self.name_similarity_normal_target}, "
                    f"type_compat>={self.single_min_type_compatibility}")
        logger.info(f"  复合键配置: max_columns={self.max_columns}, "
                    f"important_target_sim={self.composite_name_similarity_important_target}, "
                    f"type_compat>={self.composite_min_type_compatibility}")
        logger.info(f"  复合键排除角色（从配置）: {self.composite_exclude_semantic_roles}")

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

            # 收集源表的复合键组合（源表永不包含索引）
            source_combinations = self._collect_source_combinations(source_table, include_indexes=False)

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

    def _collect_source_combinations(
            self,
            table: dict,
            include_indexes: bool = False
    ) -> List[Dict[str, Any]]:
        """收集表的复合键组合

        Args:
            table: 表元数据
            include_indexes: 是否包含索引（默认False，仅对目标表使用）

        Returns:
            [{"columns": [...], "type": "physical|logical"}]
        """
        combinations = []
        table_profile = table.get("table_profile", {})
        physical = table_profile.get("physical_constraints", {})

        # 1. 主键（总是收集）
        pk = physical.get("primary_key")
        if pk and pk.get("columns"):
            pk_cols = pk["columns"]
            if 2 <= len(pk_cols) <= self.max_columns:
                combinations.append({"columns": pk_cols, "type": "physical"})

        # 2. 唯一约束（总是收集）
        for uk in physical.get("unique_constraints", []):
            uk_cols = uk.get("columns", [])
            if 2 <= len(uk_cols) <= self.max_columns:
                combinations.append({"columns": uk_cols, "type": "physical"})

        # 3. 索引（仅当 include_indexes=True 时收集）
        if include_indexes:
            for idx in physical.get("indexes", []):
                idx_cols = idx.get("columns", [])
                if 2 <= len(idx_cols) <= self.max_columns:
                    combinations.append({"columns": idx_cols, "type": "physical"})

        # 4. 逻辑主键（总是收集）
        logical_keys = table_profile.get("logical_keys", {})
        table_name = table.get("table_info", {}).get("table_name", "unknown")
        logger.debug(f"[_collect_source_combinations] 表 {table_name} 的逻辑主键候选数: {len(logical_keys.get('candidate_primary_keys', []))}")
        
        for lk in logical_keys.get("candidate_primary_keys", []):
            lk_cols = lk.get("columns", [])
            lk_conf = lk.get("confidence_score", 0)
            logger.debug(f"[_collect_source_combinations] 检查逻辑主键: {table_name}{lk_cols}, conf={lk_conf}, len={len(lk_cols)}")
            
            if 2 <= len(lk_cols) <= self.max_columns and lk_conf >= self.composite_logical_key_min_confidence:
                combinations.append({"columns": lk_cols, "type": "logical"})
                logger.debug(f"[_collect_source_combinations] ✓ 收集逻辑主键: {table_name}{lk_cols}")
            else:
                logger.debug(f"[_collect_source_combinations] ✗ 跳过逻辑主键: {table_name}{lk_cols} (len={len(lk_cols)}, conf={lk_conf}, max={self.max_columns}, min_conf={self.composite_logical_key_min_confidence})")

        return combinations

    def _find_target_columns(
            self,
            source_columns: List[str],
            source_table: dict,
            target_table: dict,
            combo_type: str
    ) -> Optional[List[str]]:
        """在目标表中查找匹配的列组合（两阶段策略）

        Stage 1: 特权模式（Privilege Mode）
            - 当源表是 PK/UK/逻辑键时，检查目标表是否有相同性质的约束
            - 使用穷举排列算法 + 较低的名称相似度阈值
            - 如果匹配成功，立即返回（短路）

        Stage 2: 动态同名匹配（Dynamic Same-Name）
            - 总是执行，不依赖 Stage 1 的结果
            - 大小写不敏感的列名匹配 + 类型兼容性检查
            - 如果匹配成功，返回

        Args:
            source_columns: 源列列表
            source_table: 源表元数据
            target_table: 目标表元数据
            combo_type: 组合类型（physical|logical）

        Returns:
            目标列列表（顺序与源列对应），未找到返回None
        """
        source_profiles = source_table.get("column_profiles", {})
        target_profiles = target_table.get("column_profiles", {})

        # ============================================================
        # Stage 1: 特权模式（Privilege Mode）
        # ============================================================
        source_table_name = source_table.get("table_info", {}).get("table_name", "unknown")
        target_table_name = target_table.get("table_info", {}).get("table_name", "unknown")
        
        if combo_type in ["physical", "logical"]:
            # 收集目标表的约束组合（根据配置决定是否包含索引）
            include_target_indexes = "composite_indexes" in self.target_sources
            target_combinations = self._collect_source_combinations(
                target_table,
                include_indexes=include_target_indexes
            )

            logger.debug(
                "[find_target_columns] %s%s → %s: Stage 1 开始（combo_type=%s, 目标约束数=%d）",
                source_table_name, source_columns, target_table_name, combo_type, len(target_combinations)
            )

            # 遍历目标表的所有约束组合
            for target_combo in target_combinations:
                target_cols = target_combo["columns"]
                target_combo_type = target_combo["type"]

                logger.debug(
                    "[find_target_columns] Stage 1: 尝试匹配目标约束 %s%s (type=%s)",
                    target_table_name, target_cols, target_combo_type
                )

                # 长度必须相等
                if len(target_cols) != len(source_columns):
                    logger.debug(
                        "[find_target_columns] Stage 1: 跳过（长度不等: %d != %d）",
                        len(target_cols), len(source_columns)
                    )
                    continue

                # 使用穷举排列算法匹配
                matched = self._match_columns_as_set(
                    source_columns=source_columns,
                    target_columns=target_cols,
                    source_profiles=source_profiles,
                    target_profiles=target_profiles,
                    min_name_similarity=self.composite_name_similarity_important_target,
                    min_type_compatibility=self.composite_min_type_compatibility,
                    source_is_physical=(combo_type == "physical"),  # 源表物理约束（PK/UK）
                    target_is_physical=(target_combo["type"] == "physical")  # 目标表物理约束（PK/UK/索引）
                )

                if matched:
                    logger.debug(
                        "[find_target_columns] Stage 1 成功: %s -> %s",
                        source_columns, matched
                    )
                    return matched

            logger.debug(
                "[find_target_columns] %s%s → %s: Stage 1 未找到匹配",
                source_table_name, source_columns, target_table_name
            )

        # ============================================================
        # Stage 2: 动态同名匹配（Dynamic Same-Name）
        # ============================================================
        # ⚠️ 修改：扩展到物理约束（PK/UK）+ 逻辑主键
        # 原因：逻辑主键也需要动态同名匹配来发现维度表→事实表的外键关系
        if combo_type in ["physical", "logical"]:
            logger.debug(
                "[find_target_columns] %s%s → %s: Stage 2 开始（combo_type=%s）",
                source_table_name, source_columns, target_table_name, combo_type
            )

            matched = self._find_dynamic_same_name(
                source_columns,
                source_table,
                target_table,
                is_physical=True  # 统一不过滤目标列，支持匹配外键
            )

            if matched:
                logger.debug(
                    "[find_target_columns] %s%s → %s: Stage 2 成功 %s",
                    source_table_name, source_columns, target_table_name, matched
                )
                return matched

            logger.debug(
                "[find_target_columns] %s%s → %s: Stage 2 未找到匹配",
                source_table_name, source_columns, target_table_name
            )
        else:
            logger.debug(
                "[find_target_columns] %s%s → %s: 跳过 Stage 2（combo_type=%s）",
                source_table_name, source_columns, target_table_name, combo_type
            )

        return None

    def _match_columns_as_set(
            self,
            source_columns: List[str],
            target_columns: List[str],
            source_profiles: Dict[str, dict],
            target_profiles: Dict[str, dict],
            min_name_similarity: float,
            min_type_compatibility: float,
            source_is_physical: bool = False,  # 新增：源表是否为物理约束（仅 PK/UK）
            target_is_physical: bool = False   # 新增：目标表是否为物理约束（PK/UK/索引）
    ) -> Optional[List[str]]:
        """穷举排列算法：在目标列中找到最佳匹配

        使用O(n! × n)的穷举排列算法，尝试所有可能的排列组合，找到综合得分最高的匹配。
        适用于复合键（2-3列），穷举成本可接受（最多6种排列）。

        Args:
            source_columns: 源列列表（有序）
            target_columns: 目标列候选池（无序）
            source_profiles: 源列画像
            target_profiles: 目标列画像
            min_name_similarity: 最低名称相似度阈值
            min_type_compatibility: 最低类型兼容性阈值
            source_is_physical: 源表是否为物理约束（仅 PK/UK，不含索引）
            target_is_physical: 目标表是否为物理约束（PK/UK/索引，广义物理约束）

        Returns:
            最佳匹配的目标列列表（顺序与源列对应），如果没有满足阈值的匹配则返回None
        """
        # === 源表过滤：完全不过滤（尊重所有约束） ===
        # 核心原则：源列（物理约束 + 逻辑主键）在候选生成阶段完全不过滤
        # - 物理约束（PK/UK）：DBA 明确定义，完全尊重
        # - 逻辑主键：在元数据生成阶段已按 composite_exclude_roles 过滤，此处不再二次过滤
        filtered_source_columns = source_columns  # ✅ 不过滤，完全尊重约束定义

        logger.debug(
            "[match_columns_as_set] 源表列不过滤（source_is_physical=%s），直接使用: %s",
            source_is_physical, source_columns
        )

        # === 目标表过滤：区分物理约束和逻辑约束 ===
        filtered_target_columns = []
        for tgt_col in target_columns:
            tgt_profile = target_profiles.get(tgt_col, {})
            tgt_semantic_role = tgt_profile.get("semantic_analysis", {}).get("semantic_role")

            # 物理约束：完全不过滤（完全尊重 DBA 定义，包括 metric）
            # ⚠️ 注意：目标表物理约束包括 PK/UK/索引（广义物理约束）
            if target_is_physical:
                logger.debug(
                    "[match_columns_as_set] 目标列 %s (物理约束: PK/UK/索引) 不过滤，语义角色=%s",
                    tgt_col, tgt_semantic_role
                )
                # ✅ 物理约束不进行语义角色过滤，直接通过
                pass
            # 逻辑约束：按配置排除
            else:
                if tgt_semantic_role in self.composite_exclude_semantic_roles:
                    logger.debug(
                        "[match_columns_as_set] 目标列 %s (逻辑约束) 语义角色=%s 被排除",
                        tgt_col, tgt_semantic_role
                    )
                    continue  # 跳过该列

            filtered_target_columns.append(tgt_col)

        # 验证：确保没有把所有列都过滤掉
        if not filtered_target_columns:
            logger.debug("[match_columns_as_set] 目标列全部被过滤，匹配失败")
            return None
        
        n = len(filtered_source_columns)
        m = len(filtered_target_columns)

        # 基本检查：目标列数量必须 >= 源列数量
        if m < n:
            return None

        # 特殊情况：如果目标列数量正好等于源列数量，穷举所有排列
        if m == n:
            candidate_pool = filtered_target_columns
        else:
            # 如果目标列数量 > 源列数量，需要先从目标列中选出n个列的所有组合
            # 这里为了简化，只考虑m==n的情况
            # 如果m>n，需要额外的组合逻辑（从m中选n个的C(m,n)种组合）
            # 但根据设计文档，这种情况较少见，暂不实现
            logger.debug(
                "[match_columns_as_set] 目标列数量(%d) > 源列数量(%d)，跳过匹配",
                m, n
            )
            return None

        best_match = None
        best_score = -1.0

        # 穷举所有排列
        for perm in permutations(candidate_pool):
            # perm 是一个元组，表示目标列的一种排列顺序
            perm_list = list(perm)

            # 逐对检查，任一配对低于阈值立即淘汰该排列
            total_name_sim = 0.0
            total_type_compat = 0.0
            is_valid = True  # 标记该排列是否有效

            for src_col, tgt_col in zip(filtered_source_columns, perm_list):
                # 1. 名称相似度
                name_sim = self._calculate_name_similarity(src_col, tgt_col)

                # 2. 类型兼容性
                src_profile = source_profiles.get(src_col, {})
                tgt_profile = target_profiles.get(tgt_col, {})

                src_type = src_profile.get("data_type", "")
                tgt_type = tgt_profile.get("data_type", "")

                type_compat = self._get_type_compatibility_score(src_type, tgt_type)

                # 🔴 关键修改：任一配对低于阈值，立即淘汰该排列
                if name_sim < min_name_similarity or type_compat < min_type_compatibility:
                    is_valid = False
                    logger.debug(
                        "[match_columns_as_set] 排列淘汰: %s->%s (name_sim=%.2f < %.2f 或 type_compat=%.2f < %.2f)",
                        src_col, tgt_col, name_sim, min_name_similarity,
                        type_compat, min_type_compatibility
                    )
                    break  # 立即跳出，不再检查该排列的其他配对

                total_name_sim += name_sim
                total_type_compat += type_compat

            # 只有所有配对都满足阈值，才计算综合得分
            if is_valid:
                avg_name_sim = total_name_sim / n
                avg_type_compat = total_type_compat / n
                # 计算综合得分（简单加权：名称50% + 类型50%）
                composite_score = 0.5 * avg_name_sim + 0.5 * avg_type_compat

                # 更新最佳匹配
                if composite_score > best_score:
                    best_score = composite_score
                    best_match = perm_list

        if best_match:
            logger.debug(
                "[match_columns_as_set] 找到最佳匹配: %s -> %s, score=%.3f",
                filtered_source_columns, best_match, best_score
            )
        else:
            logger.debug(
                "[match_columns_as_set] 未找到满足阈值的匹配: %s",
                filtered_source_columns
            )

        return best_match

    def _find_dynamic_same_name(
            self,
            source_columns: List[str],
            source_table: dict,
            target_table: dict,
            is_physical: bool = False  # 新增参数：是否为源表物理约束（PK/UK）
    ) -> Optional[List[str]]:
        """动态同名匹配（大小写不敏感 + 类型兼容）

        Args:
            source_columns: 源列列表
            source_table: 源表元数据
            target_table: 目标表元数据
            is_physical: 是否为源表物理约束（PK/UK）
                        - True：完全不过滤源表和目标表的列
                        - False：按配置过滤（但实际上不会调用，因为只对物理约束执行）

        Returns:
            目标列列表（保持源列顺序），未找到返回None

        ⚠️ 注意：此函数只在源表为物理约束（PK/UK）时调用
        """
        source_profiles = source_table.get("column_profiles", {})
        target_profiles = target_table.get("column_profiles", {})

        # === 源表：完全不过滤（移除原有的过滤代码） ===
        logger.debug(
            "[_find_dynamic_same_name] 源表物理约束（PK/UK）列不过滤: %s",
            source_columns
        )

        # === 目标表：源表为物理约束时，目标表完全不过滤 ===
        # ⚠️ 前提：此时源表必为物理约束（PK/UK），is_physical=True
        target_column_map = {}
        for col_name, col_profile in target_profiles.items():
            semantic_role = col_profile.get("semantic_analysis", {}).get("semantic_role")

            # 源表为物理约束：目标表任何列都可以作为候选，完全不过滤语义角色
            if is_physical:
                target_column_map[col_name.lower()] = col_name
                logger.debug(
                    "[_find_dynamic_same_name] 目标列 %s 不过滤（源为物理约束），语义角色=%s",
                    col_name, semantic_role
                )
            # 非物理约束：按配置过滤（实际上不会执行到这里）
            else:
                if semantic_role in self.composite_exclude_semantic_roles:
                    logger.debug(
                        "[_find_dynamic_same_name] 跳过目标列 %s（语义角色=%s）",
                        col_name, semantic_role
                    )
                    continue
                target_column_map[col_name.lower()] = col_name

        matched = []

        for src_col in source_columns:
            src_col_lower = src_col.lower()
            src_profile = source_profiles.get(src_col, {})

            # 大小写不敏感的同名检查
            if src_col_lower not in target_column_map:
                return None

            # 获取目标列的原始名称
            tgt_col = target_column_map[src_col_lower]
            tgt_profile = target_profiles.get(tgt_col, {})

            # 3. 类型兼容性检查
            src_type = src_profile.get("data_type", "")
            tgt_type = tgt_profile.get("data_type", "")

            # 使用类型兼容性评分（与 scorer 一致）
            type_score = self._get_type_compatibility_score(src_type, tgt_type)
            if type_score < self.composite_min_type_compatibility:
                logger.debug(
                    "[composite_dynamic_same_name] 类型兼容性不足: %s vs %s, score=%.2f < %.2f",
                    src_col, tgt_col, type_score, self.composite_min_type_compatibility
                )
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

    def _get_type_compatibility_score(self, type1: str, type2: str) -> float:
        """计算PostgreSQL两个类型的JOIN兼容性分数
        
        评分标准：
        - 1.0: 类型完全相同
        - 0.9: 同类型族，完全互换，零损失（如 INTEGER ↔ BIGINT, INTEGER ↔ NUMERIC）
        - 0.85: 同大类，高度兼容，实际使用无影响（如 VARCHAR ↔ TEXT）
        - 0.8: 同大族，兼容但有细微差异（如 CHAR参与, NUMERIC不同精度, TIMESTAMP时区转换）
        - 0.6: 可以JOIN但有精度问题（如 INTEGER ↔ FLOAT）
        - 0.5: 可以JOIN但精度损失明显（如 DATE ↔ TIMESTAMP, NUMERIC ↔ FLOAT）
        - 0.0: JOIN会报错，完全不兼容
        
        Args:
            type1: PostgreSQL类型1
            type2: PostgreSQL类型2
            
        Returns:
            float: 兼容性分数 [0.0, 1.0]
        """
        # 标准化类型
        t1 = self._normalize_type(type1)
        t2 = self._normalize_type(type2)
        
        # 1.0 - 完全相同
        if t1 == t2:
            return 1.0
        
        # ===== 整数类型族 =====
        int_small = {"smallint", "int2", "smallserial"}
        int_standard = {"integer", "int", "int4", "serial"}
        int_big = {"bigint", "int8", "bigserial"}
        int_all = int_small | int_standard | int_big
        
        # 0.9 - 整数族内部，完全互换
        if t1 in int_all and t2 in int_all:
            return 0.9
        
        # ===== 字符串类型族 =====
        # VARCHAR/TEXT 组（无padding问题）
        str_varchar = {"varchar", "character varying", "text"}
        # CHAR 组（有padding陷阱）
        str_char = {"char", "character", "bpchar"}
        str_all = str_varchar | str_char
        
        # 0.85 - VARCHAR/TEXT之间（安全）
        if t1 in str_varchar and t2 in str_varchar:
            return 0.85
        
        # 0.8 - CHAR参与时（有padding陷阱）
        if t1 in str_all and t2 in str_all:
            return 0.8
        
        # ===== 精确数值类型族 =====
        numeric_types = {"numeric", "decimal"}
        
        # 0.8 - NUMERIC/DECIMAL之间（精度可能不同）
        if t1 in numeric_types and t2 in numeric_types:
            return 0.8
        
        # ===== 浮点数值类型族 =====
        float_types = {"real", "float4", "double precision", "float8", "float"}
        
        # 0.8 - 浮点类型之间
        if t1 in float_types and t2 in float_types:
            return 0.8
        
        # ===== 整数与数值类型交叉 =====
        # 0.9 - 整数与NUMERIC（整数可以无损转为NUMERIC）
        if (t1 in int_all and t2 in numeric_types) or (t1 in numeric_types and t2 in int_all):
            return 0.9
        
        # 0.6 - 整数与浮点（有精度损失）
        if (t1 in int_all and t2 in float_types) or (t1 in float_types and t2 in int_all):
            return 0.6
        
        # 0.5 - NUMERIC与浮点（精确数值vs浮点，精度损失明显）
        if (t1 in numeric_types and t2 in float_types) or (t1 in float_types and t2 in numeric_types):
            return 0.5
        
        # ===== 日期时间类型族 =====
        date_types = {"date"}
        
        timestamp_without_tz = {"timestamp", "timestamp without time zone"}
        
        timestamp_with_tz = {"timestamp with time zone", "timestamptz"}
        
        timestamp_all = timestamp_without_tz | timestamp_with_tz
        
        time_types = {"time", "time without time zone", "time with time zone", "timetz"}
        
        # 1.0 - DATE 与 DATE
        if t1 in date_types and t2 in date_types:
            return 1.0
        
        # 0.9 - TIMESTAMP系列内部（同义词）
        if t1 in timestamp_without_tz and t2 in timestamp_without_tz:
            return 0.9
        
        if t1 in timestamp_with_tz and t2 in timestamp_with_tz:
            return 0.9
        
        # 0.8 - TIMESTAMP WITH TZ vs WITHOUT TZ（有时区转换）
        if (t1 in timestamp_without_tz and t2 in timestamp_with_tz) or \
           (t1 in timestamp_with_tz and t2 in timestamp_without_tz):
            return 0.8
        
        # 0.5 - DATE vs TIMESTAMP（精度损失明显：DATE只能匹配午夜00:00:00）
        if (t1 in date_types and t2 in timestamp_all) or \
           (t1 in timestamp_all and t2 in date_types):
            return 0.5
        
        # 0.85 - TIME系列内部
        if t1 in time_types and t2 in time_types:
            return 0.85
        
        # 0.0 - TIME vs DATE/TIMESTAMP（不能JOIN）
        if (t1 in time_types and (t2 in date_types or t2 in timestamp_all)) or \
           ((t1 in date_types or t1 in timestamp_all) and t2 in time_types):
            return 0.0
        
        # ===== 布尔类型 =====
        bool_types = {"boolean", "bool"}
        
        if t1 in bool_types and t2 in bool_types:
            return 0.9  # 同义词
        
        # 0.6 - BOOLEAN vs INTEGER（可JOIN但语义奇怪）
        if (t1 in bool_types and t2 in int_all) or (t1 in int_all and t2 in bool_types):
            return 0.6
        
        # ===== UUID类型 =====
        uuid_types = {"uuid"}
        
        if t1 in uuid_types and t2 in uuid_types:
            return 1.0
        
        # ===== 跨大类：全部不兼容 =====
        # 数值类型 vs 字符串类型 → 0.0
        all_numeric = int_all | numeric_types | float_types
        if (t1 in all_numeric and t2 in str_all) or (t1 in str_all and t2 in all_numeric):
            return 0.0
        
        # 时间类型 vs 字符串类型 → 0.0
        all_time = date_types | timestamp_all | time_types
        if (t1 in all_time and t2 in str_all) or (t1 in str_all and t2 in all_time):
            return 0.0
        
        # UUID vs 其他类型 → 0.0
        if (t1 in uuid_types and t2 not in uuid_types) or (t1 not in uuid_types and t2 in uuid_types):
            return 0.0
        
        # 布尔 vs 其他非数值类型 → 0.0
        if (t1 in bool_types and t2 not in (bool_types | int_all)) or \
           (t1 not in (bool_types | int_all) and t2 in bool_types):
            return 0.0
        
        # ===== 其他未知类型组合 =====
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

    def _generate_single_column_candidates(self, tables: Dict[str, dict]) -> List[Dict[str, Any]]:
        """生成单列候选
        
        统一逻辑：
        1. 源列必须是"重要列"（有定义约束 或 是逻辑主键）
        2. 遍历所有目标列，根据目标列是否"关键字段"动态调整名称相似度阈值
        3. 根据源列属性标记候选类型
        """
        candidates = []

        for source_name, source_table in tables.items():
            source_info = source_table.get("table_info", {})
            source_schema = source_info.get("schema_name")
            source_table_name = source_info.get("table_name")
            source_full_name = f"{source_schema}.{source_table_name}"
            logger.debug("[single_column_candidate] 处理源表: %s", source_full_name)
            source_profiles = source_table.get("column_profiles", {})

            for col_name, col_profile in source_profiles.items():
                # === 核心修改：先检查约束类型，不再提前过滤语义角色 ===
                # 1. 先检查源列是否"重要"（有定义约束 或 是逻辑主键）
                has_defined_constraint = self._has_defined_constraint(col_profile)
                is_logical_pk = self._is_logical_primary_key(col_name, source_table)

                # 源列必须至少满足一个条件
                if not (has_defined_constraint or is_logical_pk):
                    continue

                # 2. 源列完全不过滤（移除语义角色过滤逻辑）
                semantic_role = col_profile.get("semantic_analysis", {}).get("semantic_role")

                # ⚠️ 核心原则：源列完全不过滤
                # - 物理约束（PK/UK）：DBA 明确定义，完全尊重
                # - 逻辑主键：在元数据生成阶段已按 single_column_exclude_roles 过滤，此处不再二次过滤

                logger.debug(
                    "[single_column_candidate] 源列不过滤: %s.%s (physical=%s, logical=%s, role=%s)",
                    source_full_name, col_name, has_defined_constraint, is_logical_pk, semantic_role
                )
                
                # 3. 遍历所有目标表和目标列
                for target_name, target_table in tables.items():
                    if target_name == source_name:
                        continue

                    target_info = target_table.get("table_info", {})
                    target_schema = target_info.get("schema_name")
                    target_table_name = target_info.get("table_name")
                    target_profiles = target_table.get("column_profiles", {})

                    for target_col_name, target_col_profile in target_profiles.items():
                        # (a) 语义角色过滤：区分物理约束和逻辑约束
                        target_role = target_col_profile.get("semantic_analysis", {}).get("semantic_role")
                        target_structure_flags = target_col_profile.get("structure_flags", {})

                        # 检查目标列是否有物理约束（广义：PK/UK/索引）
                        # ⚠️ 注意：目标列物理约束包括索引（与源列不同）
                        target_has_physical = (
                            target_structure_flags.get("is_primary_key") or          # ✅ PK
                            target_structure_flags.get("is_unique") or               # ✅ UK
                            target_structure_flags.get("is_unique_constraint") or    # ✅ UK（另一种标记）
                            target_structure_flags.get("is_indexed")                 # ✅ 索引（目标表特有）
                        )

                        # 物理约束：完全不过滤（完全尊重 DBA 定义）
                        if target_has_physical:
                            logger.debug(
                                "[single_column_candidate] 目标列为物理约束（PK/UK/索引），不过滤: %s.%s (role=%s, flags=%s)",
                                f"{target_schema}.{target_table_name}", target_col_name, target_role,
                                {k: v for k, v in target_structure_flags.items() if v}  # 只显示 True 的标志
                            )
                            # ✅ 物理约束不过滤，直接通过
                            pass
                        # 非物理约束：按配置过滤
                        else:
                            if target_role in self.exclude_semantic_roles:
                                logger.debug(
                                    "[single_column_candidate] 跳过目标列 %s.%s，语义角色=%s 被排除",
                                    f"{target_schema}.{target_table_name}", target_col_name, target_role
                                )
                                continue
                            logger.debug(
                                "[single_column_candidate] 目标列通过过滤: %s.%s (role=%s)",
                                f"{target_schema}.{target_table_name}", target_col_name, target_role
                            )

                        # (b) 类型兼容性过滤
                        src_type = col_profile.get("data_type", "")
                        tgt_type = target_col_profile.get("data_type", "")
                        type_compat = self._get_type_compatibility_score(src_type, tgt_type)

                        if type_compat < self.single_min_type_compatibility:
                            logger.debug(
                                "[single_column_candidate] 跳过目标列 %s.%s -> %s.%s，类型兼容性不足: %.2f < %.2f",
                                source_full_name,
                                col_name,
                                f"{target_schema}.{target_table_name}",
                                target_col_name,
                                type_compat,
                                self.single_min_type_compatibility,
                            )
                            continue
                        
                        # (c) 判断目标列是否"关键字段"
                        is_important_target = self._is_qualified_target_column(
                            target_col_name, target_col_profile, target_table
                        )
                        
                        # (d) 名称相似度 + 动态阈值
                        name_sim = self._calculate_name_similarity(col_name, target_col_name)

                        if is_important_target:
                            threshold = self.single_name_similarity_important_target
                        else:
                            threshold = self.name_similarity_normal_target
                        
                        if name_sim < threshold:
                            logger.debug(
                                "[single_column_candidate] 跳过目标列 %s.%s -> %s.%s，名称相似度不足: %.2f < %.2f (important_target=%s)",
                                source_full_name,
                                col_name,
                                f"{target_schema}.{target_table_name}",
                                target_col_name,
                                name_sim,
                                threshold,
                                is_important_target,
                            )
                            continue
                        
                        # (e) FK 去重
                        fk_sig = self._make_signature(
                            source_schema, source_table_name, [col_name],
                            target_schema, target_table_name, [target_col_name]
                        )
                        if fk_sig in self.fk_signature_set:
                            logger.debug(
                                "[single_column_candidate] 跳过已存在的FK: %s.%s -> %s.%s",
                                source_full_name,
                                col_name,
                                f"{target_schema}.{target_table_name}",
                                target_col_name,
                            )
                            continue
                        
                        # (f) 决定 candidate_type
                        if has_defined_constraint and is_logical_pk:
                            candidate_type = "single_defined_constraint_and_logical_pk"
                        elif has_defined_constraint and not is_logical_pk:
                            candidate_type = "single_defined_constraint"
                        elif is_logical_pk and not has_defined_constraint:
                            candidate_type = "single_logical_key"
                        else:
                            # 理论上不会到这里（外层已经确保至少满足一个条件）
                            logger.warning(
                                "[single_column_candidate] 意外情况: %s.%s 既无定义约束也非逻辑主键，跳过",
                                source_full_name,
                                col_name,
                            )
                            continue
                        
                        # (g) 构造并追加候选
                        candidate = {
                            "source": source_table,
                            "target": target_table,
                            "source_columns": [col_name],
                            "target_columns": [target_col_name],
                            "candidate_type": candidate_type,
                        }
                        candidates.append(candidate)
                        logger.debug(
                            "[single_column_candidate] 候选生成: %s.%s -> %s.%s (type=%s, name_sim=%.2f, type_compat=%.2f)",
                            source_full_name,
                            col_name,
                            f"{target_schema}.{target_table_name}",
                            target_col_name,
                            candidate_type,
                            name_sim,
                            type_compat,
                        )

        return candidates

    def _has_defined_constraint(self, col_profile: dict) -> bool:
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
        # if structure_flags.get("is_indexed"):
        #     if "single_field_index" in self.important_constraints:
        #         return True

        return False

    def _is_logical_primary_key(self, col_name: str, table: dict) -> bool:
        """检查列是否为逻辑主键（单列）"""
        table_profile = table.get("table_profile", {})
        logical_keys = table_profile.get("logical_keys", {})

        for lk in logical_keys.get("candidate_primary_keys", []):
            lk_cols = lk.get("columns", [])
            lk_conf = lk.get("confidence_score", 0)

            # 单列逻辑主键且置信度足够
            if len(lk_cols) == 1 and lk_cols[0] == col_name and lk_conf >= self.single_logical_key_min_confidence:
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
        if self.name_similarity_service:
            return self.name_similarity_service.compare_pair(name1, name2)
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
