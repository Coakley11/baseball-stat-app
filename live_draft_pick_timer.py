"""Timer freeze during pick submission — local UX before shared sync completes."""

from __future__ import annotations

import time
from typing import Any

PICK_SUBMITTING_KEY = "_live_draft_pick_submitting"
TIMER_FROZEN_KEY = "_live_draft_timer_frozen"


def freeze_timer_for_pick_submit(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Stop visible countdown immediately when user queues a pick."""
    try:
        from live_draft_timer_logic import live_draft_display_seconds
    except ImportError:
        live_draft_display_seconds = None  # type: ignore[assignment,misc]

    idx = int(room.get("current_pick_index") or 0)
    remaining = int(live_draft_display_seconds(room)) if live_draft_display_seconds else 0
    session[TIMER_FROZEN_KEY] = {
        "pick_index": idx,
        "remaining_seconds": remaining,
        "frozen_at": time.time(),
    }
    session[PICK_SUBMITTING_KEY] = True


def clear_pick_submit_state(session: dict[str, Any]) -> None:
    session.pop(PICK_SUBMITTING_KEY, None)
    session.pop(TIMER_FROZEN_KEY, None)


def is_pick_submitting(session: dict[str, Any]) -> bool:
    return bool(session.get(PICK_SUBMITTING_KEY))


def frozen_display_seconds(session: dict[str, Any], room: dict[str, Any]) -> int | None:
    """Return frozen seconds if pick submission is in flight for this pick index."""
    raw = session.get(TIMER_FROZEN_KEY)
    if not isinstance(raw, dict):
        return None
    idx = int(room.get("current_pick_index") or 0)
    if int(raw.get("pick_index") or -1) != idx:
        return None
    if not session.get(PICK_SUBMITTING_KEY):
        return None
    try:
        rem = int(raw.get("remaining_seconds") or 0)
    except (TypeError, ValueError):
        return None
    return max(0, rem)


def display_seconds_with_freeze(session: dict[str, Any], room: dict[str, Any]) -> int:
    frozen = frozen_display_seconds(session, room)
    if frozen is not None:
        return frozen
    try:
        from live_draft_timer_logic import live_draft_display_seconds

        return live_draft_display_seconds(room)
    except ImportError:
        return 0


def frozen_deadline(session: dict[str, Any], room: dict[str, Any]) -> float | None:
    """Synthetic deadline for JS countdown while frozen (ticks locally but stays fixed)."""
    frozen = frozen_display_seconds(session, room)
    if frozen is None:
        return None
    return time.time() + float(frozen)
