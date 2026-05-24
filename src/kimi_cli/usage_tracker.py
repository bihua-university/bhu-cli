from datetime import UTC, datetime, timedelta
from pathlib import Path

from kosong.chat_provider import TokenUsage
from pydantic import BaseModel, ConfigDict, Field

from kimi_cli.share import get_share_dir
from kimi_cli.utils.io import atomic_json_write
from kimi_cli.utils.logging import logger

USAGE_STATS_FILE_NAME = "usage_stats.json"
_DAYS_TO_KEEP = 60


class PeriodUsageEntry(BaseModel):
    """Token usage aggregated over a time period."""

    total: int = 0
    input: int = 0
    cached_input: int = 0
    output: int = 0


class UsageStats(BaseModel):
    """Persistent token usage statistics."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    by_day: dict[str, PeriodUsageEntry] = Field(default_factory=dict)
    all_time: PeriodUsageEntry = Field(default_factory=PeriodUsageEntry)


def _usage_stats_path() -> Path:
    return get_share_dir() / USAGE_STATS_FILE_NAME


def load_usage_stats() -> UsageStats:
    """Load usage stats from disk, returning empty stats if missing or corrupt."""
    path = _usage_stats_path()
    if not path.exists():
        return UsageStats()
    try:
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return UsageStats.model_validate(data)
    except Exception:
        logger.warning("Corrupted usage stats file, using defaults: {path}", path=path)
        return UsageStats()


def save_usage_stats(stats: UsageStats) -> None:
    """Persist usage stats to disk atomically."""
    path = _usage_stats_path()
    atomic_json_write(stats.model_dump(mode="json"), path)


def _today_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _prune_old_days(stats: UsageStats) -> None:
    """Remove day entries older than ``_DAYS_TO_KEEP``."""
    cutoff = datetime.now(UTC) - timedelta(days=_DAYS_TO_KEEP)
    cutoff_key = cutoff.strftime("%Y-%m-%d")
    stats.by_day = {k: v for k, v in stats.by_day.items() if k >= cutoff_key}


def record_usage(usage: TokenUsage) -> None:
    """Incrementally record token usage.

    Updates the current day aggregate and the all-time aggregate in
    ``~/.kimi/usage_stats.json``.
    """
    try:
        stats = load_usage_stats()

        # Update current day
        day_key = _today_key()
        day_entry = stats.by_day.get(day_key)
        if day_entry is None:
            day_entry = PeriodUsageEntry()
            stats.by_day[day_key] = day_entry
        day_entry.total += usage.total
        day_entry.input += usage.input_other + usage.input_cache_creation
        day_entry.cached_input += usage.input_cache_read
        day_entry.output += usage.output

        # Prune old days
        _prune_old_days(stats)

        # Update all-time
        stats.all_time.total += usage.total
        stats.all_time.input += usage.input_other + usage.input_cache_creation
        stats.all_time.cached_input += usage.input_cache_read
        stats.all_time.output += usage.output

        save_usage_stats(stats)
    except Exception:
        logger.exception("Failed to record usage stats")
