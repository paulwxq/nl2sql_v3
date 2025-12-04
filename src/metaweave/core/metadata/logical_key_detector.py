"""逻辑主键检测器

对于缺少主键定义的表，通过样本数据分析识别潜在的逻辑主键。
"""

import logging
from typing import List, Optional
from itertools import combinations
import pandas as pd

from src.metaweave.core.metadata.models import TableMetadata, LogicalKey
from src.metaweave.utils.data_utils import (
    calculate_uniqueness,
    calculate_null_rate,
    is_potential_key_column
)

logger = logging.getLogger("metaweave.logical_key_detector")


class LogicalKeyDetector:
    """逻辑主键检测器
    
    通过分析样本数据识别潜在的逻辑主键。
    """
    
    def __init__(self, config: dict):
        """初始化逻辑主键检测器
        
        Args:
            config: 配置字典
                - min_confidence: 最小置信度阈值
                - max_combinations: 最多考虑的字段组合数
                - name_patterns: 主键字段名模式列表
                - single_column_exclude_roles: 单列检测时排除的语义角色列表
        """
        self.min_confidence = config.get("min_confidence", 0.7)
        self.max_combinations = config.get("max_combinations", 3)
        
        # 确保 name_patterns 是字符串列表
        patterns = config.get("name_patterns", ["id", "code", "key", "no", "number"])
        self.name_patterns = [str(p) for p in patterns] if patterns else ["id", "code", "key", "no", "number"]
        
        # 单列逻辑主键检测时排除的语义角色（从配置读取，默认排除 audit 和 metric）
        single_exclude = config.get("single_column_exclude_roles", ["audit", "metric"])
        self.single_column_exclude_roles = set(single_exclude) if single_exclude else {"audit", "metric"}

        # 多列逻辑主键检测时排除的语义角色（从配置读取，默认只排除 metric）
        # ⚠️ 关键：这个配置必须与 CandidateGenerator 中的 composite_exclude_semantic_roles 使用相同的配置源
        # 默认值保守策略：只排除明确不适合的 metric，description 等其他角色由用户根据实际情况选择
        composite_exclude = config.get("composite_exclude_roles", ["metric"])
        self.composite_exclude_roles = set(composite_exclude) if composite_exclude else {"metric"}

        logger.info(f"逻辑主键检测器已初始化 (最小置信度: {self.min_confidence})")
        logger.info(f"  单列排除角色（从配置）: {self.single_column_exclude_roles}")
        logger.info(f"  多列排除角色（从配置）: {self.composite_exclude_roles}")
    
    def detect(
        self,
        metadata: TableMetadata,
        sample_data: pd.DataFrame
    ) -> List[LogicalKey]:
        """检测逻辑主键
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据
            
        Returns:
            逻辑主键列表（按置信度降序）
        """
        # 如果表已有主键，则跳过
        if metadata.primary_keys:
            logger.info(f"表已有主键，跳过逻辑主键检测: {metadata.full_name}")
            return []
        
        if sample_data.empty:
            logger.warning(f"样本数据为空，无法检测逻辑主键: {metadata.full_name}")
            return []
        
        logger.info(f"开始检测逻辑主键: {metadata.full_name}")
        
        # 分析单字段候选
        candidates = []
        candidates.extend(self._analyze_single_columns(metadata, sample_data))
        
        # 分析复合键候选（2-3个字段组合）
        candidates.extend(self._analyze_composite_keys(metadata, sample_data))
        
        # 计算置信度
        for candidate in candidates:
            candidate.confidence_score = self.calculate_confidence(
                candidate, metadata, sample_data
            )
        
        # 先筛选满足最小置信度的候选（置信度不够的候选不应该阻止复合键的识别）
        confidence_filtered = [
            c for c in candidates
            if c.confidence_score >= self.min_confidence
        ]
        logger.debug(f"置信度过滤: {len(candidates)} -> {len(confidence_filtered)} (阈值={self.min_confidence})")
        
        # 然后过滤掉 superkeys，只保留最小候选键
        valid_candidates = self._filter_minimal_candidate_keys(confidence_filtered)
        
        # 按置信度降序排序
        valid_candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        
        if valid_candidates:
            logger.info(
                f"检测到 {len(valid_candidates)} 个逻辑主键候选: {metadata.full_name}"
            )
        else:
            logger.info(f"未检测到合适的逻辑主键: {metadata.full_name}")
        
        return valid_candidates
    
    def _get_suitable_columns_for_single_key(
        self,
        metadata: TableMetadata
    ) -> List[str]:
        """获取适合作为单列逻辑主键的字段列表
        
        规则：排除 single_column_exclude_roles 中指定的语义角色（默认排除 audit, metric）
        
        Args:
            metadata: 表元数据（必须已包含 column_profiles）
            
        Returns:
            适合作为单列主键的字段名列表
        """
        if not metadata.column_profiles:
            logger.warning("column_profiles 不存在，无法进行单列逻辑主键检测")
            return []
        
        suitable_columns = []
        
        for col_name, profile in metadata.column_profiles.items():
            semantic_role = profile.semantic_role
            
            # 排除指定的语义角色
            if semantic_role in self.single_column_exclude_roles:
                logger.debug(f"✗ [单列] {col_name} (semantic_role={semantic_role} 被排除)")
            else:
                suitable_columns.append(col_name)
                logger.debug(f"✓ [单列] {col_name} (semantic_role={semantic_role})")
        
        logger.info(f"适合作为单列主键的字段 ({len(suitable_columns)}): {suitable_columns}")
        return suitable_columns
    
    def _get_suitable_columns_for_composite_key(
        self,
        metadata: TableMetadata
    ) -> List[str]:
        """获取适合作为复合键组成部分的字段列表
        
        规则：排除 composite_exclude_roles 中指定的语义角色（只排除 metric）
        
        Args:
            metadata: 表元数据（必须已包含 column_profiles）
            
        Returns:
            适合作为复合键组成的字段名列表
        """
        if not metadata.column_profiles:
            logger.warning("column_profiles 不存在，无法进行复合键逻辑主键检测")
            return []
        
        suitable_columns = []
        
        for col_name, profile in metadata.column_profiles.items():
            semantic_role = profile.semantic_role
            
            # 排除指定的语义角色（只排除 metric）
            if semantic_role in self.composite_exclude_roles:
                logger.debug(f"✗ [复合] {col_name} (semantic_role={semantic_role} 被排除)")
            else:
                suitable_columns.append(col_name)
                logger.debug(f"✓ [复合] {col_name} (semantic_role={semantic_role})")
        
        logger.info(f"适合作为复合键组成的字段 ({len(suitable_columns)}): {suitable_columns}")
        return suitable_columns
    
    def _get_column_statistics_from_profile(
        self,
        metadata: TableMetadata,
        col_name: str
    ) -> tuple:
        """从 column_profiles 的 statistics 中获取统计信息
        
        Args:
            metadata: 表元数据
            col_name: 字段名
            
        Returns:
            (uniqueness, null_rate) 元组
        """
        # 优先从 column_profiles 获取统计信息（Step 2 生成的完整画像）
        if metadata.column_profiles and col_name in metadata.column_profiles:
            profile = metadata.column_profiles[col_name]
            # column_profiles 中的 statistics 可能是字典或对象
            if hasattr(profile, 'statistics') and profile.statistics:
                stats = profile.statistics
                if isinstance(stats, dict):
                    uniqueness = stats.get("uniqueness", 0.0)
                    null_rate = stats.get("null_rate", 1.0)
                else:
                    # 如果 statistics 是对象
                    uniqueness = getattr(stats, 'uniqueness', 0.0)
                    null_rate = getattr(stats, 'null_rate', 1.0)
                logger.debug(f"从 column_profiles 获取 {col_name}: uniqueness={uniqueness}, null_rate={null_rate}")
                return (float(uniqueness), float(null_rate))
        
        # 回退：从 metadata.columns 获取
        for col in metadata.columns:
            if col.column_name == col_name and col.statistics:
                stats = col.statistics
                uniqueness = stats.get("uniqueness", 0.0)
                null_rate = stats.get("null_rate", 1.0)
                logger.debug(f"从 metadata.columns 获取 {col_name}: uniqueness={uniqueness}, null_rate={null_rate}")
                return (float(uniqueness), float(null_rate))
        
        # 如果没有找到统计信息，返回默认值
        logger.warning(f"字段 {col_name} 没有统计信息（column_profiles 和 columns 都没有）")
        return (0.0, 1.0)
    
    def _analyze_single_columns(
        self,
        metadata: TableMetadata,
        sample_data: pd.DataFrame
    ) -> List[LogicalKey]:
        """分析单字段候选
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（不再使用，保留参数以保持接口一致）
            
        Returns:
            单字段逻辑主键候选列表
        """
        candidates = []
        
        # 获取适合作为单列主键的字段（排除 audit, metric）
        suitable_columns = self._get_suitable_columns_for_single_key(metadata)
        
        if not suitable_columns:
            logger.info("没有适合作为单列主键的字段")
            return candidates
        
        for col_name in suitable_columns:
            # 从 column_profiles 中获取统计信息（不重新计算）
            uniqueness, null_rate = self._get_column_statistics_from_profile(metadata, col_name)
            
            # 单字段候选的条件：唯一度 = 100% 且无空值
            if uniqueness == 1.0 and null_rate == 0.0:
                candidate = LogicalKey(
                    columns=[col_name],
                    uniqueness=uniqueness,
                    null_rate=null_rate,
                    confidence_score=0.0  # 后续计算
                )
                candidates.append(candidate)
                logger.debug(f"单字段候选: {col_name} (唯一度={uniqueness})")
        
        return candidates
    
    def _analyze_composite_keys(
        self,
        metadata: TableMetadata,
        sample_data: pd.DataFrame
    ) -> List[LogicalKey]:
        """分析复合键候选
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（用于计算组合的唯一性）
            
        Returns:
            复合键逻辑主键候选列表
        """
        candidates = []
        
        # 获取适合作为复合键组成的字段（只排除 metric）
        suitable_columns = self._get_suitable_columns_for_composite_key(metadata)
        
        if len(suitable_columns) < 2:
            logger.info("适合作为复合键组成的字段少于2个，跳过复合键分析")
            return candidates
        
        # 只对适合的字段生成组合
        for size in range(2, min(self.max_combinations + 1, len(suitable_columns) + 1)):
            for combo in combinations(suitable_columns, size):
                combo_list = list(combo)
                
                # 使用 sample_data 计算组合的唯一性和空值率
                # 注意：组合的统计信息无法从单个字段的统计中推导，必须重新计算
                uniqueness = calculate_uniqueness(sample_data, combo_list)
                null_rate = calculate_null_rate(sample_data, combo_list)
                
                # 复合键候选的条件：唯一度 = 100% 且无空值
                if uniqueness == 1.0 and null_rate == 0.0:
                    candidate = LogicalKey(
                        columns=combo_list,
                        uniqueness=uniqueness,
                        null_rate=null_rate,
                        confidence_score=0.0  # 后续计算
                    )
                    candidates.append(candidate)
                    logger.debug(f"复合键候选: {combo_list} (唯一度={uniqueness})")
        
        return candidates
    
    def _filter_minimal_candidate_keys(
        self,
        candidates: List[LogicalKey]
    ) -> List[LogicalKey]:
        """过滤掉 superkeys，只保留最小候选键
        
        根据关系数据库理论，候选键（Candidate Key）必须满足：
        1. 能够唯一标识元组（uniqueness=1.0, null_rate=0.0）
        2. 没有真子集能唯一标识元组（最小性）
        
        算法：
        - Step 1: 找出字段数最少的所有唯一组合作为候选键集合
        - Step 2: 所有包含这些候选键的组合视为 superkey，全部淘汰
        - Step 3: 允许多个同级别候选键并存（互不包含）
        
        Args:
            candidates: 所有满足唯一性的候选列表
            
        Returns:
            过滤后的最小候选键列表
        """
        if not candidates:
            return []
        
        # Step 1: 找出最小字段数
        min_size = min(len(key.columns) for key in candidates)
        
        # Step 2: 筛选出最小字段数的所有组合（这些就是最小候选键）
        minimal_keys = [
            key for key in candidates
            if len(key.columns) == min_size
        ]
        
        # Step 3: 隐式删除所有包含这些候选键的组合（superkeys）
        # 因为我们直接返回 minimal_keys，所有更大的组合自动被排除
        
        logger.info(
            f"过滤前候选数: {len(candidates)}, "
            f"最小字段数: {min_size}, "
            f"过滤后候选数: {len(minimal_keys)}"
        )
        
        return minimal_keys
    
    def calculate_confidence(
        self,
        candidate: LogicalKey,
        metadata: TableMetadata,
        sample_data: pd.DataFrame
    ) -> float:
        """计算置信度分数
        
        置信度评分规则：
        - 命名匹配度：30%
        - 唯一度：40%
        - 非空率：20%
        - 数据类型适配度：10%
        
        Args:
            candidate: 逻辑主键候选
            metadata: 表元数据
            sample_data: 样本数据
            
        Returns:
            置信度分数 (0.0 ~ 1.0)
        """
        scores = {
            "name_score": 0.0,
            "uniqueness_score": 0.0,
            "non_null_score": 0.0,
            "type_score": 0.0,
        }
        
        # 1. 命名匹配度 (30%)
        scores["name_score"] = self._calculate_name_score(candidate.columns)
        
        # 2. 唯一度 (40%)
        scores["uniqueness_score"] = candidate.uniqueness
        
        # 3. 非空率 (20%)
        scores["non_null_score"] = 1.0 - candidate.null_rate
        
        # 4. 数据类型适配度 (10%)
        scores["type_score"] = self._calculate_type_score(
            candidate.columns, metadata
        )
        
        # 计算加权平均
        weights = {
            "name_score": 0.3,
            "uniqueness_score": 0.4,
            "non_null_score": 0.2,
            "type_score": 0.1,
        }
        
        confidence = sum(scores[key] * weights[key] for key in scores)
        
        return round(confidence, 4)
    
    def _calculate_name_score(self, columns: List[str]) -> float:
        """计算命名匹配分数
        
        Args:
            columns: 字段名列表
            
        Returns:
            命名匹配分数 (0.0 ~ 1.0)
        """
        # 单字段的情况
        if len(columns) == 1:
            # 确保 col_name 是字符串
            col_name = str(columns[0]).lower()
            
            # 检查是否包含关键词
            for pattern in self.name_patterns:
                # 确保 pattern 是字符串
                pattern_str = str(pattern).lower()
                if pattern_str in col_name:
                    # 完全匹配得分更高
                    if col_name == pattern_str or col_name.endswith("_" + pattern_str):
                        return 1.0
                    else:
                        return 0.7
            
            return 0.3  # 没有匹配任何关键词
        
        # 复合键的情况
        else:
            # 检查是否至少有一个字段包含关键词
            has_key_column = any(
                is_potential_key_column(col) for col in columns
            )
            
            if has_key_column:
                return 0.6
            else:
                return 0.3
    
    def _calculate_type_score(
        self,
        columns: List[str],
        metadata: TableMetadata
    ) -> float:
        """计算数据类型适配分数
        
        Args:
            columns: 字段名列表
            metadata: 表元数据
            
        Returns:
            类型适配分数 (0.0 ~ 1.0)
        """
        # 适合作为主键的类型
        good_types = [
            "integer", "bigint", "smallint",
            "uuid", "character varying", "varchar",
            "character", "char"
        ]
        
        # 获取字段类型
        column_types = []
        for col_name in columns:
            for col in metadata.columns:
                if col.column_name == col_name:
                    column_types.append(col.data_type.lower())
                    break
        
        if not column_types:
            return 0.5
        
        # 计算适配分数
        good_type_count = sum(
            1 for dtype in column_types if dtype in good_types
        )
        
        return good_type_count / len(column_types)

