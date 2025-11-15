"""NL2SQL 父图集成测试

测试完整的 Fast Path 和 Complex Path 流程（端到端）
Mock 外部依赖（LLM、SQL生成子图、数据库），但测试父图内部各节点的协同
"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.graph import create_nl2sql_father_graph, run_nl2sql_query
from src.modules.nl2sql_father.state import create_initial_state


class TestFastPathIntegration:
    """测试 Fast Path 端到端流程"""

    @pytest.fixture
    def mock_all_dependencies(self):
        """Mock 所有外部依赖"""
        patches = []

        # Mock Router LLM
        router_llm_patch = patch("src.modules.nl2sql_father.nodes.router.ChatTongyi")
        mock_router_llm_class = router_llm_patch.start()
        mock_router_llm = MagicMock()
        mock_router_llm_class.return_value = mock_router_llm
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

        # Mock Summarizer LLM
        summarizer_llm_patch = patch("src.modules.nl2sql_father.nodes.summarizer.ChatTongyi")
        mock_summarizer_llm_class = summarizer_llm_patch.start()
        mock_summarizer_llm = MagicMock()
        mock_summarizer_llm_class.return_value = mock_summarizer_llm
        patches.append(summarizer_llm_patch)

        yield {
            "router_llm": mock_router_llm,
            "subgraph": mock_subgraph,
            "pg_client": mock_pg,
            "summarizer_llm": mock_summarizer_llm,
        }

        # 清理所有 patch
        for p in patches:
            p.stop()

    def test_fast_path_success_flow(self, mock_all_dependencies):
        """测试 Fast Path 成功流程：Router → Simple Planner → SQL Gen → SQL Exec → Summarizer"""
        # 配置 Router mock：返回 simple
        mock_router_response = MagicMock()
        mock_router_response.content = "simple"
        mock_all_dependencies["router_llm"].invoke.return_value = mock_router_response

        # 配置 SQL 生成子图 mock：返回成功
        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": "SELECT SUM(amount) FROM sales WHERE year = 2024",
            "error": None,
            "error_type": None,
            "iteration_count": 2,
        }

        # 配置数据库 mock：返回结果
        mock_all_dependencies["pg_client"].execute_query.return_value = {
            "columns": ["total_amount"],
            "rows": [[150000.00]],
        }

        # 配置 Summarizer mock：返回总结
        mock_summarizer_response = MagicMock()
        mock_summarizer_response.content = "2024年的总销售额为15万元。"
        mock_all_dependencies["summarizer_llm"].invoke.return_value = mock_summarizer_response

        # 创建图并执行
        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="查询2024年的销售额", query_id="test-001")
        final_state = app.invoke(initial_state)

        # 验证流程
        assert final_state["complexity"] == "simple"
        assert final_state["path_taken"] == "fast"
        assert len(final_state["sub_queries"]) == 1
        assert final_state["sub_queries"][0]["status"] == "completed"
        assert final_state["validated_sql"] == "SELECT SUM(amount) FROM sales WHERE year = 2024"
        assert len(final_state["execution_results"]) == 1
        assert final_state["execution_results"][0]["success"] is True
        assert final_state["summary"] == "2024年的总销售额为15万元。"

    def test_fast_path_sql_generation_failure(self, mock_all_dependencies):
        """测试 Fast Path SQL生成失败流程：跳过SQL执行，直接进入Summarizer"""
        # 配置 Router mock：返回 simple
        mock_router_response = MagicMock()
        mock_router_response.content = "simple"
        mock_all_dependencies["router_llm"].invoke.return_value = mock_router_response

        # 配置 SQL 生成子图 mock：返回失败
        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": None,
            "error": "Schema retrieval failed",
            "error_type": "schema_retrieval_failed",
            "iteration_count": 0,
        }

        # 创建图并执行
        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="查询不存在的表", query_id="test-002")
        final_state = app.invoke(initial_state)

        # 验证流程：SQL执行应该被跳过
        assert final_state["complexity"] == "simple"
        assert final_state["validated_sql"] is None
        assert final_state["execution_results"] == []  # SQL执行被跳过
        assert "抱歉" in final_state["summary"]  # 错误提示

        # 验证数据库未被调用
        mock_all_dependencies["pg_client"].execute_query.assert_not_called()

    def test_fast_path_sql_execution_failure(self, mock_all_dependencies):
        """测试 Fast Path SQL执行失败流程"""
        # 配置 Router mock
        mock_router_response = MagicMock()
        mock_router_response.content = "simple"
        mock_all_dependencies["router_llm"].invoke.return_value = mock_router_response

        # 配置 SQL 生成子图 mock：成功
        mock_all_dependencies["subgraph"].return_value = {
            "validated_sql": "SELECT * FROM nonexistent_table",
            "error": None,
            "error_type": None,
            "iteration_count": 1,
        }

        # 配置数据库 mock：执行失败
        mock_all_dependencies["pg_client"].execute_query.side_effect = Exception("表不存在")

        # 创建图并执行
        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="测试问题", query_id="test-003")
        final_state = app.invoke(initial_state)

        # 验证流程
        assert final_state["validated_sql"] is not None
        assert len(final_state["execution_results"]) == 1
        assert final_state["execution_results"][0]["success"] is False
        assert "表不存在" in final_state["execution_results"][0]["error"]
        assert "失败" in final_state["summary"]


class TestComplexPathIntegration:
    """测试 Complex Path 端到端流程（Phase 1）"""

    @pytest.fixture
    def mock_router_llm(self):
        """Mock Router LLM"""
        with patch("src.modules.nl2sql_father.nodes.router.ChatTongyi") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm_class.return_value = mock_llm
            yield mock_llm

    def test_complex_path_not_supported(self, mock_router_llm):
        """测试 Complex Path：Router判定为complex，直接进入Summarizer返回暂不支持"""
        # 配置 Router mock：返回 complex
        mock_response = MagicMock()
        mock_response.content = "complex"
        mock_router_llm.invoke.return_value = mock_response

        # 创建图并执行
        app = create_nl2sql_father_graph()
        initial_state = create_initial_state(user_query="复杂问题", query_id="test-004")
        final_state = app.invoke(initial_state)

        # 验证流程：应该直接跳转到Summarizer
        assert final_state["complexity"] == "complex"
        assert final_state["path_taken"] == "complex"
        assert final_state["sub_queries"] == []  # 没有创建子查询
        assert final_state["validated_sql"] is None
        assert final_state["execution_results"] == []
        assert "暂不支持" in final_state["summary"]


class TestRunNL2SQLQueryIntegration:
    """测试便捷函数端到端流程"""

    @pytest.fixture
    def mock_all_dependencies(self):
        """Mock 所有外部依赖"""
        patches = []

        # Mock Router
        router_patch = patch("src.modules.nl2sql_father.nodes.router.ChatTongyi")
        mock_router_class = router_patch.start()
        mock_router_llm = MagicMock()
        mock_router_response = MagicMock()
        mock_router_response.content = "simple"
        mock_router_llm.invoke.return_value = mock_router_response
        mock_router_class.return_value = mock_router_llm
        patches.append(router_patch)

        # Mock Subgraph
        subgraph_patch = patch("src.modules.sql_generation.subgraph.create_subgraph.run_sql_generation_subgraph")
        mock_subgraph = subgraph_patch.start()
        mock_subgraph.return_value = {
            "validated_sql": "SELECT 1",
            "error": None,
            "error_type": None,
            "iteration_count": 1,
        }
        patches.append(subgraph_patch)

        # Mock PGClient
        pg_patch = patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient")
        mock_pg_class = pg_patch.start()
        mock_pg = MagicMock()
        mock_pg.execute_query.return_value = {"columns": ["?column?"], "rows": [[1]]}
        mock_pg_class.return_value = mock_pg
        patches.append(pg_patch)

        # Mock Summarizer
        summarizer_patch = patch("src.modules.nl2sql_father.nodes.summarizer.ChatTongyi")
        mock_summarizer_class = summarizer_patch.start()
        mock_summarizer_llm = MagicMock()
        mock_summarizer_response = MagicMock()
        mock_summarizer_response.content = "查询成功"
        mock_summarizer_llm.invoke.return_value = mock_summarizer_response
        mock_summarizer_class.return_value = mock_summarizer_llm
        patches.append(summarizer_patch)

        yield

        for p in patches:
            p.stop()

    def test_run_nl2sql_query_auto_query_id(self, mock_all_dependencies):
        """测试 run_nl2sql_query 自动生成 query_id"""
        result = run_nl2sql_query("测试问题")

        # 验证结果结构
        assert "user_query" in result
        assert "query_id" in result
        assert "complexity" in result
        assert "path_taken" in result
        assert "summary" in result
        assert "sql" in result
        assert "metadata" in result

        # 验证 query_id 自动生成
        assert result["query_id"].startswith("q_")

        # 验证执行时间被记录
        assert "total_execution_time_ms" in result["metadata"]
        assert result["metadata"]["total_execution_time_ms"] > 0

    def test_run_nl2sql_query_custom_query_id(self, mock_all_dependencies):
        """测试 run_nl2sql_query 使用自定义 query_id"""
        result = run_nl2sql_query("测试问题", query_id="custom-id")

        # 验证使用了自定义 ID
        assert result["query_id"] == "custom-id"

    def test_run_nl2sql_query_sql_shortcut(self, mock_all_dependencies):
        """测试 run_nl2sql_query 返回的 sql 快捷字段"""
        result = run_nl2sql_query("测试问题")

        # 验证 sql 快捷字段（从第一个sub_query提取）
        assert result["sql"] == "SELECT 1"

    def test_run_nl2sql_query_complete_metadata(self, mock_all_dependencies):
        """测试 run_nl2sql_query 返回完整的元数据"""
        result = run_nl2sql_query("测试问题")

        # 验证元数据
        metadata = result["metadata"]
        assert "total_execution_time_ms" in metadata
        assert "router_latency_ms" in metadata

    def test_run_nl2sql_query_sub_queries_detail(self, mock_all_dependencies):
        """测试 run_nl2sql_query 返回完整的 sub_queries 信息"""
        result = run_nl2sql_query("测试问题")

        # 验证 sub_queries
        assert len(result["sub_queries"]) == 1
        sub_query = result["sub_queries"][0]
        assert sub_query["status"] == "completed"
        assert sub_query["validated_sql"] == "SELECT 1"
        assert sub_query["execution_result"] is not None

    def test_run_nl2sql_query_execution_results_detail(self, mock_all_dependencies):
        """测试 run_nl2sql_query 返回完整的执行结果"""
        result = run_nl2sql_query("测试问题")

        # 验证 execution_results
        assert len(result["execution_results"]) == 1
        exec_result = result["execution_results"][0]
        assert exec_result["success"] is True
        assert exec_result["columns"] == ["?column?"]
        assert exec_result["rows"] == [[1]]
