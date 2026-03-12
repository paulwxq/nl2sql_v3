"""column dimension 向量检索增强 单元测试

覆盖 docs/92_column维度文本向量检索增强设计.md 中 7.2 节定义的测试场景。
"""

from unittest.mock import MagicMock, patch, call
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Fixtures: 构造一个可测试的 SchemaRetriever（mock 掉所有外部依赖）
# ---------------------------------------------------------------------------

def _make_retriever(
    vector_client: MagicMock = None,
    embedding_client: MagicMock = None,
) -> Any:
    """构造 SchemaRetriever 实例，mock 掉外部客户端。"""
    config = {
        "schema_retrieval": {
            "topk_tables": 5,
            "topk_columns": 5,
            "dim_index_topk": 3,
            "dim_value_min_score": 0.0,
            "join_max_hops": 5,
            "similarity_threshold": 0.45,
            "table_category_mapping": {
                "fact": ["事实表", "交易表"],
                "dimension": ["维度表"],
                "bridge": ["桥接表"],
            },
        }
    }

    with patch("src.tools.schema_retrieval.retriever.get_pg_client"), \
         patch("src.tools.schema_retrieval.retriever.get_neo4j_client"), \
         patch("src.tools.schema_retrieval.retriever.get_embedding_client") as mock_emb, \
         patch("src.tools.schema_retrieval.retriever.create_vector_search_adapter") as mock_vec:

        mock_emb.return_value = embedding_client or MagicMock()
        mock_vec.return_value = vector_client or MagicMock()

        from src.tools.schema_retrieval.retriever import SchemaRetriever
        retriever = SchemaRetriever(config)

    # 确保 mock 被绑定到实例上
    if vector_client:
        retriever.vector_client = vector_client
    if embedding_client:
        retriever.embedding_client = embedding_client

    return retriever


def _make_column_hit(
    object_id: str,
    parent_id: str,
    similarity: float,
    table_category: str = "",
) -> Dict[str, Any]:
    """构造一条 search_columns 返回的列命中记录。"""
    return {
        "object_id": object_id,
        "parent_id": parent_id,
        "object_type": "column",
        "similarity": similarity,
        "table_category": table_category,
        "grain_hint": None,
    }


# ===========================================================================
# _retrieve_column_dimension_hits 测试
# ===========================================================================

