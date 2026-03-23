"""SQL 生成子图集成测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.sql_generation.subgraph.create_subgraph import (
    create_sql_generation_subgraph,
    run_sql_generation_subgraph,
    should_retry,
)
from src.modules.sql_generation.subgraph.state import (
    SQLGenerationState,
    create_initial_state,
    is_successful,
)


def _mock_llm_meta(content: str = "", side_effect=None):
    """构造 get_llm Mock 返回值（LLMWithMeta 结构）。"""
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


_SUBGRAPH_NODES = "src.modules.sql_generation.subgraph.nodes"
_SUBGRAPH_PKG = "src.modules.sql_generation.subgraph"


@pytest.fixture
def mock_all_dependencies():
    """Mock 所有外部依赖"""
    with patch(f"{_SUBGRAPH_NODES}.schema_retrieval.SchemaRetriever") as mock_retriever, \
         patch(f"{_SUBGRAPH_NODES}.question_parsing.get_llm") as mock_parser_get_llm, \
         patch(f"{_SUBGRAPH_NODES}.sql_generation.get_llm") as mock_gen_get_llm, \
         patch(f"{_SUBGRAPH_NODES}.validation.SQLValidationTool") as mock_validation, \
         patch(f"{_SUBGRAPH_NODES}.question_parsing.load_subgraph_config") as mock_cfg_parsing, \
         patch(f"{_SUBGRAPH_NODES}.sql_generation.load_subgraph_config") as mock_cfg_gen, \
         patch(f"{_SUBGRAPH_NODES}.schema_retrieval.load_subgraph_config") as mock_cfg_schema, \
         patch(f"{_SUBGRAPH_NODES}.validation.load_subgraph_config") as mock_cfg_validation, \
         patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config") as mock_cfg_subgraph:

        # 所有 load_subgraph_config mock 共享同一份配置
        _fixture_config = {
            "question_parsing": {
                "enable_internal_parser": True,
                "llm_profile": "qwen_plus",
                "temperature": 0,
                "max_tokens": 1500,
                "fallback_to_empty": True,
            },
            "schema_retrieval": {
                "topk_tables": 10,
                "topk_columns": 10,
            },
            "sql_generation": {
                "llm_profile": "qwen_max",
                "temperature": 0,
                "max_tokens": 2000,
            },
            "validation": {
                "enable_syntax_check": True,
                "enable_security_check": True,
                "enable_semantic_check": True,
            },
            "retry": {
                "max_iterations": 3,
            },
        }
        for _m in (mock_cfg_parsing, mock_cfg_gen, mock_cfg_schema,
                    mock_cfg_validation, mock_cfg_subgraph):
            _m.return_value = _fixture_config

        # Mock question parsing LLM (via get_llm)
        mock_parser_resp = MagicMock()
        mock_parser_resp.content = """{
            "rewritten_query": "查询2024年1月的订单",
            "parse_result": {
                "keywords": ["订单", "2024年1月"],
                "time": {"start": "2024-01-01", "end": "2024-02-01", "grain_inferred": "month", "is_full_period": true},
                "metric": {"text": "订单", "is_aggregate_candidate": false},
                "dimensions": [],
                "intent": {"task": "plain_agg", "topn": null},
                "signals": []
            }
        }"""
        mock_parser_llm = MagicMock()
        mock_parser_llm.invoke.return_value = mock_parser_resp
        mock_parser_meta = MagicMock()
        mock_parser_meta.llm = mock_parser_llm
        mock_parser_meta.provider = "dashscope"
        mock_parser_meta.model = "qwen-plus"
        mock_parser_get_llm.return_value = mock_parser_meta

        # Mock retriever
        mock_retriever_instance = MagicMock()
        mock_retriever_instance.retrieve.return_value = {
            "tables": ["public.orders", "public.customers"],
            "columns": [],
            "join_plans": [],
            "table_cards": {
                "public.orders": {
                    "text_raw": "订单表，包含订单ID、客户ID、金额等字段",
                    "time_col_hint": "order_date",
                }
            },
            "similar_sqls": [],
            "dim_value_matches": [],
            "candidate_fact_tables": ["public.orders"],
            "candidate_dim_tables": ["public.customers"],
            "table_similarities": {
                "public.orders": 0.9,
                "public.customers": 0.7,
            },
            "dim_value_hits": [],
            "metadata": {"retrieval_time": 0.1},
        }
        mock_retriever_instance.get_retrieval_stats.return_value = {
            "table_count": 2,
            "column_count": 0,
            "join_plan_count": 0,
            "retrieval_time": 0.1,
        }
        mock_retriever.return_value = mock_retriever_instance

        # Mock SQL generation LLM (via get_llm)
        mock_gen_resp = MagicMock()
        mock_gen_resp.content = "SELECT id, customer_id, amount FROM public.orders WHERE order_date >= '2024-01-01' AND order_date < '2024-02-01'"
        mock_gen_llm = MagicMock()
        mock_gen_llm.invoke.return_value = mock_gen_resp
        mock_gen_meta = MagicMock()
        mock_gen_meta.llm = mock_gen_llm
        mock_gen_meta.provider = "dashscope"
        mock_gen_meta.model = "qwen-max"
        mock_gen_get_llm.return_value = mock_gen_meta

        # Mock validation tool
        mock_validation_instance = MagicMock()
        mock_validation_instance.validate.return_value = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "layer": "all_passed",
            "explain_plan": "Seq Scan on orders",
        }
        mock_validation_instance.get_validation_summary.return_value = "✅ 验证通过"
        mock_validation.return_value = mock_validation_instance

        yield {
            "retriever": mock_retriever,
            "parser_get_llm": mock_parser_get_llm,
            "gen_get_llm": mock_gen_get_llm,
            "validation": mock_validation,
            "config": _fixture_config,
        }


class TestSubgraphCreation:
    """测试子图创建"""

    def test_create_subgraph_structure(self):
        """测试子图结构正确创建"""
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config"):
            subgraph = create_sql_generation_subgraph()
            assert subgraph is not None


class TestShouldRetryLogic:
    """测试重试逻辑"""

    def test_retry_on_validation_failure(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, iteration_count=1,
            validated_sql=None, error_type="validation_failed",
        )
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config") as mock_config:
            mock_config.return_value = {"retry": {"max_iterations": 3}}
            assert should_retry(state) == "retry"

    def test_success_on_validated_sql(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, iteration_count=1,
            validated_sql="SELECT * FROM public.test",
        )
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config"):
            assert should_retry(state) == "success"

    def test_fail_on_max_iterations(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, iteration_count=3,
            validated_sql=None, error_type="validation_failed",
        )
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config") as mock_config:
            mock_config.return_value = {"retry": {"max_iterations": 3}}
            assert should_retry(state) == "fail"

    def test_fail_on_non_recoverable_error(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, iteration_count=1,
            validated_sql=None, error_type="schema_retrieval_failed",
        )
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config"):
            assert should_retry(state) == "fail"

    def test_fail_on_generation_failed(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, iteration_count=1,
            validated_sql=None, error_type="generation_failed",
        )
        with patch(f"{_SUBGRAPH_PKG}.create_subgraph.load_subgraph_config"):
            assert should_retry(state) == "fail"


class TestSubgraphExecution:
    """测试子图执行"""

    def test_successful_execution(self, mock_all_dependencies):
        output = run_sql_generation_subgraph(
            query="查询2024年1月的订单", query_id="test-001", user_query="查询2024年1月的订单",
        )
        assert "validated_sql" in output
        assert output["validated_sql"] is not None
        assert "SELECT" in output["validated_sql"]

    def test_execution_with_parse_hints(self, mock_all_dependencies):
        parse_hints = {
            "time": {"start": "2024-01-01", "end": "2024-02-01"},
            "dimensions": [{"text": "北京", "type": "location"}],
        }
        output = run_sql_generation_subgraph(
            query="查询北京地区的订单", query_id="test-002",
            user_query="查询北京地区的订单", parse_hints=parse_hints,
        )
        assert output["validated_sql"] is not None

    def test_execution_with_dependencies(self, mock_all_dependencies):
        dependencies_results = {
            "sub1": {
                "question": "查询北京的门店",
                "execution_result": {
                    "sub_query_id": "sub1",
                    "sql": "SELECT store_id FROM public.dim_store WHERE city = '北京'",
                    "success": True, "columns": ["store_id"],
                    "rows": [["BJ001"]], "row_count": 1,
                    "execution_time_ms": 3.0, "error": None,
                },
            }
        }
        output = run_sql_generation_subgraph(
            query="查询这些门店的订单", query_id="test-003",
            user_query="查询北京门店的订单", dependencies_results=dependencies_results,
        )
        assert output["validated_sql"] is not None

    def test_question_parsing_prompt_includes_dependencies(self, mock_all_dependencies):
        """测试依赖结果会进入 question_parsing 提示词"""
        dependencies_results = {
            "sq1": {
                "question": "查询北京的门店",
                "execution_result": {
                    "sub_query_id": "sq1",
                    "sql": "SELECT store_id FROM public.dim_store WHERE city = '北京'",
                    "success": True,
                    "columns": ["store_id", "store_name"],
                    "rows": [["BJ001", "北京朝阳店"]],
                    "row_count": 1,
                    "execution_time_ms": 3.0,
                    "error": None,
                },
            }
        }

        parser_meta = mock_all_dependencies["parser_get_llm"].return_value

        def _parser_side_effect(messages):
            user_prompt = messages[1].content
            assert "Dependency results" in user_prompt
            assert "store_id" in user_prompt
            assert "BJ001" in user_prompt

            response = MagicMock()
            response.content = """{
                "rewritten_query": "查询门店ID为 BJ001 的订单",
                "parse_result": {
                    "keywords": ["门店ID", "订单"],
                    "time": null,
                    "metric": {"text": "订单", "is_aggregate_candidate": false},
                    "dimensions": [{"text": "BJ001", "role": "value", "evidence": "依赖结果"}],
                    "intent": {"task": "plain_agg", "topn": null},
                    "signals": []
                }
            }"""
            return response

        parser_meta.llm.invoke.side_effect = _parser_side_effect

        output = run_sql_generation_subgraph(
            query="查询这些门店的订单",
            query_id="test-003-deps",
            user_query="查询北京门店的订单",
            dependencies_results=dependencies_results,
        )
        assert output["validated_sql"] is not None

    def test_retry_on_validation_failure(self, mock_all_dependencies):
        validation_results = [
            {"valid": False, "errors": ["表名不存在"], "warnings": [], "layer": "semantic", "explain_plan": None},
            {"valid": True, "errors": [], "warnings": [], "layer": "all_passed", "explain_plan": "Seq Scan"},
        ]
        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.side_effect = validation_results

        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-004", user_query="查询订单",
        )
        assert output["iteration_count"] == 2
        assert output["validated_sql"] is not None

    def test_max_iterations_reached(self, mock_all_dependencies):
        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.return_value = {
            "valid": False, "errors": ["持续错误"], "warnings": [], "layer": "semantic", "explain_plan": None,
        }
        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-005", user_query="查询订单",
        )
        assert output["iteration_count"] == 3
        assert output["validated_sql"] is None
        assert output["error"] is not None

    def test_schema_retrieval_failure(self, mock_all_dependencies):
        mock_retriever_instance = mock_all_dependencies["retriever"].return_value
        mock_retriever_instance.retrieve.side_effect = Exception("数据库连接失败")

        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-006", user_query="查询订单",
        )
        assert output["validated_sql"] is None
        assert output["error"] is not None
        assert (
            "Schema检索失败" in output["error"]
            or "数据库连接失败" in output["error"]
            or "Schema检索结果为空" in output["error"]
        )

    def test_sql_generation_failure(self, mock_all_dependencies):
        mock_gen_meta = mock_all_dependencies["gen_get_llm"].return_value
        mock_gen_meta.llm.invoke.side_effect = Exception("API 调用失败")

        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-007", user_query="查询订单",
        )
        assert output["validated_sql"] is None
        assert output["error"] is not None
        assert "SQL生成失败" in output["error"] or "API 调用失败" in output["error"]
        assert output["error_type"] == "generation_failed"

    def test_execution_time_recorded(self, mock_all_dependencies):
        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-008", user_query="查询订单",
        )
        assert "execution_time" in output
        assert output["execution_time"] >= 0

    def test_validation_history_recorded(self, mock_all_dependencies):
        validation_results = [
            {"valid": False, "errors": ["错误1"], "warnings": [], "layer": "semantic", "explain_plan": None},
            {"valid": True, "errors": [], "warnings": [], "layer": "all_passed", "explain_plan": "Seq Scan"},
        ]
        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.side_effect = validation_results

        output = run_sql_generation_subgraph(
            query="查询订单", query_id="test-009", user_query="查询订单",
        )
        assert "validation_history" in output
        assert len(output["validation_history"]) == 2


class TestStateHelpers:
    """测试状态辅助函数"""

    def test_create_initial_state(self):
        state = create_initial_state(query="test query", query_id="q1", user_query="original query")
        assert state["query"] == "test query"
        assert state["query_id"] == "q1"
        assert state["user_query"] == "original query"
        assert state["iteration_count"] == 0
        assert state["validation_history"] == []

    def test_is_successful_true(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, validated_sql="SELECT * FROM test",
        )
        assert is_successful(state) is True

    def test_is_successful_false(self):
        state = SQLGenerationState(
            messages=[], query="test", query_id="q1", user_query="test",
            dependencies_results={}, validated_sql=None,
        )
        assert is_successful(state) is False


class TestEndToEndScenarios:
    """端到端场景测试"""

    def test_simple_query_success(self, mock_all_dependencies):
        output = run_sql_generation_subgraph(
            query="查询所有订单", query_id="e2e-001", user_query="查询所有订单",
        )
        assert output["validated_sql"] is not None
        assert output["error"] is None
        assert output["iteration_count"] >= 1

    def test_complex_query_with_hints(self, mock_all_dependencies):
        parse_hints = {
            "time": {"start": "2024-01-01", "end": "2024-12-31"},
            "dimensions": [
                {"text": "北京", "type": "location"},
                {"text": "电子产品", "type": "category"},
            ],
            "metric": {"text": "销售额", "aggregation": "sum"},
        }
        output = run_sql_generation_subgraph(
            query="查询北京地区电子产品的销售额", query_id="e2e-002",
            user_query="2024年北京地区电子产品的销售额", parse_hints=parse_hints,
        )
        assert output["validated_sql"] is not None

    def test_query_with_dependencies(self, mock_all_dependencies):
        dependencies = {
            "sub_query_1": {
                "question": "查询某些门店",
                "execution_result": {
                    "sub_query_id": "sub_query_1",
                    "sql": "SELECT store_id FROM public.dim_store WHERE region = 'A'",
                    "success": True, "columns": ["store_id"],
                    "rows": [["001"], ["002"]], "row_count": 2,
                    "execution_time_ms": 3.0, "error": None,
                },
            }
        }
        output = run_sql_generation_subgraph(
            query="查询这些门店的订单总额", query_id="e2e-003",
            user_query="查询这些门店的订单总额", dependencies_results=dependencies,
        )
        assert output["validated_sql"] is not None
