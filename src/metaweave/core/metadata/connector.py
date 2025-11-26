"""数据库连接器

负责连接 PostgreSQL 数据库并执行查询。
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from contextlib import contextmanager

from src.metaweave.utils.sql_templates import (
    GET_SCHEMAS_SQL,
    GET_TABLES_SQL,
    SAMPLE_DATA_SQL,
    CHECK_TABLE_EXISTS_SQL,
)

logger = logging.getLogger("metaweave.connector")


class DatabaseConnector:
    """PostgreSQL 数据库连接器
    
    使用 psycopg3 和连接池管理数据库连接。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化数据库连接器
        
        Args:
            config: 数据库配置字典，包含 host, port, database, user, password
        """
        self.config = config
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 5432)
        self.database = config.get("database")
        self.user = config.get("user")
        self.password = config.get("password")
        
        # 打印实际配置值用于调试
        logger.info(f"数据库配置:")
        logger.info(f"  Host: {self.host}")
        logger.info(f"  Port: {self.port}")
        logger.info(f"  Database: {self.database}")
        logger.info(f"  User: {self.user}")
        logger.info(f"  Password: {'*' * len(str(self.password)) if self.password else 'None'}")
        
        # 验证必需参数
        if not self.database:
            raise ValueError("数据库名称（database）未配置")
        if not self.user:
            raise ValueError("数据库用户（user）未配置")
        if not self.password:
            raise ValueError("数据库密码（password）未配置")
        
        # 构建连接字符串
        self.conninfo = (
            f"host={self.host} "
            f"port={self.port} "
            f"dbname={self.database} "
            f"user={self.user} "
            f"password={self.password}"
        )
        
        # 连接池配置
        min_size = config.get("pool_min_size", 1)
        max_size = config.get("pool_max_size", 5)
        
        # 初始化连接池
        self.pool: Optional[ConnectionPool] = None
        try:
            self.pool = ConnectionPool(
                self.conninfo,
                min_size=min_size,
                max_size=max_size,
                open=True,
            )
            logger.info(f"数据库连接池已创建: {self.database}@{self.host}:{self.port}")
        except Exception as e:
            logger.error(f"创建数据库连接池失败: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）
        
        Yields:
            psycopg.Connection: 数据库连接对象
        """
        if self.pool is None:
            raise RuntimeError("连接池未初始化")
        
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
        except Exception as e:
            logger.error(f"获取数据库连接失败: {e}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)
    
    def execute_query(
        self, 
        sql: str, 
        params: Optional[Tuple] = None,
        fetch_one: bool = False
    ) -> List[Dict[str, Any]]:
        """执行查询并返回结果
        
        Args:
            sql: SQL 查询语句
            params: 查询参数
            fetch_one: 是否只返回一行结果
            
        Returns:
            查询结果列表（字典格式）
        """
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(sql, params)
                    if fetch_one:
                        result = cur.fetchone()
                        return [result] if result else []
                    else:
                        return cur.fetchall()
                except Exception as e:
                    logger.error(f"执行查询失败: {e}\nSQL: {sql}\nParams: {params}")
                    raise
    
    def get_schemas(self, exclude_system: bool = True) -> List[str]:
        """获取所有 schema
        
        Args:
            exclude_system: 是否排除系统 schema
            
        Returns:
            schema 名称列表
        """
        try:
            results = self.execute_query(GET_SCHEMAS_SQL)
            schemas = [row["schema_name"] for row in results]
            logger.info(f"获取到 {len(schemas)} 个 schema: {schemas}")
            return schemas
        except Exception as e:
            logger.error(f"获取 schema 列表失败: {e}")
            return []
    
    def get_tables(self, schema: str) -> List[str]:
        """获取指定 schema 下的所有表
        
        Args:
            schema: schema 名称
            
        Returns:
            表名列表
        """
        try:
            results = self.execute_query(GET_TABLES_SQL, (schema,))
            tables = [row["tablename"] for row in results]
            logger.info(f"Schema '{schema}' 包含 {len(tables)} 张表")
            return tables
        except Exception as e:
            logger.error(f"获取表列表失败 (schema={schema}): {e}")
            return []
    
    def check_table_exists(self, schema: str, table: str) -> bool:
        """检查表是否存在
        
        Args:
            schema: schema 名称
            table: 表名
            
        Returns:
            表是否存在
        """
        try:
            results = self.execute_query(CHECK_TABLE_EXISTS_SQL, (schema, table), fetch_one=True)
            return results[0]["exists"] if results else False
        except Exception as e:
            logger.error(f"检查表是否存在失败 (schema={schema}, table={table}): {e}")
            return False
    
    def sample_data(
        self, 
        schema: str, 
        table: str, 
        limit: int = 1000
    ) -> pd.DataFrame:
        """采样表数据
        
        Args:
            schema: schema 名称
            table: 表名
            limit: 采样行数
            
        Returns:
            样本数据 DataFrame
        """
        try:
            # 使用标识符引用来处理特殊字符
            sql = SAMPLE_DATA_SQL.format(
                schema=psycopg.sql.Identifier(schema).as_string(None),
                table=psycopg.sql.Identifier(table).as_string(None)
            )
            
            with self.get_connection() as conn:
                df = pd.read_sql_query(sql, conn, params=(limit,))
                logger.info(f"采样 {schema}.{table} 获取 {len(df)} 行数据")
                return df
        except Exception as e:
            logger.error(f"采样数据失败 (schema={schema}, table={table}): {e}")
            return pd.DataFrame()
    
    def test_connection(self) -> bool:
        """测试数据库连接
        
        Returns:
            连接是否成功
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    version = cur.fetchone()
                    logger.info(f"数据库连接测试成功: {version[0]}")
                    return True
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False
    
    def close(self):
        """关闭连接池"""
        if self.pool:
            self.pool.close()
            logger.info("数据库连接池已关闭")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