class TestRetrieveColumnDimensionHits:
    """_retrieve_column_dimension_hits 方法测试"""

    def test_single_column_dimension(self):
        """单个 role='column' 维度：正确调用 embed_query + search_columns，父表进入结果"""
        embedding_client = MagicMock()
        embedding_client.embed_query.return_value = [0.1] * 128

        vector_client = MagicMock()
        vector_client.search_columns.return_value = [
            _make_column_hit("db.public.city.city", "db.public.city", 0.87),
        ]

        retriever = _make_retriever(vector_client, embedding_client)

        parse_result = {
            "dimensions": [
                {"text": "城市", "role": "column"},
            ]
        }
        hits = retriever._retrieve_column_dimension_hits(parse_result)

        assert len(hits) == 1
        assert hits[0]["parent_id"] == "db.public.city"
        assert hits[0]["source_dimension_text"] == "城市"
        embedding_client.embed_query.assert_called_once_with("城市")
        vector_client.search_columns.assert_called_once()

    def test_multiple_column_dimensions(self):
        """多个 role='column' 维度：每个独立检索，结果合并"""
        embedding_client = MagicMock()
        embedding_client.embed_query.return_value = [0.1] * 128

        vector_client = MagicMock()
        vector_client.search_columns.side_effect = [
            [_make_column_hit("db.public.city.city", "db.public.city", 0.87)],
            [_make_column_hit("db.public.staff.email", "db.public.staff", 0.72)],
        ]

        retriever = _make_retriever(vector_client, embedding_client)

        parse_result = {
            "dimensions": [
                {"text": "城市", "role": "column"},
                {"text": "邮箱", "role": "column"},
            ]
        }
        hits = retriever._retrieve_column_dimension_hits(parse_result)

        assert len(hits) == 2
        assert embedding_client.embed_query.call_count == 2
        assert vector_client.search_columns.call_count == 2
        # 验证 source_dimension_text 正确绑定
        assert hits[0]["source_dimension_text"] == "城市"
        assert hits[1]["source_dimension_text"] == "邮箱"

    def test_duplicate_column_text_dedup(self):
        """同一 role='column' 文本重复抽取：去重后只调用一次"""
        embedding_client = MagicMock()
        embedding_client.embed_query.return_value = [0.1] * 128

        vector_client = MagicMock()
        vector_client.search_columns.return_value = [
            _make_column_hit("db.public.city.city", "db.public.city", 0.87),
        ]

        retriever = _make_retriever(vector_client, embedding_client)

        parse_result = {
            "dimensions": [
                {"text": "城市", "role": "column"},
                {"text": "城市", "role": "column"},
            ]
        }
        hits = retriever._retrieve_column_dimension_hits(parse_result)

        assert len(hits) == 1
        embedding_client.embed_query.assert_called_once_with("城市")
        vector_client.search_columns.assert_called_once()

    def test_no_column_dimensions(self):
        """无 role='column' 维度：返回空列表，不影响现有流程"""
        embedding_client = MagicMock()
        vector_client = MagicMock()

        retriever = _make_retriever(vector_client, embedding_client)

        parse_result = {
            "dimensions": [
                {"text": "Mike Hillyer", "role": "value"},
            ]
        }
        hits = retriever._retrieve_column_dimension_hits(parse_result)

        assert hits == []
        embedding_client.embed_query.assert_not_called()
        vector_client.search_columns.assert_not_called()

    def test_none_parse_result(self):
        """parse_result 为 None：返回空列表"""
        retriever = _make_retriever()
        hits = retriever._retrieve_column_dimension_hits(None)
        assert hits == []

    def test_empty_dimensions(self):
        """dimensions 为空列表：返回空列表"""
        retriever = _make_retriever()
        hits = retriever._retrieve_column_dimension_hits({"dimensions": []})
        assert hits == []


# ===========================================================================
# _collect_and_classify_tables 中 column_dim_hits 集成测试
# ===========================================================================

