"""Tests for usage_tracker module."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from inline_snapshot import snapshot
from kosong.chat_provider import TokenUsage

from kimi_cli.usage_tracker import (
    USAGE_STATS_FILE_NAME,
    PeriodUsageEntry,
    UsageStats,
    _today_key,
    load_usage_stats,
    record_usage,
    save_usage_stats,
)


@pytest.fixture
def temp_share_dir(tmp_path: Path) -> Path:
    """Create a temporary share directory for usage stats."""
    share_dir = tmp_path / ".kimi"
    share_dir.mkdir(parents=True, exist_ok=True)
    return share_dir


@pytest.fixture(autouse=True)
def patch_share_dir(temp_share_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Patch get_share_dir to use the temporary directory."""
    monkeypatch.setenv("KIMI_SHARE_DIR", str(temp_share_dir))


class TestLoadUsageStats:
    def test_missing_file_returns_empty_stats(self, temp_share_dir: Path):
        stats = load_usage_stats()
        assert stats.model_dump() == snapshot(
            {
                "version": 1,
                "by_day": {},
                "all_time": {"total": 0, "input": 0, "cached_input": 0, "output": 0},
            }
        )

    def test_corrupt_file_returns_empty_stats(self, temp_share_dir: Path):
        path = temp_share_dir / USAGE_STATS_FILE_NAME
        path.write_text("not json", encoding="utf-8")
        stats = load_usage_stats()
        assert stats.model_dump() == snapshot(
            {
                "version": 1,
                "by_day": {},
                "all_time": {"total": 0, "input": 0, "cached_input": 0, "output": 0},
            }
        )

    def test_valid_file_loads_correctly(self, temp_share_dir: Path):
        path = temp_share_dir / USAGE_STATS_FILE_NAME
        data = {
            "version": 1,
            "by_day": {"2026-05-25": {"total": 200, "input": 150, "output": 50}},
            "all_time": {"total": 300, "input": 230, "output": 70},
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        stats = load_usage_stats()
        assert stats.model_dump() == snapshot(
            {
                "version": 1,
                "by_day": {
                    "2026-05-25": {"total": 200, "input": 150, "cached_input": 0, "output": 50}
                },
                "all_time": {"total": 300, "input": 230, "cached_input": 0, "output": 70},
            }
        )


class TestSaveUsageStats:
    def test_round_trip(self, temp_share_dir: Path):
        stats = UsageStats()
        stats.by_day["2026-05-25"] = PeriodUsageEntry(total=200, input=150, output=50)
        stats.all_time = PeriodUsageEntry(total=300, input=230, output=70)
        save_usage_stats(stats)

        loaded = load_usage_stats()
        assert loaded.model_dump() == snapshot(
            {
                "version": 1,
                "by_day": {
                    "2026-05-25": {"total": 200, "input": 150, "cached_input": 0, "output": 50}
                },
                "all_time": {"total": 300, "input": 230, "cached_input": 0, "output": 70},
            }
        )


class TestRecordUsage:
    def test_new_session_creates_entry(self, temp_share_dir: Path):
        usage = TokenUsage(input_other=10, output=5)
        record_usage(usage)

        stats = load_usage_stats()
        assert stats.all_time.model_dump() == snapshot(
            {"total": 15, "input": 10, "cached_input": 0, "output": 5}
        )
        assert stats.by_day[_today_key()].model_dump() == snapshot(
            {"total": 15, "input": 10, "cached_input": 0, "output": 5}
        )

    def test_existing_session_accumulates(self, temp_share_dir: Path):
        usage1 = TokenUsage(input_other=10, output=5)
        usage2 = TokenUsage(input_other=20, output=10)
        record_usage(usage1)
        record_usage(usage2)

        stats = load_usage_stats()
        assert stats.all_time.model_dump() == snapshot(
            {"total": 45, "input": 30, "cached_input": 0, "output": 15}
        )

    def test_weekly_aggregation(self, temp_share_dir: Path):
        usage = TokenUsage(input_other=10, output=5)
        record_usage(usage)

        stats = load_usage_stats()
        day_key = _today_key()
        assert day_key in stats.by_day
        assert stats.by_day[day_key].model_dump() == snapshot(
            {"total": 15, "input": 10, "cached_input": 0, "output": 5}
        )

    def test_all_time_aggregation(self, temp_share_dir: Path):
        usage1 = TokenUsage(input_other=10, output=5)
        usage2 = TokenUsage(input_other=20, output=10)
        record_usage(usage1)
        record_usage(usage2)

        stats = load_usage_stats()
        assert stats.all_time.model_dump() == snapshot(
            {"total": 45, "input": 30, "cached_input": 0, "output": 15}
        )

    def test_multiple_sessions_in_same_week(self, temp_share_dir: Path):
        usage1 = TokenUsage(input_other=10, output=5)
        usage2 = TokenUsage(input_other=20, output=10)
        record_usage(usage1)
        record_usage(usage2)

        stats = load_usage_stats()
        day_key = _today_key()
        assert stats.by_day[day_key].model_dump() == snapshot(
            {"total": 45, "input": 30, "cached_input": 0, "output": 15}
        )

    def test_different_weeks_create_separate_entries(self, temp_share_dir: Path):
        # First record in current day
        usage1 = TokenUsage(input_other=10, output=5)
        record_usage(usage1)

        # Mock next day
        next_day_key = "2099-12-31"
        with patch("kimi_cli.usage_tracker._today_key", return_value=next_day_key):
            usage2 = TokenUsage(input_other=20, output=10)
            record_usage(usage2)

        stats = load_usage_stats()
        current_day_key = _today_key()
        assert stats.by_day[current_day_key].model_dump() == snapshot(
            {"total": 15, "input": 10, "cached_input": 0, "output": 5}
        )
        assert stats.by_day[next_day_key].model_dump() == snapshot(
            {"total": 30, "input": 20, "cached_input": 0, "output": 10}
        )


class TestCurrentWeekKey:
    def test_format(self):
        with patch("kimi_cli.usage_tracker.datetime") as mock_dt:
            mock_now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = mock_now
            mock_dt.UTC = UTC
            assert _today_key() == snapshot("2026-05-25")
