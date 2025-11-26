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


@pytest.fixture
def mock_all_dependencies():
    """Mock 所有外部依赖"""
    with patch("src.modules.sql_generation.subgraph.nodes.schema_retrieval.SchemaRetriever") as mock_retriever, \
         patch("src.modules.sql_generation.subgraph.nodes.sql_generation.ChatTongyi") as mock_llm, \
         patch("src.modules.sql_generation.subgraph.nodes.validation.SQLValidationTool") as mock_validation, \
         patch("src.services.config_loader.load_subgraph_config") as mock_config:

        # Mock config
        mock_config.return_value = {
            "schema_retrieval": {
                "topk_tables": 10,
                "topk_columns": 10,
            },
            "sql_generation": {
                "llm_model": "qwen-plus",
                "api_key": "test-key",
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

        # Mock LLM
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "SELECT id, customer_id, amount FROM public.orders WHERE order_date >= '2024-01-01' AND order_date < '2024-02-01'"
        mock_llm_instance.invoke.return_value = mock_response
        mock_llm.return_value = mock_llm_instance

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
            "llm": mock_llm,
            "validation": mock_validation,
            "config": mock_config,
        }


class TestSubgraphCreation:
    """测试子图创建"""

    def test_create_subgraph_structure(self):
        """测试子图结构正确创建"""
        with patch("src.services.config_loader.load_subgraph_config"):
            subgraph = create_sql_generation_subgraph()

            # 子图应该被成功编译
            assert subgraph is not None

            # 验证子图可以被调用
            # （不实际运行，只验证结构）


class TestShouldRetryLogic:
    """测试重试逻辑"""

    def test_retry_on_validation_failure(self):
        """测试验证失败时重试"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            iteration_count=1,
            validated_sql=None,
            error_type="validation_failed",
        )

        with patch("src.modules.sql_generation.subgraph.create_subgraph.load_subgraph_config") as mock_config:
            mock_config.return_value = {"retry": {"max_iterations": 3}}

            result = should_retry(state)

            assert result == "retry"

    def test_success_on_validated_sql(self):
        """测试有 validated_sql 时返回成功"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            iteration_count=1,
            validated_sql="SELECT * FROM public.test",
        )

        with patch("src.modules.sql_generation.subgraph.create_subgraph.load_subgraph_config"):
            result = should_retry(state)

            assert result == "success"

    def test_fail_on_max_iterations(self):
        """测试达到最大迭代次数时失败"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            iteration_count=3,
            validated_sql=None,
            error_type="validation_failed",
        )

        with patch("src.modules.sql_generation.subgraph.create_subgraph.load_subgraph_config") as mock_config:
            mock_config.return_value = {"retry": {"max_iterations": 3}}

            result = should_retry(state)

            assert result == "fail"

    def test_fail_on_non_recoverable_error(self):
        """测试不可恢复错误时直接失败"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            iteration_count=1,
            validated_sql=None,
            error_type="schema_retrieval_failed",
        )

        with patch("src.modules.sql_generation.subgraph.create_subgraph.load_subgraph_config"):
            result = should_retry(state)

            assert result == "fail"

    def test_fail_on_generation_failed(self):
        """测试 SQL 生成失败时直接失败"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            iteration_count=1,
            validated_sql=None,
            error_type="generation_failed",
        )

        with patch("src.modules.sql_generation.subgraph.create_subgraph.load_subgraph_config"):
            result = should_retry(state)

            assert result == "fail"


class TestSubgraphExecution:
    """测试子图执行"""

    def test_successful_execution(self, mock_all_dependencies):
        """测试成功执行流程"""
        output = run_sql_generation_subgraph(
            query="查询2024年1月的订单",
            query_id="test-001",
            user_query="查询2024年1月的订单",
        )

        # 验证输出包含必要字段
        assert "validated_sql" in output
        assert "error" in output
        assert "execution_time" in output

        # 验证成功生成了 SQL
        assert output["validated_sql"] is not None
        assert "SELECT" in output["validated_sql"]

    def test_execution_with_parse_hints(self, mock_all_dependencies):
        """测试带解析提示的执行"""
        parse_hints = {
            "time": {
                "start": "2024-01-01",
                "end": "2024-02-01",
            },
            "dimensions": [
                {"text": "北京", "type": "location"}
            ],
        }

        output = run_sql_generation_subgraph(
            query="查询北京地区的订单",
            query_id="test-002",
            user_query="查询北京地区的订单",
            parse_hints=parse_hints,
        )

        assert output["validated_sql"] is not None

    def test_execution_with_dependencies(self, mock_all_dependencies):
        """测试带依赖结果的执行"""
        dependencies_results = {
            "sub1": {
                "question": "查询北京的门店",
                "execution_result": {
                    "sub_query_id": "sub1",
                    "sql": "SELECT store_id FROM public.dim_store WHERE city = '北京'",
                    "success": True,
                    "columns": ["store_id"],
                    "rows": [["BJ001"]],
                    "row_count": 1,
                    "execution_time_ms": 3.0,
                    "error": None
                }
            }
        }

        output = run_sql_generation_subgraph(
            query="查询这些门店的订单",
            query_id="test-003",
            user_query="查询北京门店的订单",
            dependencies_results=dependencies_results,
        )

        assert output["validated_sql"] is not None

    def test_retry_on_validation_failure(self, mock_all_dependencies):
        """测试验证失败后重试"""
        # 第一次验证失败，第二次成功
        validation_results = [
            {
                "valid": False,
                "errors": ["表名不存在"],
                "warnings": [],
                "layer": "semantic",
                "explain_plan": None,
            },
            {
                "valid": True,
                "errors": [],
                "warnings": [],
                "layer": "all_passed",
                "explain_plan": "Seq Scan",
            },
        ]

        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.side_effect = validation_results

        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-004",
            user_query="查询订单",
        )

        # 应该经过 2 次迭代
        assert output["iteration_count"] == 2
        assert output["validated_sql"] is not None

    def test_max_iterations_reached(self, mock_all_dependencies):
        """测试达到最大迭代次数"""
        # 所有验证都失败
        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.return_value = {
            "valid": False,
            "errors": ["持续错误"],
            "warnings": [],
            "layer": "semantic",
            "explain_plan": None,
        }

        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-005",
            user_query="查询订单",
        )

        # 应该达到最大迭代次数
        assert output["iteration_count"] == 3
        assert output["validated_sql"] is None
        assert output["error"] is not None

    def test_schema_retrieval_failure(self, mock_all_dependencies):
        """测试 Schema 检索失败"""
        # Mock retriever 抛出异常
        mock_retriever_instance = mock_all_dependencies["retriever"].return_value
        mock_retriever_instance.retrieve.side_effect = Exception("数据库连接失败")

        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-006",
            user_query="查询订单",
        )

        # 应该返回错误
        assert output["validated_sql"] is None
        assert output["error"] is not None
        assert "Schema检索失败" in output["error"] or "数据库连接失败" in output["error"]
        assert output["error_type"] == "schema_retrieval_failed"

    def test_sql_generation_failure(self, mock_all_dependencies):
        """测试 SQL 生成失败"""
        # Mock LLM 抛出异常
        mock_llm_instance = mock_all_dependencies["llm"].return_value
        mock_llm_instance.invoke.side_effect = Exception("API 调用失败")

        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-007",
            user_query="查询订单",
        )

        # 应该返回错误
        assert output["validated_sql"] is None
        assert output["error"] is not None
        assert "SQL生成失败" in output["error"] or "API 调用失败" in output["error"]
        assert output["error_type"] == "generation_failed"

    def test_execution_time_recorded(self, mock_all_dependencies):
        """测试执行时间被记录"""
        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-008",
            user_query="查询订单",
        )

        # 执行时间应该被记录
        assert "execution_time" in output
        assert output["execution_time"] >= 0

    def test_validation_history_recorded(self, mock_all_dependencies):
        """测试验证历史被记录"""
        # 设置验证失败一次，然后成功
        validation_results = [
            {
                "valid": False,
                "errors": ["错误1"],
                "warnings": [],
                "layer": "semantic",
                "explain_plan": None,
            },
            {
                "valid": True,
                "errors": [],
                "warnings": [],
                "layer": "all_passed",
                "explain_plan": "Seq Scan",
            },
        ]

        mock_validation_instance = mock_all_dependencies["validation"].return_value
        mock_validation_instance.validate.side_effect = validation_results

        output = run_sql_generation_subgraph(
            query="查询订单",
            query_id="test-009",
            user_query="查询订单",
        )

        # 验证历史应该包含 2 条记录
        assert "validation_history" in output
        assert len(output["validation_history"]) == 2


class TestStateHelpers:
    """测试状态辅助函数"""

    def test_create_initial_state(self):
        """测试创建初始状态"""
        state = create_initial_state(
            query="test query",
            query_id="q1",
            user_query="original query",
        )

        assert state["query"] == "test query"
        assert state["query_id"] == "q1"
        assert state["user_query"] == "original query"
        assert state["iteration_count"] == 0
        assert state["validation_history"] == []

    def test_is_successful_true(self):
        """测试成功判断"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            validated_sql="SELECT * FROM test",
        )

        assert is_successful(state) is True

    def test_is_successful_false(self):
        """测试失败判断"""
        state = SQLGenerationState(
            messages=[],
            query="test",
            query_id="q1",
            user_query="test",
            dependencies_results={},
            validated_sql=None,
        )

        assert is_successful(state) is False


