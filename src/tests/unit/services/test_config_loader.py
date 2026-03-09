"""config_loader 单元测试

测试 ConfigLoader._replace_env_var_in_string() 的延迟校验行为：
- 缺失无默认值的独立占位符 → 返回 None，不抛异常
- 缺失有默认值的占位符 → 返回默认值
- 内嵌在长字符串中的缺失变量 → 替换为空字符串，记 WARNING
- 正常变量 → 正常替换并做类型转换
- None api_key 流经 get_llm() → 调用时才报错（完整链路）
"""

import os
import textwrap
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.services.config_loader import ConfigLoader


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _loader_from_yaml(yaml_text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """将 YAML 文本加载为配置字典，env 参数模拟环境变量。"""
    loader = ConfigLoader.__new__(ConfigLoader)
    with patch.dict(os.environ, env or {}, clear=False):
        # 直接调用 _replace_env_vars，绕过文件 I/O
        raw = yaml.safe_load(textwrap.dedent(yaml_text))
        return loader._replace_env_vars(raw)


# ---------------------------------------------------------------------------
# 独立占位符（整个值就是 ${VAR}）
# ---------------------------------------------------------------------------

class TestSolePlaceholder:
    """整个 YAML 值是单个 ${VAR} 占位符的场景"""

    def test_missing_no_default_returns_none(self):
        """未设置且无默认值 → None，不抛异常"""
        result = _loader_from_yaml(
            "api_key: ${MISSING_KEY_XYZ_UNIQUE}",
            env={},
        )
        assert result["api_key"] is None

    def test_missing_with_default_returns_default(self):
        """未设置但有默认值 → 使用默认值"""
        result = _loader_from_yaml(
            "host: ${MISSING_HOST:localhost}",
            env={},
        )
        assert result["host"] == "localhost"

    def test_missing_with_empty_default_returns_empty_string(self):
        """${VAR:} 空默认值 → 空字符串"""
        result = _loader_from_yaml(
            "api_key: ${MISSING_KEY_XYZ_UNIQUE:}",
            env={},
        )
        assert result["api_key"] == ""

    def test_present_var_substituted(self):
        """已设置的变量正常替换"""
        result = _loader_from_yaml(
            "api_key: ${MY_API_KEY}",
            env={"MY_API_KEY": "sk-test-123"},
        )
        assert result["api_key"] == "sk-test-123"

    def test_present_var_type_conversion_int(self):
        """整数值正确转换类型"""
        result = _loader_from_yaml(
            "port: ${MY_PORT}",
            env={"MY_PORT": "5432"},
        )
        assert result["port"] == 5432
        assert isinstance(result["port"], int)

    def test_present_var_type_conversion_bool(self):
        """布尔值正确转换类型"""
        result = _loader_from_yaml(
            "enabled: ${MY_FLAG}",
            env={"MY_FLAG": "true"},
        )
        assert result["enabled"] is True

    def test_missing_no_default_logs_warning(self, caplog):
        """缺失变量应记录 WARNING 日志"""
        import logging
        with caplog.at_level(logging.WARNING, logger="src.services.config_loader"):
            _loader_from_yaml(
                "api_key: ${MISSING_KEY_XYZ_UNIQUE}",
                env={},
            )
        assert any("MISSING_KEY_XYZ_UNIQUE" in record.message for record in caplog.records)
        assert any(record.levelname == "WARNING" for record in caplog.records)


# ---------------------------------------------------------------------------
# 内嵌占位符（${VAR} 嵌在更长字符串中）
# ---------------------------------------------------------------------------

class TestEmbeddedPlaceholder:
    """${VAR} 内嵌在字符串中的场景"""

    def test_present_var_embedded(self):
        """内嵌变量正常替换"""
        result = _loader_from_yaml(
            "base_url: https://${MY_HOST}/v1",
            env={"MY_HOST": "api.example.com"},
        )
        assert result["base_url"] == "https://api.example.com/v1"

    def test_missing_embedded_replaced_with_empty_string(self):
        """内嵌变量缺失 → 替换为空字符串（而非 None）"""
        result = _loader_from_yaml(
            "base_url: https://${MISSING_HOST_XYZ}/v1",
            env={},
        )
        assert result["base_url"] == "https:///v1"

    def test_missing_embedded_logs_warning(self, caplog):
        """内嵌缺失变量应记录 WARNING"""
        import logging
        with caplog.at_level(logging.WARNING, logger="src.services.config_loader"):
            _loader_from_yaml(
                "base_url: https://${MISSING_HOST_XYZ}/v1",
                env={},
            )
        assert any("MISSING_HOST_XYZ" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 嵌套结构（llm_providers 典型场景）
# ---------------------------------------------------------------------------

class TestNestedStructure:
    """模拟 config.yaml 中 llm_providers 段的完整结构"""

    _yaml = """
        llm_providers:
          dashscope:
            api_key: ${DASHSCOPE_API_KEY}
          minimax:
            api_key: ${MINIMAX_API_KEY}
            base_url: https://api.minimaxi.com/v1
    """

    def test_configured_provider_normal(self):
        """已配置的 provider api_key 正常展开"""
        result = _loader_from_yaml(
            self._yaml,
            env={"DASHSCOPE_API_KEY": "sk-dashscope-real", "MINIMAX_API_KEY": "sk-minimax-real"},
        )
        assert result["llm_providers"]["dashscope"]["api_key"] == "sk-dashscope-real"
        assert result["llm_providers"]["minimax"]["api_key"] == "sk-minimax-real"

    def test_missing_provider_key_becomes_none(self):
        """未配置的 provider api_key → None，已配置的正常，不影响启动"""
        result = _loader_from_yaml(
            self._yaml,
            env={"DASHSCOPE_API_KEY": "sk-dashscope-real"},
            # MINIMAX_API_KEY 故意不设置
        )
        assert result["llm_providers"]["dashscope"]["api_key"] == "sk-dashscope-real"
        assert result["llm_providers"]["minimax"]["api_key"] is None
        # base_url 不含变量，应正常保留
        assert result["llm_providers"]["minimax"]["base_url"] == "https://api.minimaxi.com/v1"

    def test_all_missing_becomes_none(self):
        """所有 provider api_key 未配置 → 全部 None，不抛异常"""
        result = _loader_from_yaml(self._yaml, env={})
        assert result["llm_providers"]["dashscope"]["api_key"] is None
        assert result["llm_providers"]["minimax"]["api_key"] is None


# ---------------------------------------------------------------------------
# 完整链路：None api_key → get_llm() 调用时才报错
# ---------------------------------------------------------------------------

class TestEndToEndNoneApiKey:
    """None api_key 经过 llm_factory.get_llm() 时才抛 ValueError"""

    @patch("src.services.llm_factory.get_config")
    def test_none_api_key_raises_on_get_llm(self, mock_get_config):
        """api_key=None 的 provider 在 get_llm() 时报错，而非启动时"""
        from src.services.llm_factory import get_llm

        store = {
            "llm_providers": {
                "minimax": {
                    "api_key": None,   # 模拟未设置环境变量后的结果
                    "base_url": "https://api.minimaxi.com/v1",
                },
            },
            "llm_profiles": {
                "minimax_m21": {
                    "provider": "minimax",
                    "model": "MiniMax-M2.1",
                },
            },
        }
        mock_cfg = MagicMock()
        mock_cfg.get = lambda k, d=None: store.get(k, d)
        mock_get_config.return_value = mock_cfg

        with pytest.raises(ValueError, match="api_key"):
            get_llm("minimax_m21")

    @patch("src.services.llm_factory._import_class")
    @patch("src.services.llm_factory.get_config")
    def test_present_api_key_works_normally(self, mock_get_config, mock_import):
        """api_key 有值时 get_llm() 正常创建实例"""
        from src.services.llm_factory import LLMWithMeta, get_llm

        store = {
            "llm_providers": {
                "minimax": {
                    "api_key": "sk-minimax-real",
                    "base_url": "https://api.minimaxi.com/v1",
                },
            },
            "llm_profiles": {
                "minimax_m21": {
                    "provider": "minimax",
                    "model": "MiniMax-M2.1",
                },
            },
        }
        mock_cfg = MagicMock()
        mock_cfg.get = lambda k, d=None: store.get(k, d)
        mock_get_config.return_value = mock_cfg

        mock_cls = MagicMock()
        mock_cls.return_value = MagicMock()
        mock_import.return_value = mock_cls

        result = get_llm("minimax_m21")

        assert isinstance(result, LLMWithMeta)
        assert result.provider == "minimax"
        assert result.model == "MiniMax-M2.1"
        mock_cls.assert_called_once_with(
            model="MiniMax-M2.1",
            api_key="sk-minimax-real",
            base_url="https://api.minimaxi.com/v1",
        )
