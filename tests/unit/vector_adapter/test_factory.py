"""向量检索适配器工厂函数测试"""

import pytest
from unittest.mock import Mock, patch
from src.services.vector_adapter.factory import create_vector_search_adapter
from src.services.vector_adapter.pgvector_adapter import PgVectorSearchAdapter
from src.services.vector_adapter.milvus_adapter import MilvusSearchAdapter


@pytest.fixture
def mock_get_config():
    """Mock get_config"""
    with patch("src.services.vector_adapter.factory.get_config") as mock:
        yield mock


@pytest.fixture
def pgvector_config():
    """PgVector 配置"""
    return {
        "vector_database": {
            "active": "pgvector",
            "providers": {
                "pgvector": {
                    "host": "localhost",
                    "database": "test_db",
                }
            },
        }
    }


@pytest.fixture
def milvus_config():
    """Milvus 配置"""
    return {
        "vector_database": {
            "active": "milvus",
            "providers": {
                "milvus": {
                    "host": "localhost",
                    "port": 19530,
                    "database": "nl2sql",
                }
            },
        }
    }


@pytest.fixture
def subgraph_config_with_milvus_params():
    """包含 Milvus 搜索参数的子图配置"""
    return {
        "schema_retrieval": {
            "milvus_search_params": {
                "metric_type": "COSINE",
                "params": {"ef": 100},
            }
        }
    }


class TestFactoryBasicFunctionality:
    """工厂函数基础功能测试"""

    @patch("src.services.vector_adapter.factory.PgVectorSearchAdapter")
    def test_create_pgvector_adapter(
        self, mock_pgvector_class, mock_get_config, pgvector_config
    ):
        """测试创建 PgVector 适配器"""
        mock_get_config.return_value = pgvector_config
        mock_instance = Mock()
        mock_pgvector_class.return_value = mock_instance

        adapter = create_vector_search_adapter()

        # 验证创建了 PgVector 适配器
        mock_pgvector_class.assert_called_once()
        assert adapter == mock_instance

    @patch("src.services.vector_adapter.factory.MilvusSearchAdapter")
    def test_create_milvus_adapter(
        self, mock_milvus_class, mock_get_config, milvus_config
    ):
        """测试创建 Milvus 适配器"""
        mock_get_config.return_value = milvus_config
        mock_instance = Mock()
        mock_milvus_class.return_value = mock_instance

        adapter = create_vector_search_adapter()

        # 验证创建了 Milvus 适配器
        mock_milvus_class.assert_called_once()
        assert adapter == mock_instance

    @patch("src.services.vector_adapter.factory.MilvusSearchAdapter")
    def test_milvus_adapter_with_search_params(
        self,
        mock_milvus_class,
        mock_get_config,
        milvus_config,
        subgraph_config_with_milvus_params,
    ):
        """测试创建 Milvus 适配器时传递搜索参数"""
        mock_get_config.return_value = milvus_config
        mock_instance = Mock()
        mock_milvus_class.return_value = mock_instance

        adapter = create_vector_search_adapter(subgraph_config_with_milvus_params)

        # 验证 Milvus 适配器被正确调用，包含搜索参数
        call_args = mock_milvus_class.call_args
        assert call_args.kwargs["config"] == milvus_config["vector_database"]
        assert call_args.kwargs["search_params"] == {
            "metric_type": "COSINE",
            "params": {"ef": 100},
        }


class TestFactoryErrorHandling:
    """工厂函数错误处理测试"""

    def test_missing_vector_database_config(self, mock_get_config):
        """测试缺少 vector_database 配置时抛出异常"""
        mock_get_config.return_value = {}  # 缺少 vector_database

        with pytest.raises(ValueError, match="缺少 vector_database 配置"):
            create_vector_search_adapter()

    def test_missing_active_field(self, mock_get_config):
        """测试缺少 active 字段时抛出异常"""
        mock_get_config.return_value = {
            "vector_database": {
                # 缺少 active 字段
                "providers": {"pgvector": {}}
            }
        }

        with pytest.raises(ValueError, match="缺少 vector_database.active 配置"):
            create_vector_search_adapter()

    def test_unsupported_vector_db_type(self, mock_get_config):
        """测试不支持的向量数据库类型时抛出异常"""
        mock_get_config.return_value = {
            "vector_database": {
                "active": "elasticsearch",  # 不支持的类型
                "providers": {},
            }
        }

        with pytest.raises(ValueError, match="不支持的向量数据库类型: elasticsearch"):
            create_vector_search_adapter()

    def test_empty_active_field(self, mock_get_config):
        """测试 active 字段为空时抛出异常"""
        mock_get_config.return_value = {
            "vector_database": {
                "active": "",  # 空字符串
                "providers": {},
            }
        }

        with pytest.raises(ValueError, match="缺少 vector_database.active 配置"):
            create_vector_search_adapter()

    def test_none_active_field(self, mock_get_config):
        """测试 active 字段为 None 时抛出异常"""
        mock_get_config.return_value = {
            "vector_database": {
                "active": None,
                "providers": {},
            }
        }

        with pytest.raises(ValueError, match="缺少 vector_database.active 配置"):
            create_vector_search_adapter()


