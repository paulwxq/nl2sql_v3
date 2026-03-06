"""identifiers 单元测试 — parse_thread_id_datetime"""

from __future__ import annotations

from datetime import datetime, timezone

from src.services.langgraph_persistence.identifiers import parse_thread_id_datetime


class TestParseThreadIdDatetime:
    def test_valid_thread_id(self):
        dt = parse_thread_id_datetime("guest:20260305T183946997Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 5
        assert dt.hour == 18
        assert dt.minute == 39
        assert dt.second == 46
        assert dt.microsecond == 997_000
        assert dt.tzinfo == timezone.utc

    def test_different_user_id(self):
        dt = parse_thread_id_datetime("alice:20251219T163045123Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 12
        assert dt.day == 19
        assert dt.hour == 16
        assert dt.minute == 30
        assert dt.second == 45
        assert dt.microsecond == 123_000

    def test_invalid_format_returns_none(self):
        assert parse_thread_id_datetime("") is None
        assert parse_thread_id_datetime("not-a-thread-id") is None
        assert parse_thread_id_datetime("guest:badtimestamp") is None

    def test_zero_milliseconds(self):
        dt = parse_thread_id_datetime("guest:20260101T000000000Z")
        assert dt is not None
        assert dt.microsecond == 0
