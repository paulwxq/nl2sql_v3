"""llm_factory 单元测试

测试 get_llm() / _build_params() 的参数映射、校验逻辑和异常路径。
通过 patch get_config 隔离全局单例，确保每个 test case 独立控制配置内容。
"""

import pytest
from unittest.mock import MagicMock, patch

from src.services.llm_factory import (
    LLMWithMeta,
    _build_params,
    extract_overrides,
    get_llm,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    profiles: dict | None = None,
    providers: dict | None = None,
) -> MagicMock:
    """构造一个模拟 ConfigLoader 实例，支持 .get(key_path) 调用。"""
    if providers is None:
        providers = {
            "dashscope": {"api_key": "test-dashscope-key"},
        }
    if profiles is None:
        profiles = {
            "qwen_max": {"provider": "dashscope", "model": "qwen-max"},
        }

    store = {
        "llm_providers": providers,
        "llm_profiles": profiles,
    }

    mock_config = MagicMock()
    mock_config.get = lambda key_path, default=None: store.get(key_path, default)
    return mock_config


# ---------------------------------------------------------------------------
# _build_params — DashScope 分支
# ---------------------------------------------------------------------------

class TestBuildParamsDashScope:
    """DashScope provider 参数构建规则"""

    def test_basic_params(self):
        params = _build_params(
            "dashscope",
            {"api_key": "sk-xxx"},
            "qwen-max",
            {},
        )
        assert params == {
            "model": "qwen-max",
            "dashscope_api_key": "sk-xxx",
        }

    def test_temperature_routed_to_model_kwargs(self):
        params = _build_params(
            "dashscope",
            {"api_key": "sk-xxx"},
            "qwen-max",
            {"temperature": 0},
        )
        assert params["model_kwargs"] == {"temperature": 0}
        assert "temperature" not in params

    def test_max_tokens_routed_to_model_kwargs(self):
        params = _build_params(
            "dashscope",
            {"api_key": "sk-xxx"},
            "qwen-max",
            {"max_tokens": 2000},
        )
        assert params["model_kwargs"] == {"max_tokens": 2000}

    def test_temperature_and_max_tokens_combined(self):
        params = _build_params(
            "dashscope",
            {"api_key": "sk-xxx"},
            "qwen-max",
            {"temperature": 0.7, "max_tokens": 1500},
        )
        assert params["model_kwargs"] == {"temperature": 0.7, "max_tokens": 1500}

    def test_timeout_raises_error(self):
        with pytest.raises(ValueError, match="DashScope.*timeout"):
            _build_params(
                "dashscope",
                {"api_key": "sk-xxx"},
                "qwen-max",
                {"timeout": 30},
            )

    def test_no_model_kwargs_when_no_overrides(self):
        params = _build_params(
            "dashscope",
            {"api_key": "sk-xxx"},
            "qwen-max",
            {},
        )
        assert "model_kwargs" not in params


# ---------------------------------------------------------------------------
# _build_params — OpenAI 分支
# ---------------------------------------------------------------------------

class TestBuildParamsOpenAI:
    """OpenAI provider 参数构建规则"""

    def test_basic_params(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {},
        )
        assert params == {
            "model": "gpt-4",
            "api_key": "sk-openai",
        }

    def test_temperature_as_direct_field(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {"temperature": 0.5},
        )
        assert params["temperature"] == 0.5
        assert "model_kwargs" not in params

    def test_max_tokens_as_direct_field(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {"max_tokens": 4096},
        )
        assert params["max_tokens"] == 4096

    def test_timeout_mapped_to_request_timeout(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {"timeout": 60},
        )
        assert params["request_timeout"] == 60
        assert "timeout" not in params

    def test_base_url_included(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai", "base_url": "https://custom.api/v1"},
            "gpt-4",
            {},
        )
        assert params["base_url"] == "https://custom.api/v1"

    def test_all_overrides_combined(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {"temperature": 0.8, "max_tokens": 2048, "timeout": 30},
        )
        assert params["temperature"] == 0.8
        assert params["max_tokens"] == 2048
        assert params["request_timeout"] == 30


# ---------------------------------------------------------------------------
# _build_params — OpenRouter 分支（OpenAI 兼容）
# ---------------------------------------------------------------------------

