"""Inject Params 节点单元测试（Phase 2）"""

import pytest

from src.modules.nl2sql_father.nodes.inject_params import inject_params_node
from src.modules.nl2sql_father.state import create_initial_state


class TestInjectParamsNode:
    """测试 Inject Params 节点"""

    def test_inject_single_dependency(self):
        """测试注入单个依赖结果"""
        state = create_initial_state(user_query="测试", query_id="test_q1")

        # 设置子查询
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "query": "查询1",
                "status": "completed",
                "dependencies": [],
                "validated_sql": "SELECT 1",
                "execution_result": {
                    "sub_query_id": "sq1",
                    "sql": "SELECT 1",
                    "success": True,
                    "columns": ["result"],
                    "rows": [[101]],
                    "row_count": 1,
                    "execution_time_ms": 3.0,
                    "error": None
                },
                "error": None,
                "iteration_count": 1,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "query": "查询2",
                "status": "pending",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行注入
        result = inject_params_node(state)

        # 验证结果
        assert result["current_batch_ids"] == ["sq2"]
        assert state["sub_queries"][1]["status"] == "in_progress"
        assert state["sub_queries"][1]["dependencies_results"] is not None
        assert "sq1" in state["sub_queries"][1]["dependencies_results"]
        
        # 验证新格式
        dep_data = state["sub_queries"][1]["dependencies_results"]["sq1"]
        assert "question" in dep_data
        assert "execution_result" in dep_data
        assert dep_data["question"] == "查询1"
        assert dep_data["execution_result"]["rows"] == [[101]]

    def test_inject_multiple_dependencies(self):
        """测试注入多个依赖结果"""
        state = create_initial_state(user_query="测试", query_id="test_q1")

        # 设置子查询
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "query": "查询1",
                "status": "completed",
                "dependencies": [],
                "validated_sql": "SELECT 1",
                "execution_result": {
                    "sub_query_id": "sq1",
                    "sql": "SELECT 1",
                    "success": True,
                    "columns": ["result"],
                    "rows": [[101]],
                    "row_count": 1,
                    "execution_time_ms": 3.0,
                    "error": None
                },
                "error": None,
                "iteration_count": 1,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "query": "查询2",
                "status": "completed",
                "dependencies": [],
                "validated_sql": "SELECT 2",
                "execution_result": {
                    "sub_query_id": "sq2",
                    "sql": "SELECT 2",
                    "success": True,
                    "columns": ["result"],
                    "rows": [[202]],
                    "row_count": 1,
                    "execution_time_ms": 3.0,
                    "error": None
                },
                "error": None,
                "iteration_count": 1,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq3",
                "query": "查询3",
                "status": "pending",
                "dependencies": ["sq1", "sq2"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行注入
        result = inject_params_node(state)

        # 验证结果
        assert result["current_batch_ids"] == ["sq3"]
        assert state["sub_queries"][2]["status"] == "in_progress"
        assert len(state["sub_queries"][2]["dependencies_results"]) == 2
        assert "sq1" in state["sub_queries"][2]["dependencies_results"]
        assert "sq2" in state["sub_queries"][2]["dependencies_results"]
        
        # 验证新格式
        dep1 = state["sub_queries"][2]["dependencies_results"]["sq1"]
        assert "question" in dep1
        assert "execution_result" in dep1
        assert dep1["question"] == "查询1"
        assert dep1["execution_result"]["rows"] == [[101]]
        
        dep2 = state["sub_queries"][2]["dependencies_results"]["sq2"]
        assert "question" in dep2
        assert "execution_result" in dep2
        assert dep2["question"] == "查询2"
        assert dep2["execution_result"]["rows"] == [[202]]

    def test_parallel_batch_selection(self):
        """测试并行批次选择（同一轮执行多个无依赖关系的子查询）"""
        state = create_initial_state(user_query="测试", query_id="test_q1")

        # 设置子查询
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "query": "查询1",
                "status": "completed",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": {"sql": "SELECT 1", "rows": [[101]], "success": True},
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "query": "查询2",
                "status": "pending",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq3",
                "query": "查询3",
                "status": "pending",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行注入
        result = inject_params_node(state)

        # 验证结果：sq2 和 sq3 都应该在当前批次（都依赖 sq1，可以并行执行）
        assert len(result["current_batch_ids"]) == 2
        assert "sq2" in result["current_batch_ids"]
        assert "sq3" in result["current_batch_ids"]
        assert state["sub_queries"][1]["status"] == "in_progress"
        assert state["sub_queries"][2]["status"] == "in_progress"

    def test_no_ready_queries(self):
        """测试没有准备好的子查询"""
        state = create_initial_state(user_query="测试", query_id="test_q1")

        # 设置子查询：sq2 依赖 sq1，但 sq1 尚未完成（sq1 也有依赖 sq0，但 sq0 不存在）
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "query": "查询1",
                "status": "pending",
                "dependencies": ["sq0"],  # 依赖一个不存在的子查询
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "query": "查询2",
                "status": "pending",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行注入
        result = inject_params_node(state)

        # 验证结果：没有准备好的子查询（因为 sq1 依赖不存在的 sq0，sq2 依赖未完成的 sq1）
        assert result["current_batch_ids"] == []

    def test_skip_in_progress_and_completed_queries(self):
        """测试跳过已经 in_progress 和 completed 的子查询"""
        state = create_initial_state(user_query="测试", query_id="test_q1")

        # 设置子查询
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "query": "查询1",
                "status": "completed",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": {"sql": "SELECT 1", "rows": [[101]], "success": True},
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "query": "查询2",
                "status": "in_progress",  # 已经 in_progress
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq3",
                "query": "查询3",
                "status": "completed",  # 已经 completed
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": {"sql": "SELECT 3", "rows": [[303]], "success": True},
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行注入
        result = inject_params_node(state)

        # 验证结果：没有新的待执行子查询
        assert result["current_batch_ids"] == []
