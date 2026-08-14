"""Same-run Pause-preemption observability (diagnostic-only; no product semantics)."""

from __future__ import annotations

import threading
from typing import Any

PAUSE_BUTTON_CALL_RETURNED = "PAUSE_BUTTON_CALL_RETURNED"
PAUSE_BRANCH_ENTERED = "PAUSE_BRANCH_ENTERED"
PAUSE_RERUN_REQUEST_ENTRY = "PAUSE_RERUN_REQUEST_ENTRY"
LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL = "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL"
LIVE_DRAFT_RERUN_BLOCKED = "LIVE_DRAFT_RERUN_BLOCKED"

PAUSE_WIDGET_KEY = "live_draft_pause"
PAUSE_RERUN_SOURCE = "pause_draft"


def _diag_enabled(st: Any, session: dict[str, Any] | None) -> bool:
    sess = session if isinstance(session, dict) else {}
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, sess))
    except ImportError:
        return bool(sess.get("_solo_component_diag_enabled"))


def _diagnostic_run_id(session: dict[str, Any] | None) -> str:
    sess = session if isinstance(session, dict) else {}
    return str(
        sess.get("_solo_stage1_run_id")
        or sess.get("diagnostic_run_id")
        or sess.get("application_diagnostic_run_id")
        or ""
    )[:64]


def _script_run_seq(session: dict[str, Any] | None) -> int:
    sess = session if isinstance(session, dict) else {}
    try:
        return int(sess.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _streamlit_session_id() -> str:
    try:
        from live_draft_stage1_s3_process_global_diag import streamlit_session_id_from_ctx

        return str(streamlit_session_id_from_ctx() or "")[:64]
    except ImportError:
        pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _ctx_fragment_fields() -> dict[str, Any]:
    out: dict[str, Any] = {
        "fragment_id": "",
        "current_fragment_id_ctx": "",
        "fragment_ids_this_run": [],
    }
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None:
            fid = str(getattr(ctx, "current_fragment_id", "") or "")[:80]
            out["fragment_id"] = fid
            out["current_fragment_id_ctx"] = fid
            out["fragment_ids_this_run"] = [str(x) for x in list(getattr(ctx, "fragment_ids_this_run", None) or [])][:32]
    except Exception:
        pass
    return out


def _room_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    return str(room.get("draft_room_id") or room.get("room_id") or "")[:16]


def _run_identity(session: dict[str, Any] | None, room: dict[str, Any] | None) -> dict[str, Any]:
    seq = _script_run_seq(session)
    frag = _ctx_fragment_fields()
    return {
        "streamlit_session_id": _streamlit_session_id(),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "script_run_seq": seq,
        "full_app_run_seq": seq,
        "room_id": _room_id(room),
        "thread_id": int(threading.get_ident()),
        **frag,
    }


def _append(phase: str, session: dict[str, Any] | None, room: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    identity = _run_identity(session, room)
    try:
        from live_draft_stage1_s3_process_global_diag import append_module_event

        return append_module_event(
            str(identity.get("streamlit_session_id") or ""),
            str(phase or "")[:48],
            **{k: v for k, v in {**identity, **fields}.items() if k != "streamlit_session_id" and v is not None},
        )
    except ImportError:
        return {"phase": phase, **identity, **fields}


def emit_pause_button_call_returned(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    returned: bool,
    room_status: str = "",
) -> None:
    if not _diag_enabled(st, session):
        return
    try:
        status = str(room_status or (room.get("status") if isinstance(room, dict) else "") or "")[:32]
        _append(
            PAUSE_BUTTON_CALL_RETURNED,
            session,
            room,
            widget_key=PAUSE_WIDGET_KEY,
            st_button_returned=bool(returned),
            room_status_before_branch=status,
        )
    except Exception:
        pass


def emit_pause_branch_entered(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    room_status: str = "",
) -> None:
    if not _diag_enabled(st, session):
        return
    try:
        status = str(room_status or (room.get("status") if isinstance(room, dict) else "") or "")[:32]
        _append(
            PAUSE_BRANCH_ENTERED,
            session,
            room,
            widget_key=PAUSE_WIDGET_KEY,
            pause_button_returned=True,
            source=PAUSE_RERUN_SOURCE,
            room_status_before=status,
        )
    except Exception:
        pass


def emit_pause_rerun_request_entry(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    room_status: str = "",
) -> None:
    if not _diag_enabled(st, session):
        return
    try:
        status = str(room_status or (room.get("status") if isinstance(room, dict) else "") or "")[:32]
        _append(
            PAUSE_RERUN_REQUEST_ENTRY,
            session,
            room,
            source=PAUSE_RERUN_SOURCE,
            room_status=status,
        )
    except Exception:
        pass


def emit_st_rerun_about_to_call(
    st: Any,
    session: dict[str, Any],
    *,
    source: str,
    room: dict[str, Any] | None = None,
    rerun_allowed: bool = True,
    rerun_blocked_reason: str = "",
) -> None:
    if not _diag_enabled(st, session):
        return
    try:
        _append(
            LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL,
            session,
            room,
            source=str(source or "")[:64],
            rerun_allowed=bool(rerun_allowed),
            rerun_blocked_reason=str(rerun_blocked_reason or "")[:120] or None,
        )
    except Exception:
        pass


def emit_live_draft_rerun_blocked(
    st: Any,
    session: dict[str, Any],
    *,
    source: str,
    room: dict[str, Any] | None = None,
    rerun_blocked_reason: str = "",
) -> None:
    if not _diag_enabled(st, session):
        return
    try:
        _append(
            LIVE_DRAFT_RERUN_BLOCKED,
            session,
            room,
            source=str(source or "")[:64],
            rerun_allowed=False,
            rerun_blocked_reason=str(rerun_blocked_reason or "")[:120],
        )
    except Exception:
        pass