class TestBuildParamsOpenRouter:
    """OpenRouter provider 参数构建规则（复用 ChatOpenAI，需 base_url）"""

    def test_basic_params_with_base_url(self):
        params = _build_params(
            "openrouter",
            {"api_key": "sk-or-xxx", "base_url": "https://openrouter.ai/api/v1"},
            "anthropic/claude-3.5-sonnet",
            {},
        )
        assert params == {
            "model": "anthropic/claude-3.5-sonnet",
            "api_key": "sk-or-xxx",
            "base_url": "https://openrouter.ai/api/v1",
        }

    def test_temperature_and_max_tokens_as_direct_fields(self):
        params = _build_params(
            "openrouter",
            {"api_key": "sk-or-xxx", "base_url": "https://openrouter.ai/api/v1"},
            "deepseek/deepseek-chat",
            {"temperature": 0.7, "max_tokens": 4096},
        )
        assert params["temperature"] == 0.7
        assert params["max_tokens"] == 4096
        assert "model_kwargs" not in params

    def test_timeout_mapped_to_request_timeout(self):
        params = _build_params(
            "openrouter",
            {"api_key": "sk-or-xxx", "base_url": "https://openrouter.ai/api/v1"},
            "meta-llama/llama-3-70b",
            {"timeout": 45},
        )
        assert params["request_timeout"] == 45
        assert "timeout" not in params

    def test_all_overrides_combined(self):
        params = _build_params(
            "openrouter",
            {"api_key": "sk-or-xxx", "base_url": "https://openrouter.ai/api/v1"},
            "anthropic/claude-3.5-sonnet",
            {"temperature": 0.5, "max_tokens": 2048, "timeout": 60},
        )
        assert params == {
            "model": "anthropic/claude-3.5-sonnet",
            "api_key": "sk-or-xxx",
            "base_url": "https://openrouter.ai/api/v1",
            "temperature": 0.5,
            "max_tokens": 2048,
            "request_timeout": 60,
        }


# ---------------------------------------------------------------------------
# _build_params — 白名单校验
# ---------------------------------------------------------------------------

class TestBuildParamsWhitelist:
    """Override 白名单校验"""

    def test_model_override_rejected(self):
        with pytest.raises(ValueError, match="不允许.*override"):
            _build_params("dashscope", {"api_key": "x"}, "qwen-max", {"model": "gpt-4"})

    def test_api_key_override_rejected(self):
        with pytest.raises(ValueError, match="不允许.*override"):
            _build_params("dashscope", {"api_key": "x"}, "qwen-max", {"api_key": "other"})

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError, match="不允许.*override"):
            _build_params("dashscope", {"api_key": "x"}, "qwen-max", {"foo": "bar"})


# ---------------------------------------------------------------------------
# _build_params — 不支持的 provider
# ---------------------------------------------------------------------------

class TestBuildParamsUnsupportedProvider:

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="不支持的 provider"):
            _build_params("anthropic", {"api_key": "x"}, "claude", {})


# ---------------------------------------------------------------------------
# get_llm — 正常路径
# ---------------------------------------------------------------------------