class TestFactoryConfigPassing:
    """工厂函数配置传递测试"""

    @patch("src.services.vector_adapter.factory.PgVectorSearchAdapter")
    def test_pgvector_adapter_receives_correct_config(
        self, mock_pgvector_class, mock_get_config, pgvector_config
    ):
        """测试 PgVector 适配器接收正确的配置"""
        mock_get_config.return_value = pgvector_config

        create_vector_search_adapter()

        # 验证配置正确传递
        call_args = mock_pgvector_class.call_args
        assert call_args.args[0] == pgvector_config["vector_database"]

    @patch("src.services.vector_adapter.factory.MilvusSearchAdapter")
    def test_milvus_adapter_without_subgraph_config(
        self, mock_milvus_class, mock_get_config, milvus_config
    ):
        """测试没有子图配置时 Milvus 适配器使用默认搜索参数"""
        mock_get_config.return_value = milvus_config

        create_vector_search_adapter()  # 不传 subgraph_config

        # 验证 search_params 为 None（适配器内部会使用默认值）
        call_args = mock_milvus_class.call_args
        assert call_args.kwargs["search_params"] is None

    @patch("src.services.vector_adapter.factory.MilvusSearchAdapter")
    def test_milvus_adapter_with_empty_subgraph_config(
        self, mock_milvus_class, mock_get_config, milvus_config
    ):
        """测试空子图配置时 Milvus 适配器使用默认搜索参数"""
        mock_get_config.return_value = milvus_config

        create_vector_search_adapter(subgraph_config={})  # 空配置

        # 验证 search_params 为 None
        call_args = mock_milvus_class.call_args
        assert call_args.kwargs["search_params"] is None


class TestFactoryCaseSensitivity:
    """工厂函数大小写敏感性测试"""

    @patch("src.services.vector_adapter.factory.PgVectorSearchAdapter")
    def test_active_field_lowercase(
        self, mock_pgvector_class, mock_get_config, pgvector_config
    ):
        """测试 active 字段小写正确识别"""
        mock_get_config.return_value = pgvector_config

        create_vector_search_adapter()

        # 验证创建了 PgVector 适配器
        mock_pgvector_class.assert_called_once()

    @patch("src.services.vector_adapter.factory.MilvusSearchAdapter")
    def test_active_field_case_variations(
        self, mock_milvus_class, mock_get_config, milvus_config
    ):
        """测试 active 字段不同大小写（应严格匹配）"""
        # 测试大写
        milvus_config["vector_database"]["active"] = "MILVUS"
        mock_get_config.return_value = milvus_config

        # 应该抛出异常（不支持大写）
        with pytest.raises(ValueError, match="不支持的向量数据库类型: MILVUS"):
            create_vector_search_adapter()


class TestFactoryIntegration:
    """工厂函数集成测试（不使用 mock，测试真实创建）"""

    @patch("src.services.vector_adapter.pgvector_adapter.PGClient")
    def test_real_pgvector_adapter_creation(
        self, mock_pg_client_class, mock_get_config, pgvector_config
    ):
        """测试真实创建 PgVector 适配器"""
        mock_get_config.return_value = pgvector_config

        # Mock PGClient instance
        mock_pg_client_class.return_value = Mock()

        adapter = create_vector_search_adapter()

        # 验证返回的是 PgVectorSearchAdapter 实例
        assert isinstance(adapter, PgVectorSearchAdapter)

    @patch("src.services.vector_adapter.milvus_adapter.MilvusClient")
    @patch("src.services.vector_adapter.milvus_adapter.get_embedding_client")
    @patch("src.services.vector_adapter.milvus_adapter._lazy_import_milvus")
    def test_real_milvus_adapter_creation(
        self,
        mock_lazy_import,
        mock_embedding_client,
        mock_milvus_client,
        mock_get_config,
        milvus_config,
        subgraph_config_with_milvus_params,
    ):
        """测试真实创建 Milvus 适配器"""
        mock_get_config.return_value = milvus_config

        # Mock _lazy_import_milvus 返回
        Collection = Mock()
        mock_lazy_import.return_value = (None, None, None, None, Collection, None, None)

        # Mock MilvusClient
        client_instance = Mock()
        client_instance.alias = "default"
        mock_milvus_client.return_value = client_instance

        adapter = create_vector_search_adapter(subgraph_config_with_milvus_params)

        # 验证返回的是 MilvusSearchAdapter 实例
        assert isinstance(adapter, MilvusSearchAdapter)
        assert adapter.search_params["metric_type"] == "COSINE"
        assert adapter.search_params["params"]["ef"] == 100