class TestCollectAndClassifyWithColumnDim:
    """_collect_and_classify_tables 中 column_dim_hits 相关逻辑测试"""

    def _make_retriever_with_mocks(
        self,
        column_dim_hits: List[Dict] = None,
        fetch_categories_result: Dict[str, str] = None,
        dim_value_hits: List[Dict] = None,
    ):
        """构造 retriever 并 mock 内部方法。"""
        vector_client = MagicMock()
        vector_client.fetch_table_categories.return_value = fetch_categories_result or {}
        embedding_client = MagicMock()

        retriever = _make_retriever(vector_client, embedding_client)
        retriever._retrieve_dim_value_hits = MagicMock(return_value=dim_value_hits or [])
        retriever._retrieve_column_dimension_hits = MagicMock(return_value=column_dim_hits or [])
        return retriever

    def test_column_dim_hits_added_to_candidates(self):
        """column_dim_hits 的父表被加入候选集"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.87),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={"dimensions": [{"text": "城市", "role": "column"}]},
        )

        assert "db.public.city" in result["candidate_dim_tables"]

    def test_column_dim_hits_fact_classification(self):
        """column_dim_hits 父表按 table_category 归入事实表"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.sales.amount", "db.public.sales", 0.80),
                 "source_dimension_text": "金额"},
            ],
            fetch_categories_result={"db.public.sales": "事实表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={"dimensions": [{"text": "金额", "role": "column"}]},
        )

        assert "db.public.sales" in result["candidate_fact_tables"]
        assert "db.public.sales" not in result["candidate_dim_tables"]

    def test_same_parent_multiple_columns_similarity_max(self):
        """同一父表多列命中：table_similarities 取 max"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.72),
                 "source_dimension_text": "城市"},
                {**_make_column_hit("db.public.city.city_id", "db.public.city", 0.87),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={"dimensions": [{"text": "城市", "role": "column"}]},
        )

        assert result["table_similarities"]["db.public.city"] == 0.87

    def test_same_parent_dedup_in_candidates(self):
        """同一父表多列命中：候选表去重"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.72),
                 "source_dimension_text": "城市"},
                {**_make_column_hit("db.public.city.city_id", "db.public.city", 0.87),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        assert result["candidate_dim_tables"].count("db.public.city") == 1

    def test_table_category_three_layer_fallback_fetch_success(self):
        """table_category 补全：列记录为空 → fetch_table_categories 补全成功 → 正确分类"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.sales.amount", "db.public.sales", 0.80),
                 "source_dimension_text": "金额"},
            ],
            # fetch 返回事实表分类
            fetch_categories_result={"db.public.sales": "交易表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        # "交易表" 在 fact 映射中，应归入事实表
        assert "db.public.sales" in result["candidate_fact_tables"]
        # table_categories 也应包含
        assert result["table_categories"].get("db.public.sales") == "交易表"

    def test_table_category_three_layer_fallback_fetch_miss(self):
        """table_category 补全：fetch 也未返回 → 归为 dimension"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.unknown.col", "db.public.unknown", 0.60),
                 "source_dimension_text": "未知"},
            ],
            # fetch 返回空（该表不在 Milvus 中）
            fetch_categories_result={},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        # 空分类默认归为维度表
        assert "db.public.unknown" in result["candidate_dim_tables"]

    def test_fetch_partial_hit(self):
        """fetch_table_categories 部分命中：有分类的正确归类，无分类的归为 dimension"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.sales.amount", "db.public.sales", 0.80),
                 "source_dimension_text": "金额"},
                {**_make_column_hit("db.public.unknown.col", "db.public.unknown", 0.60),
                 "source_dimension_text": "未知"},
            ],
            fetch_categories_result={"db.public.sales": "事实表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        assert "db.public.sales" in result["candidate_fact_tables"]
        assert "db.public.unknown" in result["candidate_dim_tables"]

    def test_merge_with_semantic_tables_dedup(self):
        """与 semantic_tables 合并：dict.fromkeys 去重正确"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.72),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        # city 也出现在 semantic_tables 中
        semantic_tables = [
            {
                "object_id": "db.public.city",
                "object_type": "table",
                "similarity": 0.90,
                "table_category": "维度表",
            }
        ]

        result = retriever._collect_and_classify_tables(
            semantic_tables=semantic_tables,
            semantic_columns=[],
            parse_result={},
        )

        # 不应有重复
        assert result["candidate_dim_tables"].count("db.public.city") == 1
        # 表级检索分数（信号优先级高）应覆盖列级分数
        assert result["table_similarities"]["db.public.city"] == 0.90

    def test_merge_with_dim_tables_from_values_dedup(self):
        """与 dim_tables_from_values 合并：去重正确"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.72),
                 "source_dimension_text": "城市"},
            ],
            dim_value_hits=[
                {"dim_table": "db.public.city", "dim_col": "city", "matched_text": "北京", "score": 0.95},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        assert result["candidate_dim_tables"].count("db.public.city") == 1

    def test_column_dim_summary_structure(self):
        """column_dim_summary 包含正确的汇总信息"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.87),
                 "source_dimension_text": "城市"},
                {**_make_column_hit("db.public.address.city_id", "db.public.address", 0.72),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={
                "db.public.city": "维度表",
                "db.public.address": "维度表",
            },
        )

        result = retriever._collect_and_classify_tables(
            semantic_tables=[],
            semantic_columns=[],
            parse_result={},
        )

        summary = result["column_dim_summary"]
        assert "db.public.city" in summary
        assert "db.public.address" in summary
        assert summary["db.public.city"]["best_similarity"] == 0.87
        assert summary["db.public.city"]["source_texts"] == ["城市"]

    def test_table_level_similarity_overrides_column_level(self):
        """表级检索分数按信号优先级覆盖列级推导分数"""
        retriever = self._make_retriever_with_mocks(
            column_dim_hits=[
                {**_make_column_hit("db.public.city.city", "db.public.city", 0.95),
                 "source_dimension_text": "城市"},
            ],
            fetch_categories_result={"db.public.city": "维度表"},
        )

        # 表级检索返回较低分数（但信号优先级更高）
        semantic_tables = [
            {
                "object_id": "db.public.city",
                "object_type": "table",
                "similarity": 0.60,
                "table_category": "维度表",
            }
        ]

        result = retriever._collect_and_classify_tables(
            semantic_tables=semantic_tables,
            semantic_columns=[],
            parse_result={},
        )

        # 表级 0.60 应覆盖列级 0.95（按信号优先级，非数值大小）
        assert result["table_similarities"]["db.public.city"] == 0.60


