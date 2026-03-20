"""PgVector 适配器单元测试"""

import pytest
from unittest.mock import Mock, patch
from src.services.vector_adapter.pgvector_adapter import PgVectorSearchAdapter


@pytest.fixture
def mock_pg_client():
    """Mock PGClient"""
    with patch("src.services.vector_adapter.pgvector_adapter.PGClient") as mock:
        client = Mock()
        mock.return_value = client
        yield client


@pytest.fixture
def adapter(mock_pg_client):
    """创建 PgVector 适配器实例"""
    config = {"providers": {"pgvector": {"host": "localhost", "database": "test"}}}
    return PgVectorSearchAdapter(config)


class TestPgVectorSearchAdapter:
    """PgVector 适配器测试"""

    def test_search_tables(self, adapter, mock_pg_client):
        """测试表检索"""
        # 准备测试数据
        embedding = [0.1] * 768
        expected_result = [
            {
                "object_id": "public.table1",
                "table_name": "public.table1",
                "object_type": "table",
                "similarity": 0.85,
                "grain_hint": "daily",
                "time_col_hint": "created_at",
                "table_category": "fact",
            }
        ]
        mock_pg_client.search_semantic_tables.return_value = expected_result

        # 调用方法
        result = adapter.search_tables(
            embedding=embedding, top_k=10, similarity_threshold=0.5
        )

        # 验证调用
        mock_pg_client.search_semantic_tables.assert_called_once_with(
            embedding=embedding, top_k=10, similarity_threshold=0.5
        )

        # 验证结果
        assert result == expected_result

    def test_search_columns(self, adapter, mock_pg_client):
        """测试列检索"""
        embedding = [0.1] * 768
        expected_result = [
            {
                "object_id": "public.table1.col1",
                "parent_id": "public.table1",
                "table_name": "public.table1",
                "object_type": "column",
                "similarity": 0.75,
                "grain_hint": None,
                "table_category": "fact",
            }
        ]
        mock_pg_client.search_semantic_columns.return_value = expected_result

        result = adapter.search_columns(
            embedding=embedding, top_k=10, similarity_threshold=0.5
        )

        mock_pg_client.search_semantic_columns.assert_called_once_with(
            embedding=embedding, top_k=10, similarity_threshold=0.5
        )
        assert result == expected_result

    def test_search_dim_values(self, adapter, mock_pg_client):
        """测试维度值检索"""
        query_value = "北京"
        expected_result = [
            {
                "dim_table": "public.dim_city",
                "dim_col": "city_name",
                "matched_text": "北京市",
                "score": 0.92,
                "key_col": "city_id",
                "key_value": "110000",
            }
        ]
        mock_pg_client.search_dim_values.return_value = expected_result

        result = adapter.search_dim_values(query_value=query_value, top_k=5)

        mock_pg_client.search_dim_values.assert_called_once_with(
            query_value=query_value, top_k=5  # min_score=0.0（默认），不 * 2
        )
        assert result == expected_result

    def test_search_dim_values_with_min_score(self, adapter, mock_pg_client):
        """测试维度值检索的 min_score 参数过滤低分结果"""
        query_value = "京东"
        # Mock PGClient 返回的结果（包含高分和低分）
        pg_results = [
            {
                "dim_table": "public.dim_store",
                "dim_col": "store_name",
                "matched_text": "京东便利店",
                "score": 0.85,
                "key_col": "store_id",
                "key_value": "S001",
            },
            {
                "dim_table": "public.dim_store",
                "dim_col": "store_name",
                "matched_text": "京东",
                "score": 0.35,  # 低分，应被过滤
                "key_col": "store_id",
                "key_value": "S002",
            },
            {
                "dim_table": "public.dim_store",
                "dim_col": "store_name",
                "matched_text": "京东物流",
                "score": 0.65,
                "key_col": "store_id",
                "key_value": "S003",
            },
        ]
        mock_pg_client.search_dim_values.return_value = pg_results

        # 调用 search_dim_values（min_score=0.5，应该过滤掉低分结果）
        result = adapter.search_dim_values(
            query_value=query_value, top_k=3, min_score=0.5
        )

        # 验证调用参数（top_k * 2 因为需要多取数据后过滤）
        mock_pg_client.search_dim_values.assert_called_once_with(
            query_value=query_value, top_k=6
        )

        # 验证只返回高分结果（score >= 0.5）
        assert len(result) == 2
        assert result[0]["matched_text"] == "京东便利店"
        assert result[0]["score"] == 0.85
        assert result[1]["matched_text"] == "京东物流"
        assert result[1]["score"] == 0.65

    def test_search_similar_sqls(self, adapter, mock_pg_client):
        """测试历史 SQL 检索"""
        embedding = [0.1] * 768
        expected_result = [
            {
                "sql_text": "SELECT * FROM table1",
                "similarity": 0.88,
                "metadata": {"tags": ["sales"]},
            }
        ]
        mock_pg_client.search_similar_sqls.return_value = expected_result

        result = adapter.search_similar_sqls(
            embedding=embedding, top_k=3, similarity_threshold=0.6
        )

        mock_pg_client.search_similar_sqls.assert_called_once_with(
            embedding=embedding, top_k=3, similarity_threshold=0.6
        )
        assert result == expected_result

    def test_fetch_table_cards(self, adapter, mock_pg_client):
        """测试表卡片获取"""
        table_names = ["public.table1", "public.table2"]
        expected_result = {
            "public.table1": {
                "text_raw": "表1描述",
                "grain_hint": "daily",
                "time_col_hint": "created_at",
                "table_category": "fact",
            },
            "public.table2": {
                "text_raw": "表2描述",
                "grain_hint": None,
                "time_col_hint": None,
                "table_category": "dimension",
            },
        }
        mock_pg_client.fetch_table_cards.return_value = expected_result

        result = adapter.fetch_table_cards(table_names=table_names)

        mock_pg_client.fetch_table_cards.assert_called_once_with(
            table_names=table_names
        )
        assert result == expected_result

    def test_fetch_table_categories(self, adapter, mock_pg_client):
        """测试表分类获取"""
        table_names = ["public.table1", "public.table2"]
        expected_result = {"public.table1": "fact", "public.table2": "dimension"}
        mock_pg_client.fetch_table_categories.return_value = expected_result

        result = adapter.fetch_table_categories(table_names=table_names)

        mock_pg_client.fetch_table_categories.assert_called_once_with(
            table_names=table_names
        )
        assert result == expected_result

    def test_empty_results(self, adapter, mock_pg_client):
        """测试空结果"""
        mock_pg_client.search_semantic_tables.return_value = []
        mock_pg_client.fetch_table_cards.return_value = {}

        # 表检索空结果
        result = adapter.search_tables(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
        )
        assert result == []

        # 表卡片空结果
        result = adapter.fetch_table_cards(table_names=[])
        assert result == {}

    def test_exception_propagation(self, adapter, mock_pg_client):
        """测试异常传播"""
        # 模拟 PGClient 抛出异常
        mock_pg_client.search_semantic_tables.side_effect = Exception(
            "Database connection error"
        )

        # 验证异常会传播
        with pytest.raises(Exception, match="Database connection error"):
            adapter.search_tables(
                embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
            )
