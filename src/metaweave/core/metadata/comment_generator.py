"""注释生成器

使用 LLM 生成表和字段的注释，支持缓存避免重复调用。
"""

import logging
from typing import List, Dict, Optional, Any
import pandas as pd

from src.metaweave.services.llm_service import LLMService
from src.metaweave.services.cache_service import CacheService
from src.metaweave.core.metadata.models import ColumnInfo, TableMetadata
from src.metaweave.utils.data_utils import dataframe_to_sample_dict

logger = logging.getLogger("metaweave.comment_generator")


class CommentGenerator:
    """注释生成器
    
    使用 LLM 生成表和字段的注释，支持缓存。
    """
    
    def __init__(
        self,
        llm_service: LLMService,
        cache_service: Optional[CacheService] = None,
        cache_enabled: bool = True
    ):
        """初始化注释生成器
        
        Args:
            llm_service: LLM 服务实例
            cache_service: 缓存服务实例（可选）
            cache_enabled: 是否启用缓存
        """
        self.llm_service = llm_service
        self.cache_service = cache_service
        self.cache_enabled = cache_enabled and cache_service is not None
        
        logger.info(f"注释生成器已初始化 (缓存: {'启用' if self.cache_enabled else '禁用'})")
    
    def generate_table_comment(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None,
        force_regenerate: bool = False
    ) -> str:
        """生成表注释
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（可选）
            force_regenerate: 是否强制重新生成（忽略缓存）
            
        Returns:
            生成的表注释
        """
        # 构建缓存键
        cache_key = f"table:{metadata.schema_name}.{metadata.table_name}"
        
        # 检查缓存
        if self.cache_enabled and not force_regenerate:
            cached_comment = self.cache_service.get(cache_key)
            if cached_comment:
                logger.info(f"从缓存获取表注释: {metadata.full_name}")
                return cached_comment
        
        # 准备字段信息
        columns = [
            {"name": col.column_name, "type": col.data_type}
            for col in metadata.columns
        ]
        
        # 准备样本数据
        sample_dict = None
        if sample_data is not None and not sample_data.empty:
            # 统一使用最多5行样本数据，便于 LLM 理解表结构
            sample_dict = dataframe_to_sample_dict(sample_data, max_rows=5)
        
        # 调用 LLM 生成注释
        try:
            comment = self.llm_service.generate_table_comment(
                table_name=metadata.table_name,
                columns=columns,
                sample_data=sample_dict
            )
            
            if comment:
                # 保存到缓存
                if self.cache_enabled:
                    self.cache_service.set(cache_key, comment)
                
                logger.info(f"生成表注释: {metadata.full_name}")
                return comment
            else:
                logger.warning(f"LLM 返回空注释: {metadata.full_name}")
                return ""
        
        except Exception as e:
            logger.error(f"生成表注释失败 ({metadata.full_name}): {e}")
            return ""
    
    def generate_column_comments(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None,
        force_regenerate: bool = False
    ) -> Dict[str, str]:
        """批量生成字段注释
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（可选）
            force_regenerate: 是否强制重新生成（忽略缓存）
            
        Returns:
            字段注释字典 {column_name: comment}
        """
        # 筛选需要生成注释的字段
        columns_need_comment = [
            col for col in metadata.columns
            if not col.comment or force_regenerate
        ]
        
        if not columns_need_comment:
            logger.info(f"所有字段都有注释: {metadata.full_name}")
            return {}
        
        # 构建缓存键
        cache_key = f"columns:{metadata.schema_name}.{metadata.table_name}"
        
        # 检查缓存
        if self.cache_enabled and not force_regenerate:
            cached_comments = self.cache_service.get(cache_key)
            if cached_comments and isinstance(cached_comments, dict):
                logger.info(f"从缓存获取字段注释: {metadata.full_name}")
                return cached_comments
        
        # 准备字段信息（包含样本值）
        columns_info = []
        for col in columns_need_comment:
            col_info = {
                "name": col.column_name,
                "type": col.data_type,
            }
            
            # 添加样本值
            if sample_data is not None and col.column_name in sample_data.columns:
                sample_values = sample_data[col.column_name].dropna().head(5).tolist()
                col_info["sample_values"] = sample_values
            
            columns_info.append(col_info)
        
        # 准备样本数据
        sample_dict = None
        if sample_data is not None and not sample_data.empty:
            # 与表注释一致，最多提供5行样本数据
            sample_dict = dataframe_to_sample_dict(sample_data, max_rows=5)
        
        # 调用 LLM 生成注释
        try:
            comments = self.llm_service.generate_column_comments(
                table_name=metadata.table_name,
                columns=columns_info,
                sample_data=sample_dict
            )
            
            if comments:
                # 保存到缓存
                if self.cache_enabled:
                    self.cache_service.set(cache_key, comments)
                
                logger.info(f"生成字段注释: {metadata.full_name}, {len(comments)} 个字段")
                return comments
            else:
                logger.warning(f"LLM 返回空注释: {metadata.full_name}")
                return {}
        
        except Exception as e:
            logger.error(f"生成字段注释失败 ({metadata.full_name}): {e}")
            return {}
    
    def enrich_metadata_with_comments(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None,
        generate_table_comment: bool = True,
        generate_column_comments: bool = True
    ) -> int:
        """使用 LLM 增强元数据的注释
        
        Args:
            metadata: 表元数据（会被修改）
            sample_data: 样本数据（可选）
            generate_table_comment: 是否生成表注释
            generate_column_comments: 是否生成字段注释
            
        Returns:
            生成的注释数量
        """
        generated_count = 0
        
        # 生成表注释
        if generate_table_comment and not metadata.comment:
            comment = self.generate_table_comment(metadata, sample_data)
            if comment:
                metadata.comment = comment
                metadata.comment_source = "llm_generated"
                generated_count += 1
        
        # 生成字段注释
        if generate_column_comments:
            column_comments = self.generate_column_comments(metadata, sample_data)
            
            # 更新字段注释
            for column in metadata.columns:
                if column.column_name in column_comments:
                    column.comment = column_comments[column.column_name]
                    column.comment_source = "llm_generated"
                    generated_count += 1
        
        logger.info(f"生成注释完成: {metadata.full_name}, {generated_count} 个注释")
        return generated_count

