"""Planner 节点单元测试（Phase 2）"""

import pytest
from unittest.mock import Mock, patch

from src.modules.nl2sql_father.nodes.planner import (
    planner_node,
    _build_dependency_graph,
    _has_cycle,
)
from src.modules.nl2sql_father.state import create_initial_state


class TestBuildDependencyGraph:
    """测试依赖图构建"""

    def test_build_simple_graph(self):
        """测试简单的两节点依赖图"""
        sub_queries = [
            {"sub_query_id": "sq1", "dependencies": []},
            {"sub_query_id": "sq2", "dependencies": ["sq1"]},
        ]

        graph = _build_dependency_graph(sub_queries)

        assert graph["nodes"] == ["sq1", "sq2"]
        assert graph["edges"] == [{"from": "sq1", "to": "sq2"}]

    def test_build_complex_graph(self):
        """测试复杂的多依赖图"""
        sub_queries = [
            {"sub_query_id": "sq1", "dependencies": []},
            {"sub_query_id": "sq2", "dependencies": ["sq1"]},
            {"sub_query_id": "sq3", "dependencies": ["sq1", "sq2"]},
        ]

        graph = _build_dependency_graph(sub_queries)

        assert graph["nodes"] == ["sq1", "sq2", "sq3"]
        assert len(graph["edges"]) == 3
        assert {"from": "sq1", "to": "sq2"} in graph["edges"]
        assert {"from": "sq1", "to": "sq3"} in graph["edges"]
        assert {"from": "sq2", "to": "sq3"} in graph["edges"]

    def test_build_no_dependencies(self):
        """测试无依赖的并行查询"""
        sub_queries = [
            {"sub_query_id": "sq1", "dependencies": []},
            {"sub_query_id": "sq2", "dependencies": []},
        ]

        graph = _build_dependency_graph(sub_queries)

        assert graph["nodes"] == ["sq1", "sq2"]
        assert graph["edges"] == []


class TestHasCycle:
    """测试环检测"""

    def test_no_cycle_simple(self):
        """测试无环的简单图"""
        graph = {
            "nodes": ["sq1", "sq2"],
            "edges": [{"from": "sq1", "to": "sq2"}],
        }

        assert _has_cycle(graph) is False

    def test_no_cycle_complex(self):
        """测试无环的复杂图"""
        graph = {
            "nodes": ["sq1", "sq2", "sq3"],
            "edges": [
                {"from": "sq1", "to": "sq2"},
                {"from": "sq1", "to": "sq3"},
                {"from": "sq2", "to": "sq3"},
            ],
        }

        assert _has_cycle(graph) is False

    def test_has_cycle_simple(self):
        """测试简单的环"""
        graph = {
            "nodes": ["sq1", "sq2"],
            "edges": [
                {"from": "sq1", "to": "sq2"},
                {"from": "sq2", "to": "sq1"},
            ],
        }

        assert _has_cycle(graph) is True

    def test_has_cycle_complex(self):
        """测试复杂的环"""
        graph = {
            "nodes": ["sq1", "sq2", "sq3"],
            "edges": [
                {"from": "sq1", "to": "sq2"},
                {"from": "sq2", "to": "sq3"},
                {"from": "sq3", "to": "sq1"},
            ],
        }

        assert _has_cycle(graph) is True

    def test_no_cycle_parallel(self):
        """测试无依赖的并行查询（无环）"""
        graph = {
            "nodes": ["sq1", "sq2", "sq3"],
            "edges": [],
        }

        assert _has_cycle(graph) is False


class TestPlannerNode:
    """测试 Planner 节点"""

    @patch("src.modules.nl2sql_father.nodes.planner.ChatTongyi")
    def test_planner_success(self, mock_chat):
        """测试 Planner 成功拆分问题"""
        # Mock LLM 响应
        mock_response = Mock()
        mock_response.content = """```json
{
  "sub_queries": [
    {
      "sub_query_id": "sq1",
      "query": "找出销售额最高的服务区ID",
      "dependencies": []
    },
    {
      "sub_query_id": "sq2",
      "query": "查询服务区 {{sq1.result}} 的地址和公司",
      "dependencies": ["sq1"]
    }
  ]
}
```"""
        mock_chat.return_value.invoke.return_value = mock_response

        # 创建初始 State
        state = create_initial_state(user_query="哪个服务区销售最高？它的地址是？", query_id="test_q1")

        # 执行 Planner
        result = planner_node(state)

        # 验证结果
        assert "sub_queries" in result
        assert len(result["sub_queries"]) == 2
        assert result["current_round"] == 1
        assert result["max_rounds"] == 5
        assert result["path_taken"] == "complex"
        assert "dependency_graph" in result
        assert result["dependency_graph"]["nodes"] == ["test_q1_sq1", "test_q1_sq2"]

    @patch("src.modules.nl2sql_father.nodes.planner.ChatTongyi")
    def test_planner_json_parse_failure(self, mock_chat):
        """测试 Planner JSON 解析失败"""
        # Mock LLM 返回无效 JSON
        mock_response = Mock()
        mock_response.content = "这不是有效的JSON"
        mock_chat.return_value.invoke.return_value = mock_response

        state = create_initial_state(user_query="测试问题", query_id="test_q2")

        # 执行 Planner
        result = planner_node(state)

        # 验证返回错误
        assert "error" in result
        assert result["error_type"] == "planning_failed"
        assert "JSON" in result["error"]

    @patch("src.modules.nl2sql_father.nodes.planner.ChatTongyi")
    def test_planner_cycle_detection(self, mock_chat):
        """测试 Planner 检测到环"""
        # Mock LLM 返回有环的依赖关系
        mock_response = Mock()
        mock_response.content = """```json
{
  "sub_queries": [
    {
      "sub_query_id": "sq1",
      "query": "查询1",
      "dependencies": ["sq2"]
    },
    {
      "sub_query_id": "sq2",
      "query": "查询2",
      "dependencies": ["sq1"]
    }
  ]
}
```"""
        mock_chat.return_value.invoke.return_value = mock_response

        state = create_initial_state(user_query="测试问题", query_id="test_q3")

        # 执行 Planner
        result = planner_node(state)

        # 验证返回错误
        assert "error" in result
        assert result["error_type"] == "planning_failed"
        assert "循环依赖" in result["error"]

    @patch("src.modules.nl2sql_father.nodes.planner.ChatTongyi")
    def test_planner_too_few_sub_queries(self, mock_chat):
        """测试子查询数量不足"""
        # Mock LLM 返回只有1个子查询
        mock_response = Mock()
        mock_response.content = """```json
{
  "sub_queries": [
    {
      "sub_query_id": "sq1",
      "query": "查询1",
      "dependencies": []
    }
  ]
}
```"""
        mock_chat.return_value.invoke.return_value = mock_response

        state = create_initial_state(user_query="测试问题", query_id="test_q4")

        # 执行 Planner
        result = planner_node(state)

        # 验证返回错误
        assert "error" in result
        assert result["error_type"] == "planning_failed"
        assert "至少需要" in result["error"]
