"""chat_history_reader 单元测试"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

from src.services.langgraph_persistence.chat_history_reader import (
    get_recent_turns,
    list_recent_sessions,
)


@dataclass
class _FakeItem:
    key: str
    value: Dict[str, Any]
    updated_at: datetime


class _FakeStore:
    def __init__(self, items: List[_FakeItem]):
        self._items = items

    def search(self, *_args, **_kwargs):
        return list(self._items)


class TestChatHistoryReader:
    def test_empty_thread_id_returns_empty(self):
        assert (
            get_recent_turns(
                thread_id="",
                history_max_turns=3,
                max_history_content_length=50,
            )
            == []
        )

    def test_filters_and_orders_most_recent_turns(self):
        now = datetime.now()
        items = [
            _FakeItem(
                key="q1",
                value={"success": True, "user": {"content": "Q1"}, "assistant": {"content": "A1"}},
                updated_at=now - timedelta(seconds=30),
            ),
            _FakeItem(
                key="q2",
                value={"success": False, "user": {"content": "Q2"}, "assistant": {"content": "A2"}},
                updated_at=now - timedelta(seconds=20),
            ),
            _FakeItem(
                key="q3",
                value={"user": {"content": "Q3"}, "assistant": {"content": "A3"}},  # missing success
                updated_at=now - timedelta(seconds=10),
            ),
            _FakeItem(
                key="q4",
                value={"success": True, "user": {"content": "Q4"}, "assistant": {"content": "A4"}},
                updated_at=now - timedelta(seconds=5),
            ),
            _FakeItem(
                key="q5",
                value={"success": True, "user": {"content": "Q5"}, "assistant": {"content": "A5"}},
                updated_at=now - timedelta(seconds=1),
            ),
        ]

        store = _FakeStore(items[::-1])  # 乱序/反序，确保 reader 自己排序

        with (
            patch("src.services.langgraph_persistence.chat_history_reader.is_store_enabled", return_value=True),
            patch("src.services.langgraph_persistence.chat_history_reader.get_postgres_store", return_value=store),
            patch("src.services.langgraph_persistence.chat_history_reader.get_store_namespace", return_value="chat_history"),
        ):
            turns = get_recent_turns(
                thread_id="guest:20251222T000000Z",
                history_max_turns=2,
                max_history_content_length=50,
            )

        assert turns == [
            {"question": "Q4", "answer": "A4"},
            {"question": "Q5", "answer": "A5"},
        ]

    def test_exclude_query_id(self):
        now = datetime.now()
        items = [
            _FakeItem(
                key="q1",
                value={"success": True, "user": {"content": "Q1"}, "assistant": {"content": "A1"}},
                updated_at=now - timedelta(seconds=2),
            ),
            _FakeItem(
                key="q2",
                value={"success": True, "user": {"content": "Q2"}, "assistant": {"content": "A2"}},
                updated_at=now - timedelta(seconds=1),
            ),
        ]
        store = _FakeStore(items)

        with (
            patch("src.services.langgraph_persistence.chat_history_reader.is_store_enabled", return_value=True),
            patch("src.services.langgraph_persistence.chat_history_reader.get_postgres_store", return_value=store),
            patch("src.services.langgraph_persistence.chat_history_reader.get_store_namespace", return_value="chat_history"),
        ):
            turns = get_recent_turns(
                thread_id="guest:20251222T000000Z",
                history_max_turns=3,
                max_history_content_length=50,
                exclude_query_id="q2",
            )

        assert turns == [{"question": "Q1", "answer": "A1"}]

    def test_truncation_only_when_needed(self):
        now = datetime.now()
        items = [
            _FakeItem(
                key="q1",
                value={
                    "success": True,
                    "user": {"content": "123456"},
                    "assistant": {"content": "abcdef"},
                },
                updated_at=now,
            ),
        ]
        store = _FakeStore(items)

        with (
            patch("src.services.langgraph_persistence.chat_history_reader.is_store_enabled", return_value=True),
            patch("src.services.langgraph_persistence.chat_history_reader.get_postgres_store", return_value=store),
            patch("src.services.langgraph_persistence.chat_history_reader.get_store_namespace", return_value="chat_history"),
        ):
            turns = get_recent_turns(
                thread_id="guest:20251222T000000Z",
                history_max_turns=3,
                max_history_content_length=6,
            )

        assert turns == [{"question": "123456", "answer": "abcdef"}]

        with (
            patch("src.services.langgraph_persistence.chat_history_reader.is_store_enabled", return_value=True),
            patch("src.services.langgraph_persistence.chat_history_reader.get_postgres_store", return_value=store),
            patch("src.services.langgraph_persistence.chat_history_reader.get_store_namespace", return_value="chat_history"),
        ):
            turns = get_recent_turns(
                thread_id="guest:20251222T000000Z",
                history_max_turns=3,
                max_history_content_length=5,
            )

        assert turns == [{"question": "12...", "answer": "ab..."}]

    def test_fail_open_on_search_error(self):
        class _BadStore:
            def search(self, *_args, **_kwargs):
                raise RuntimeError("db down")

        with (
            patch("src.services.langgraph_persistence.chat_history_reader.is_store_enabled", return_value=True),
            patch("src.services.langgraph_persistence.chat_history_reader.get_postgres_store", return_value=_BadStore()),
            patch("src.services.langgraph_persistence.chat_history_reader.get_store_namespace", return_value="chat_history"),
        ):
            turns = get_recent_turns(
                thread_id="guest:20251222T000000Z",
                history_max_turns=3,
                max_history_content_length=50,
                timeout_seconds=0.1,
            )

        assert turns == []


# ============================================================
# list_recent_sessions 测试
# ============================================================


_MODULE = "src.services.langgraph_persistence.chat_history_reader"


class TestListRecentSessions:
    """list_recent_sessions() 单元测试"""

    def test_store_disabled_returns_empty(self):
        with patch(f"{_MODULE}.is_store_enabled", return_value=False):
            result = list_recent_sessions(user_id="guest")
        assert result == []

    def test_returns_sessions_sorted_newest_first(self):
        fake_rows = [
            {"prefix": "chat_history.guest:20260305T183946997Z", "first_question": "问题A"},
            {"prefix": "chat_history.guest:20260304T120000000Z", "first_question": "问题B"},
        ]

        with (
            patch(f"{_MODULE}.is_store_enabled", return_value=True),
            patch(f"{_MODULE}.get_store_namespace", return_value="chat_history"),
            patch(f"{_MODULE}._get_persistence_config", return_value={"database": {"schema": "langgraph"}}),
            patch(f"{_MODULE}._query_recent_sessions", return_value=fake_rows),
        ):
            result = list_recent_sessions(user_id="guest", max_sessions=3)

        assert len(result) == 2
        assert result[0]["thread_id"] == "guest:20260305T183946997Z"
        assert result[0]["first_question"] == "问题A"
        assert result[0]["created_at"].year == 2026
        assert result[1]["thread_id"] == "guest:20260304T120000000Z"

    def test_skips_invalid_prefix(self):
        fake_rows = [
            {"prefix": "no_dot_here", "first_question": "问题"},
        ]

        with (
            patch(f"{_MODULE}.is_store_enabled", return_value=True),
            patch(f"{_MODULE}.get_store_namespace", return_value="chat_history"),
            patch(f"{_MODULE}._get_persistence_config", return_value={"database": {"schema": "langgraph"}}),
            patch(f"{_MODULE}._query_recent_sessions", return_value=fake_rows),
        ):
            result = list_recent_sessions(user_id="guest")

        assert result == []

    def test_fail_open_on_timeout(self):
        def _slow_query(**kwargs):
            import time
            time.sleep(5)
            return []

        with (
            patch(f"{_MODULE}.is_store_enabled", return_value=True),
            patch(f"{_MODULE}.get_store_namespace", return_value="chat_history"),
            patch(f"{_MODULE}._get_persistence_config", return_value={"database": {"schema": "langgraph"}}),
            patch(f"{_MODULE}._query_recent_sessions", side_effect=_slow_query),
        ):
            result = list_recent_sessions(user_id="guest", timeout_seconds=0.1)

        assert result == []

    def test_fail_open_on_exception(self):
        with (
            patch(f"{_MODULE}.is_store_enabled", return_value=True),
            patch(f"{_MODULE}.get_store_namespace", return_value="chat_history"),
            patch(f"{_MODULE}._get_persistence_config", return_value={"database": {"schema": "langgraph"}}),
            patch(f"{_MODULE}._query_recent_sessions", side_effect=RuntimeError("db down")),
        ):
            result = list_recent_sessions(user_id="guest", timeout_seconds=0.5)

        assert result == []

    def test_empty_first_question_stripped(self):
        fake_rows = [
            {"prefix": "chat_history.guest:20260305T183946997Z", "first_question": "  "},
        ]

        with (
            patch(f"{_MODULE}.is_store_enabled", return_value=True),
            patch(f"{_MODULE}.get_store_namespace", return_value="chat_history"),
            patch(f"{_MODULE}._get_persistence_config", return_value={"database": {"schema": "langgraph"}}),
            patch(f"{_MODULE}._query_recent_sessions", return_value=fake_rows),
        ):
            result = list_recent_sessions(user_id="guest")

        assert len(result) == 1
        assert result[0]["first_question"] == ""

