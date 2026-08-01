"""Stage-1 room latch diagnostics (observability only; no functional draft behavior)."""

from __future__ import annotations

import time
from typing import Any

EVENT_WRITE = "production_stage1_room_state_write"
EVENT_CLEAR = "production_stage1_room_state_clear"
EVENT_RESTORE = "production_stage1_room_state_restore"
EVENT_READ = "production_stage1_room_state_read"
EVENT_SURFACE = "production_stage1_surface_decision"
EVENT_RERUN = "production_stage1_rerun_transition"
EVENT_HANDLER_SESSION_PROOF = "production_stage1_handler_exit_session_state_proof"

LATCH_EXPORT_PINNED = frozenset(
    {
        EVENT_WRITE,
        EVENT_CLEAR,
        EVENT_RESTORE,
        EVENT_READ,
        EVENT_SURFACE,
        EVENT_RERUN,
        EVENT_HANDLER_SESSION_PROOF,
    }
)

CANONICAL_ROOM_KEYS = (
    "live_draft_room",
    "live_draft_state",
    "_start_live_draft_pending",
    "_start_live_draft_mode",
    "active_shared_draft_room_code",
    "_live_draft_restore_blocked_reason",
    "_live_draft_setup_snapshot_after_delete",
    "_live_draft_start_in_flight",
    "_solo_stage1_run_id",
)


def _enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except Exception:
        return False


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _script_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except Exception:
        return 0


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id

        return str(ensure_stage1_run_id(session) or "")[:32]
    except Exception:
        return ""


def _safe_room_id(room: Any) -> str:
    if not isinstance(room, dict):
        return ""
    return str(room.get("draft_room_id") or room.get("draft_id") or "").strip().upper()[:32]


def _room_status(room: Any) -> str:
    if not isinstance(room, dict):
        return ""
    return str(room.get("status") or "").strip().lower()[:32]


def _pick_index(room: Any, session: dict[str, Any]) -> Any:
    if isinstance(room, dict) and room.get("current_pick_index") is not None:
        return room.get("current_pick_index")
    blob = session.get("live_draft_state")
    if isinstance(blob, dict):
        return blob.get("current_pick_index")
    return None


def _deadline_token(session: dict[str, Any], room: Any) -> str:
    tok = str(session.get("_solo_persistent_wake_last_token") or "")[:120]
    if tok:
        return tok
    if isinstance(room, dict):
        dl = room.get("pick_deadline_ts") or room.get("deadline_ts")
        if dl is not None:
            return str(dl)[:120]
    return ""


