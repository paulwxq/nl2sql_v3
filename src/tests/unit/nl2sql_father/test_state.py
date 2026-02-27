"""State 模块单元测试"""

import pytest

from src.modules.nl2sql_father.state import create_initial_state, extract_final_result


class TestCreateInitialState:
    """测试 create_initial_state 函数"""

    def test_auto_generate_query_id(self):
        """测试 query_id 为 None 时自动生成"""
        state = create_initial_state(user_query="测试问题")

        # 验证自动生成
        assert state["query_id"] is not None
        assert state["query_id"].startswith("q_")
        assert len(state["query_id"]) == 10  # "q_" + 8位hex

        # 验证其他字段正确初始化
        assert state["user_query"] == "测试问题"
        assert state["sub_queries"] == []
        assert state["execution_results"] == []
        assert state["complexity"] is None
        assert state["validated_sql"] is None

    def test_with_custom_query_id(self):
        """测试显式传递 query_id"""
        state = create_initial_state(user_query="测试问题", query_id="custom-id")

        # 验证使用自定义 ID
        assert state["query_id"] == "custom-id"

        # 验证其他字段正确初始化
        assert state["user_query"] == "测试问题"

    def test_auto_generated_ids_are_unique(self):
        """测试多次自动生成的 ID 不重复"""
        state1 = create_initial_state(user_query="问题1")
        state2 = create_initial_state(user_query="问题2")

        # 验证 ID 不重复
        assert state1["query_id"] != state2["query_id"]

        # 验证格式一致
        assert state1["query_id"].startswith("q_")
        assert state2["query_id"].startswith("q_")

    def test_initial_state_structure(self):
        """测试初始 State 的完整结构"""
        state = create_initial_state(user_query="完整测试", query_id="test-001")

        # 验证所有必填字段存在
        required_fields = [
            "user_query",
            "query_id",
            "thread_id",
            "user_id",
            "conversation_history",
            "sub_queries",
            "current_sub_query_id",
            "complexity",
            "router_reason",
            "router_latency_ms",
            "validated_sql",
            "error",
            "error_type",
            "iteration_count",
            "execution_results",
            "summary",
            "path_taken",
            "metadata",
        ]

        for field in required_fields:
            assert field in state, f"缺少字段: {field}"

    def test_initial_values_are_none_or_empty(self):
        """测试初始值为 None 或空列表"""
        state = create_initial_state(user_query="测试", query_id="test-002")

        # 验证初始为 None 的字段
        none_fields = [
            "current_sub_query_id",
            "complexity",
            "router_reason",
            "router_latency_ms",
            "validated_sql",
            "error",
            "error_type",
            "iteration_count",
            "summary",
            "path_taken",
            "metadata",
            "conversation_history",
        ]

        for field in none_fields:
            assert state[field] is None, f"{field} 应该初始化为 None"

        # 验证初始为空列表的字段
        assert state["sub_queries"] == []
        assert state["execution_results"] == []


class TestExtractFinalResult:
    """测试 extract_final_result 函数"""

    def test_extract_basic_fields(self):
        """测试提取基本字段"""
        state = create_initial_state(user_query="测试问题", query_id="test-001")
        state["complexity"] = "simple"
        state["path_taken"] = "fast"
        state["summary"] = "测试总结"

        result = extract_final_result(state)

        # 验证基本字段
        assert result["user_query"] == "测试问题"
        assert result["query_id"] == "test-001"
        assert result["complexity"] == "simple"
        assert result["path_taken"] == "fast"
        assert result["summary"] == "测试总结"

    def test_extract_sql_shortcut(self):
        """测试提取 SQL 快捷字段（从第一个 sub_query）"""
        state = create_initial_state(user_query="测试", query_id="test-002")
        state["sub_queries"] = [
            {
                "sub_query_id": "test-002_sq1",
                "query": "子查询",
                "status": "completed",
                "validated_sql": "SELECT 1",
                "dependencies": [],
                "execution_result": None,
                "error": None,
                "iteration_count": 1,
            }
        ]

        result = extract_final_result(state)

        # 验证 SQL 快捷访问
        assert result["sql"] == "SELECT 1"

    def test_extract_sql_shortcut_when_no_sub_queries(self):
        """测试无 sub_queries 时 SQL 为 None"""
        state = create_initial_state(user_query="测试", query_id="test-003")

        result = extract_final_result(state)

        # 验证 SQL 为 None
        assert result["sql"] is None

    def test_extract_execution_results(self):
        """测试提取执行结果"""
        state = create_initial_state(user_query="测试", query_id="test-004")
        state["execution_results"] = [
            {
                "sub_query_id": "test-004_sq1",
                "sql": "SELECT 1",
                "success": True,
                "columns": ["result"],
                "rows": [[1]],
                "row_count": 1,
                "execution_time_ms": 10.5,
                "error": None,
            }
        ]

        result = extract_final_result(state)

        # 验证执行结果
        assert len(result["execution_results"]) == 1
        assert result["execution_results"][0]["success"] is True

    def test_extract_metadata(self):
        """测试提取元数据"""
        state = create_initial_state(user_query="测试", query_id="test-005")
        state["router_latency_ms"] = 123.4
        state["total_execution_time_ms"] = 1000.0

        result = extract_final_result(state)

        # 验证元数据
        assert "metadata" in result
        assert result["metadata"]["router_latency_ms"] == 123.4
        assert result["metadata"]["total_execution_time_ms"] == 1000.0

    def test_extract_error_fields(self):
        """测试提取错误字段"""
        state = create_initial_state(user_query="测试", query_id="test-006")
        state["error"] = "测试错误"
        state["error_type"] = "generation_failed"

        result = extract_final_result(state)

        # 验证错误字段
        assert result["error"] == "测试错误"
