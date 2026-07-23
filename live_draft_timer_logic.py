"""Pure live draft timer helpers — no Streamlit imports or side effects."""

from __future__ import annotations

import math
import time
from typing import Any

# Persisted on the room after a deadline expiration has successfully produced a pick.
LAST_PROCESSED_EXPIRATION_TOKEN_KEY = "last_processed_expiration_token"


def ensure_full_pick_order(room: dict[str, Any]) -> list[dict[str, Any]]:
    """Repair truncated pick_order from config so timer/autopick cannot stall after Pick 1."""
    if not isinstance(room, dict):
        return []
    teams = [str(t).strip() for t in (room.get("teams") or []) if str(t).strip()]
    cfg = dict(room.get("config") or {})
    if not teams:
        teams = [str(t).strip() for t in (cfg.get("teams") or []) if str(t).strip()]
    rounds = int(cfg.get("picks_per_team") or cfg.get("rounds") or 0)
    expected = len(teams) * rounds if teams and rounds else 0
    existing = list(room.get("pick_order") or [])
    if expected <= 0:
        return [p for p in existing if isinstance(p, dict)]
    if len(existing) >= expected:
        room["pick_order"] = existing
        return existing
    order: list[dict[str, Any]] = []
    pick_n = 1
    for rnd in range(1, rounds + 1):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    room["pick_order"] = order
    return order


def live_draft_current_slot(room: dict[str, Any]) -> dict[str, Any] | None:
    ensure_full_pick_order(room)
    picks = room.get("pick_order", [])
    idx = int(room.get("current_pick_index", 0))
    if idx >= len(picks):
        return None
    slot = picks[idx]
    return slot if isinstance(slot, dict) else None


def live_draft_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    for key in ("draft_room_id", "room_code", "id", "draft_id"):
        val = str(room.get(key) or "").strip()
        if val:
            return val
    meta = room.get("meta")
    if isinstance(meta, dict):
        for key in ("draft_room_id", "room_code", "draft_id"):
            val = str(meta.get(key) or "").strip()
            if val:
                return val
    return ""


def build_expiration_token(room: dict[str, Any], *, now: float | None = None) -> str:
    """Stable token for a single pick-clock deadline (draft + pick + team + deadline)."""
    _ = now  # reserved for tests / clock injection
    idx = int(room.get("current_pick_index") or 0)
    slot = live_draft_current_slot(room) or {}
    team = str(slot.get("Team") or room.get("on_clock_team") or "").strip()
    deadline = live_draft_timer_deadline(room)
    deadline_s = f"{float(deadline):.3f}" if deadline is not None else "none"
    return f"{live_draft_id(room)}|{idx}|{team}|{deadline_s}"


def expiration_already_processed(room: dict[str, Any], token: str | None = None) -> bool:
    tok = str(token or build_expiration_token(room) or "").strip()
    if not tok:
        return False
    return str(room.get(LAST_PROCESSED_EXPIRATION_TOKEN_KEY) or "").strip() == tok


def mark_expiration_processed(
    room: dict[str, Any],
    token: str | None = None,
    *,
    expired_pick_index: int | None = None,
) -> str:
    """Record that this deadline was processed so duplicate reruns cannot re-pick it.

    Pass the pre-advance ``token`` (and optionally ``expired_pick_index``) because
    ``live_draft_make_pick`` advances the pick and resets the deadline first.
    """
    tok = str(token or "").strip() or build_expiration_token(room)
    if tok:
        room[LAST_PROCESSED_EXPIRATION_TOKEN_KEY] = tok
    if expired_pick_index is not None:
        room["timer_handled_index"] = int(expired_pick_index)
    return tok


def live_draft_pause_timer(room: dict[str, Any]) -> int:
    """Freeze the clock, preserving remaining seconds for a later resume."""
    remaining = live_draft_seconds_remaining(room) if room.get("status") == "in_progress" else int(
        room.get("paused_remaining_seconds") or _timer_seconds(room)
    )
    remaining = max(0, int(remaining))
    room["paused_remaining_seconds"] = remaining
    room["status"] = "paused"
    live_draft_clear_timer(room)
    return remaining


def reconstruct_timer_deadline(room: dict[str, Any]) -> bool:
    """Rebuild timer_deadline from persisted started_at / paused remaining after reload.

    Returns True when the room timer fields were mutated.
    """
    if room.get("status") == "complete":
        live_draft_clear_timer(room)
        return False
    if room.get("status") == "paused":
        # Keep countdown frozen; display uses paused_remaining_seconds.
        if room.get("paused_remaining_seconds") is None and room.get("timer_deadline") is not None:
            room["paused_remaining_seconds"] = live_draft_seconds_remaining(
                {**room, "status": "in_progress"}
            )
            live_draft_clear_timer(room)
            return True
        return False
    if room.get("status") != "in_progress":
        return False
    if room.get("timer_deadline") is not None:
        return False
    started = room.get("timer_started_at")
    if started is not None:
        room["timer_deadline"] = float(started) + _timer_seconds(room)
        return True
    paused = room.get("paused_remaining_seconds")
    if paused is not None:
        live_draft_resume_timer(room, int(paused))
        return True
    live_draft_reset_timer(room)
    return True


def resolve_live_draft_on_clock_slot(
    room: dict[str, Any] | None,
    *,
    manual_recovery_available: bool | None = None,
) -> dict[str, Any] | None:
    """Current pick slot — mirrors Live Draft Room banner recovery when index is stale."""
    if not isinstance(room, dict):
        return None
    ensure_full_pick_order(room)
    slot = live_draft_current_slot(room)
    if isinstance(slot, dict) and str(slot.get("Team") or "").strip():
        return slot
    picks = list(room.get("pick_order") or [])
    if not picks:
        return slot if isinstance(slot, dict) else None
    board = room.get("draft_board") or []
    board_count = len(board) if isinstance(board, list) else 0
    idx = int(room.get("current_pick_index") or 0)
    if board_count < len(picks) and idx < board_count:
        idx = board_count
        room["current_pick_index"] = idx
    if manual_recovery_available is False:
        return slot if isinstance(slot, dict) else None
    if 0 <= idx < len(picks) and isinstance(picks[idx], dict):
        return picks[idx]
    return slot if isinstance(slot, dict) else None


def _timer_seconds(room: dict[str, Any]) -> int:
    override = room.get("_solo_diag_timer_seconds")
    if override is not None:
        return int(override)
    return int(room.get("config", {}).get("timer_seconds", 60))


def live_draft_seconds_remaining(room: dict[str, Any]) -> int:
    """Whole seconds left on the clock (ceil) — matches client-side countdown."""
    if room.get("status") != "in_progress":
        return _timer_seconds(room)
    deadline = room.get("timer_deadline")
    if deadline is not None:
        return max(0, int(math.ceil(float(deadline) - time.time())))
    started = room.get("timer_started_at")
    if started is None:
        return _timer_seconds(room)
    remaining = float(_timer_seconds(room)) - max(0.0, time.time() - float(started))
    return max(0, int(math.ceil(remaining)))


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
    if expiration_already_processed(room):
        return False
    idx = int(room.get("current_pick_index", 0))
    if room.get("timer_handled_index") == idx:
        return False
    return live_draft_seconds_remaining(room) <= 0


def active_draft_must_not_show_zero(room: dict[str, Any]) -> bool:
    """True when an in-progress draft is displaying 0:00 and still needs expire handling."""
    if room.get("status") != "in_progress":
        return False
    if live_draft_seconds_remaining(room) > 0:
        return False
    return not expiration_already_processed(room)
