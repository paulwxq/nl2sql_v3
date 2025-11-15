"""Simple Planner 节点单元测试"""

import pytest

from src.modules.nl2sql_father.nodes.simple_planner import simple_planner_node


class TestSimplePlannerNode:
    """测试 Simple Planner 节点"""

    @pytest.fixture
    def base_state(self):
        """基础 State"""
        return {
            "user_query": "查询2024年的销售额",
            "query_id": "test-001",
        }

    def test_create_sub_query(self, base_state):
        """测试创建子查询"""
        result = simple_planner_node(base_state)

        # 验证返回结果
        assert "sub_queries" in result
        assert "current_sub_query_id" in result

        # 验证子查询列表
        sub_queries = result["sub_queries"]
        assert len(sub_queries) == 1

        # 验证子查询结构
        sub_query = sub_queries[0]
        assert sub_query["sub_query_id"] == "test-001_sq1"
        assert sub_query["query"] == "查询2024年的销售额"
        assert sub_query["status"] == "pending"
        assert sub_query["dependencies"] == []
        assert sub_query["validated_sql"] is None
        assert sub_query["execution_result"] is None
        assert sub_query["error"] is None
        assert sub_query["iteration_count"] == 0

    def test_current_sub_query_id(self, base_state):
        """测试 current_sub_query_id 设置正确"""
        result = simple_planner_node(base_state)

        # 验证 current_sub_query_id 与子查询 ID 一致
        assert result["current_sub_query_id"] == "test-001_sq1"
        assert result["current_sub_query_id"] == result["sub_queries"][0]["sub_query_id"]

    def test_query_id_prefix(self, base_state):
        """测试子查询 ID 使用正确的前缀"""
        # 修改 query_id
        base_state["query_id"] = "custom-query-id"

        result = simple_planner_node(base_state)

        # 验证子查询 ID 包含正确的前缀
        assert result["sub_queries"][0]["sub_query_id"] == "custom-query-id_sq1"

    def test_query_content_preserved(self, base_state):
        """测试查询内容完整保留"""
        # 使用包含特殊字符的查询
        base_state["user_query"] = "查询销售额>1000的店铺，并按销售额降序排列"

        result = simple_planner_node(base_state)

        # 验证查询内容完全一致（Phase 1 直接复制）
        assert result["sub_queries"][0]["query"] == base_state["user_query"]

    def test_no_llm_call(self, base_state):
        """测试不调用 LLM（纯函数）"""
        import time

        # 测量执行时间
        start = time.time()
        result = simple_planner_node(base_state)
        elapsed_ms = (time.time() - start) * 1000

        # 验证：应该在 1ms 内完成（纯函数，无 LLM 调用）
        assert elapsed_ms < 1.0

        # 验证结果正确
        assert len(result["sub_queries"]) == 1

    def test_empty_dependencies(self, base_state):
        """测试 Phase 1 无依赖"""
        result = simple_planner_node(base_state)

        # 验证 dependencies 为空列表（Phase 1 不支持依赖）
        assert result["sub_queries"][0]["dependencies"] == []
        assert isinstance(result["sub_queries"][0]["dependencies"], list)

    def test_initial_status_pending(self, base_state):
        """测试初始状态为 pending"""
        result = simple_planner_node(base_state)

        # 验证状态
        assert result["sub_queries"][0]["status"] == "pending"

    def test_initial_fields_null(self, base_state):
        """测试初始字段为 None"""
        result = simple_planner_node(base_state)

        sub_query = result["sub_queries"][0]

        # 验证未执行前的字段为 None
        assert sub_query["validated_sql"] is None
        assert sub_query["execution_result"] is None
        assert sub_query["error"] is None

    def test_iteration_count_zero(self, base_state):
        """测试初始 iteration_count 为 0"""
        result = simple_planner_node(base_state)

        # 验证迭代次数初始为 0
        assert result["sub_queries"][0]["iteration_count"] == 0

    def test_deterministic_output(self, base_state):
        """测试多次调用输出一致（纯函数特性）"""
        # 多次调用
        result1 = simple_planner_node(base_state)
        result2 = simple_planner_node(base_state)

        # 验证输出一致
        assert result1["current_sub_query_id"] == result2["current_sub_query_id"]
        assert result1["sub_queries"][0]["query"] == result2["sub_queries"][0]["query"]
        assert result1["sub_queries"][0]["status"] == result2["sub_queries"][0]["status"]
