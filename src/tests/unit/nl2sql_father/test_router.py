"""Router 节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.nodes.router import router_node


class TestRouterNode:
    """测试 Router 节点"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.nl2sql_father.nodes.router.load_config") as mock:
            mock.return_value = {
                "router": {
                    "model": "qwen-turbo",
                    "temperature": 0,
                    "timeout": 5,
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
        # Mock LLM 响应
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "simple"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证结果
            assert result["complexity"] == "simple"  # 字符串，不是布尔值
            assert result["path_taken"] == "fast"
            assert "router_latency_ms" in result
            assert result["router_latency_ms"] > 0

    def test_complex_classification(self, mock_config, base_state):
        """测试复杂问题分类"""
        # Mock LLM 响应
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "complex"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证结果
            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"
            assert "router_latency_ms" in result

    def test_llm_response_with_explanation(self, mock_config, base_state):
        """测试 LLM 返回带解释的响应"""
        # Mock LLM 响应（包含解释文本）
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "simple\n这是一个简单的单表查询问题"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证：应该能从文本中提取出 "simple"
            assert result["complexity"] == "simple"
            assert result["path_taken"] == "fast"

    def test_unrecognized_response_fallback(self, mock_config, base_state):
        """测试无法识别的响应回退到默认值"""
        # Mock LLM 返回无法识别的内容
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "不确定"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证：应该回退到配置的默认值 "complex"
            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"

    def test_llm_failure_fallback(self, mock_config, base_state):
        """测试 LLM 调用失败回退到默认值"""
        # Mock LLM 抛出异常
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = Exception("API 调用失败")
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证：应该回退到配置的默认值 "complex"
            assert result["complexity"] == "complex"
            assert result["path_taken"] == "complex"
            assert "Router failed" in result["router_reason"]

    def test_router_reason_truncation(self, mock_config, base_state):
        """测试 router_reason 截断到 200 字符"""
        # Mock LLM 返回超长文本
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            long_text = "simple\n" + "x" * 300  # 超过 200 字符
            mock_response.content = long_text
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证：router_reason 应该被截断到 200 字符
            assert len(result["router_reason"]) <= 200

    def test_complexity_string_not_boolean(self, mock_config, base_state):
        """测试 complexity 是字符串而非布尔值（重要！）"""
        # Mock LLM 响应
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "simple"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            # 执行 Router
            result = router_node(base_state)

            # 验证：complexity 必须是字符串类型
            assert isinstance(result["complexity"], str)
            assert result["complexity"] in ["simple", "complex"]
            assert result["complexity"] != True  # 不应该是布尔值
            assert result["complexity"] != False

    def test_default_on_error_simple(self, base_state):
        """测试配置 default_on_error 为 simple"""
        # 清空配置缓存
        import src.modules.nl2sql_father.nodes.router as router_module
        router_module._router_config_cache = None

        # Mock 配置返回 default_on_error = "simple"
        with patch("src.modules.nl2sql_father.nodes.router.load_config") as mock_config:
            mock_config.return_value = {
                "router": {
                    "model": "qwen-turbo",
                    "temperature": 0,
                    "timeout": 5,
                    "default_on_error": "simple",  # 改为 simple
                    "log_decision": True,
                }
            }

            # Mock LLM 失败
            with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.invoke.side_effect = Exception("API 失败")
                mock_llm_class.return_value = mock_llm

                # 执行 Router
                result = router_node(base_state)

                # 验证：应该回退到 "simple"
                assert result["complexity"] == "simple"
                assert result["path_taken"] == "fast"

                # 清空缓存
                router_module._router_config_cache = None
