"""llm_factory 单元测试

测试 get_llm() / _build_params() 的参数映射、校验逻辑和异常路径。
通过 patch get_config 隔离全局单例，确保每个 test case 独立控制配置内容。
"""

import pytest
from unittest.mock import MagicMock, patch

from src.services.llm_factory import (
    LLMWithMeta,
    _build_params,
    extract_llm_content,
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

    def test_top_p_routed_to_model_kwargs(self):
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-max", {"top_p": 0.9},
        )
        assert params["model_kwargs"] == {"top_p": 0.9}

    def test_enable_thinking_routed_to_model_kwargs(self):
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus", {"enable_thinking": True},
        )
        assert params["model_kwargs"] == {"enable_thinking": True}

    def test_enable_search_routed_to_model_kwargs(self):
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus", {"enable_search": True},
        )
        assert params["model_kwargs"] == {"enable_search": True}

    def test_search_options_routed_to_model_kwargs(self):
        opts = {"enable_source": True, "forced_search": True, "search_strategy": "max"}
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus",
            {"enable_search": True, "search_options": opts},
        )
        assert params["model_kwargs"]["enable_search"] is True
        assert params["model_kwargs"]["search_options"] == opts

    def test_response_format_routed_to_model_kwargs(self):
        fmt = {"type": "json_object"}
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus", {"response_format": fmt},
        )
        assert params["model_kwargs"] == {"response_format": fmt}

    def test_stream_mapped_to_streaming(self):
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus", {"stream": True},
        )
        assert params["streaming"] is True
        assert "stream" not in params
        assert "model_kwargs" not in params

    def test_all_dashscope_overrides_combined(self):
        params = _build_params(
            "dashscope", {"api_key": "sk-xxx"}, "qwen-plus",
            {
                "temperature": 0.6,
                "max_tokens": 4096,
                "top_p": 0.95,
                "enable_thinking": True,
                "enable_search": True,
                "search_options": {"forced_search": True},
                "response_format": {"type": "text"},
                "stream": True,
            },
        )
        assert params["streaming"] is True
        assert params["model_kwargs"] == {
            "temperature": 0.6,
            "max_tokens": 4096,
            "top_p": 0.95,
            "enable_thinking": True,
            "enable_search": True,
            "search_options": {"forced_search": True},
            "response_format": {"type": "text"},
        }

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

    def test_top_p_as_direct_field(self):
        params = _build_params(
            "openai", {"api_key": "sk-openai"}, "gpt-4", {"top_p": 0.9},
        )
        assert params["top_p"] == 0.9

    def test_stream_mapped_to_streaming(self):
        params = _build_params(
            "openai", {"api_key": "sk-openai"}, "gpt-4", {"stream": True},
        )
        assert params["streaming"] is True
        assert "stream" not in params

    def test_response_format_as_direct_field(self):
        fmt = {"type": "json_object"}
        params = _build_params(
            "openai", {"api_key": "sk-openai"}, "gpt-4", {"response_format": fmt},
        )
        assert params["response_format"] == fmt

    def test_all_overrides_combined(self):
        params = _build_params(
            "openai",
            {"api_key": "sk-openai"},
            "gpt-4",
            {"temperature": 0.8, "max_tokens": 2048, "timeout": 30, "top_p": 0.9},
        )
        assert params["temperature"] == 0.8
        assert params["max_tokens"] == 2048
        assert params["request_timeout"] == 30
        assert params["top_p"] == 0.9

    def test_dashscope_only_params_rejected(self):
        with pytest.raises(ValueError, match="仅适用于 DashScope"):
            _build_params(
                "openai", {"api_key": "sk-openai"}, "gpt-4",
                {"enable_thinking": True},
            )

    def test_dashscope_only_search_rejected(self):
        with pytest.raises(ValueError, match="仅适用于 DashScope"):
            _build_params(
                "openai", {"api_key": "sk-openai"}, "gpt-4",
                {"enable_search": True, "search_options": {"forced_search": True}},
            )


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

    def test_dashscope_only_params_rejected_on_openrouter(self):
        with pytest.raises(ValueError, match="仅适用于 DashScope"):
            _build_params(
                "openrouter",
                {"api_key": "sk-or-xxx", "base_url": "https://openrouter.ai/api/v1"},
                "deepseek/deepseek-chat",
                {"enable_thinking": True},
            )


