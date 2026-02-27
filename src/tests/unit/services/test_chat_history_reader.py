"""chat_history_reader 单元测试"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

from src.services.langgraph_persistence.chat_history_reader import get_recent_turns


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

