"""PgVector 向量检索适配器。

封装 PGClient 的向量检索方法，提供统一接口。
"""

from typing import Any, Dict, List

from src.services.db.pg_client import PGClient
from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.utils.logger import get_module_logger

logger = get_module_logger("pgvector_adapter")


class PgVectorSearchAdapter(BaseVectorSearchAdapter):
    """PgVector 检索适配器。

    复用现有 PGClient 的向量检索能力，不需要修改返回格式。
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化 PgVector 适配器。

        Args:
            config: 向量数据库配置（来自 config.yaml 的 vector_database 段）
        """
        super().__init__(config)
        self.pg_client = PGClient()

    def search_tables(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的表。

        直接调用 pg_client.search_semantic_tables()。
        """
        results = self.pg_client.search_semantic_tables(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

        # 确保所有记录包含 object_type 字段（用于统一接口）
        for item in results:
            if "object_type" not in item:
                item["object_type"] = "table"
            if "table_name" not in item:
                item["table_name"] = item.get("object_id")

        return results

    def search_columns(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的列。

        直接调用 pg_client.search_semantic_columns()。
        """
        results = self.pg_client.search_semantic_columns(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

        # 确保所有记录包含 object_type 字段（用于统一接口）
        for item in results:
            if "object_type" not in item:
                item["object_type"] = "column"
            if "table_name" not in item:
                item["table_name"] = item.get("parent_id")

        return results

    def search_dim_values(
        self,
        query_value: str,
        top_k: int,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索维度值匹配。

        调用 pg_client.search_dim_values()，然后在内存中过滤分数。

        Note:
            PgVector 使用 pg_trgm + norm_zh() 函数进行模糊匹配，
            返回结果包含完整的 key_col/key_value 主键信息。
        """
        # 调用 PGClient（返回所有满足 %% 运算符的结果）
        # ⚠️ 多取一些数据，后续在内存中过滤阈值
        matches = self.pg_client.search_dim_values(
            query_value=query_value,
            top_k=top_k * 2 if min_score > 0.0 else top_k,
        )

        # ✅ 在内存中过滤分数
        if min_score > 0.0:
            filtered = [m for m in matches if m.get("score", 0.0) >= min_score]
            # ✅ 取前 top_k 个
            return filtered[:top_k]

        return matches

    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索历史相似 SQL。

        直接调用 pg_client.search_similar_sqls()。
        """
        return self.pg_client.search_similar_sqls(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    def fetch_table_cards(
        self,
        table_names: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """获取表卡片（批量精确查询）。

        直接调用 pg_client.fetch_table_cards()。
        """
        return self.pg_client.fetch_table_cards(table_names=table_names)

    def fetch_table_categories(
        self,
        table_names: List[str],
    ) -> Dict[str, str]:
        """批量查询表的 table_category 字段。

        直接调用 pg_client.fetch_table_categories()。
        """
        return self.pg_client.fetch_table_categories(table_names=table_names)
