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


SESSION_ENDED_NOTICE_KEY = "_live_draft_session_ended_notice"


def end_live_draft_session(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str = "end_live_draft_session",
) -> dict[str, Any]:
    """Close the active Live Draft runtime session without deleting archives/shared leagues.

    Clears the in-room/session hydrate path so Live Draft Room returns to Create/Join.
    Saved drafts, Shared Leagues, and historical results are left untouched.
    Does not auto-start another draft — landing page lets the user choose next.
    """
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        room = {}
    cfg = dict(room.get("config") or {})
    draft_label = str(
        cfg.get("league_name") or room.get("league_name") or cfg.get("draft_name") or "Live Draft"
    ).strip()
    shared_code = str(session.get("active_shared_draft_room_code") or "").strip()

    if shared_code:
        try:
            from draft_room_context import leave_shared_draft_room

            leave_shared_draft_room(session)
        except Exception:
            shared_code = ""
    if not shared_code:
        try:
            from draft_room_state import delete_live_draft_only

            delete_live_draft_only(session)
        except Exception:
            try:
                from live_draft_state import clear_live_draft_state

                clear_live_draft_state(session, reason=reason)
            except Exception:
                session.pop("live_draft_room", None)
                session.pop("live_draft_state", None)

    for key in (
        "active_shared_draft_room_code",
        "draft_room_shared_meta",
        "draft_room_participant_team",
        "draft_room_participant_id",
        "draft_room_participant_notes",
        "room_your_team",
        "live_draft_my_team",
        "_live_draft_shared_league_confirm_open",
        "_live_draft_browsing_away",
        "_live_draft_force_sync_on_return",
        "_shared_draft_poll_ts",
        "_draft_room_publish_error",
        "_draft_room_conflict_notice",
        "_draft_room_membership_notice",
        "_start_live_draft_pending",
    ):
        session.pop(key, None)

    session[SESSION_ENDED_NOTICE_KEY] = {
        "message": (
            f"Ended the Live Draft session for **{draft_label}**. "
            "Saved drafts and Shared Leagues were preserved. "
            "Fantasy pages restored to the Active Draft when Live Draft Override is off."
        ),
        "ended_at": _utc_now_iso(),
    }

    try:
        from live_draft_state import commit_live_draft_room

        if st is not None:
            commit_live_draft_room(st, session, None, reason=reason)
        else:
            from live_draft_state import clear_live_draft_state

            clear_live_draft_state(session, reason=reason)
    except Exception:
        session.pop("live_draft_room", None)
        session.pop("live_draft_state", None)

    # Live Draft Override OFF → temporary board is gone; restore Active Draft my-team.
    try:
        from fantasy_context_source import (
            USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
            invalidate_fantasy_workflow_descriptor_cache,
        )

        override_on = bool(session.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY))
        invalidate_fantasy_workflow_descriptor_cache(session)
        if not override_on:
            from global_fantasy_settings_state import sync_active_fantasy_team_to_canonical

            restored = sync_active_fantasy_team_to_canonical(session)
            session["_live_draft_ended_restored_active_team"] = restored
    except Exception:
        pass

    return {"ok": True, "reason": reason, "draft_label": draft_label}


def on_end_live_draft_session() -> None:
    """Streamlit on_click: end session and return to Live Draft landing (no auto-start)."""
    try:
        import streamlit as st_mod
    except Exception:
        return
    end_live_draft_session(
        st_mod.session_state,
        st=st_mod,
        reason="end_live_draft_session",
    )