def session_state_room_snapshot(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Authoritative st.session_state view (not handler locals)."""
    room = session.get("live_draft_room")
    blob = session.get("live_draft_state")
    keys_present = {k: k in session for k in CANONICAL_ROOM_KEYS}
    safe_values: dict[str, Any] = {}
    for k in CANONICAL_ROOM_KEYS:
        if k not in session:
            continue
        v = session.get(k)
        if k == "live_draft_room" and isinstance(v, dict):
            safe_values[k] = {
                "room_id": _safe_room_id(v),
                "status": _room_status(v),
                "pick_index": v.get("current_pick_index"),
                "object_id": id(v),
            }
        elif k == "live_draft_state" and isinstance(v, dict):
            safe_values[k] = {
                "room_id": str(v.get("draft_room_id") or "").upper()[:32],
                "status": str(v.get("status") or "")[:32],
                "pick_index": v.get("current_pick_index"),
                "object_id": id(v),
            }
        elif isinstance(v, (str, int, float, bool)) or v is None:
            safe_values[k] = v
        else:
            safe_values[k] = type(v).__name__
    return {
        "streamlit_session_id": _streamlit_session_id(),
        "script_run_seq": _script_run_seq(session),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "session_room_id": _safe_room_id(room),
        "session_draft_status": _room_status(room),
        "session_pick_index": _pick_index(room, session),
        "session_deadline_token": _deadline_token(session, room),
        "canonical_blob_room_id": str((blob or {}).get("draft_room_id") or "").upper()[:32]
        if isinstance(blob, dict)
        else "",
        "pending_start": bool(session.get("_start_live_draft_pending")),
        "start_mode": str(session.get("_start_live_draft_mode") or "")[:32],
        "restore_blocked_reason": str(session.get("_live_draft_restore_blocked_reason") or "")[:120],
        "keys_present": keys_present,
        "safe_key_values": safe_values,
        "live_draft_room_object_id": id(room) if isinstance(room, dict) else None,
    }


def _note(st: Any | None, session: dict[str, Any], event: str, **extra: Any) -> dict[str, Any]:
    if not _enabled(st, session):
        return {}
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
        return note_stage1_event(
            session,
            event,
            st=st,
            room=room,
            widget_key="room_latch",
            extra={
                "streamlit_session_id": _streamlit_session_id(),
                "script_run_seq": _script_run_seq(session),
                "diagnostic_run_id": _diagnostic_run_id(session),
                **extra,
            },
        )
    except Exception:
        return {}


def emit_room_state_read(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    read_label: str,
    source: str = "",
) -> dict[str, Any]:
    snap = session_state_room_snapshot(session, st=st)
    return _note(
        st,
        session,
        EVENT_READ,
        read_label=str(read_label or "")[:80],
        read_source=str(source or "")[:120],
        **snap,
    )


def emit_room_state_write(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    operation: str,
    reason: str,
    prev_room: Any = None,
    new_room: Any = None,
    module: str = "",
    function: str = "",
    lineno: int = 0,
) -> dict[str, Any]:
    return _note(
        st,
        session,
        EVENT_WRITE,
        operation=str(operation or "set")[:24],
        reason=str(reason or "")[:120],
        prev_room_id=_safe_room_id(prev_room),
        prev_status=_room_status(prev_room),
        new_room_id=_safe_room_id(new_room),
        new_status=_room_status(new_room),
        module=str(module or "")[:80],
        function=str(function or "")[:80],
        line=int(lineno or 0),
        post_write_snapshot=session_state_room_snapshot(session, st=st),
    )


def emit_room_state_clear(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str,
    prev_room: Any = None,
    module: str = "",
    function: str = "",
    lineno: int = 0,
) -> dict[str, Any]:
    return _note(
        st,
        session,
        EVENT_CLEAR,
        reason=str(reason or "")[:120],
        prev_room_id=_safe_room_id(prev_room),
        prev_status=_room_status(prev_room),
        module=str(module or "")[:80],
        function=str(function or "")[:80],
        line=int(lineno or 0),
        post_clear_snapshot=session_state_room_snapshot(session, st=st),
    )


def emit_room_state_restore(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    reason: str,
    restored_room: Any = None,
    source: str = "",
) -> dict[str, Any]:
    return _note(
        st,
        session,
        EVENT_RESTORE,
        reason=str(reason or "")[:120],
        restore_source=str(source or "")[:120],
        restored_room_id=_safe_room_id(restored_room),
        restored_status=_room_status(restored_room),
        post_restore_snapshot=session_state_room_snapshot(session, st=st),
    )


def emit_surface_decision(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    surface: str,
    in_progress: bool,
    setup_visible: bool,
    source: str = "",
) -> dict[str, Any]:
    snap = session_state_room_snapshot(session, st=st)
    return _note(
        st,
        session,
        EVENT_SURFACE,
        surface=str(surface or "")[:64],
        setup_surface_active=bool(setup_visible),
        draft_in_progress=bool(in_progress),
        decision_source=str(source or "")[:120],
        **snap,
    )


def emit_rerun_transition(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    requested: bool,
    rerun_type: str,
    source: str = "",
    script_run_seq_before: int | None = None,
) -> dict[str, Any]:
    return _note(
        st,
        session,
        EVENT_RERUN,
        rerun_requested=bool(requested),
        rerun_type=str(rerun_type or "")[:48],
        rerun_source=str(source or "")[:120],
        script_run_seq_before=script_run_seq_before if script_run_seq_before is not None else _script_run_seq(session),
        streamlit_session_id_before=_streamlit_session_id(),
        pre_rerun_snapshot=session_state_room_snapshot(session, st=st),
    )


def emit_handler_exit_session_state_proof(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    local_created_room_id: str = "",
    local_draft_status: str = "",
    local_pick_index: Any = None,
    handler_success: bool = False,
) -> dict[str, Any]:
    snap = session_state_room_snapshot(session, st=st)
    sess_rid = str(snap.get("session_room_id") or "")
    local_rid = str(local_created_room_id or "").strip().upper()[:32]
    return _note(
        st,
        session,
        EVENT_HANDLER_SESSION_PROOF,
        handler_success=bool(handler_success),
        local_created_room_id=local_rid,
        local_draft_status=str(local_draft_status or "")[:32],
        local_pick_index=local_pick_index,
        session_matches_local=bool(local_rid and sess_rid == local_rid),
        authoritative_session_state=snap,
    )


def emit_ultra_early_latch_snapshot(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    return emit_room_state_read(
        session,
        st=st,
        read_label="ultra_early_before_cleanup",
        source="bootstrap_post_global_canary",
    )
