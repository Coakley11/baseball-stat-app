"""Explicit Live Draft completion state — separate from in-progress drafting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

COMPLETION_RECORD_KEY = "live_draft_completion_record"

DRAFT_COMPLETE_HUB_ACTIONS = (
    "Review Draft Results",
    "Save Draft",
    "Analyze Draft",
    "Create Shared League",
    "Export Draft",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _draft_id(room: dict[str, Any]) -> str:
    return str(
        room.get("draft_room_id")
        or room.get("draft_id")
        or (room.get("config") or {}).get("draft_id")
        or ""
    ).strip()


def _draft_fingerprint(room: dict[str, Any]) -> str:
    try:
        from fantasy_league_identity import compute_draft_fingerprint

        cfg = dict(room.get("config") or {})
        return str(compute_draft_fingerprint(cfg) or "").strip()
    except ImportError:
        return str(room.get("draft_fingerprint") or "").strip()


def build_completion_record(room: dict[str, Any]) -> dict[str, Any]:
    """Explicit completion record stored on the room."""
    try:
        from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks

        complete = bool(is_draft_truly_complete(room))
        final_pick = int(total_expected_picks(room) or 0)
    except ImportError:
        board = room.get("draft_board") or []
        final_pick = len(board) if isinstance(board, list) else 0
        complete = str(room.get("status") or "").strip() == "complete" and final_pick > 0

    return {
        "draft_status": "complete" if complete else str(room.get("status") or "in_progress"),
        "completed_at": _utc_now_iso() if complete else None,
        "final_pick_number": final_pick,
        "draft_id": _draft_id(room),
        "draft_fingerprint": _draft_fingerprint(room),
        "final_board_locked": bool(complete),
    }


def get_completion_record(room: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(room, dict):
        return {}
    record = room.get(COMPLETION_RECORD_KEY)
    return dict(record) if isinstance(record, dict) else {}


def apply_live_draft_completion(room: dict[str, Any], session: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mark the room complete, stop the timer, and lock the final board."""
    try:
        from live_draft_safe_mode import is_draft_truly_complete, reconcile_live_draft_room

        if session is not None:
            reconcile_live_draft_room(session, room)
        complete = bool(is_draft_truly_complete(room))
    except ImportError:
        complete = str(room.get("status") or "").strip() == "complete"

    if complete:
        room["status"] = "complete"
        room["timer_started_at"] = None
        room["timer_deadline"] = None
        board = room.get("draft_board") or []
        room["current_pick_index"] = len(board) if isinstance(board, list) else int(room.get("current_pick_index") or 0)
        existing = get_completion_record(room)
        record = build_completion_record(room)
        record["draft_status"] = "complete"
        record["final_board_locked"] = True
        record["completed_at"] = (
            existing.get("completed_at")
            or record.get("completed_at")
            or _utc_now_iso()
        )
        room[COMPLETION_RECORD_KEY] = record
        if isinstance(session, dict):
            try:
                from live_draft_state import LIVE_DRAFT_ROOM_KEY

                session[LIVE_DRAFT_ROOM_KEY] = room
            except ImportError:
                pass
    return room


def is_live_draft_explicitly_complete(room: dict[str, Any] | None) -> bool:
    if not isinstance(room, dict):
        return False
    record = get_completion_record(room)
    if record.get("draft_status") == "complete" and record.get("final_board_locked"):
        return True
    try:
        from live_draft_safe_mode import is_draft_truly_complete

        return bool(is_draft_truly_complete(room))
    except ImportError:
        return str(room.get("status") or "").strip() == "complete"
