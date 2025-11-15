"""PostgreSQL 业务客户端 - 向量检索、SQL案例检索、维度值检索"""

import json
from typing import Any, Dict, List, Optional, Tuple

from src.services.db.pg_connection import get_pg_manager


class PGClient:
    """PostgreSQL 业务客户端"""

    def __init__(self):
        """初始化 PostgreSQL 客户端"""
        self.pg_manager = get_pg_manager()

    # ==================== 向量检索 ====================

    def search_semantic_tables(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        检索语义相关的表（system.sem_object_vec, object_type='table'）

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值（0.0-1.0）

        Returns:
            表信息列表，每个元素包含：
            - object_id: 表ID（如 "public.fact_sales"）
            - lang: 语言
            - grain_hint: 粒度提示
            - time_col_hint: 时间列提示
            - table_category: 表分类（fact/dim/bridge）
            - similarity: 相似度分数
        """
        query = """
            SELECT
                object_id,
                lang,
                grain_hint,
                time_col_hint,
                table_category,
                1 - (embedding <=> %s::vector) AS similarity
            FROM system.sem_object_vec
            WHERE object_type = 'table'
              AND (1 - (embedding <=> %s::vector)) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (embedding, embedding, similarity_threshold, embedding, top_k))
                rows = cur.fetchall()

        return [dict(row) for row in rows]

    def search_semantic_columns(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        检索语义相关的列（列携带 parent_id=表，归一化 parent_category）

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值

        Returns:
            列信息列表，每个元素包含：
            - object_id: 列ID（如 "public.fact_sales.amount"）
            - parent_id: 父表ID
            - table_category: 父表分类
            - similarity: 相似度分数
        """
        query = """
            SELECT
                col.object_id,
                col.parent_id,
                tbl.table_category,
                1 - (col.embedding <=> %s::vector) AS similarity
            FROM system.sem_object_vec AS col
            LEFT JOIN system.sem_object_vec AS tbl
              ON tbl.object_id = col.parent_id AND tbl.object_type = 'table'
            WHERE col.object_type = 'column'
              AND (1 - (col.embedding <=> %s::vector)) >= %s
            ORDER BY col.embedding <=> %s::vector
            LIMIT %s
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (embedding, embedding, similarity_threshold, embedding, top_k))
                rows = cur.fetchall()

        return [dict(row) for row in rows]

    # ==================== 表卡片 ====================

    def fetch_table_cards(self, table_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取表卡片（表的详细描述）

        Args:
            table_names: 表名列表

        Returns:
            表卡片字典，key为表名，value为表卡片信息
        """
        if not table_names:
            return {}

        query = """
            SELECT
                object_id,
                text_raw,
                grain_hint,
                time_col_hint
            FROM system.sem_object_vec
            WHERE object_type = 'table'
              AND object_id = ANY(%s)
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (table_names,))
                rows = cur.fetchall()

        cards = {}
        for row in rows:
            cards[row["object_id"]] = {
                "text_raw": row["text_raw"],
                "grain_hint": row["grain_hint"],
                "time_col_hint": row["time_col_hint"],
            }

        return cards

    def fetch_table_categories(self, table_names: List[str]) -> Dict[str, str]:
        """
        批量查询表的 table_category 字段
        
        用于补全候选表的原始类型信息（用于提示词展示）
        
        Args:
            table_names: 表名列表
            
        Returns:
            {table_id: table_category} 字典，例如：
            {
                "public.fact_sales": "事实表",
                "public.dim_product": "维度表",
                "public.bridge_xxx": "桥接表"
            }
        """
        if not table_names:
            return {}

        query = """
            SELECT
                object_id,
                table_category
            FROM system.sem_object_vec
            WHERE object_type = 'table'
              AND object_id = ANY(%s)
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (table_names,))
                rows = cur.fetchall()

        categories = {}
        for row in rows:
            category = row.get("table_category") or ""
            if category:  # 只记录非空的类型
                categories[row["object_id"]] = category

        return categories

    # ==================== 历史 SQL 检索 ====================

    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int = 3,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        从 system.sql_embedding 检索历史相似 SQL

        从 document 字段解析 JSON 获取 question/sql

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值

        Returns:
            相似 SQL 列表，每个元素包含：
            - question: 问题文本
            - sql: SQL 语句
            - similarity: 相似度分数
        """
        query = """
            SELECT
                document,
                1 - (embedding <=> %s::vector) AS similarity
            FROM system.sql_embedding
            WHERE type = 'sql'
              AND (1 - (embedding <=> %s::vector)) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (embedding, embedding, similarity_threshold, embedding, top_k))
                rows = cur.fetchall()

        hits = []
        for row in rows:
            doc_str = row["document"]
            sim = float(row["similarity"])

            question = ""
            sql_text = ""

            try:
                # 尝试解析 JSON
                doc = json.loads(doc_str) if isinstance(doc_str, str) else (doc_str or {})
                question = doc.get("question", "")
                sql_text = doc.get("sql", "")
            except Exception:
                # 降级：无法解析时将原文作为 SQL 展示
                sql_text = doc_str

            hits.append({
                "question": question,
                "sql": sql_text,
                "similarity": sim,
            })

        return hits

    # ==================== 维度值检索 ====================

    def search_dim_values(
        self,
        query_value: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        从 system.dim_value_index 检索维度值匹配

        使用 pg_trgm + norm_zh() 函数进行模糊匹配

        Args:
            query_value: 查询的维度值（如"京东便利店"）
            top_k: 返回 Top-K 个结果

        Returns:
            维度值匹配列表，每个元素包含：
            - dim_table: 维表名（不含 schema）
            - dim_col: 维度列名
            - key_col: 主键列名
            - key_value: 主键值
            - matched_text: 匹配到的文本
            - score: 相似度分数
        """
        # 注意：这里假设数据库已经创建了 norm_zh() 函数和 pg_trgm 扩展
        query = """
            SELECT
                dim_table,
                dim_col,
                key_col,
                key_value,
                value_text AS matched_text,
                word_similarity(value_norm, norm_zh(%s)) AS score
            FROM system.dim_value_index
            WHERE value_norm %% norm_zh(%s)
            ORDER BY score DESC
            LIMIT %s
        """

        try:
            with self.pg_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (query_value, query_value, top_k))
                    rows = cur.fetchall()

            return [dict(row) for row in rows]

        except Exception as e:
            # 如果 norm_zh() 函数不存在，降级为简单匹配
            print(f"⚠️ 维度值检索失败（可能是 norm_zh() 函数未创建）: {e}")
            return self._search_dim_values_fallback(query_value, top_k)

    def _search_dim_values_fallback(self, query_value: str, top_k: int) -> List[Dict[str, Any]]:
        """
        维度值检索降级方案（不使用 norm_zh()）

        Args:
            query_value: 查询的维度值
            top_k: 返回 Top-K 个结果

        Returns:
            维度值匹配列表
        """
        query = """
            SELECT
                dim_table,
                dim_col,
                key_col,
                key_value,
                value_text AS matched_text,
                similarity(value_norm, lower(%s)) AS score
            FROM system.dim_value_index
            WHERE value_norm %% lower(%s)
            ORDER BY score DESC
            LIMIT %s
        """

        try:
            with self.pg_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (query_value, query_value, top_k))
                    rows = cur.fetchall()

            return [dict(row) for row in rows]

        except Exception as e:
            print(f"❌ 维度值检索降级方案也失败: {e}")
            return []

    # ==================== EXPLAIN 查询 ====================

    def explain_query(
        self,
        sql: str,
        analyze: bool = False,
        timeout: int = 5,
    ) -> Tuple[bool, str, List[str]]:
        """
        执行 EXPLAIN 查询（不实际执行 SQL）

        Args:
            sql: 要分析的 SQL 语句
            analyze: 是否使用 EXPLAIN ANALYZE（实际执行）
            timeout: 超时时间（秒）

        Returns:
            (success, explain_plan, errors)
            - success: 是否成功
            - explain_plan: 查询计划文本
            - errors: 错误列表
        """
        explain_sql = f"EXPLAIN {'ANALYZE ' if analyze else ''}{sql}"
        errors = []

        try:
            with self.pg_manager.get_connection() as conn:
                # 设置语句超时
                with conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {timeout * 1000}")

                # 执行 EXPLAIN
                with conn.cursor() as cur:
                    cur.execute(explain_sql)
                    rows = cur.fetchall()

                # 提取查询计划
                plan_lines = [row[list(row.keys())[0]] for row in rows]
                explain_plan = "\n".join(plan_lines)

                return True, explain_plan, []

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            return False, "", errors

    # ==================== 工具方法 ====================

    def test_table_exists(self, table_name: str) -> bool:
        """
        测试表是否存在

        Args:
            table_name: 表名（格式：schema.table 或 table）

        Returns:
            存在返回 True，否则返回 False
        """
        # 解析 schema 和表名
        if "." in table_name:
            schema, table = table_name.split(".", 1)
        else:
            schema = "public"
            table = table_name

        query = """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
            )
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (schema, table))
                result = cur.fetchone()
                return result["exists"]

    def get_table_columns(self, table_name: str) -> List[str]:
        """
        获取表的所有列名

        Args:
            table_name: 表名（格式：schema.table 或 table）

        Returns:
            列名列表
        """
        # 解析 schema 和表名
        if "." in table_name:
            schema, table = table_name.split(".", 1)
        else:
            schema = "public"
            table = table_name

        query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
        """

        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (schema, table))
                rows = cur.fetchall()

        return [row["column_name"] for row in rows]

    def execute_query(
        self,
        sql: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        执行SQL查询（通用方法）

        用于父图的 SQL执行节点，支持任意 SELECT 查询。

        Args:
            sql: 要执行的SQL语句
            timeout: 超时时间（秒）

        Returns:
            查询结果字典：
            {
                "columns": List[str],  # 列名列表
                "rows": List[List[Any]],  # 数据行（列表的列表）
            }

        Raises:
            Exception: SQL执行失败时抛出异常
        """
        with self.pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                # 设置语句超时
                cur.execute(f"SET statement_timeout = {timeout * 1000}")

                # 执行查询
                cur.execute(sql)

                # 获取列名
                columns = [desc[0] for desc in cur.description] if cur.description else []

                # 获取数据
                rows = cur.fetchall()

                # 转换为列表的列表（便于序列化）
                rows_list = [list(row.values()) for row in rows]

                return {
                    "columns": columns,
                    "rows": rows_list,
                }


# 全局 PG 客户端实例（单例）
_global_pg_client: Optional[PGClient] = None


def get_pg_client() -> PGClient:
    """
    获取全局 PG 客户端（单例）

    Returns:
        PGClient 实例
    """
    global _global_pg_client

    if _global_pg_client is None:
        _global_pg_client = PGClient()

    return _global_pg_client
