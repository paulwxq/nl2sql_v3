"""Milvus 适配器单元测试

重点测试：
1. COSINE 距离转换的"先raw过滤、再clamp"原则
2. 字段映射正确性（object_desc → text_raw, time_col_hint, grain_hint=None）
3. 配置验证（清晰失败原则）
4. JSON 序列化的精确查询
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from src.services.vector_adapter.milvus_adapter import MilvusSearchAdapter


@pytest.fixture
def valid_config():
    """有效的 Milvus 配置"""
    return {
        "providers": {
            "milvus": {
                "host": "localhost",
                "port": 19530,
                "database": "nl2sql",
                "user": "root",
                "password": "Milvus",
            }
        }
    }


@pytest.fixture
def search_params():
    """Milvus 搜索参数"""
    return {"metric_type": "COSINE", "params": {"ef": 100}}


@pytest.fixture
def mock_milvus_client():
    """Mock MilvusClient"""
    with patch("src.services.vector_adapter.milvus_adapter.MilvusClient") as mock:
        client_instance = Mock()
        client_instance.alias = "default"
        client_instance.connect = Mock()
        mock.return_value = client_instance
        yield client_instance


@pytest.fixture
def mock_collection():
    """Mock Milvus Collection"""
    collection = Mock()
    return collection


@pytest.fixture
def mock_embedding_client():
    """Mock Embedding Client"""
    with patch(
        "src.services.vector_adapter.milvus_adapter.get_embedding_client"
    ) as mock:
        client = Mock()
        client.embed_query.return_value = [0.1] * 768
        mock.return_value = client
        yield client


@pytest.fixture
def mock_lazy_import():
    """Mock _lazy_import_milvus"""
    with patch("src.services.vector_adapter.milvus_adapter._lazy_import_milvus") as mock:
        Collection = Mock()
        mock.return_value = (None, None, None, None, Collection, None, None)
        yield Collection


class TestMilvusAdapterInitialization:
    """Milvus 适配器初始化测试"""

    def test_valid_config_initialization(
        self, valid_config, search_params, mock_milvus_client, mock_lazy_import
    ):
        """测试有效配置初始化"""
        adapter = MilvusSearchAdapter(config=valid_config, search_params=search_params)

        assert adapter.config == valid_config
        assert adapter.search_params == search_params
        mock_milvus_client.connect.assert_called_once()

    def test_missing_milvus_config(self):
        """测试缺少 Milvus 配置时抛出异常"""
        config = {"providers": {}}  # 缺少 milvus 配置

        with pytest.raises(ValueError, match="Milvus 配置缺失"):
            MilvusSearchAdapter(config=config)

    def test_missing_required_fields(self):
        """测试缺少必需字段时抛出异常"""
        config = {
            "providers": {
                "milvus": {
                    "host": "localhost",
                    # 缺少 database 字段
                }
            }
        }

        with pytest.raises(ValueError, match="Milvus 配置不完整.*database"):
            MilvusSearchAdapter(config=config)

    def test_default_search_params(self, valid_config, mock_milvus_client, mock_lazy_import):
        """测试默认搜索参数"""
        adapter = MilvusSearchAdapter(config=valid_config)

        assert adapter.search_params["metric_type"] == "COSINE"
        assert adapter.search_params["params"]["ef"] == 100


class TestCOSINEDistanceConversion:
    """COSINE 距离转换测试（核心测试）"""

    @pytest.mark.parametrize(
        "distance,expected_raw,expected_clamped,should_pass_threshold",
        [
            (0.0, 1.0, 1.0, True),  # 完全相同
            (0.2, 0.8, 0.8, True),  # 高相似度
            (0.5, 0.5, 0.5, True),  # 阈值边界
            (1.0, 0.0, 0.0, True),  # 零相似度（边界情况，允许通过）
            (1.5, -0.5, 0.0, False),  # 负相似度（应被过滤）
            (2.0, -1.0, 0.0, False),  # 极端负相似度
        ],
    )
    def test_cosine_conversion_logic(
        self,
        distance,
        expected_raw,
        expected_clamped,
        should_pass_threshold,
    ):
        """测试 COSINE 距离转换逻辑（先raw过滤、再clamp）"""
        # 模拟转换逻辑
        raw_similarity = 1.0 - distance
        assert abs(raw_similarity - expected_raw) < 1e-10  # 允许浮点误差

        # 验证阈值过滤（使用 raw_similarity）
        threshold = 0.0
        passes_threshold = raw_similarity >= threshold
        assert passes_threshold == should_pass_threshold

        # 验证 clamp（用于返回值）
        similarity = max(0.0, min(1.0, raw_similarity))
        assert abs(similarity - expected_clamped) < 1e-10  # 允许浮点误差

    def test_negative_similarity_filtered_before_clamp(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试负相似度在 clamp 之前被过滤（关键测试）"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search() 返回负相似度结果
        mock_collection = Mock()
        mock_hit = Mock()
        mock_hit.distance = 1.2  # raw_similarity = -0.2
        mock_hit.entity = {
            "object_id": "public.table1",
            "object_type": "table",
            "table_category": "fact",
            "time_col_hint": "created_at",
        }

        mock_collection.search.return_value = [[mock_hit]]
        adapter._collection_table_schema = mock_collection

        # 调用 search_tables，阈值为 0
        results = adapter.search_tables(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.0
        )

        # 验证：负相似度应被过滤，结果为空
        assert len(results) == 0


class TestFieldMapping:
    """字段映射测试"""

    def test_fetch_table_cards_field_mapping(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 fetch_table_cards() 的字段映射（object_desc → text_raw）"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.query() 返回
        mock_collection = Mock()
        mock_collection.query.return_value = [
            {
                "object_id": "public.table1",
                "object_desc": "表1的描述信息",  # Milvus 字段
                "time_col_hint": "created_at",
                "table_category": "fact",
            }
        ]
        adapter._collection_table_schema = mock_collection

        # 调用 fetch_table_cards
        result = adapter.fetch_table_cards(table_names=["public.table1"])

        # 验证字段映射
        assert result["public.table1"]["text_raw"] == "表1的描述信息"
        assert result["public.table1"]["grain_hint"] is None  # Milvus 无此字段
        assert result["public.table1"]["time_col_hint"] == "created_at"
        assert result["public.table1"]["table_category"] == "fact"

    def test_search_tables_returns_time_col_hint(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 search_tables() 返回 time_col_hint 字段"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search()
        mock_collection = Mock()
        mock_hit = Mock()
        mock_hit.distance = 0.2  # similarity = 0.8
        mock_hit.entity = {
            "object_id": "public.fact_sales",
            "object_type": "table",
            "table_category": "fact",
            "time_col_hint": "sale_date",
        }
        mock_collection.search.return_value = [[mock_hit]]
        adapter._collection_table_schema = mock_collection

        # 调用 search_tables
        results = adapter.search_tables(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
        )

        # 验证 time_col_hint 被正确返回
        assert len(results) == 1
        assert results[0]["time_col_hint"] == "sale_date"
        assert results[0]["grain_hint"] is None  # Milvus 无此字段

    def test_search_columns_grain_hint_none(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 search_columns() 返回 grain_hint=None"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search()
        mock_collection = Mock()
        mock_hit = Mock()
        mock_hit.distance = 0.3  # similarity = 0.7
        mock_hit.entity = {
            "object_id": "public.table1.col1",
            "parent_id": "public.table1",
            "object_type": "column",
            "table_category": "fact",
        }
        mock_collection.search.return_value = [[mock_hit]]
        adapter._collection_table_schema = mock_collection

        # 调用 search_columns
        results = adapter.search_columns(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
        )

        # 验证 grain_hint=None
        assert len(results) == 1
        assert results[0]["grain_hint"] is None

    def test_search_dim_values_missing_key_fields(
        self, valid_config, mock_milvus_client, mock_lazy_import, mock_embedding_client
    ):
        """测试 search_dim_values() 不返回 key_col/key_value（Milvus 无此字段）"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search()
        mock_collection = Mock()
        mock_hit = Mock()
        mock_hit.distance = 0.15  # similarity = 0.85
        mock_hit.entity = {
            "table_name": "public.dim_city",
            "col_name": "city_name",
            "col_value": "北京市",
        }
        mock_collection.search.return_value = [[mock_hit]]
        adapter._collection_dim_value = mock_collection

        # 调用 search_dim_values
        results = adapter.search_dim_values(query_value="北京", top_k=5)

        # 验证：不返回 key_col/key_value
        assert len(results) == 1
        assert "key_col" not in results[0]
        assert "key_value" not in results[0]
        assert results[0]["dim_table"] == "public.dim_city"
        assert results[0]["dim_col"] == "city_name"
        assert results[0]["matched_text"] == "北京市"


