"""FastAPI 路由单元测试

使用 FastAPI TestClient 测试各接口，核心函数通过 mock 隔离。
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """创建 TestClient，跳过 lifespan 中的重型初始化"""
    with patch(
        "src.modules.nl2sql_father.graph.get_compiled_father_graph"
    ), patch(
        "src.api.core.logging.init_api_logging", return_value=MagicMock()
    ), patch(
        "src.services.langgraph_persistence.chat_history_reader.shutdown_read_executor"
    ), patch(
        "src.services.langgraph_persistence.chat_history_writer.shutdown_write_executor"
    ), patch(
        "src.services.langgraph_persistence.postgres.close_persistence"
    ):
        from src.api.main import app

        with TestClient(app) as c:
            yield c


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestQueryEndpoint:
    @patch("src.modules.nl2sql_father.graph.run_nl2sql_query")
    def test_query_success(self, mock_run, client):
        mock_run.return_value = {
            "user_query": "测试问题",
            "query_id": "q_test1234",
            "thread_id": "guest:20260307T120000000Z",
            "user_id": "guest",
            "complexity": "simple",
            "path_taken": "fast",
            "summary": "查询成功，共 108 个国家。",
            "error": None,
            "error_type": None,
            "failed_step": None,
            "sql": "SELECT COUNT(*) FROM country",
            "sub_queries": [],
            "execution_results": [
                {
                    "sub_query_id": "q_test1234_sq1",
                    "sql": "SELECT COUNT(*) FROM country",
                    "success": True,
                    "columns": ["count"],
                    "rows": [[108]],
                    "row_count": 1,
                    "execution_time_ms": 5.0,
                    "error": None,
                }
            ],
            "dependency_graph": None,
            "current_round": None,
            "max_rounds": None,
            "metadata": {
                "total_execution_time_ms": 1000.0,
                "router_latency_ms": 200.0,
                "planner_latency_ms": None,
                "parallel_execution_count": None,
                "sub_query_count": 1,
            },
        }

        resp = client.post(
            "/api/v1/query",
            json={"query": "测试问题", "user_id": "guest"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["trace_id"] == "q_test1234"
        assert body["data"]["summary"] == "查询成功，共 108 个国家。"
        assert body["data"]["sql"] == "SELECT COUNT(*) FROM country"
        assert body["data"]["error"] is None
        assert body["data"]["error_type"] is None
        assert body["data"]["failed_step"] is None

    @patch("src.modules.nl2sql_father.graph.run_nl2sql_query")
    def test_query_with_error(self, mock_run, client):
        mock_run.return_value = {
            "user_query": "错误问题",
            "query_id": "q_err12345",
            "thread_id": None,
            "user_id": "guest",
            "complexity": "simple",
            "path_taken": "fast",
            "summary": "抱歉，系统遇到了问题。",
            "error": "Schema检索失败",
            "error_type": "schema_retrieval_failed",
            "failed_step": "schema_retrieval",
            "sql": None,
            "sub_queries": [],
            "execution_results": [],
            "dependency_graph": None,
            "current_round": None,
            "max_rounds": None,
            "metadata": {},
        }

        resp = client.post(
            "/api/v1/query",
            json={"query": "错误问题"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200  # 业务级错误仍返回 200
        assert body["data"]["error"] == "Schema检索失败"
        assert body["data"]["error_type"] == "schema_retrieval_failed"
        assert body["data"]["failed_step"] == "schema_retrieval"

    @patch("src.modules.nl2sql_father.graph.run_nl2sql_query")
    def test_query_system_exception(self, mock_run, client):
        mock_run.side_effect = RuntimeError("数据库连接失败")

        resp = client.post(
            "/api/v1/query",
            json={"query": "任意问题"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 500
        assert "数据库连接失败" in body["message"]

    def test_query_too_long(self, client):
        resp = client.post(
            "/api/v1/query",
            json={"query": "a" * 1001},
        )
        assert resp.status_code == 422  # Pydantic 校验失败


class TestSessionsEndpoint:
    @patch("src.services.langgraph_persistence.chat_history_reader.list_recent_sessions")
    def test_list_sessions(self, mock_list, client):
        mock_list.return_value = [
            {
                "thread_id": "guest:20260307T100000000Z",
                "created_at": "2026-03-07T10:00:00Z",
                "first_question": "测试问题",
            }
        ]

        resp = client.get("/api/v1/sessions", params={"user_id": "guest"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert len(body["data"]) == 1
        assert body["data"][0]["thread_id"] == "guest:20260307T100000000Z"

    @patch("src.services.langgraph_persistence.chat_history_reader.list_recent_sessions")
    def test_list_sessions_empty(self, mock_list, client):
        mock_list.return_value = []

        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestTurnsEndpoint:
    @patch("src.services.langgraph_persistence.chat_history_reader.get_recent_turns")
    def test_get_turns(self, mock_turns, client):
        mock_turns.return_value = [
            {"question": "广州销售额", "answer": "广州销售额为 12345 元。"}
        ]

        resp = client.get(
            "/api/v1/sessions/turns",
            params={"thread_id": "guest:20260307T100000000Z"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert len(body["data"]) == 1
        assert body["data"][0]["question"] == "广州销售额"

    def test_get_turns_missing_thread_id(self, client):
        resp = client.get("/api/v1/sessions/turns")
        assert resp.status_code == 422  # thread_id 是必填参数

    @patch("src.services.langgraph_persistence.chat_history_reader.get_recent_turns")
    def test_get_turns_with_colon_in_thread_id(self, mock_turns, client):
        """验证 thread_id 含 : 字符时作为 Query 参数正常工作"""
        mock_turns.return_value = []

        resp = client.get(
            "/api/v1/sessions/turns",
            params={"thread_id": "guest:20260307T100000000Z", "limit": 10},
        )
        assert resp.status_code == 200
        mock_turns.assert_called_once_with(
            thread_id="guest:20260307T100000000Z",
            history_max_turns=10,
            max_history_content_length=10000,
        )
