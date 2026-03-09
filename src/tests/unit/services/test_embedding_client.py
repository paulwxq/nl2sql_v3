"""EmbeddingClient 配置加载单元测试

测试 _load_profile_config() 从 embedding_profiles + llm_providers 解析配置的逻辑。
通过 patch get_config 隔离全局单例，确保每个 test case 独立控制配置内容。
"""

import pytest
from unittest.mock import MagicMock, patch


def _make_config(
    *,
    embedding_profiles: dict | None = None,
    providers: dict | None = None,
) -> MagicMock:
    """构造一个模拟 ConfigLoader 实例。"""
    if providers is None:
        providers = {
            "dashscope": {"api_key": "test-dashscope-key"},
        }
    if embedding_profiles is None:
        embedding_profiles = {
            "active": "text_embedding_v3",
            "text_embedding_v3": {
                "provider": "dashscope",
                "model": "text-embedding-v3",
                "dimensions": 1024,
                "batch_size": 20,
                "timeout": 30,
                "max_retries": 3,
            },
        }

    store = {
        "embedding_profiles": embedding_profiles,
        "llm_providers": providers,
    }

    mock_config = MagicMock()
    mock_config.get = lambda key_path, default=None: store.get(key_path, default)
    mock_config.__getitem__ = lambda self, key: store[key]
    return mock_config


class TestLoadProfileConfig:
    """测试 _load_profile_config 正常路径和异常校验"""

    @patch("src.services.embedding.embedding_client.dashscope")
    @patch("src.services.embedding.embedding_client.get_config")
    def test_happy_path(self, mock_get_config, mock_dashscope):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config()

        profile = EmbeddingClient._load_profile_config()

        assert profile["model"] == "text-embedding-v3"
        assert profile["dimensions"] == 1024
        assert profile["batch_size"] == 20
        assert profile["provider"] == "dashscope"
        mock_dashscope.api_key = "test-dashscope-key"

    @patch("src.services.embedding.embedding_client.get_config")
    def test_missing_embedding_profiles(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(embedding_profiles=None)
        mock_get_config.return_value.get = lambda k, d=None: (
            None if k == "embedding_profiles" else d
        )

        with pytest.raises(ValueError, match="embedding_profiles"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_missing_active_field(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            embedding_profiles={
                "text_embedding_v3": {
                    "provider": "dashscope",
                    "model": "text-embedding-v3",
                },
            }
        )

        with pytest.raises(ValueError, match="active"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_active_profile_not_found(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            embedding_profiles={
                "active": "nonexistent",
                "text_embedding_v3": {
                    "provider": "dashscope",
                    "model": "text-embedding-v3",
                },
            }
        )

        with pytest.raises(ValueError, match="nonexistent"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_missing_provider_field(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            embedding_profiles={
                "active": "bad_profile",
                "bad_profile": {"model": "text-embedding-v3"},
            }
        )

        with pytest.raises(ValueError, match="provider"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_provider_not_in_llm_providers(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            embedding_profiles={
                "active": "test",
                "test": {"provider": "ghost", "model": "m"},
            },
            providers={"dashscope": {"api_key": "x"}},
        )

        with pytest.raises(ValueError, match="ghost"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_provider_missing_api_key(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            providers={"dashscope": {}},
        )

        with pytest.raises(ValueError, match="api_key"):
            EmbeddingClient._load_profile_config()

    @patch("src.services.embedding.embedding_client.get_config")
    def test_provider_empty_api_key(self, mock_get_config):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            providers={"dashscope": {"api_key": ""}},
        )

        with pytest.raises(ValueError, match="api_key"):
            EmbeddingClient._load_profile_config()


class TestEmbeddingClientInit:
    """测试 EmbeddingClient 初始化"""

    @patch("src.services.embedding.embedding_client.dashscope")
    @patch("src.services.embedding.embedding_client.get_config")
    def test_init_from_global_config(self, mock_get_config, mock_dashscope):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config()

        client = EmbeddingClient()

        assert client.model == "text-embedding-v3"
        assert client.dimensions == 1024
        assert client.batch_size == 20
        assert client.timeout == 30
        assert client.max_retries == 3

    def test_init_with_explicit_config(self):
        """直接传入 config 字典时不读取全局配置"""
        from src.services.embedding.embedding_client import EmbeddingClient

        config = {
            "model": "custom-embedding",
            "dimensions": 512,
            "batch_size": 10,
            "timeout": 15,
            "max_retries": 2,
        }

        client = EmbeddingClient(config=config)

        assert client.model == "custom-embedding"
        assert client.dimensions == 512
        assert client.batch_size == 10

    @patch("src.services.embedding.embedding_client.dashscope")
    @patch("src.services.embedding.embedding_client.get_config")
    def test_defaults_when_optional_fields_missing(self, mock_get_config, mock_dashscope):
        from src.services.embedding.embedding_client import EmbeddingClient

        mock_get_config.return_value = _make_config(
            embedding_profiles={
                "active": "minimal",
                "minimal": {"provider": "dashscope"},
            }
        )

        client = EmbeddingClient()

        assert client.model == "text-embedding-v3"
        assert client.dimensions == 1024
        assert client.batch_size == 20
        assert client.timeout == 30
        assert client.max_retries == 3