class TestJSONSerialization:
    """JSON 序列化测试（精确查询安全性）"""

    def test_fetch_table_cards_json_serialization(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 fetch_table_cards() 使用 JSON 序列化"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.query()
        mock_collection = Mock()
        mock_collection.query.return_value = []
        adapter._collection_table_schema = mock_collection

        # 调用 fetch_table_cards
        table_names = ["public.table1", "public.table2"]
        adapter.fetch_table_cards(table_names=table_names)

        # 验证 expr 使用 JSON 序列化（双引号，而非单引号）
        call_args = mock_collection.query.call_args
        expr = call_args.kwargs["expr"]

        # 验证使用 JSON 格式（双引号列表）
        assert '["public.table1", "public.table2"]' in expr or \
               '["public.table2", "public.table1"]' in expr  # 顺序可能不同

    def test_fetch_table_categories_json_serialization(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 fetch_table_categories() 使用 JSON 序列化"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.query()
        mock_collection = Mock()
        mock_collection.query.return_value = []
        adapter._collection_table_schema = mock_collection

        # 调用 fetch_table_categories
        table_names = ["public.dim_store"]
        adapter.fetch_table_categories(table_names=table_names)

        # 验证 expr 使用 JSON 序列化
        call_args = mock_collection.query.call_args
        expr = call_args.kwargs["expr"]

        assert '["public.dim_store"]' in expr
        assert 'object_type == "table"' in expr


class TestSearchMethods:
    """搜索方法测试"""

    def test_search_similar_sqls_returns_empty(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试 search_similar_sqls() 返回空列表（暂不支持）"""
        adapter = MilvusSearchAdapter(config=valid_config)

        result = adapter.search_similar_sqls(
            embedding=[0.1] * 768, top_k=3, similarity_threshold=0.6
        )

        # 验证返回空列表
        assert result == []

    def test_search_dim_values_with_embedding(
        self, valid_config, mock_milvus_client, mock_lazy_import, mock_embedding_client
    ):
        """测试 search_dim_values() 对 query_value 进行向量化"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search()
        mock_collection = Mock()
        mock_collection.search.return_value = [[]]
        adapter._collection_dim_value = mock_collection

        # 调用 search_dim_values
        adapter.search_dim_values(query_value="测试值", top_k=5)

        # 验证 embedding_client.embed_query() 被调用
        mock_embedding_client.embed_query.assert_called_once_with("测试值")


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_table_names(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试空表名列表"""
        adapter = MilvusSearchAdapter(config=valid_config)

        result = adapter.fetch_table_cards(table_names=[])
        assert result == {}

        result = adapter.fetch_table_categories(table_names=[])
        assert result == {}

    def test_no_search_results(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试无搜索结果"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search() 返回空
        mock_collection = Mock()
        mock_collection.search.return_value = [[]]
        adapter._collection_table_schema = mock_collection

        results = adapter.search_tables(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
        )

        assert results == []

    def test_search_dim_values_with_min_score(
        self, valid_config, mock_milvus_client, mock_lazy_import, mock_embedding_client
    ):
        """测试 search_dim_values() 的 min_score 参数过滤低分结果"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock 搜索结果（包含高分和低分）
        mock_hit_high = Mock()
        mock_hit_high.distance = 0.2  # distance=0.2 → raw_similarity=0.8
        mock_hit_high.entity = {
            "table_name": "dim_store",
            "col_name": "store_name",
            "col_value": "京东便利店",
        }

        mock_hit_low = Mock()
        mock_hit_low.distance = 0.7  # distance=0.7 → raw_similarity=0.3
        mock_hit_low.entity = {
            "table_name": "dim_store",
            "col_name": "store_name",
            "col_value": "京东",
        }

        mock_collection = Mock()
        mock_collection.search.return_value = [[mock_hit_high, mock_hit_low]]
        adapter._collection_dim_value = mock_collection

        # 调用 search_dim_values（min_score=0.5，应该过滤掉低分结果）
        results = adapter.search_dim_values(
            query_value="京东便利店", top_k=5, min_score=0.5
        )

        # 验证只返回高分结果
        assert len(results) == 1
        assert results[0]["matched_text"] == "京东便利店"
        assert results[0]["score"] == 0.8  # 0.8 >= 0.5，通过

    def test_search_dim_values_default_min_score(
        self, valid_config, mock_milvus_client, mock_lazy_import, mock_embedding_client
    ):
        """测试 search_dim_values() 默认 min_score=0.0（不过滤）"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock 搜索结果（包含正相似度和负相似度）
        mock_hit_positive = Mock()
        mock_hit_positive.distance = 0.9  # distance=0.9 → raw_similarity=0.1
        mock_hit_positive.entity = {
            "table_name": "dim_store",
            "col_name": "store_name",
            "col_value": "京东",
        }

        mock_hit_negative = Mock()
        mock_hit_negative.distance = 1.2  # distance=1.2 → raw_similarity=-0.2
        mock_hit_negative.entity = {
            "table_name": "dim_store",
            "col_name": "store_name",
            "col_value": "无关文本",
        }

        mock_collection = Mock()
        mock_collection.search.return_value = [[mock_hit_positive, mock_hit_negative]]
        adapter._collection_dim_value = mock_collection

        # 调用 search_dim_values（默认 min_score=0.0，但负相似度仍会被过滤）
        results = adapter.search_dim_values(query_value="京东", top_k=5)

        # 验证只返回正相似度结果
        assert len(results) == 1
        assert results[0]["matched_text"] == "京东"
        assert abs(results[0]["score"] - 0.1) < 1e-10  # 0.1 >= 0.0，通过（浮点误差容忍）

    def test_similarity_threshold_filtering(
        self, valid_config, mock_milvus_client, mock_lazy_import
    ):
        """测试相似度阈值过滤"""
        adapter = MilvusSearchAdapter(config=valid_config)

        # Mock Collection.search() 返回多个结果
        mock_collection = Mock()
        hit1 = Mock()
        hit1.distance = 0.1  # similarity = 0.9
        hit1.entity = {
            "object_id": "public.table1",
            "object_type": "table",
            "table_category": "fact",
            "time_col_hint": "created_at",
        }

        hit2 = Mock()
        hit2.distance = 0.6  # similarity = 0.4
        hit2.entity = {
            "object_id": "public.table2",
            "object_type": "table",
            "table_category": "dimension",
            "time_col_hint": None,
        }

        mock_collection.search.return_value = [[hit1, hit2]]
        adapter._collection_table_schema = mock_collection

        # 调用 search_tables，阈值为 0.5
        results = adapter.search_tables(
            embedding=[0.1] * 768, top_k=10, similarity_threshold=0.5
        )

        # 验证：只有 hit1 通过阈值
        assert len(results) == 1
        assert results[0]["object_id"] == "public.table1"
        assert results[0]["similarity"] == pytest.approx(0.9, abs=0.01)
