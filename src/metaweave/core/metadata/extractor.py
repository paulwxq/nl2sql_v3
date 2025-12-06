"""元数据提取器

从 PostgreSQL 数据库中提取表结构、字段、约束、索引等元数据信息。
"""

import logging
from typing import List, Optional, Dict, Any

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.metadata.models import (
    TableMetadata,
    ColumnInfo,
    PrimaryKey,
    ForeignKey,
    UniqueConstraint,
    IndexInfo,
)
from src.metaweave.utils.sql_templates import (
    GET_SINGLE_TABLE_INFO_SQL,
    GET_COLUMNS_SQL,
    GET_PRIMARY_KEYS_SQL,
    GET_FOREIGN_KEYS_SQL,
    GET_UNIQUE_CONSTRAINTS_SQL,
    GET_INDEXES_SQL,
)

logger = logging.getLogger("metaweave.extractor")


class MetadataExtractor:
    """元数据提取器
    
    负责从数据库中提取表的完整元数据信息。
    """
    
    def __init__(self, connector: DatabaseConnector):
        """初始化元数据提取器
        
        Args:
            connector: 数据库连接器实例
        """
        self.connector = connector
    
    def extract_table_info(self, schema: str, table: str) -> Optional[Dict[str, Any]]:
        """提取表基本信息
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            表信息字典，如果表不存在则返回 None
        """
        try:
            results = self.connector.execute_query(
                GET_SINGLE_TABLE_INFO_SQL,
                (schema, table),
                fetch_one=True
            )
            if results:
                return results[0]
            return None
        except Exception as e:
            logger.error(f"提取表信息失败 ({schema}.{table}): {e}")
            return None
    
    def extract_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """提取字段信息
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            字段信息列表
        """
        try:
            results = self.connector.execute_query(GET_COLUMNS_SQL, (schema, table))
            
            columns = []
            for row in results:
                # 安全地处理 is_nullable
                is_nullable_value = row.get("is_nullable")
                if isinstance(is_nullable_value, bool):
                    is_nullable = is_nullable_value
                else:
                    is_nullable = (str(is_nullable_value).upper() == "YES")
                
                # 安全地处理 column_default
                column_default = row.get("column_default")
                if column_default is not None and not isinstance(column_default, str):
                    column_default = str(column_default)
                
                # 安全地处理 column_comment
                column_comment = row.get("column_comment")
                if column_comment and not isinstance(column_comment, str):
                    column_comment = str(column_comment)
                
                column = ColumnInfo(
                    column_name=row["column_name"],
                    ordinal_position=row["ordinal_position"],
                    data_type=row["data_type"],
                    character_maximum_length=row.get("character_maximum_length"),
                    numeric_precision=row.get("numeric_precision"),
                    numeric_scale=row.get("numeric_scale"),
                    is_nullable=is_nullable,
                    column_default=column_default,
                    comment=column_comment or "",
                    comment_source="db" if column_comment else "",
                )
                columns.append(column)
            
            logger.info(f"提取到 {len(columns)} 个字段 ({schema}.{table})")
            return columns
        except Exception as e:
            logger.error(f"提取字段信息失败 ({schema}.{table}): {e}")
            return []
    
    def extract_primary_keys(self, schema: str, table: str) -> List[PrimaryKey]:
        """提取主键约束
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            主键列表
        """
        try:
            results = self.connector.execute_query(GET_PRIMARY_KEYS_SQL, (schema, table))
            
            primary_keys = []
            for row in results:
                # 解析 PostgreSQL 数组类型
                columns = self._parse_pg_array(row.get("columns"))
                
                pk = PrimaryKey(
                    constraint_name=row["constraint_name"],
                    columns=columns,
                )
                primary_keys.append(pk)
            
            if primary_keys:
                logger.info(f"提取到 {len(primary_keys)} 个主键 ({schema}.{table})")
            return primary_keys
        except Exception as e:
            logger.error(f"提取主键失败 ({schema}.{table}): {e}")
            return []
    
    def _parse_pg_array(self, value) -> List[str]:
        """解析 PostgreSQL 数组类型
        
        PostgreSQL 数组可能以不同形式返回：
        - Python list: ['col1', 'col2']
        - 字符串格式: '{col1,col2}'
        - None
        
        Args:
            value: PostgreSQL 数组值
            
        Returns:
            Python 列表
        """
        if value is None:
            return []
        
        # 已经是 Python list
        if isinstance(value, list):
            return value
        
        # 字符串格式（PostgreSQL 数组表示）
        if isinstance(value, str):
            # 移除大括号并分割
            value = value.strip()
            if value.startswith('{') and value.endswith('}'):
                value = value[1:-1]
            
            # 空数组
            if not value:
                return []
            
            # 分割并清理
            return [col.strip() for col in value.split(',') if col.strip()]
        
        # 其他类型，尝试转换为列表
        try:
            return list(value)
        except (TypeError, ValueError):
            logger.warning(f"无法解析 PostgreSQL 数组: {value} (类型: {type(value)})")
            return []
    
    def extract_foreign_keys(self, schema: str, table: str) -> List[ForeignKey]:
        """提取外键约束
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            外键列表
        """
        try:
            results = self.connector.execute_query(GET_FOREIGN_KEYS_SQL, (schema, table))
            
            foreign_keys = []
            for row in results:
                # 解析 PostgreSQL 数组类型
                source_columns = self._parse_pg_array(row.get("source_columns"))
                target_columns = self._parse_pg_array(row.get("target_columns"))
                
                fk = ForeignKey(
                    constraint_name=row["constraint_name"],
                    source_columns=source_columns,
                    target_schema=row["target_schema"],
                    target_table=row["target_table"],
                    target_columns=target_columns,
                    on_delete=row.get("delete_rule", "NO ACTION"),
                    on_update=row.get("update_rule", "NO ACTION"),
                )
                foreign_keys.append(fk)
            
            if foreign_keys:
                logger.info(f"提取到 {len(foreign_keys)} 个外键 ({schema}.{table})")
            return foreign_keys
        except Exception as e:
            logger.error(f"提取外键失败 ({schema}.{table}): {e}")
            return []
    
    def extract_unique_constraints(self, schema: str, table: str) -> List[UniqueConstraint]:
        """提取唯一约束
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            唯一约束列表
        """
        try:
            results = self.connector.execute_query(GET_UNIQUE_CONSTRAINTS_SQL, (schema, table))
            
            unique_constraints = []
            for row in results:
                # 解析 PostgreSQL 数组类型
                columns = self._parse_pg_array(row.get("columns"))
                
                uc = UniqueConstraint(
                    constraint_name=row["constraint_name"],
                    columns=columns,
                    is_partial=False,  # PostgreSQL 不直接标记部分索引，需要另外判断
                )
                unique_constraints.append(uc)
            
            if unique_constraints:
                logger.info(f"提取到 {len(unique_constraints)} 个唯一约束 ({schema}.{table})")
            return unique_constraints
        except Exception as e:
            logger.error(f"提取唯一约束失败 ({schema}.{table}): {e}")
            return []
    
    def extract_indexes(self, schema: str, table: str) -> List[IndexInfo]:
        """提取索引信息
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            索引列表
        """
        try:
            results = self.connector.execute_query(GET_INDEXES_SQL, (schema, table))
            
            indexes = []
            for row in results:
                # 解析 PostgreSQL 数组类型
                columns = self._parse_pg_array(row.get("columns"))
                
                idx = IndexInfo(
                    index_name=row["index_name"],
                    index_type=row.get("index_type", "btree"),
                    columns=columns,
                    is_unique=row.get("is_unique", False),
                    is_primary=row.get("is_primary", False),
                    condition=row.get("condition"),
                )
                indexes.append(idx)
            
            if indexes:
                logger.info(f"提取到 {len(indexes)} 个索引 ({schema}.{table})")
            return indexes
        except Exception as e:
            logger.error(f"提取索引失败 ({schema}.{table}): {e}")
            return []
    
    def extract_all(self, schema: str, table: str) -> Optional[TableMetadata]:
        """提取表的完整元数据
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            完整的表元数据对象，如果提取失败则返回 None
        """
        try:
            # 检查表是否存在
            if not self.connector.check_table_exists(schema, table):
                logger.warning(f"表不存在: {schema}.{table}")
                return None
            
            # 提取表基本信息
            table_info = self.extract_table_info(schema, table)
            if not table_info:
                logger.error(f"无法获取表基本信息: {schema}.{table}")
                return None
            
            # 创建 TableMetadata 对象
            metadata = TableMetadata(
                schema_name=schema,
                table_name=table,
                table_type="table",  # 默认为 table，可以后续扩展支持 view
                comment=table_info.get("table_comment") or "",
                comment_source="db" if table_info.get("table_comment") else "",
                row_count=table_info.get("row_count", 0),
            )
            
            # 提取字段信息
            metadata.columns = self.extract_columns(schema, table)
            
            # 提取约束信息
            metadata.primary_keys = self.extract_primary_keys(schema, table)
            metadata.foreign_keys = self.extract_foreign_keys(schema, table)
            metadata.unique_constraints = self.extract_unique_constraints(schema, table)
            
            # 提取索引信息
            metadata.indexes = self.extract_indexes(schema, table)
            
            logger.info(f"成功提取表元数据: {schema}.{table}")
            return metadata
            
        except Exception as e:
            logger.error(f"提取表元数据失败 ({schema}.{table}): {e}")
            return None

