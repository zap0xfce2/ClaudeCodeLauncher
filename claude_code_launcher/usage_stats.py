"""Claude-Nutzungsstatistik: openusage-CLI-Abruf, Cache-Konvertierung, Formatierung."""

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from .constants import (
    MINUTES_PER_DAY,
    MINUTES_PER_HOUR,
    OPENUSAGE_BINARY,
    OPENUSAGE_FETCH_TIMEOUT,
    OPENUSAGE_PROVIDER,
)

USAGE_CACHE_REQUIRED_KEYS = {
    "session_used",
    "session_resets_at",
    "weekly_used",
    "weekly_resets_at",
    "generated_at",
    "expires_at",
}


def _fetch_claude_usage_stats() -> dict[str, Any] | None:
    """Liest Claude-Nutzungsdaten von der openusage-CLI, oder None falls nicht verfügbar/fehlerhaft."""
    try:
        result = subprocess.run(
            [OPENUSAGE_BINARY, OPENUSAGE_PROVIDER],
            capture_output=True,
            text=True,
            timeout=OPENUSAGE_FETCH_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        provider = data["providers"][OPENUSAGE_PROVIDER]
        resources = provider["resources"]
        session = resources["session"]
        weekly = resources["weekly"]
        return {
            "session": {"used": session["used"], "resetsAt": session["resetsAt"]},
            "weekly": {"used": weekly["used"], "resetsAt": weekly["resetsAt"]},
            "generated_at": data["generatedAt"],
            "expires_at": provider["expiresAt"],
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _usage_stats_to_cache(usage: dict[str, Any]) -> dict[str, Any]:
    """Flacht ein _fetch_claude_usage_stats()-Ergebnis für die config.toml-Speicherung ab."""
    return {
        "session_used": usage["session"]["used"],
        "session_resets_at": usage["session"]["resetsAt"],
        "weekly_used": usage["weekly"]["used"],
        "weekly_resets_at": usage["weekly"]["resetsAt"],
        "generated_at": usage["generated_at"],
        "expires_at": usage["expires_at"],
    }


def _usage_stats_from_cache(cache: dict[str, Any]) -> dict[str, Any]:
    """Baut aus einem flachen usage_cache-Dict wieder die Form von _fetch_claude_usage_stats()."""
    return {
        "session": {
            "used": cache["session_used"],
            "resetsAt": cache["session_resets_at"],
        },
        "weekly": {"used": cache["weekly_used"], "resetsAt": cache["weekly_resets_at"]},
        "generated_at": cache["generated_at"],
        "expires_at": cache["expires_at"],
    }


def _format_relative_reset(reset_iso: str) -> str:
    """Formatiert einen ISO-Zeitstempel als relative Restzeit (z. B. "4d23h", "1h15m", "15m")."""
    reset_dt = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
    total_minutes = max(
        int((reset_dt - datetime.now(timezone.utc)).total_seconds() // 60), 0
    )
    days, rem_minutes = divmod(total_minutes, MINUTES_PER_DAY)
    hours, minutes = divmod(rem_minutes, MINUTES_PER_HOUR)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def _format_absolute_time(timestamp_iso: str) -> str:
    """Formatiert einen ISO-Zeitstempel als lokale Uhrzeit (z. B. "14:32")."""
    timestamp_dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    return timestamp_dt.astimezone().strftime("%H:%M")