# ---------------------------------------------------------------------------
# _build_params — DeepSeek 分支
# ---------------------------------------------------------------------------

class TestBuildParamsDeepSeek:
    """DeepSeek provider 参数构建规则"""

    _provider_cfg = {"api_key": "sk-ds-xxx", "base_url": "https://api.deepseek.com"}

    def test_basic_params(self):
        params = _build_params("deepseek", self._provider_cfg, "deepseek-chat", {})
        assert params == {
            "model": "deepseek-chat",
            "api_key": "sk-ds-xxx",
            "base_url": "https://api.deepseek.com",
        }

    def test_temperature_as_direct_field(self):
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-chat", {"temperature": 0}
        )
        assert params["temperature"] == 0
        assert "model_kwargs" not in params

    def test_max_tokens_as_direct_field(self):
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-chat", {"max_tokens": 8192}
        )
        assert params["max_tokens"] == 8192

    def test_top_p_as_direct_field(self):
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-chat", {"top_p": 0.9}
        )
        assert params["top_p"] == 0.9

    def test_timeout_mapped_to_request_timeout(self):
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-chat", {"timeout": 60}
        )
        assert params["request_timeout"] == 60
        assert "timeout" not in params

    def test_stream_mapped_to_streaming(self):
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-chat", {"stream": True}
        )
        assert params["streaming"] is True
        assert "stream" not in params

    def test_thinking_via_extra_body(self):
        """thinking 参数必须通过 extra_body 传入，不能放 model_kwargs"""
        params = _build_params(
            "deepseek",
            self._provider_cfg,
            "deepseek-chat",
            {"thinking": {"type": "enabled"}},
        )
        assert params["extra_body"] == {"thinking": {"type": "enabled"}}
        assert "model_kwargs" not in params
        assert "thinking" not in params

    def test_no_thinking_no_extra_body(self):
        """不传 thinking 时不应产生 extra_body 字段"""
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-reasoner", {}
        )
        assert "extra_body" not in params

    def test_deepseek_reasoner_with_max_tokens(self):
        """deepseek-reasoner 常见用法：只设 max_tokens，不设 temperature"""
        params = _build_params(
            "deepseek", self._provider_cfg, "deepseek-reasoner", {"max_tokens": 32768}
        )
        assert params["max_tokens"] == 32768
        assert "temperature" not in params
        assert "extra_body" not in params

    def test_all_overrides_combined(self):
        params = _build_params(
            "deepseek",
            self._provider_cfg,
            "deepseek-chat",
            {
                "temperature": 0,
                "max_tokens": 8192,
                "top_p": 0.95,
                "timeout": 60,
                "stream": True,
                "response_format": {"type": "json_object"},
            },
        )
        assert params["temperature"] == 0
        assert params["max_tokens"] == 8192
        assert params["top_p"] == 0.95
        assert params["request_timeout"] == 60
        assert params["streaming"] is True
        assert params["response_format"] == {"type": "json_object"}
        assert "extra_body" not in params

    def test_dashscope_only_params_rejected(self):
        with pytest.raises(ValueError, match="仅适用于 DashScope"):
            _build_params(
                "deepseek", self._provider_cfg, "deepseek-chat", {"enable_thinking": True}
            )

    def test_dashscope_search_rejected(self):
        with pytest.raises(ValueError, match="仅适用于 DashScope"):
            _build_params(
                "deepseek", self._provider_cfg, "deepseek-chat", {"enable_search": True}
            )

    def test_thinking_rejected_on_openai(self):
        """thinking 参数传给 openai provider 应报错"""
        with pytest.raises(ValueError, match="仅适用于 DeepSeek"):
            _build_params(
                "openai",
                {"api_key": "sk-openai"},
                "gpt-4",
                {"thinking": {"type": "enabled"}},
            )

    def test_thinking_rejected_on_openrouter(self):
        """thinking 参数传给 openrouter provider 应报错"""
        with pytest.raises(ValueError, match="仅适用于 DeepSeek"):
            _build_params(
                "openrouter",
                {"api_key": "sk-or", "base_url": "https://openrouter.ai/api/v1"},
                "meta-llama/llama-3",
                {"thinking": {"type": "enabled"}},
            )


