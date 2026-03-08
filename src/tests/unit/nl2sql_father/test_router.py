"""Router 节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.nodes.router import router_node


def _mock_get_llm_return(content: str = "simple", side_effect=None):
    """构造 get_llm 的 Mock 返回值（LLMWithMeta 结构）。"""
    mock_llm = MagicMock()
    if side_effect:
        mock_llm.invoke.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.content = content
        mock_llm.invoke.return_value = mock_response

    mock_meta = MagicMock()
    mock_meta.llm = mock_llm
    mock_meta.provider = "dashscope"
    mock_meta.model = "qwen-turbo"
    return mock_meta


class TestRouterNode:
    """测试 Router 节点"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.nl2sql_father.nodes.router.load_config") as mock:
            mock.return_value = {
                "router": {
                    "llm_profile": "qwen_turbo",
                    "temperature": 0,
                    "default_on_error": "complex",
                    "log_decision": True,
                }
            }
            yield mock

    @pytest.fixture
    def base_state(self):
        """基础 State"""
        return {
            "user_query": "查询2024年的销售额",
            "query_id": "test-001",
        }

    def test_simple_classification(self, mock_config, base_state):
        """测试简单问题分类"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return("simple")

            result = router_node(base_state)

            assert result["complexity"] == "simple"
            assert result["path_taken"] == "fast"
            assert "router_latency_ms" in result
            assert result["router_latency_ms"] >= 0

    def test_complex_classification(self, mock_config, base_state):
        """测试复杂问题分类"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return("complex")

            result = router_node(base_state)

            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"
            assert "router_latency_ms" in result

    def test_llm_response_with_explanation(self, mock_config, base_state):
        """测试 LLM 返回带解释的响应"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return(
                "simple\n这是一个简单的单表查询问题"
            )

            result = router_node(base_state)

            assert result["complexity"] == "simple"
            assert result["path_taken"] == "fast"

    def test_unrecognized_response_fallback(self, mock_config, base_state):
        """测试无法识别的响应回退到默认值"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return("不确定")

            result = router_node(base_state)

            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"

    def test_llm_failure_fallback(self, mock_config, base_state):
        """测试 LLM 调用失败回退到默认值"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=Exception("API 调用失败")
            )

            result = router_node(base_state)

            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"
            assert "Router failed" in result["router_reason"]

    def test_router_reason_truncation(self, mock_config, base_state):
        """测试 router_reason 截断到 200 字符"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            long_text = "simple\n" + "x" * 300
            mock_get_llm.return_value = _mock_get_llm_return(long_text)

            result = router_node(base_state)

            assert len(result["router_reason"]) <= 200

    def test_complexity_string_not_boolean(self, mock_config, base_state):
        """测试 complexity 是字符串而非布尔值（重要！）"""
        with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return("simple")

            result = router_node(base_state)

            assert isinstance(result["complexity"], str)
            assert result["complexity"] in ["simple", "complex"]
            assert result["complexity"] != True  # noqa: E712
            assert result["complexity"] != False  # noqa: E712

    def test_default_on_error_simple(self, base_state):
        """测试配置 default_on_error 为 simple"""
        import src.modules.nl2sql_father.nodes.router as router_module
        router_module._router_config_cache = None

        with patch("src.modules.nl2sql_father.nodes.router.load_config") as mock_config:
            mock_config.return_value = {
                "router": {
                    "llm_profile": "qwen_turbo",
                    "temperature": 0,
                    "default_on_error": "simple",
                    "log_decision": True,
                }
            }

            with patch("src.modules.nl2sql_father.nodes.router.get_llm") as mock_get_llm:
                mock_get_llm.return_value = _mock_get_llm_return(
                    side_effect=Exception("API 失败")
                )

                result = router_node(base_state)

                assert result["complexity"] == "simple"
                assert result["path_taken"] == "fast"

                router_module._router_config_cache = None
