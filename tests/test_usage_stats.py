import time
from datetime import datetime, timedelta, timezone

from claude_code_launcher import usage_stats


# --- _format_relative_reset / _format_absolute_time ---


def test_format_relative_reset_days_and_hours():
    reset_iso = (datetime.now(timezone.utc) + timedelta(days=4, hours=23, minutes=30)).isoformat()
    assert usage_stats._format_relative_reset(reset_iso) == "4d23h"


def test_format_relative_reset_already_expired_returns_zero_minutes():
    reset_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert usage_stats._format_relative_reset(reset_iso) == "0m"


def test_format_absolute_time_formats_as_local_hh_mm(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    assert usage_stats._format_absolute_time("2024-01-01T12:34:00Z") == "12:34"


# --- usage_cache Konvertierung ---


def test_usage_stats_to_cache_and_back_roundtrip():
    usage = {
        "session": {"used": 0.27, "resetsAt": "2026-08-12T00:00:00Z"},
        "weekly": {"used": 0.11, "resetsAt": "2026-08-15T00:00:00Z"},
        "generated_at": "2026-08-11T10:00:00Z",
        "expires_at": "2026-08-11T10:05:00Z",
    }
    assert usage_stats._usage_stats_from_cache(usage_stats._usage_stats_to_cache(usage)) == usage