class TestGetLlmHappyPath:
    """get_llm 正常创建 LLM 实例"""

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_dashscope_profile(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config()

        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_import.return_value = mock_cls

        result = get_llm("qwen_max", temperature=0)

        assert isinstance(result, LLMWithMeta)
        assert result.llm is mock_instance
        assert result.provider == "dashscope"
        assert result.model == "qwen-max"

        mock_cls.assert_called_once_with(
            model="qwen-max",
            dashscope_api_key="test-dashscope-key",
            model_kwargs={"temperature": 0},
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_openai_profile(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config(
            providers={
                "openai": {
                    "api_key": "sk-openai",
                    "base_url": "https://api.openai.com/v1",
                },
            },
            profiles={
                "gpt4": {"provider": "openai", "model": "gpt-4"},
            },
        )

        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("gpt4", temperature=0.5, timeout=30)

        assert result.provider == "openai"
        assert result.model == "gpt-4"

        mock_cls.assert_called_once_with(
            model="gpt-4",
            api_key="sk-openai",
            base_url="https://api.openai.com/v1",
            temperature=0.5,
            request_timeout=30,
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_openrouter_profile(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config(
            providers={
                "openrouter": {
                    "api_key": "sk-or-xxx",
                    "base_url": "https://openrouter.ai/api/v1",
                },
            },
            profiles={
                "claude_sonnet": {
                    "provider": "openrouter",
                    "model": "anthropic/claude-3.5-sonnet",
                },
            },
        )

        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("claude_sonnet", temperature=0.3, max_tokens=4096)

        assert result.provider == "openrouter"
        assert result.model == "anthropic/claude-3.5-sonnet"

        mock_cls.assert_called_once_with(
            model="anthropic/claude-3.5-sonnet",
            api_key="sk-or-xxx",
            base_url="https://openrouter.ai/api/v1",
            temperature=0.3,
            max_tokens=4096,
        )


# ---------------------------------------------------------------------------
# get_llm — 配置校验（各种异常路径）
# ---------------------------------------------------------------------------

class TestGetLlmValidation:
    """get_llm 配置缺失 / 引用错误场景"""

    @patch("src.services.llm_factory.get_config")
    def test_missing_llm_profiles(self, mock_get_config):
        mock_get_config.return_value = _make_config(profiles=None)
        # profiles=None → store["llm_profiles"] = None
        mock_get_config.return_value.get = lambda k, d=None: (
            None if k == "llm_profiles" else {"dashscope": {"api_key": "x"}}.get(k, d)
        )
        with pytest.raises(ValueError, match="llm_profiles"):
            get_llm("qwen_max")

    @patch("src.services.llm_factory.get_config")
    def test_missing_llm_providers(self, mock_get_config):
        store = {
            "llm_profiles": {"qwen_max": {"provider": "dashscope", "model": "qwen-max"}},
            "llm_providers": None,
        }
        mock_cfg = MagicMock()
        mock_cfg.get = lambda k, d=None: store.get(k, d)
        mock_get_config.return_value = mock_cfg

        with pytest.raises(ValueError, match="llm_providers"):
            get_llm("qwen_max")

    @patch("src.services.llm_factory.get_config")
    def test_profile_not_found(self, mock_get_config):
        mock_get_config.return_value = _make_config()
        with pytest.raises(ValueError, match="不存在"):
            get_llm("nonexistent_profile")

    @patch("src.services.llm_factory.get_config")
    def test_profile_missing_provider_field(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            profiles={"bad": {"model": "qwen-max"}},
        )
        with pytest.raises(ValueError, match="provider"):
            get_llm("bad")

    @patch("src.services.llm_factory.get_config")
    def test_profile_missing_model_field(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            profiles={"bad": {"provider": "dashscope"}},
        )
        with pytest.raises(ValueError, match="model"):
            get_llm("bad")

    @patch("src.services.llm_factory.get_config")
    def test_provider_not_registered(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            profiles={"p": {"provider": "unknown_provider", "model": "m"}},
            providers={"unknown_provider": {"api_key": "x"}},
        )
        with pytest.raises(ValueError, match="不支持的 provider"):
            get_llm("p")

    @patch("src.services.llm_factory.get_config")
    def test_provider_not_in_providers_section(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            profiles={"p": {"provider": "ghost", "model": "m"}},
            providers={"dashscope": {"api_key": "x"}},
        )
        with pytest.raises(ValueError, match="不存在的 provider 'ghost'"):
            get_llm("p")

    @patch("src.services.llm_factory.get_config")
    def test_provider_missing_api_key(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            providers={"dashscope": {}},
        )
        with pytest.raises(ValueError, match="api_key"):
            get_llm("qwen_max")

    @patch("src.services.llm_factory.get_config")
    def test_provider_empty_api_key(self, mock_get_config):
        mock_get_config.return_value = _make_config(
            providers={"dashscope": {"api_key": ""}},
        )
        with pytest.raises(ValueError, match="api_key"):
            get_llm("qwen_max")

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_import_failure(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config()
        mock_import.side_effect = ImportError("No module named 'langchain_community'")

        with pytest.raises(ValueError, match="无法导入"):
            get_llm("qwen_max")


# ---------------------------------------------------------------------------
# extract_overrides 测试
# ---------------------------------------------------------------------------

class TestExtractOverrides:
    """测试 extract_overrides 从节点配置中提取允许的 override"""

    def test_extracts_temperature_only(self):
        config = {"llm_profile": "qwen_turbo", "temperature": 0, "log_decision": True}
        assert extract_overrides(config) == {"temperature": 0}

    def test_extracts_all_allowed(self):
        config = {"llm_profile": "qwen_max", "temperature": 0.3, "max_tokens": 2000, "timeout": 30}
        result = extract_overrides(config)
        assert result == {"temperature": 0.3, "max_tokens": 2000, "timeout": 30}

    def test_ignores_non_override_keys(self):
        config = {
            "llm_profile": "qwen_plus",
            "temperature": 0,
            "prompt": {"template_path": "..."},
            "strategy": {"prefer_explicit_joins": True},
        }
        assert extract_overrides(config) == {"temperature": 0}

    def test_empty_config(self):
        assert extract_overrides({}) == {}

    def test_no_matching_keys(self):
        config = {"llm_profile": "qwen_turbo", "log_decision": True}
        assert extract_overrides(config) == {}
