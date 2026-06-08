"""
UTC-normalized activity timestamps and user-local display formatting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
# Naive ISO strings from legacy writers are treated as UTC.
_LEGACY_NAIVE_IS_UTC = True


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_timestamp_iso(ts: str | None) -> str:
    """Normalize any supported timestamp string to UTC ISO with ``Z``."""
    dt = parse_activity_timestamp(ts)
    if dt is None:
        return ""
    return utc_iso_from_datetime(dt)


def utc_iso_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_activity_timestamp(ts: str | None) -> datetime | None:
    """
    Parse activity event timestamps to timezone-aware UTC.

    Supports ``Z``, numeric offsets, and legacy naive ISO strings.
    """
    raw = str(ts or "").strip()
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text[:26])
    except ValueError:
        return None
    if dt.tzinfo is None:
        if _LEGACY_NAIVE_IS_UTC:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone().replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def get_display_timezone() -> timezone:
    """Local timezone for feed display (Streamlit host / browser locale)."""
    try:
        return datetime.now().astimezone().tzinfo or timezone.utc
    except Exception:
        return timezone.utc


def to_display_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_display_timezone())


def format_relative_time(dt: datetime, *, now: datetime | None = None) -> str:
    """
    Human-readable relative time in the user's local timezone.

    Just now · N min ago · N hour(s) ago · Yesterday · absolute date
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    local_dt = to_display_local(dt)
    local_now = to_display_local(now)
    delta = local_now - local_dt
    seconds = max(0, int(delta.total_seconds()))

    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        mins = max(1, seconds // 60)
        return f"{mins} min ago" if mins == 1 else f"{mins} min ago"
    if seconds < 86400 and local_dt.date() == local_now.date():
        hours = max(1, seconds // 3600)
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    if local_dt.date() == local_now.date() - timedelta(days=1):
        return "Yesterday"
    return local_dt.strftime("%b %d · %I:%M %p").replace(" 0", " ")


def format_activity_display_time(ts: str | None, *, now: datetime | None = None) -> str:
    """Format a stored timestamp for the activity feed."""
    dt = parse_activity_timestamp(ts)
    if dt is None:
        return str(ts or "")[:16]
    return format_relative_time(dt, now=now)


def sort_key_for_event(event: dict[str, Any]) -> datetime:
    """UTC sort key; invalid/missing timestamps sort oldest."""
    dt = parse_activity_timestamp(str(event.get("timestamp") or ""))
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt
