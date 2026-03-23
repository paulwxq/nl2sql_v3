"""Summarizer 节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.nodes.summarizer import summarizer_node


def _mock_get_llm_return(content: str = "", side_effect=None):
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
    mock_meta.model = "qwen-plus"
    return mock_meta


class TestSummarizerNode:
    """测试 Summarizer 节点"""

    @pytest.fixture(autouse=True)
    def reset_summarizer_cache(self):
        """每个测试前后重置配置缓存。"""
        import src.modules.nl2sql_father.nodes.summarizer as summarizer_module

        summarizer_module._summarizer_config_cache = None
        yield
        summarizer_module._summarizer_config_cache = None

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.nl2sql_father.nodes.summarizer.load_config") as mock:
            mock.return_value = {
                "summarizer": {
                    "llm_profile": "qwen_plus",
                    "temperature": 0.3,
                    "max_rows_in_prompt": 10,
                    "use_template": False,
                    "llm_retry": {"max_attempts": 3, "delays_seconds": [1, 2, 3]},
                }
            }
            yield mock

    @pytest.fixture
    def mock_config_template(self):
        """Mock 配置（使用模板）"""
        with patch("src.modules.nl2sql_father.nodes.summarizer.load_config") as mock:
            mock.return_value = {
                "summarizer": {
                    "llm_profile": "qwen_plus",
                    "temperature": 0.3,
                    "max_rows_in_prompt": 10,
                    "use_template": True,
                    "llm_retry": {"max_attempts": 3, "delays_seconds": [1, 2, 3]},
                }
            }
            yield mock

    # ========== 场景 1：SQL 生成失败 ==========

    def test_scenario_1_sql_generation_failed(self, mock_config):
        """场景 1：SQL 生成失败"""
        state = {
            "user_query": "查询销售额",
            "query_id": "test-002",
            "execution_results": [],
            "error": "Schema retrieval failed",
            "error_type": "schema_retrieval_failed",
        }

        result = summarizer_node(state)

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

        assert "summary" in result
        assert "SQL" in result["summary"] or "抱歉" in result["summary"]

    def test_scenario_2_all_sql_failed(self, mock_config):
        """场景 2：所有 SQL 执行失败"""
        state = {
            "user_query": "测试",
            "query_id": "test-007",
            "execution_results": [
                {"success": False, "error": "表不存在"},
                {"success": False, "error": "列不存在"},
            ],
        }

        result = summarizer_node(state)

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

        with patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return("2024年的总销售额为15万元。")

            result = summarizer_node(state)

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

        assert "summary" in result
        assert "3条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_empty_result_with_template(self, mock_config_template):
        """场景 3：查询成功但无数据（使用模板）"""
        state = {
            "user_query": "查询不存在的数据",
            "query_id": "test-010",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": []},
            ],
        }

        result = summarizer_node(state)

        assert "summary" in result
        assert "未找到" in result["summary"] or "无数据" in result["summary"]

    def test_scenario_3_single_row_with_template(self, mock_config_template):
        """场景 3：单行结果（使用模板）"""
        state = {
            "user_query": "查询",
            "query_id": "test-011",
            "execution_results": [
                {"success": True, "columns": ["value"], "rows": [[42]]},
            ],
        }

        result = summarizer_node(state)

        assert "summary" in result
        assert "1条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_llm_failure_fallback(self, mock_config):
        """场景 3：LLM 失败时回退到模板"""
        state = {
            "user_query": "查询",
            "query_id": "test-012",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": [[1], [2]]},
            ],
        }

        with patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=Exception("API 失败")
            )

            result = summarizer_node(state)

            assert "summary" in result
            assert "2条" in result["summary"] or "成功" in result["summary"]

    def test_scenario_3_multi_sql_success(self, mock_config):
        """场景 3：多 SQL 成功（Phase 2）"""
        state = {
            "user_query": "复合查询",
            "query_id": "test-013",
            "execution_results": [
                {"success": True, "columns": ["sales"], "rows": [[1000]]},
                {"success": True, "columns": ["cost"], "rows": [[600]]},
            ],
            "sub_queries": [
                {"sub_query_id": "test-013_sq1", "query": "查询销售额"},
                {"sub_query_id": "test-013_sq2", "query": "查询成本"},
            ],
        }

        with patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return(
                "销售额为1000，成本为600，利润为400。"
            )

            result = summarizer_node(state)

            assert "summary" in result

    def test_scenario_3_multi_sql_prefers_rewritten_query_in_prompt(self, mock_config):
        """测试多 SQL 场景下优先展示 rewritten_query。"""
        state = {
            "user_query": "复合查询",
            "query_id": "test-013b",
            "execution_results": [
                {
                    "success": True,
                    "sub_query_id": "test-013b_sq1",
                    "columns": ["service_area_id"],
                    "rows": [["abc123"]],
                },
                {
                    "success": True,
                    "sub_query_id": "test-013b_sq2",
                    "columns": ["service_no"],
                    "rows": [["1055"]],
                },
            ],
            "sub_queries": [
                {
                    "sub_query_id": "test-013b_sq1",
                    "query": "找出档口数量最多的服务区 ID",
                    "rewritten_query": "找出档口数量最多的服务区 ID",
                },
                {
                    "sub_query_id": "test-013b_sq2",
                    "query": "查询服务区 {{sq1.result}} 的编码",
                    "rewritten_query": "查询服务区 abc123 的编码",
                },
            ],
        }

        with patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm:
            llm_meta = _mock_get_llm_return("最终回答")
            mock_get_llm.return_value = llm_meta

            result = summarizer_node(state)

            prompt = llm_meta.llm.invoke.call_args[0][0]
            assert "【查询服务区 abc123 的编码】" in prompt
            assert "【查询服务区 {{sq1.result}} 的编码】" not in prompt
            assert result["summary"] == "最终回答"

    def test_scenario_3_llm_retry_succeeds_on_third_attempt(self, mock_config):
        """测试可重试异常会在后续 attempt 成功。"""
        state = {
            "user_query": "查询",
            "query_id": "test-012b",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": [[1], [2]]},
            ],
        }

        with (
            patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm,
            patch("src.modules.nl2sql_father.nodes.summarizer.time.sleep") as mock_sleep,
        ):
            timeout_error = Exception("ConnectTimeout: temporary timeout")
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=[timeout_error, timeout_error, MagicMock(content="第三次成功")]
            )

            result = summarizer_node(state)

            assert result["summary"] == "第三次成功"
            assert mock_get_llm.return_value.llm.invoke.call_count == 3
            assert mock_sleep.call_count == 2
            assert mock_sleep.call_args_list[0].args[0] == 1
            assert mock_sleep.call_args_list[1].args[0] == 2

    def test_scenario_3_llm_retry_skips_400(self, mock_config):
        """测试 400 错误不重试，直接模板兜底。"""
        state = {
            "user_query": "查询",
            "query_id": "test-012c",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": [[1], [2]]},
            ],
        }

        with (
            patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm,
            patch("src.modules.nl2sql_father.nodes.summarizer.time.sleep") as mock_sleep,
        ):
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=Exception("HTTP 400 Bad Request")
            )

            result = summarizer_node(state)

            assert "2条" in result["summary"] or "成功" in result["summary"]
            assert mock_get_llm.return_value.llm.invoke.call_count == 1
            mock_sleep.assert_not_called()

    def test_scenario_3_llm_retry_skips_401(self, mock_config):
        """测试 401 错误不重试，直接模板兜底。"""
        state = {
            "user_query": "查询",
            "query_id": "test-012d",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": [[1], [2]]},
            ],
        }

        with (
            patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm,
            patch("src.modules.nl2sql_father.nodes.summarizer.time.sleep") as mock_sleep,
        ):
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=Exception("HTTP 401 Unauthorized")
            )

            result = summarizer_node(state)

            assert "2条" in result["summary"] or "成功" in result["summary"]
            assert mock_get_llm.return_value.llm.invoke.call_count == 1
            mock_sleep.assert_not_called()

    def test_scenario_3_llm_retry_exhausted_falls_back_to_template(self, mock_config):
        """测试可重试异常连续失败后回退模板。"""
        state = {
            "user_query": "查询",
            "query_id": "test-012e",
            "execution_results": [
                {"success": True, "columns": ["id"], "rows": [[1], [2]]},
            ],
        }

        with (
            patch("src.modules.nl2sql_father.nodes.summarizer.get_llm") as mock_get_llm,
            patch("src.modules.nl2sql_father.nodes.summarizer.time.sleep") as mock_sleep,
        ):
            timeout_error = Exception("ConnectTimeout: temporary timeout")
            mock_get_llm.return_value = _mock_get_llm_return(
                side_effect=[timeout_error, timeout_error, timeout_error]
            )

            result = summarizer_node(state)

            assert "2条" in result["summary"] or "成功" in result["summary"]
            assert mock_get_llm.return_value.llm.invoke.call_count == 3
            assert mock_sleep.call_count == 2

    def test_scenario_3_partial_success(self, mock_config_template):
        """场景 3：部分 SQL 成功"""
        state = {
            "user_query": "测试",
            "query_id": "test-014",
            "execution_results": [
                {"success": True, "columns": ["value"], "rows": [[100]]},
                {"success": False, "error": "失败"},
            ],
        }

        result = summarizer_node(state)

        assert "summary" in result
        assert "成功" in result["summary"] or "1条" in result["summary"]

    # ========== 辅助函数测试 ==========

    def test_format_table_empty(self):
        from src.modules.nl2sql_father.nodes.summarizer import _format_table
        result = _format_table(["col1"], [])
        assert "无数据" in result

    def test_format_table_normal(self):
        from src.modules.nl2sql_father.nodes.summarizer import _format_table
        columns = ["id", "name"]
        rows = [[1, "Alice"], [2, "Bob"]]
        result = _format_table(columns, rows)
        assert "id" in result
        assert "name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_format_table_truncation(self):
        from src.modules.nl2sql_father.nodes.summarizer import _format_table
        columns = ["num"]
        rows = [[i] for i in range(15)]
        result = _format_table(columns, rows)
        assert "..." in result

    def test_build_error_summary_parsing_failed(self):
        from src.modules.nl2sql_father.nodes.summarizer import _build_error_summary
        summary = _build_error_summary("Error", "parsing_failed", "测试")
        assert "换一种方式" in summary or "无法理解" in summary

    def test_build_error_summary_unknown_type(self):
        from src.modules.nl2sql_father.nodes.summarizer import _build_error_summary
        summary = _build_error_summary("Error", "unknown_type", "测试")
        assert "抱歉" in summary

    def test_format_multi_results_prefers_rewritten_query(self):
        from src.modules.nl2sql_father.nodes.summarizer import _format_multi_results

        results = [
            {
                "sub_query_id": "sq2",
                "columns": ["service_no"],
                "rows": [["1055"]],
            }
        ]
        sub_queries = [
            {
                "sub_query_id": "sq2",
                "query": "查询服务区 {{sq1.result}} 的编码",
                "rewritten_query": "查询服务区 abc123 的编码",
            }
        ]

        result = _format_multi_results(results, sub_queries, max_rows=10)
        assert "【查询服务区 abc123 的编码】" in result
        assert "{{sq1.result}}" not in result
