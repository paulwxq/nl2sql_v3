"""Summarizer 节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.nodes.summarizer import summarizer_node


class TestSummarizerNode:
    """测试 Summarizer 节点"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.nl2sql_father.nodes.summarizer.load_config") as mock:
            mock.return_value = {
                "summarizer": {
                    "model": "qwen-plus",
                    "temperature": 0.3,
                    "timeout": 10,
                    "max_rows_in_prompt": 10,
                    "use_template": False,
                }
            }
            yield mock

    @pytest.fixture
    def mock_config_template(self):
        """Mock 配置（使用模板）"""
        # 清空配置缓存
        import src.modules.nl2sql_father.nodes.summarizer as summarizer_module
        summarizer_module._summarizer_config_cache = None

        with patch("src.modules.nl2sql_father.nodes.summarizer.load_config") as mock:
            mock.return_value = {
                "summarizer": {
                    "model": "qwen-plus",
                    "temperature": 0.3,
                    "timeout": 10,
                    "max_rows_in_prompt": 10,
                    "use_template": True,  # 使用模板，不调用 LLM
                }
            }
            yield mock
            # 测试后清空缓存
            summarizer_module._summarizer_config_cache = None

    # ========== 场景 1：SQL 生成失败 ==========

    def test_scenario_1_sql_generation_failed(self, mock_config):
        """场景 1：SQL 生成失败"""
        state = {
            "user_query": "查询销售额",
            "query_id": "test-002",
            "execution_results": [],  # 无执行结果
            "error": "Schema retrieval failed",
            "error_type": "schema_retrieval_failed",
        }

        result = summarizer_node(state)

        # 验证返回友好错误提示
        assert "summary" in result
        assert "抱歉" in result["summary"]

    def test_scenario_1_error_type_parsing_failed(self, mock_config):
        """场景 1：解析失败错误"""
        state = {
            "user_query": "测试",
            "query_id": "test-003",
            "execution_results": [],
            "error": "Parsing error",
            "error_type": "parsing_failed",
        }

        result = summarizer_node(state)

        # 验证错误提示包含"换一种方式"
        assert "换一种方式" in result["summary"] or "抱歉" in result["summary"]

    def test_scenario_1_error_type_generation_failed(self, mock_config):
        """场景 1：生成失败错误"""
        state = {
            "user_query": "测试",
            "query_id": "test-004",
            "execution_results": [],
            "error": "Generation failed",
            "error_type": "generation_failed",
        }

        result = summarizer_node(state)

        # 验证错误提示
        assert "summary" in result
        assert "抱歉" in result["summary"]

    def test_scenario_1_error_type_unknown(self, mock_config):
        """场景 1：未知错误类型"""
        state = {
            "user_query": "测试",
            "query_id": "test-005",
            "execution_results": [],
            "error": "Unknown error",
            "error_type": "unknown_error",
        }

        result = summarizer_node(state)

        # 验证使用通用错误提示
        assert "summary" in result
        assert "抱歉" in result["summary"]

    # ========== 场景 2：SQL 执行失败 ==========

    def test_scenario_2_no_execution_results(self, mock_config):
        """场景 2：无执行结果"""
        state = {
            "user_query": "测试",
            "query_id": "test-006",
            "execution_results": [],
        }

        result = summarizer_node(state)

        # 验证返回"未能生成有效的SQL"提示
        assert "summary" in result
        assert "SQL" in result["summary"] or "抱歉" in result["summary"]

    def test_scenario_2_all_sql_failed(self, mock_config):
        """场景 2：所有 SQL 执行失败"""
        state = {
            "user_query": "测试",
            "query_id": "test-007",
            "execution_results": [
                {
                    "success": False,
                    "error": "表不存在",
                },
                {
                    "success": False,
                    "error": "列不存在",
                },
            ],
        }

        result = summarizer_node(state)

        # 验证返回错误汇总
        assert "summary" in result
        assert "失败" in result["summary"]
        assert "表不存在" in result["summary"] or "错误" in result["summary"]

    # ========== 场景 3：SQL 执行成功 ==========

    def test_scenario_3_single_sql_success_with_llm(self, mock_config):
        """场景 3：单 SQL 成功（使用 LLM 生成总结）"""
        state = {
            "user_query": "查询2024年的销售额",
            "query_id": "test-008",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["total_amount"],
                    "rows": [[150000.00]],
                }
            ],
        }

        # Mock LLM
        with patch("src.modules.nl2sql_father.nodes.summarizer.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "2024年的总销售额为15万元。"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            result = summarizer_node(state)

            # 验证返回 LLM 生成的总结
            assert "summary" in result
            assert result["summary"] == "2024年的总销售额为15万元。"

    def test_scenario_3_single_sql_success_with_template(self, mock_config_template):
        """场景 3：单 SQL 成功（使用模板）"""
        state = {
            "user_query": "查询销售额",
            "query_id": "test-009",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["id", "amount"],
                    "rows": [[1, 100], [2, 200], [3, 300]],
                }
            ],
        }

        result = summarizer_node(state)

        # 验证返回模板总结
        assert "summary" in result
        assert "3条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_empty_result_with_template(self, mock_config_template):
        """场景 3：查询成功但无数据（使用模板）"""
        state = {
            "user_query": "查询不存在的数据",
            "query_id": "test-010",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["id"],
                    "rows": [],
                }
            ],
        }

        result = summarizer_node(state)

        # 验证返回"未找到"提示
        assert "summary" in result
        assert "未找到" in result["summary"] or "无数据" in result["summary"]

    def test_scenario_3_single_row_with_template(self, mock_config_template):
        """场景 3：单行结果（使用模板）"""
        state = {
            "user_query": "查询",
            "query_id": "test-011",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["value"],
                    "rows": [[42]],
                }
            ],
        }

        result = summarizer_node(state)

        # 验证返回"1条记录"
        assert "summary" in result
        assert "1条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_llm_failure_fallback(self, mock_config):
        """场景 3：LLM 失败时回退到模板"""
        state = {
            "user_query": "查询",
            "query_id": "test-012",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["id"],
                    "rows": [[1], [2]],
                }
            ],
        }

        # Mock LLM 抛出异常
        with patch("src.modules.nl2sql_father.nodes.summarizer.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = Exception("API 失败")
            mock_llm_class.return_value = mock_llm

            result = summarizer_node(state)

            # 验证回退到模板
            assert "summary" in result
            assert "2条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_multi_sql_success(self, mock_config):
        """场景 3：多 SQL 成功（Phase 2）"""
        state = {
            "user_query": "复合查询",
            "query_id": "test-013",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["sales"],
                    "rows": [[1000]],
                },
                {
                    "success": True,
                    "columns": ["cost"],
                    "rows": [[600]],
                },
            ],
            "sub_queries": [
                {"sub_query_id": "test-013_sq1", "query": "查询销售额"},
                {"sub_query_id": "test-013_sq2", "query": "查询成本"},
            ],
        }

        # Mock LLM
        with patch("src.modules.nl2sql_father.nodes.summarizer.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "销售额为1000，成本为600，利润为400。"
            mock_llm.invoke = MagicMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm

            result = summarizer_node(state)

            # 验证多 SQL 总结
            assert "summary" in result

    def test_scenario_3_partial_success(self, mock_config_template):
        """场景 3：部分 SQL 成功"""
        state = {
            "user_query": "测试",
            "query_id": "test-014",
            "execution_results": [
                {
                    "success": True,
                    "columns": ["value"],
                    "rows": [[100]],
                },
                {
                    "success": False,
                    "error": "失败",
                },
            ],
        }

        result = summarizer_node(state)

        # 验证只总结成功的结果
        assert "summary" in result
        assert "成功" in result["summary"] or "1条" in result["summary"]

    # ========== 辅助函数测试 ==========

    def test_format_table_empty(self):
        """测试空表格式化"""
        from src.modules.nl2sql_father.nodes.summarizer import _format_table

        result = _format_table(["col1"], [])

        assert "无数据" in result

    def test_format_table_normal(self):
        """测试正常表格式化"""
        from src.modules.nl2sql_father.nodes.summarizer import _format_table

        columns = ["id", "name"]
        rows = [[1, "Alice"], [2, "Bob"]]

        result = _format_table(columns, rows)

        # 验证包含列名和数据
        assert "id" in result
        assert "name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_format_table_truncation(self):
        """测试表格截断（>= 10 行）"""
        from src.modules.nl2sql_father.nodes.summarizer import _format_table

        columns = ["num"]
        rows = [[i] for i in range(15)]

        result = _format_table(columns, rows)

        # 验证添加了省略号
        assert "..." in result

    def test_build_error_summary_parsing_failed(self):
        """测试错误转换：解析失败"""
        from src.modules.nl2sql_father.nodes.summarizer import _build_error_summary

        summary = _build_error_summary("Error", "parsing_failed", "测试")

        assert "换一种方式" in summary or "无法理解" in summary

    def test_build_error_summary_unknown_type(self):
        """测试错误转换：未知类型"""
        from src.modules.nl2sql_father.nodes.summarizer import _build_error_summary

        summary = _build_error_summary("Error", "unknown_type", "测试")

        # 应该返回通用模板
        assert "抱歉" in summary
