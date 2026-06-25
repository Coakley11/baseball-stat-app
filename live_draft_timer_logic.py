"""Pure live draft timer helpers — no Streamlit imports or side effects."""

from __future__ import annotations

import time
from typing import Any


def live_draft_current_slot(room: dict[str, Any]) -> dict[str, Any] | None:
    picks = room.get("pick_order", [])
    idx = int(room.get("current_pick_index", 0))
    if idx >= len(picks):
        return None
    slot = picks[idx]
    return slot if isinstance(slot, dict) else None


def _timer_seconds(room: dict[str, Any]) -> int:
    return int(room.get("config", {}).get("timer_seconds", 60))


def live_draft_seconds_remaining(room: dict[str, Any]) -> int:
    if room.get("status") != "in_progress":
        return _timer_seconds(room)
    deadline = room.get("timer_deadline")
    if deadline is not None:
        return max(0, int(float(deadline) - time.time()))
    started = room.get("timer_started_at")
    if started is None:
        return _timer_seconds(room)
    elapsed = max(0.0, time.time() - float(started))
    return max(0, _timer_seconds(room) - int(elapsed))


def live_draft_reset_timer(room: dict[str, Any]) -> None:
    """Set canonical shared countdown deadline (unix epoch seconds)."""
    timer_seconds = _timer_seconds(room)
    now = time.time()
    room["timer_started_at"] = now
    room["timer_deadline"] = now + timer_seconds
    room["timer_handled_index"] = -1


def live_draft_resume_timer(room: dict[str, Any], remaining_seconds: int) -> None:
    """Resume from pause with a specific seconds-left value."""
    remaining = max(0, int(remaining_seconds))
    now = time.time()
    timer_seconds = _timer_seconds(room)
    room["timer_deadline"] = now + remaining
    room["timer_started_at"] = now - max(0, timer_seconds - remaining)
    room["timer_handled_index"] = -1
    room["paused_remaining_seconds"] = None


def live_draft_display_seconds(room: dict[str, Any]) -> int:
    """Seconds to show in the UI (respects paused state)."""
    if room.get("status") == "in_progress":
        return live_draft_seconds_remaining(room)
    cfg = dict(room.get("config") or {})
    return int(room.get("paused_remaining_seconds") or cfg.get("timer_seconds", 60))


def live_draft_timer_deadline(room: dict[str, Any]) -> float | None:
    if room.get("status") != "in_progress":
        return None
    deadline = room.get("timer_deadline")
    if deadline is not None:
        return float(deadline)
    started = room.get("timer_started_at")
    if started is None:
        return None
    return float(started) + _timer_seconds(room)


def live_draft_clear_timer(room: dict[str, Any]) -> None:
    room["timer_started_at"] = None
    room["timer_deadline"] = None


def ensure_live_draft_timer_for_pick(room: dict[str, Any]) -> bool:
    """Reset timer when a new pick is on the clock but timer state is missing or stale."""
    if room.get("status") != "in_progress":
        return False
    idx = int(room.get("current_pick_index", 0))
    handled = room.get("timer_handled_index")
    deadline = room.get("timer_deadline")
    started = room.get("timer_started_at")
    if deadline is None and started is None:
        live_draft_reset_timer(room)
        return True
    if handled is not None and int(handled) >= 0 and int(handled) < idx:
        live_draft_reset_timer(room)
        return True
    if live_draft_seconds_remaining(room) <= 0 and handled != idx:
        return False
    return False


def live_draft_timer_expired_for_pick(room: dict[str, Any]) -> bool:
    if room.get("status") != "in_progress":
        return False
    idx = int(room.get("current_pick_index", 0))
    if room.get("timer_handled_index") == idx:
        return False
    return live_draft_seconds_remaining(room) <= 0
