"""NL2SQL 父图集成测试

测试完整的 Fast Path 和 Complex Path 流程（端到端）
Mock 外部依赖（LLM、SQL生成子图、数据库），但测试父图内部各节点的协同
"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.graph import create_nl2sql_father_graph, run_nl2sql_query
from src.modules.nl2sql_father.state import create_initial_state


def _mock_get_llm_return(content: str = "", side_effect=None, provider="dashscope", model="qwen-turbo"):
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
    mock_meta.provider = provider
    mock_meta.model = model
    return mock_meta


class TestFastPathIntegration:
    """测试 Fast Path 端到端流程"""

    @pytest.fixture
    def mock_all_dependencies(self):
        """Mock 所有外部依赖"""
        patches = []

        # Mock Router LLM (get_llm)
        router_llm_patch = patch("src.modules.nl2sql_father.nodes.router.get_llm")
        mock_router_get_llm = router_llm_patch.start()
        patches.append(router_llm_patch)

        # Mock SQL 生成子图
        subgraph_patch = patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph")
        mock_subgraph = subgraph_patch.start()
        patches.append(subgraph_patch)

        # Mock PGClient
        pg_patch = patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient")
        mock_pg_class = pg_patch.start()
        mock_pg = MagicMock()
        mock_pg_class.return_value = mock_pg
        patches.append(pg_patch)

        # Mock Summarizer LLM (get_llm)
        summarizer_llm_patch = patch("src.modules.nl2sql_father.nodes.summarizer.get_llm")
        mock_summarizer_get_llm = summarizer_llm_patch.start()
        patches.append(summarizer_llm_patch)

        yield {
            "router_get_llm": mock_router_get_llm,
            "subgraph": mock_subgraph,
            "pg_client": mock_pg,
            "summarizer_get_llm": mock_summarizer_get_llm,
        }

        for p in patches:
            p.stop()

    def test_fast_path_success_flow(self, mock_all_dependencies):
        """测试 Fast Path 成功流程"""
        # Router → simple
        mock_all_dependencies["router_get_llm"].return_value = _mock_get_llm_return("simple")

        # SQL 生成子图 → 成功
        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": "SELECT SUM(amount) FROM sales WHERE year = 2024",
            "error": None, "error_type": None, "iteration_count": 2,
        }

        # 数据库 → 返回结果
        mock_all_dependencies["pg_client"].execute_query.return_value = {
            "columns": ["total_amount"], "rows": [[150000.00]],
        }

        # Summarizer → 总结
        mock_all_dependencies["summarizer_get_llm"].return_value = _mock_get_llm_return(
            "2024年的总销售额为15万元。", model="qwen-plus",
        )

        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="查询2024年的销售额", query_id="test-001")
        final_state = app.invoke(initial_state)

        assert final_state["complexity"] == "simple"
        assert final_state["path_taken"] == "fast"
        assert len(final_state["sub_queries"]) == 1
        assert final_state["sub_queries"][0]["status"] == "completed"
        assert final_state["validated_sql"] == "SELECT SUM(amount) FROM sales WHERE year = 2024"
        assert len(final_state["execution_results"]) == 1
        assert final_state["execution_results"][0]["success"] is True
        assert final_state["summary"] == "2024年的总销售额为15万元。"

    def test_fast_path_sql_generation_failure(self, mock_all_dependencies):
        """测试 Fast Path SQL生成失败流程"""
        mock_all_dependencies["router_get_llm"].return_value = _mock_get_llm_return("simple")

        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": None,
            "error": "Schema retrieval failed",
            "error_type": "schema_retrieval_failed",
            "iteration_count": 0,
        }

        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="查询不存在的表", query_id="test-002")
        final_state = app.invoke(initial_state)

        assert final_state["complexity"] == "simple"
        assert final_state["validated_sql"] is None
        assert final_state["execution_results"] == []
        assert "抱歉" in final_state["summary"]

        mock_all_dependencies["pg_client"].execute_query.assert_not_called()

    def test_fast_path_sql_execution_failure(self, mock_all_dependencies):
        """测试 Fast Path SQL执行失败流程"""
        mock_all_dependencies["router_get_llm"].return_value = _mock_get_llm_return("simple")

        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": "SELECT * FROM nonexistent_table",
            "error": None, "error_type": None, "iteration_count": 1,
        }

        mock_all_dependencies["pg_client"].execute_query.side_effect = Exception("表不存在")

        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="测试问题", query_id="test-003")
        final_state = app.invoke(initial_state)

        assert final_state["validated_sql"] is not None
        assert len(final_state["execution_results"]) == 1
        assert final_state["execution_results"][0]["success"] is False
        assert "表不存在" in final_state["execution_results"][0]["error"]
        assert "失败" in final_state["summary"]


class TestComplexPathIntegration:
    """测试 Complex Path 端到端流程"""

    @pytest.fixture
    def mock_complex_dependencies(self):
        """Mock Router + Planner LLM"""
        patches = []

        router_patch = patch("src.modules.nl2sql_father.nodes.router.get_llm")
        mock_router_get_llm = router_patch.start()
        patches.append(router_patch)

        planner_patch = patch("src.modules.nl2sql_father.nodes.planner.get_llm")
        mock_planner_get_llm = planner_patch.start()
        patches.append(planner_patch)

        yield {
            "router_get_llm": mock_router_get_llm,
            "planner_get_llm": mock_planner_get_llm,
        }

        for p in patches:
            p.stop()

    def test_complex_path_planner_failure(self, mock_complex_dependencies):
        """测试 Complex Path：Router判定为complex，Planner失败后进入Summarizer返回错误提示"""
        mock_complex_dependencies["router_get_llm"].return_value = _mock_get_llm_return("complex")

        # Planner 返回无效 JSON，触发 planning_failed 错误路由到 Summarizer
        mock_complex_dependencies["planner_get_llm"].return_value = _mock_get_llm_return(
            "无法拆分", model="qwen-max",
        )

        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="复杂问题", query_id="test-004")
        final_state = app.invoke(initial_state)

        assert final_state["complexity"] == "complex"
        assert final_state["path_taken"] == "complex"
        assert "error" in final_state and final_state["error"] is not None
        assert "summary" in final_state
        assert "抱歉" in final_state["summary"]


class TestRunNL2SQLQueryIntegration:
    """测试便捷函数端到端流程"""

    @pytest.fixture
    def mock_all_dependencies(self):
        """Mock 所有外部依赖"""
        patches = []

        # Mock Router (get_llm)
        router_patch = patch("src.modules.nl2sql_father.nodes.router.get_llm")
        mock_router_get_llm = router_patch.start()
        mock_router_get_llm.return_value = _mock_get_llm_return("simple")
        patches.append(router_patch)

        # Mock Subgraph
        subgraph_patch = patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph")
        mock_subgraph = subgraph_patch.start()
        mock_subgraph.return_value = {
            "validated_sql": "SELECT 1", "error": None,
            "error_type": None, "iteration_count": 1,
        }
        patches.append(subgraph_patch)

        # Mock PGClient
        pg_patch = patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient")
        mock_pg_class = pg_patch.start()
        mock_pg = MagicMock()
        mock_pg.execute_query.return_value = {"columns": ["?column?"], "rows": [[1]]}
        mock_pg_class.return_value = mock_pg
        patches.append(pg_patch)

        # Mock Summarizer (get_llm)
        summarizer_patch = patch("src.modules.nl2sql_father.nodes.summarizer.get_llm")
        mock_summarizer_get_llm = summarizer_patch.start()
        mock_summarizer_get_llm.return_value = _mock_get_llm_return(
            "查询成功", model="qwen-plus",
        )
        patches.append(summarizer_patch)

        # 禁用 store 读写与 history 读取
        store_enabled_patch = patch("src.services.langgraph_persistence.postgres.is_store_enabled", return_value=False)
        store_enabled_patch.start()
        patches.append(store_enabled_patch)

        cfg_patch = patch(
            "src.modules.nl2sql_father.graph._get_father_graph_config",
            return_value={"conversation_history": {"enabled": False}},
        )
        cfg_patch.start()
        patches.append(cfg_patch)

        yield

        for p in patches:
            p.stop()

    def test_run_nl2sql_query_auto_query_id(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题")

        assert "user_query" in result
        assert "query_id" in result
        assert "complexity" in result
        assert "path_taken" in result
        assert "summary" in result
        assert "sql" in result
        assert "metadata" in result
        assert result["query_id"].startswith("q_")
        assert "total_execution_time_ms" in result["metadata"]
        assert result["metadata"]["total_execution_time_ms"] > 0

    def test_run_nl2sql_query_custom_query_id(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题", query_id="custom-id")
        assert result["query_id"] == "custom-id"

    def test_run_nl2sql_query_sql_shortcut(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题")
        assert result["sql"] == "SELECT 1"

    def test_run_nl2sql_query_complete_metadata(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题")
        metadata = result["metadata"]
        assert "total_execution_time_ms" in metadata
        assert "router_latency_ms" in metadata

    def test_run_nl2sql_query_sub_queries_detail(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题")
        assert len(result["sub_queries"]) == 1
        sub_query = result["sub_queries"][0]
        assert sub_query["status"] == "completed"
        assert sub_query["validated_sql"] == "SELECT 1"
        assert sub_query["execution_result"] is not None

    def test_run_nl2sql_query_execution_results_detail(self, mock_all_dependencies):
        result = run_nl2sql_query("测试问题")
        assert len(result["execution_results"]) == 1
        exec_result = result["execution_results"][0]
        assert exec_result["success"] is True
        assert exec_result["columns"] == ["?column?"]
        assert exec_result["rows"] == [[1]]
