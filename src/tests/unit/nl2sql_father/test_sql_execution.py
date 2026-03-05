"""SQL 执行节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.nl2sql_father.nodes.sql_execution import sql_execution_node


class TestSQLExecutionNode:
    """测试 SQL 执行节点"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.nl2sql_father.nodes.sql_execution.load_config") as mock:
            mock.return_value = {
                "sql_execution": {
                    "timeout_per_sql": 30,
                    "max_rows_per_query": 1000,
                    "max_concurrency": 1,
                    "log_sql": True,
                }
            }
            yield mock

    @pytest.fixture
    def base_state_with_sql(self):
        """包含已完成 SQL 的 State"""
        return {
            "query_id": "test-001",
            "user_query": "查询2024年的销售额",
            "sub_queries": [
                {
                    "sub_query_id": "test-001_sq1",
                    "query": "查询2024年的销售额",
                    "status": "completed",
                    "validated_sql": "SELECT SUM(amount) FROM sales WHERE year = 2024",
                    "execution_result": None,
                }
            ],
        }

    @pytest.fixture
    def base_state_no_sql(self):
        """无待执行 SQL 的 State"""
        return {
            "query_id": "test-002",
            "user_query": "测试问题",
            "sub_queries": [
                {
                    "sub_query_id": "test-002_sq1",
                    "query": "测试问题",
                    "status": "pending",  # 非 completed 状态
                    "validated_sql": None,
                }
            ],
        }

    def test_execute_sql_success(self, mock_config, base_state_with_sql):
        """测试 SQL 执行成功"""
        # Mock PGClient
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": ["total_amount"],
                "rows": [[150000.00]],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证返回结果
            assert "execution_results" in result
            assert len(result["execution_results"]) == 1

            exec_result = result["execution_results"][0]
            assert exec_result["sub_query_id"] == "test-001_sq1"
            assert exec_result["sql"] == "SELECT SUM(amount) FROM sales WHERE year = 2024"
            assert exec_result["success"] is True
            assert exec_result["columns"] == ["total_amount"]
            assert exec_result["rows"] == [[150000.00]]
            assert exec_result["row_count"] == 1
            assert exec_result["execution_time_ms"] > 0
            assert exec_result["error"] is None

    def test_execute_sql_failure(self, mock_config, base_state_with_sql):
        """测试 SQL 执行失败"""
        # Mock PGClient 抛出异常
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.side_effect = Exception("SQL 语法错误")
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证返回结果
            assert len(result["execution_results"]) == 1

            exec_result = result["execution_results"][0]
            assert exec_result["success"] is False
            assert exec_result["columns"] is None
            assert exec_result["rows"] is None
            assert exec_result["row_count"] == 0
            assert exec_result["error"] == "SQL 语法错误"

    def test_no_sql_to_execute(self, mock_config, base_state_no_sql):
        """测试无待执行 SQL"""
        # 执行节点
        result = sql_execution_node(base_state_no_sql)

        # 验证返回空列表
        assert "execution_results" not in result

    def test_dual_binding_success(self, mock_config, base_state_with_sql):
        """测试双向绑定：成功时更新 sub_query.execution_result"""
        # Mock PGClient
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": ["total"],
                "rows": [[100]],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证 sub_query 的 execution_result 被更新
            sub_query = base_state_with_sql["sub_queries"][0]
            assert sub_query["execution_result"] is not None
            assert sub_query["execution_result"]["success"] is True
            assert sub_query["execution_result"]["sub_query_id"] == "test-001_sq1"

    def test_dual_binding_failure(self, mock_config, base_state_with_sql):
        """测试双向绑定：失败时也更新 sub_query.execution_result"""
        # Mock PGClient 抛出异常
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.side_effect = Exception("执行失败")
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证 sub_query 的 execution_result 被更新
            sub_query = base_state_with_sql["sub_queries"][0]
            assert sub_query["execution_result"] is not None
            assert sub_query["execution_result"]["success"] is False
            assert sub_query["execution_result"]["error"] == "执行失败"

    def test_multiple_sql_execution(self, mock_config):
        """测试多 SQL 执行（Phase 2 场景）"""
        # 创建包含多个已完成 SQL 的 State
        state = {
            "query_id": "test-003",
            "sub_queries": [
                {
                    "sub_query_id": "test-003_sq1",
                    "status": "completed",
                    "validated_sql": "SELECT * FROM table1",
                },
                {
                    "sub_query_id": "test-003_sq2",
                    "status": "completed",
                    "validated_sql": "SELECT * FROM table2",
                },
            ],
        }

        # Mock PGClient
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.side_effect = [
                {"columns": ["col1"], "rows": [[1]]},
                {"columns": ["col2"], "rows": [[2]]},
            ]
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(state)

            # 验证：执行了 2 条 SQL
            assert len(result["execution_results"]) == 2
            assert result["execution_results"][0]["sub_query_id"] == "test-003_sq1"
            assert result["execution_results"][1]["sub_query_id"] == "test-003_sq2"

    def test_skip_non_completed_sql(self, mock_config):
        """测试跳过非 completed 状态的 SQL"""
        state = {
            "query_id": "test-004",
            "sub_queries": [
                {
                    "sub_query_id": "test-004_sq1",
                    "status": "pending",  # 非 completed
                    "validated_sql": "SELECT 1",
                },
                {
                    "sub_query_id": "test-004_sq2",
                    "status": "completed",
                    "validated_sql": "SELECT 2",
                },
            ],
        }

        # Mock PGClient
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": ["num"],
                "rows": [[2]],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(state)

            # 验证：只执行了 sq2
            assert len(result["execution_results"]) == 1
            assert result["execution_results"][0]["sub_query_id"] == "test-004_sq2"

    def test_skip_empty_validated_sql(self, mock_config):
        """测试跳过 validated_sql 为空的子查询"""
        state = {
            "query_id": "test-005",
            "sub_queries": [
                {
                    "sub_query_id": "test-005_sq1",
                    "status": "completed",
                    "validated_sql": None,  # 无 SQL
                },
            ],
        }

        # 执行节点
        result = sql_execution_node(state)

        # 验证：无 SQL 执行
        assert "execution_results" not in result

    def test_timeout_configuration(self, mock_config, base_state_with_sql):
        """测试超时配置传递给 PGClient"""
        # Mock PGClient
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": [],
                "rows": [],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            sql_execution_node(base_state_with_sql)

            # 验证：调用时传递了 timeout 参数（配置中为 30）
            mock_pg.execute_query.assert_called_once_with(
                "SELECT SUM(amount) FROM sales WHERE year = 2024",
                timeout=30,
            )

    def test_row_count_calculation(self, mock_config, base_state_with_sql):
        """测试 row_count 正确计算"""
        # Mock PGClient 返回多行
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": ["id", "name"],
                "rows": [[1, "A"], [2, "B"], [3, "C"]],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证 row_count
            assert result["execution_results"][0]["row_count"] == 3

    def test_empty_result_set(self, mock_config, base_state_with_sql):
        """测试空结果集"""
        # Mock PGClient 返回空结果
        with patch("src.modules.nl2sql_father.nodes.sql_execution.PGClient") as mock_pg_class:
            mock_pg = MagicMock()
            mock_pg.execute_query.return_value = {
                "columns": ["id"],
                "rows": [],
            }
            mock_pg_class.return_value = mock_pg

            # 执行节点
            result = sql_execution_node(base_state_with_sql)

            # 验证空结果
            exec_result = result["execution_results"][0]
            assert exec_result["success"] is True
            assert exec_result["row_count"] == 0
            assert exec_result["rows"] == []
