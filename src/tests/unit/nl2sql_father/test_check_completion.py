"""Check Completion 节点单元测试（Phase 2）"""

import pytest

from src.modules.nl2sql_father.nodes.check_completion import check_completion_node
from src.modules.nl2sql_father.state import create_initial_state


class TestCheckCompletionNode:
    """测试 Check Completion 节点"""

    def test_all_completed(self):
        """测试所有子查询已完成"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 2
        state["max_rounds"] = 5

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回空字典（表示结束）
        assert result == {}

    def test_all_failed(self):
        """测试所有子查询失败"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 1
        state["max_rounds"] = 5

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "failed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": "测试错误",
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回空字典（表示结束）
        assert result == {}

    def test_continue_loop(self):
        """测试继续循环"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 2
        state["max_rounds"] = 5

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "pending",  # 还有未完成的
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回递增后的轮次
        assert result["current_round"] == 3

    def test_max_rounds_protection(self):
        """测试最大轮次保护"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 5  # 已经达到最大轮次
        state["max_rounds"] = 5

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "pending",  # 还有未完成的
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回了 sub_queries（覆盖模式需要显式返回 in-place 修改）
        assert "sub_queries" in result
        # 验证 pending 的子查询被标记为 failed
        assert result["sub_queries"][1]["status"] == "failed"
        assert "超过最大轮次" in result["sub_queries"][1]["error"]

    def test_cycle_detection(self):
        """测试依赖环检测"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 2
        state["max_rounds"] = 5

        # 两个 pending 子查询互相依赖（形成环）
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "pending",
                "query": "",
                "dependencies": ["sq2"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "pending",
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回了 sub_queries（覆盖模式需要显式返回 in-place 修改）
        assert "sub_queries" in result
        # 验证 pending 的子查询被标记为 failed
        assert result["sub_queries"][0]["status"] == "failed"
        assert result["sub_queries"][1]["status"] == "failed"
        assert "依赖环" in result["sub_queries"][0]["error"]

    def test_orphaned_query_detection(self):
        """测试孤立子查询检测"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 2
        state["max_rounds"] = 5

        # sq2 依赖 sq1，但 sq1 失败了（sq2 成为孤立子查询）
        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "failed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": "SQL生成失败",
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "pending",  # 依赖 sq1，但 sq1 失败
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回了 sub_queries（覆盖模式需要显式返回 in-place 修改）
        assert "sub_queries" in result
        # 验证孤立子查询被标记为 failed
        assert result["sub_queries"][1]["status"] == "failed"
        assert "孤立子查询" in result["sub_queries"][1]["error"]

    def test_max_rounds_returns_modified_sub_queries(self):
        """测试最大轮次保护时返回的 sub_queries 包含 failed 状态"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 3
        state["max_rounds"] = 3

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": "SELECT 1",
                "execution_result": {"success": True},
                "error": None,
                "iteration_count": 1,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "in_progress",
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        result = check_completion_node(state)

        # 验证 sub_queries 被显式返回且包含 in-place 修改
        assert "sub_queries" in result
        assert len(result["sub_queries"]) == 2
        # sq1 不受影响
        assert result["sub_queries"][0]["status"] == "completed"
        # sq2 被标记为 failed
        assert result["sub_queries"][1]["status"] == "failed"
        assert "超过最大轮次" in result["sub_queries"][1]["error"]

    def test_in_progress_queries(self):
        """测试有 in_progress 的子查询时不结束"""
        state = create_initial_state(user_query="测试", query_id="test_q1")
        state["current_round"] = 2
        state["max_rounds"] = 5

        state["sub_queries"] = [
            {
                "sub_query_id": "sq1",
                "status": "completed",
                "query": "",
                "dependencies": [],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
            {
                "sub_query_id": "sq2",
                "status": "in_progress",  # 正在执行
                "query": "",
                "dependencies": ["sq1"],
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "iteration_count": 0,
                "dependencies_results": None,
            },
        ]

        # 执行检查
        result = check_completion_node(state)

        # 验证返回递增后的轮次（继续循环）
        assert result["current_round"] == 3