class TestEndToEndScenarios:
    """端到端场景测试"""

    def test_simple_query_success(self, mock_all_dependencies):
        """测试简单查询成功场景"""
        output = run_sql_generation_subgraph(
            query="查询所有订单",
            query_id="e2e-001",
            user_query="查询所有订单",
        )

        assert output["validated_sql"] is not None
        assert output["error"] is None
        assert output["iteration_count"] >= 1

    def test_complex_query_with_hints(self, mock_all_dependencies):
        """测试复杂查询带提示的场景"""
        parse_hints = {
            "time": {"start": "2024-01-01", "end": "2024-12-31"},
            "dimensions": [
                {"text": "北京", "type": "location"},
                {"text": "电子产品", "type": "category"},
            ],
            "metric": {"text": "销售额", "aggregation": "sum"},
        }

        output = run_sql_generation_subgraph(
            query="查询北京地区电子产品的销售额",
            query_id="e2e-002",
            user_query="2024年北京地区电子产品的销售额",
            parse_hints=parse_hints,
        )

        assert output["validated_sql"] is not None

    def test_query_with_dependencies(self, mock_all_dependencies):
        """测试带依赖的查询场景"""
        dependencies = {
            "sub_query_1": {
                "question": "查询某些门店",
                "execution_result": {
                    "sub_query_id": "sub_query_1",
                    "sql": "SELECT store_id FROM public.dim_store WHERE region = 'A'",
                    "success": True,
                    "columns": ["store_id"],
                    "rows": [["001"], ["002"]],
                    "row_count": 2,
                    "execution_time_ms": 3.0,
                    "error": None
                }
            }
        }

        output = run_sql_generation_subgraph(
            query="查询这些门店的订单总额",
            query_id="e2e-003",
            user_query="查询这些门店的订单总额",
            dependencies_results=dependencies,
        )

        assert output["validated_sql"] is not None
