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


def live_draft_seconds_remaining(room: dict[str, Any]) -> int:
    if room.get("status") != "in_progress":
        return int(room.get("config", {}).get("timer_seconds", 60))
    started = room.get("timer_started_at")
    if started is None:
        return int(room.get("config", {}).get("timer_seconds", 60))
    elapsed = max(0.0, time.time() - float(started))
    timer_seconds = int(room.get("config", {}).get("timer_seconds", 60))
    return max(0, timer_seconds - int(elapsed))


def live_draft_reset_timer(room: dict[str, Any]) -> None:
    room["timer_started_at"] = time.time()
    room["timer_handled_index"] = -1


def live_draft_display_seconds(room: dict[str, Any]) -> int:
    """Seconds to show in the UI (respects paused state)."""
    if room.get("status") == "in_progress":
        return live_draft_seconds_remaining(room)
    cfg = dict(room.get("config") or {})
    return int(room.get("paused_remaining_seconds") or cfg.get("timer_seconds", 60))


def live_draft_timer_deadline(room: dict[str, Any]) -> float | None:
    if room.get("status") != "in_progress":
        return None
    started = room.get("timer_started_at")
    if started is None:
        return None
    timer_seconds = int(room.get("config", {}).get("timer_seconds", 60))
    return float(started) + timer_seconds