# ===========================================================================
# metadata 统计口径测试
# ===========================================================================

class TestMetadataStatistics:
    """metadata.table_count / column_count 统计口径测试"""

    def test_table_count_includes_all_sources(self):
        """table_count 使用总去重后的候选表数量"""
        vector_client = MagicMock()
        vector_client.search_tables.return_value = [
            {"object_id": "db.public.staff", "object_type": "table",
             "similarity": 0.80, "table_category": "维度表"},
        ]
        vector_client.search_columns.return_value = []
        vector_client.fetch_table_categories.return_value = {"db.public.city": "维度表"}
        vector_client.fetch_table_cards.return_value = {}
        vector_client.search_similar_sqls.return_value = []

        embedding_client = MagicMock()
        embedding_client.embed_query.return_value = [0.1] * 128

        retriever = _make_retriever(vector_client, embedding_client)
        # Mock: column dimension backfill 补入 city 表
        original_collect = retriever._collect_and_classify_tables

        def patched_collect(semantic_tables, semantic_columns, parse_result):
            # 先调用真实方法
            result = original_collect(semantic_tables, semantic_columns, parse_result)
            return result

        # 直接 mock _retrieve_column_dimension_hits 来注入 column_dim_hits
        retriever._retrieve_column_dimension_hits = MagicMock(return_value=[
            {**_make_column_hit("db.public.city.city", "db.public.city", 0.87),
             "source_dimension_text": "城市"},
        ])
        retriever._retrieve_dim_value_hits = MagicMock(return_value=[])

        with patch.object(retriever, "neo4j_client"):
            retriever.neo4j_client.plan_join_paths.return_value = []
            schema_context = retriever.retrieve(
                query="测试查询",
                parse_result={"dimensions": [{"text": "城市", "role": "column"}]},
            )

        # staff 来自 semantic_tables，city 来自 column_dim backfill
        assert schema_context["metadata"]["table_count"] == 2

    def test_column_count_includes_column_dim_hits(self):
        """column_count 包含 column_dim_hits 的数量"""
        vector_client = MagicMock()
        vector_client.search_tables.return_value = []
        vector_client.search_columns.return_value = []  # 整句语义列召回 = 0
        vector_client.fetch_table_categories.return_value = {"db.public.city": "维度表"}
        vector_client.fetch_table_cards.return_value = {}
        vector_client.search_similar_sqls.return_value = []

        embedding_client = MagicMock()
        embedding_client.embed_query.return_value = [0.1] * 128

        retriever = _make_retriever(vector_client, embedding_client)
        # column_dim backfill 返回 2 条列命中
        retriever._retrieve_column_dimension_hits = MagicMock(return_value=[
            {**_make_column_hit("db.public.city.city", "db.public.city", 0.87),
             "source_dimension_text": "城市"},
            {**_make_column_hit("db.public.address.city_id", "db.public.address", 0.72),
             "source_dimension_text": "城市"},
        ])
        retriever._retrieve_dim_value_hits = MagicMock(return_value=[])

        with patch.object(retriever, "neo4j_client"):
            retriever.neo4j_client.plan_join_paths.return_value = []
            schema_context = retriever.retrieve(
                query="测试查询",
                parse_result={"dimensions": [{"text": "城市", "role": "column"}]},
            )

        # semantic_columns=0 + column_dim_hits=2
        assert schema_context["metadata"]["column_count"] == 2
