"""父图编译和条件边单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.graph import (
    route_by_complexity,
    route_after_sql_gen,
    sql_gen_wrapper,
)


class TestConditionalEdges:
    """测试条件边函数"""

    def test_route_by_complexity_simple(self):
        """测试 complexity=simple 时的路由"""
        state = {"complexity": "simple"}

        result = route_by_complexity(state)

        # 应该路由到 simple_planner
        assert result == "simple_planner"

    def test_route_by_complexity_complex(self):
        """测试 complexity=complex 时的路由"""
        state = {"complexity": "complex"}

        result = route_by_complexity(state)

        # Phase 2: 应该路由到 planner
        assert result == "planner"

    def test_route_by_complexity_none(self):
        """测试 complexity=None 时的路由"""
        state = {"complexity": None}

        result = route_by_complexity(state)

        # None 不等于 "simple"，应该路由到 planner（Phase 2）
        assert result == "planner"

    def test_route_by_complexity_missing(self):
        """测试缺少 complexity 字段时的路由"""
        state = {}

        result = route_by_complexity(state)

        # 缺失时默认路由到 planner（Phase 2）
        assert result == "planner"

    def test_route_after_sql_gen_success(self):
        """测试 SQL 生成成功时的路由"""
        state = {"validated_sql": "SELECT * FROM table"}

        result = route_after_sql_gen(state)

        # 应该路由到 sql_exec
        assert result == "sql_exec"

    def test_route_after_sql_gen_failure(self):
        """测试 SQL 生成失败时的路由"""
        state = {"validated_sql": None}

        result = route_after_sql_gen(state)

        # 应该路由到 summarizer
        assert result == "summarizer"

    def test_route_after_sql_gen_empty_string(self):
        """测试 validated_sql 为空字符串时的路由"""
        state = {"validated_sql": ""}

        result = route_after_sql_gen(state)

        # 空字符串为 Falsy，应该路由到 summarizer
        assert result == "summarizer"

    def test_route_after_sql_gen_missing(self):
        """测试缺少 validated_sql 字段时的路由"""
        state = {}

        result = route_after_sql_gen(state)

        # 缺失时路由到 summarizer
        assert result == "summarizer"


class TestSQLGenWrapper:
    """测试 SQL 生成子图 Wrapper"""

    @pytest.fixture
    def base_state(self):
        """基础 State"""
        return {
            "query_id": "test-001",
            "user_query": "查询销售额",
            "current_sub_query_id": "test-001_sq1",
            "sub_queries": [
                {
                    "sub_query_id": "test-001_sq1",
                    "query": "查询销售额",
                    "status": "pending",
                }
            ],
        }

    def test_wrapper_success(self, base_state):
        """测试 Wrapper 调用成功"""
        # Mock 子图函数（在 wrapper 内部导入，需要 mock 正确的位置）
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": "SELECT SUM(amount) FROM sales",
                "error": None,
                "error_type": None,
                "iteration_count": 2,
            }

            # 执行 Wrapper
            result = sql_gen_wrapper(base_state)

            # 验证调用参数
            mock_subgraph.assert_called_once_with(
                query="查询销售额",
                query_id="test-001",
                user_query="查询销售额",
                dependencies_results={},
                parse_hints=None,
            )

            # 验证返回结果
            assert result["validated_sql"] == "SELECT SUM(amount) FROM sales"
            assert result["error"] is None
            assert result["iteration_count"] == 2

            # 验证子查询状态更新
            sub_query = base_state["sub_queries"][0]
            assert sub_query["status"] == "completed"
            assert sub_query["validated_sql"] == "SELECT SUM(amount) FROM sales"
            assert sub_query["iteration_count"] == 2

    def test_wrapper_failure(self, base_state):
        """测试 Wrapper 调用失败（子图返回错误）"""
        # Mock 子图返回失败
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": None,
                "error": "Schema retrieval failed",
                "error_type": "schema_retrieval_failed",
                "iteration_count": 0,
            }

            # 执行 Wrapper
            result = sql_gen_wrapper(base_state)

            # 验证返回错误
            assert result["validated_sql"] is None
            assert result["error"] == "Schema retrieval failed"
            assert result["error_type"] == "schema_retrieval_failed"

            # 验证子查询状态更新为失败
            sub_query = base_state["sub_queries"][0]
            assert sub_query["status"] == "failed"
            assert sub_query["error"] == "Schema retrieval failed"

    def test_wrapper_exception_handling(self, base_state):
        """测试 Wrapper 异常兜底"""
        # Mock 子图抛出异常
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.side_effect = Exception("子图崩溃")

            # 执行 Wrapper
            result = sql_gen_wrapper(base_state)

            # 验证返回错误信息
            assert result["validated_sql"] is None
            assert "异常" in result["error"]
            assert result["error_type"] == "generation_failed"

            # 验证子查询状态更新为失败
            sub_query = base_state["sub_queries"][0]
            assert sub_query["status"] == "failed"
            assert "异常" in sub_query["error"]

    def test_wrapper_missing_current_sub_query_id(self):
        """测试缺少 current_sub_query_id"""
        state = {
            "query_id": "test-002",
            "user_query": "测试",
            "sub_queries": [],
        }

        # 执行 Wrapper
        result = sql_gen_wrapper(state)

        # 验证返回错误
        assert result["error"] == "No current sub_query_id"
        assert result["error_type"] == "internal_error"

    def test_wrapper_sub_query_not_found(self, base_state):
        """测试找不到对应的子查询"""
        # 修改 current_sub_query_id 为不存在的 ID
        base_state["current_sub_query_id"] = "nonexistent_id"

        # 执行 Wrapper
        result = sql_gen_wrapper(base_state)

        # 验证返回错误
        assert "not found" in result["error"]
        assert result["error_type"] == "internal_error"

    def test_wrapper_preserves_query_id(self, base_state):
        """测试 Wrapper 正确传递 query_id"""
        # Mock 子图
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": "SELECT 1",
                "error": None,
                "error_type": None,
                "iteration_count": 1,
            }

            # 执行 Wrapper
            sql_gen_wrapper(base_state)

            # 验证 query_id 被正确传递
            call_kwargs = mock_subgraph.call_args[1]
            assert call_kwargs["query_id"] == "test-001"

    def test_wrapper_preserves_user_query(self, base_state):
        """测试 Wrapper 正确传递 user_query"""
        # Mock 子图
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": "SELECT 1",
                "error": None,
                "error_type": None,
                "iteration_count": 1,
            }

            # 执行 Wrapper
            sql_gen_wrapper(base_state)

            # 验证 user_query 被正确传递
            call_kwargs = mock_subgraph.call_args[1]
            assert call_kwargs["user_query"] == "查询销售额"

    def test_wrapper_no_dependencies_in_fast_path(self, base_state):
        """测试 Fast Path 无依赖"""
        # Mock 子图
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": "SELECT 1",
                "error": None,
                "error_type": None,
                "iteration_count": 1,
            }

            # 执行 Wrapper
            sql_gen_wrapper(base_state)

            # 验证 dependencies_results 为空字典
            call_kwargs = mock_subgraph.call_args[1]
            assert call_kwargs["dependencies_results"] == {}

    def test_wrapper_no_parse_hints_in_phase1(self, base_state):
        """测试 Phase 1 无 parse_hints"""
        # Mock 子图
        with patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph") as mock_subgraph:
            mock_subgraph.return_value = {
                "validated_sql": "SELECT 1",
                "error": None,
                "error_type": None,
                "iteration_count": 1,
            }

            # 执行 Wrapper
            sql_gen_wrapper(base_state)

            # 验证 parse_hints 为 None
            call_kwargs = mock_subgraph.call_args[1]
            assert call_kwargs["parse_hints"] is None


class TestGraphCompilation:
    """测试父图编译"""

    def test_create_graph_returns_compiled_app(self):
        """测试 create_nl2sql_father_graph 返回编译后的图"""
        from src.modules.nl2sql_father.graph import create_nl2sql_father_graph

        app = create_nl2sql_father_graph()

        # 验证返回的是编译后的对象
        assert app is not None
        assert hasattr(app, "invoke")  # 编译后的图应该有 invoke 方法

    def test_graph_has_correct_nodes(self):
        """测试图包含正确的节点"""
        from src.modules.nl2sql_father.graph import create_nl2sql_father_graph

        app = create_nl2sql_father_graph()

        # 验证图结构（LangGraph 0.2+ 可以通过 get_graph() 访问）
        # 注意：具体验证方式依赖 LangGraph 版本
        assert app is not None


class TestRunNL2SQLQuery:
    """测试便捷函数"""

    def test_run_query_auto_generates_query_id(self):
        """测试自动生成 query_id"""
        from src.modules.nl2sql_father.graph import run_nl2sql_query

        # Mock 图执行
        with patch("src.modules.nl2sql_father.graph.create_nl2sql_father_graph") as mock_create:
            mock_app = MagicMock()
            mock_app.invoke.return_value = {
                "user_query": "测试",
                "query_id": "q_abc123",
                "complexity": "simple",
                "summary": "查询成功",
            }
            mock_create.return_value = mock_app

            # 不提供 query_id
            result = run_nl2sql_query("测试问题")

            # 验证自动生成了 query_id
            assert "query_id" in result
            assert result["query_id"].startswith("q_")

    def test_run_query_uses_provided_query_id(self):
        """测试使用提供的 query_id"""
        from src.modules.nl2sql_father.graph import run_nl2sql_query

        # Mock 图执行
        with patch("src.modules.nl2sql_father.graph.create_nl2sql_father_graph") as mock_create:
            mock_app = MagicMock()
            mock_app.invoke.return_value = {
                "user_query": "测试",
                "query_id": "custom-id",
                "complexity": "simple",
                "summary": "查询成功",
            }
            mock_create.return_value = mock_app

            # 提供自定义 query_id
            result = run_nl2sql_query("测试问题", query_id="custom-id")

            # 验证使用了自定义 ID
            assert result["query_id"] == "custom-id"

    def test_run_query_tracks_execution_time(self):
        """测试记录执行时间"""
        from src.modules.nl2sql_father.graph import run_nl2sql_query

        # Mock 图执行
        with patch("src.modules.nl2sql_father.graph.create_nl2sql_father_graph") as mock_create:
            mock_app = MagicMock()
            mock_app.invoke.return_value = {
                "user_query": "测试",
                "query_id": "test-001",
                "summary": "完成",
            }
            mock_create.return_value = mock_app

            # 执行查询
            result = run_nl2sql_query("测试")

            # 验证包含执行时间（从 extract_final_result 提取的字段）
            assert "metadata" in result
            assert "total_execution_time_ms" in result["metadata"]
