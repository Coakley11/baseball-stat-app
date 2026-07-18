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

SESSION_ENDED_NOTICE_KEY = "_live_draft_session_ended_notice"
ENDED_ROOM_CODES_KEY = "_live_draft_ended_room_codes"
ENDED_DRAFT_IDS_KEY = "_live_draft_ended_draft_ids"

# Mutually exclusive Live Draft page states — never paint setup + board together.
LIFECYCLE_SETUP = "setup"
LIFECYCLE_WAITING_SHARED_LOBBY = "waiting_shared_lobby"
LIFECYCLE_ACTIVE_DRAFT = "active_draft"
LIFECYCLE_SAVED_FOR_LATER = "saved_for_later"
LIFECYCLE_DELETING = "deleting"
LIFECYCLE_HISTORICAL_READ_ONLY = "historical_read_only"
# Backward-compatible alias
LIFECYCLE_COMPLETED_HISTORY_VIEW = LIFECYCLE_HISTORICAL_READ_ONLY

# Transient runtime pointers cleared by End Draft (setup preferences are preserved).
END_DRAFT_CLEAR_KEYS = (
    "active_shared_draft_room_code",
    "draft_room_shared_meta",
    "draft_room_participant_team",
    "draft_room_participant_id",
    "draft_room_participant_notes",
    "room_your_team",
    "live_draft_my_team",
    "live_draft_room",
    "live_draft_state",
    "_live_draft_shared_league_confirm_open",
    "_live_draft_browsing_away",
    "_live_draft_force_sync_on_return",
    "_shared_draft_poll_ts",
    "_draft_room_publish_error",
    "_draft_room_conflict_notice",
    "_draft_room_membership_notice",
    "_start_live_draft_pending",
    "live_draft_join_code_input",
    "live_draft_join_team_pick",
    "_draft_join_flash",
    "_draft_join_error",
    "_draft_room_claim_diag",
    "_draft_room_sync_diag",
    "_draft_room_join_attempt_diag",
    "_live_draft_resume_last_room",
    "_live_draft_force_resume",
    "active_draft_source",
    "_active_draft_source",
    "_shared_lobby_authority_doc",
    "_shared_lobby_sync_diag",
    "_shared_lobby_host_refresh_trace",
    "_shared_room_doc_soft_cache",
    "_live_draft_rec_cache",
    "_live_draft_joined_participants_cache",
    "_live_draft_timer_expired_pending",
    "_live_draft_page_owns_expired",
    "_live_draft_poll_diag",
    "_live_draft_poll_apply_pending",
    "_active_live_draft_mode_resolve",
    "_live_draft_queue_last_good",
    "_draft_queue_widget_epoch",
    "show_live_draft",
    "draft_started",
    "live_draft_active",
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


def record_ended_live_draft_tombstone(
    session: dict[str, Any],
    *,
    room_code: str = "",
    draft_room_id: str = "",
) -> None:
    """Durable marker so reboot/refresh cannot auto-restore an ended room."""
    try:
        from live_draft_termination import persist_durable_tombstones

        persist_durable_tombstones(
            session, draft_id=draft_room_id, room_id=draft_room_id, room_code=room_code
        )
        return
    except ImportError:
        pass
    code = str(room_code or "").strip().upper()
    draft_id = str(draft_room_id or "").strip()
    if code:
        codes = session.setdefault(ENDED_ROOM_CODES_KEY, [])
        if not isinstance(codes, list):
            codes = []
            session[ENDED_ROOM_CODES_KEY] = codes
        if code not in codes:
            codes.append(code)
    if draft_id:
        ids = session.setdefault(ENDED_DRAFT_IDS_KEY, [])
        if not isinstance(ids, list):
            ids = []
            session[ENDED_DRAFT_IDS_KEY] = ids
        if draft_id not in ids:
            ids.append(draft_id)


def is_live_draft_ended_tombstoned(
    session: dict[str, Any],
    *,
    room_code: str = "",
    draft_room_id: str = "",
) -> bool:
    try:
        from live_draft_termination import is_live_draft_permanently_retired

        return is_live_draft_permanently_retired(
            session, draft_id=draft_room_id, room_code=room_code
        )
    except ImportError:
        pass
    code = str(room_code or "").strip().upper()
    draft_id = str(draft_room_id or "").strip()
    codes = session.get(ENDED_ROOM_CODES_KEY)
    if code and isinstance(codes, list) and code in codes:
        return True
    ids = session.get(ENDED_DRAFT_IDS_KEY)
    if draft_id and isinstance(ids, list) and draft_id in ids:
        return True
    return False


def resolve_live_draft_lifecycle(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
) -> str:
    """Canonical page lifecycle — setup and active draft are mutually exclusive."""
    deleting = str(session.get("_live_draft_deleting") or "").strip().lower()
    if deleting == "in_progress":
        return LIFECYCLE_DELETING
    if deleting == "done" and not isinstance(
        room if isinstance(room, dict) else session.get("live_draft_room"), dict
    ):
        return LIFECYCLE_SETUP

    if bool(session.get("_live_draft_history_view")):
        return LIFECYCLE_HISTORICAL_READ_ONLY

    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        try:
            from live_draft_resumable_slot import get_resumable_live_draft_slot

            if get_resumable_live_draft_slot(session):
                # Parked draft — setup UI with Continue Saved Draft, not active room chrome.
                return LIFECYCLE_SETUP
        except ImportError:
            pass
        return LIFECYCLE_SETUP

    code = str(session.get("active_shared_draft_room_code") or "").strip().upper()
    if not code:
        try:
            from draft_room_context import resolve_shared_room_code

            code = str(resolve_shared_room_code(session) or "").strip().upper()
        except ImportError:
            code = ""
    draft_id = _draft_id(live)
    if is_live_draft_ended_tombstoned(session, room_code=code, draft_room_id=draft_id):
        return LIFECYCLE_SETUP
    try:
        from live_draft_termination import is_live_draft_permanently_retired

        if is_live_draft_permanently_retired(
            session, draft_id=draft_id, room_code=code, room=live
        ):
            return LIFECYCLE_SETUP
    except ImportError:
        pass

    status = str(live.get("status") or "").strip().lower()
    if status in ("ended", "closed", "deleted"):
        return LIFECYCLE_SETUP
    if status in ("complete", "completed") and bool(session.get("_live_draft_history_view")):
        return LIFECYCLE_HISTORICAL_READ_ONLY
    # Completed without explicit history view → setup (temporary board lives in Simulator).
    if status in ("complete", "completed") or is_live_draft_explicitly_complete(live):
        return LIFECYCLE_SETUP

    if status in ("waiting", "not_started"):
        try:
            from live_draft_setup_mode import resolve_active_live_draft_mode

            active = resolve_active_live_draft_mode(session, authoritative_room=live)
            if active.get("is_shared_multiplayer"):
                return LIFECYCLE_WAITING_SHARED_LOBBY
        except Exception:
            if code:
                return LIFECYCLE_WAITING_SHARED_LOBBY
    return LIFECYCLE_ACTIVE_DRAFT


def end_live_draft_session(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str = "end_live_draft_session",
) -> dict[str, Any]:
    """Compatibility wrapper → permanently_end_live_draft."""
    try:
        from live_draft_termination import permanently_end_live_draft

        return permanently_end_live_draft(session, st=st, reason=reason)
    except ImportError:
        pass
    # Minimal fallback if termination module missing.
    record_ended_live_draft_tombstone(
        session,
        room_code=str(session.get("active_shared_draft_room_code") or ""),
        draft_room_id=_draft_id(session.get("live_draft_room") or {}),
    )
    session.pop("live_draft_room", None)
    session.pop("live_draft_state", None)
    return {"ok": True, "reason": reason}


def on_end_live_draft_session() -> None:
    """Streamlit on_click: permanently end and rerun into clean setup."""
    try:
        from live_draft_termination import on_permanently_end_live_draft

        on_permanently_end_live_draft()
        return
    except ImportError:
        pass
    try:
        import streamlit as st_mod
    except Exception:
        return
    end_live_draft_session(
        st_mod.session_state,
        st=st_mod,
        reason="end_live_draft_session",
    )