class TestGetLlmDeepSeek:
    """get_llm 完整流程 — DeepSeek provider"""

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_deepseek_chat_basic(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config(
            providers={
                "deepseek": {
                    "api_key": "sk-ds-xxx",
                    "base_url": "https://api.deepseek.com",
                },
            },
            profiles={
                "deepseek_chat": {"provider": "deepseek", "model": "deepseek-chat"},
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("deepseek_chat", temperature=0, max_tokens=8192)

        assert result.provider == "deepseek"
        assert result.model == "deepseek-chat"
        mock_cls.assert_called_once_with(
            model="deepseek-chat",
            api_key="sk-ds-xxx",
            base_url="https://api.deepseek.com",
            temperature=0,
            max_tokens=8192,
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_deepseek_reasoner_no_temperature(self, mock_get_config, mock_import):
        """deepseek-reasoner profile 不配置 temperature，构造参数中不应含 temperature"""
        mock_get_config.return_value = _make_config(
            providers={
                "deepseek": {
                    "api_key": "sk-ds-xxx",
                    "base_url": "https://api.deepseek.com",
                },
            },
            profiles={
                "deepseek_reasoner": {
                    "provider": "deepseek",
                    "model": "deepseek-reasoner",
                    "max_tokens": 32768,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("deepseek_reasoner")

        assert result.provider == "deepseek"
        assert result.model == "deepseek-reasoner"
        mock_cls.assert_called_once_with(
            model="deepseek-reasoner",
            api_key="sk-ds-xxx",
            base_url="https://api.deepseek.com",
            max_tokens=32768,
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_deepseek_chat_thinking_profile(self, mock_get_config, mock_import):
        """profile 中配置 thinking 参数，应通过 extra_body 传入"""
        mock_get_config.return_value = _make_config(
            providers={
                "deepseek": {
                    "api_key": "sk-ds-xxx",
                    "base_url": "https://api.deepseek.com",
                },
            },
            profiles={
                "deepseek_chat_thinking": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "thinking": {"type": "enabled"},
                    "max_tokens": 32768,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        get_llm("deepseek_chat_thinking")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
        assert call_kwargs["max_tokens"] == 32768
        assert "model_kwargs" not in call_kwargs


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

class TestBuildParamsAutoDetected:
    """自动检测的 provider（不在 _PROVIDER_MAP 中）走 OpenAI 兼容路径"""

    _provider_cfg = {
        "api_key": "sk-ds-xxx",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }

    def test_basic_params(self):
        params = _build_params(
            "dashscope_openai", self._provider_cfg, "qwen3.5-plus", {},
        )
        assert params == {
            "model": "qwen3.5-plus",
            "api_key": "sk-ds-xxx",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }

    def test_enable_thinking_passthrough_via_extra_body(self):
        """自动检测的 provider 允许 enable_thinking，透传为 extra_body"""
        params = _build_params(
            "dashscope_openai", self._provider_cfg, "qwen3.5-plus",
            {"enable_thinking": False},
        )
        assert params["extra_body"] == {"enable_thinking": False}
        assert "enable_thinking" not in params.get("model_kwargs", {})

    def test_enable_search_passthrough_via_extra_body(self):
        params = _build_params(
            "dashscope_openai", self._provider_cfg, "qwen3.5-plus",
            {"enable_search": True, "search_options": {"forced_search": True}},
        )
        assert params["extra_body"] == {
            "enable_search": True,
            "search_options": {"forced_search": True},
        }

    def test_temperature_as_direct_field(self):
        params = _build_params(
            "dashscope_openai", self._provider_cfg, "qwen3.5-plus",
            {"temperature": 0},
        )
        assert params["temperature"] == 0
        assert "extra_body" not in params

    def test_all_overrides_combined(self):
        params = _build_params(
            "dashscope_openai", self._provider_cfg, "qwen3.5-plus",
            {
                "temperature": 0,
                "max_tokens": 4096,
                "enable_thinking": False,
                "timeout": 60,
                "stream": True,
            },
        )
        assert params["temperature"] == 0
        assert params["max_tokens"] == 4096
        assert params["request_timeout"] == 60
        assert params["streaming"] is True
        assert params["extra_body"] == {"enable_thinking": False}

    def test_thinking_rejected_on_auto_detected(self):
        """DeepSeek thinking 参数对自动检测的 provider 仍应报错"""
        with pytest.raises(ValueError, match="仅适用于 DeepSeek"):
            _build_params(
                "dashscope_openai", self._provider_cfg, "qwen3.5-plus",
                {"thinking": {"type": "enabled"}},
            )


class TestBuildParamsUnsupportedProvider:

    def test_unknown_provider_raises(self):
        """不在 _PROVIDER_MAP 且无 base_url 的 provider 在 get_llm 阶段报错，
        但 _build_params 的 else 分支仍可处理（由 get_llm 网关控制）"""
        # _build_params 的 else 分支现在是 OpenAI 兼容路径，
        # 不再有 "不支持的 provider" 错误；由 get_llm 网关控制
        params = _build_params("anthropic", {"api_key": "x"}, "claude", {})
        assert params["model"] == "claude"
        assert params["api_key"] == "x"


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
# get_llm — 自动检测的 provider（OpenAI 兼容模式）
# ---------------------------------------------------------------------------

class TestGetLlmAutoDetected:
    """get_llm 完整流程 — 自动检测的 provider（如 dashscope_openai）"""

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_dashscope_openai_basic(self, mock_get_config, mock_import):
        mock_get_config.return_value = _make_config(
            providers={
                "dashscope_openai": {
                    "api_key": "sk-ds-xxx",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                },
            },
            profiles={
                "qwen3_5_plus": {
                    "provider": "dashscope_openai",
                    "model": "qwen3.5-plus",
                    "enable_thinking": False,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("qwen3_5_plus", temperature=0, max_tokens=100)

        assert result.provider == "dashscope_openai"
        assert result.model == "qwen3.5-plus"
        mock_import.assert_called_once_with("langchain_openai", "ChatOpenAI")
        mock_cls.assert_called_once_with(
            model="qwen3.5-plus",
            api_key="sk-ds-xxx",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0,
            max_tokens=100,
            extra_body={"enable_thinking": False},
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_auto_detected_no_base_url_raises(self, mock_get_config, mock_import):
        """未注册 provider + 无 base_url → 报错"""
        mock_get_config.return_value = _make_config(
            providers={
                "custom_provider": {"api_key": "sk-xxx"},
            },
            profiles={
                "custom": {"provider": "custom_provider", "model": "some-model"},
            },
        )
        with pytest.raises(ValueError, match="base_url"):
            get_llm("custom")


# ---------------------------------------------------------------------------
# get_llm — profile 级参数默认值
# ---------------------------------------------------------------------------

class TestGetLlmProfileDefaults:
    """profile 中除 provider/model 外的字段作为参数默认值"""

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_profile_defaults_applied(self, mock_get_config, mock_import):
        """profile 定义了 temperature/top_p，调用时不传 override 应使用 profile 值"""
        mock_get_config.return_value = _make_config(
            profiles={
                "qwen_plus_thinking": {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "enable_thinking": True,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        get_llm("qwen_plus_thinking")

        mock_cls.assert_called_once_with(
            model="qwen-plus",
            dashscope_api_key="test-dashscope-key",
            model_kwargs={
                "temperature": 0.6,
                "top_p": 0.95,
                "enable_thinking": True,
            },
        )

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_node_override_wins_over_profile_default(self, mock_get_config, mock_import):
        """节点 override 优先级高于 profile 默认值"""
        mock_get_config.return_value = _make_config(
            profiles={
                "qwen_plus_hot": {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "temperature": 0.9,
                    "top_p": 0.95,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        get_llm("qwen_plus_hot", temperature=0)

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model_kwargs"]["temperature"] == 0
        assert call_kwargs["model_kwargs"]["top_p"] == 0.95

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_profile_with_search_options(self, mock_get_config, mock_import):
        """profile 中配置 enable_search + search_options 嵌套对象"""
        mock_get_config.return_value = _make_config(
            profiles={
                "qwen_search": {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "enable_search": True,
                    "search_options": {
                        "enable_source": True,
                        "search_strategy": "turbo",
                    },
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        get_llm("qwen_search")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model_kwargs"]["enable_search"] is True
        assert call_kwargs["model_kwargs"]["search_options"] == {
            "enable_source": True,
            "search_strategy": "turbo",
        }

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_profile_with_stream(self, mock_get_config, mock_import):
        """profile 级 stream 参数映射为 streaming 构造参数"""
        mock_get_config.return_value = _make_config(
            profiles={
                "qwen_stream": {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "stream": True,
                },
            },
        )
        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        get_llm("qwen_stream")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["streaming"] is True
        assert "stream" not in call_kwargs

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_profile_invalid_override_rejected(self, mock_get_config, mock_import):
        """profile 中含非白名单字段应被 _build_params 拒绝"""
        mock_get_config.return_value = _make_config(
            profiles={
                "bad_profile": {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "api_key": "sneaky-override",
                },
            },
        )
        mock_import.return_value = MagicMock()

        with pytest.raises(ValueError, match="不允许.*override"):
            get_llm("bad_profile")


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
    def test_provider_not_registered_no_base_url(self, mock_get_config):
        """未注册的 provider 且无 base_url 应报错并提示配置 base_url"""
        mock_get_config.return_value = _make_config(
            profiles={"p": {"provider": "unknown_provider", "model": "m"}},
            providers={"unknown_provider": {"api_key": "x"}},
        )
        with pytest.raises(ValueError, match="base_url"):
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

    def test_extracts_new_dashscope_params(self):
        config = {
            "llm_profile": "qwen_plus",
            "top_p": 0.9,
            "enable_thinking": True,
            "enable_search": True,
            "search_options": {"forced_search": True},
            "response_format": {"type": "json_object"},
            "stream": True,
            "unrelated_key": "ignored",
        }
        result = extract_overrides(config)
        assert result == {
            "top_p": 0.9,
            "enable_thinking": True,
            "enable_search": True,
            "search_options": {"forced_search": True},
            "response_format": {"type": "json_object"},
            "stream": True,
        }

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


# ---------------------------------------------------------------------------
# extract_llm_content 测试
# ---------------------------------------------------------------------------

class TestExtractLlmContent:
    """extract_llm_content 从 LLM 响应中提取干净文本。

    测试覆盖：
    - 无 think 标签时透传（不启用 thinking 的常规场景）
    - 剥离单个 <think>...</think> 块
    - 剥离多个 think 块
    - 大小写不敏感（<THINK>、<Think> 等）
    - think 块跨多行
    - response.content 为 None / 空字符串
    - think 块后有有效内容
    - additional_kwargs 中包含 reasoning_content 时不影响 content 提取
    """

    def _mock_response(self, content):
        """构造一个只含 content 字段的模拟 LLM 响应对象。"""
        mock = MagicMock()
        mock.content = content
        return mock

    def test_plain_content_unchanged(self):
        """无 think 标签时返回原始内容（不启用 thinking 的常规场景）"""
        response = self._mock_response("SELECT * FROM orders WHERE date = '2024-01'")
        assert extract_llm_content(response) == "SELECT * FROM orders WHERE date = '2024-01'"

    def test_json_content_unchanged(self):
        """JSON 内容无 think 标签时原样返回"""
        content = '{"rewritten_query": "2024年1月订单", "parse_result": {}}'
        response = self._mock_response(content)
        assert extract_llm_content(response) == content

    def test_strips_single_think_block(self):
        """剥离单个 <think>...</think> 块，保留后续内容"""
        content = "<think>这是推理过程，用户想查询订单。</think>\nSELECT * FROM orders"
        response = self._mock_response(content)
        assert extract_llm_content(response) == "SELECT * FROM orders"

    def test_strips_multiline_think_block(self):
        """剥离跨多行的 think 块"""
        content = (
            "<think>\n"
            "第一步：分析用户意图\n"
            "第二步：确定表结构\n"
            "</think>\n"
            '{"rewritten_query": "2024年销售额"}'
        )
        response = self._mock_response(content)
        assert extract_llm_content(response) == '{"rewritten_query": "2024年销售额"}'

    def test_strips_multiple_think_blocks(self):
        """剥离多个 think 块"""
        content = "<think>第一段推理</think>\n中间内容\n<think>第二段推理</think>\n最终答案"
        response = self._mock_response(content)
        result = extract_llm_content(response)
        assert "中间内容" in result
        assert "最终答案" in result
        assert "<think>" not in result
        assert "第一段推理" not in result
        assert "第二段推理" not in result

    def test_case_insensitive_think_tag(self):
        """think 标签大小写不敏感（如 <THINK>、<Think>）"""
        response_upper = self._mock_response("<THINK>推理内容</THINK>\nsimple")
        assert extract_llm_content(response_upper) == "simple"

        response_mixed = self._mock_response("<Think>推理内容</Think>\ncomplex")
        assert extract_llm_content(response_mixed) == "complex"

    def test_none_content_returns_empty_string(self):
        """response.content 为 None 时返回空字符串"""
        response = self._mock_response(None)
        assert extract_llm_content(response) == ""

    def test_empty_content_returns_empty_string(self):
        """response.content 为空字符串时返回空字符串"""
        response = self._mock_response("")
        assert extract_llm_content(response) == ""

    def test_only_think_block_returns_empty(self):
        """只有 think 标签、无实际内容时返回空字符串"""
        response = self._mock_response("<think>只有推理，没有答案</think>")
        assert extract_llm_content(response) == ""

    def test_whitespace_trimmed(self):
        """返回值去除首尾空白"""
        response = self._mock_response("  <think>x</think>  \n  结果内容  \n  ")
        assert extract_llm_content(response) == "结果内容"

    def test_reasoning_content_in_additional_kwargs_not_leaked(self):
        """reasoning_content 在 additional_kwargs 中时不影响 content 提取（标准行为验证）"""
        response = MagicMock()
        response.content = '{"rewritten_query": "月销售额"}'
        response.additional_kwargs = {"reasoning_content": "大量推理内容..."}
        assert extract_llm_content(response) == '{"rewritten_query": "月销售额"}'

    def test_think_block_before_json_parseable(self):
        """剥离 think 块后，残余内容可直接被 json.loads() 解析"""
        import json
        content = '<think>分析：用户查询月销售额</think>\n{"rewritten_query": "月销售额", "parse_result": {}}'
        response = self._mock_response(content)
        result = extract_llm_content(response)
        parsed = json.loads(result)
        assert parsed["rewritten_query"] == "月销售额"
