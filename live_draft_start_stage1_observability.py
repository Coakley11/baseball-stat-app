"""Durable Stage-1 ledger events for Live Draft start pipeline (observability only)."""

from __future__ import annotations

import json
import time
from typing import Any

START_BUTTON_KEY = "live_draft_start_btn"
START_BUTTON_LABEL = "Start New Live Draft"

EVENT_CONTROL_RENDERED = "production_stage1_start_control_rendered"
EVENT_BUTTON_VALUE = "production_stage1_start_button_value"
EVENT_CALLBACK_ENTERED = "production_stage1_start_callback_entered"
EVENT_CALLBACK_EXITED = "production_stage1_start_callback_exited"
EVENT_HANDLER_ENTERED = "production_stage1_start_handler_entered"
EVENT_HANDLER_EXITED = "production_stage1_start_handler_exited"
EVENT_PENDING_OBSERVED = "production_stage1_pending_start_observed"
EVENT_PENDING_CONSUMED = "production_stage1_pending_start_consumed"
EVENT_PENDING_ABSENT = "production_stage1_pending_start_absent"
EVENT_ROOM_CREATION_ENTERED = "production_stage1_room_creation_entered"
EVENT_ROOM_CREATION_EXITED = "production_stage1_room_creation_exited"

START_EXPORT_PINNED = frozenset(
    {
        EVENT_CONTROL_RENDERED,
        EVENT_BUTTON_VALUE,
        EVENT_CALLBACK_ENTERED,
        EVENT_CALLBACK_EXITED,
        EVENT_HANDLER_ENTERED,
        EVENT_HANDLER_EXITED,
        EVENT_PENDING_OBSERVED,
        EVENT_PENDING_CONSUMED,
        EVENT_PENDING_ABSENT,
        EVENT_ROOM_CREATION_ENTERED,
        EVENT_ROOM_CREATION_EXITED,
        "production_live_draft_branch_canary",
        "production_global_script_run_canary",
    }
)


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _deployment_sha(session: dict[str, Any]) -> str:
    sha = str(session.get("_solo_stage1_deployment_sha") or "").strip()
    if sha:
        return sha[:7]
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "")[:7]
    except ImportError:
        return ""


def _script_run_seq(session: dict[str, Any]) -> int:
    return int(session.get("_solo_stage1_script_run_seq") or 0)


def _resolve_lifecycle(session: dict[str, Any], room: dict[str, Any] | None) -> str:
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        return str(resolve_live_draft_lifecycle(session, room=room) or "")
    except ImportError:
        return ""


def _room_snapshot(session: dict[str, Any], room: dict[str, Any] | None) -> dict[str, Any]:
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(live, dict):
        live = {}
    rid = str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()
    return {
        "room_id": rid,
        "room_status": str(live.get("status") or ""),
        "pick_index": live.get("current_pick_index"),
    }


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id

        return str(ensure_stage1_run_id(session) or "")[:32]
    except Exception:
        return ""


def _note(st: Any | None, session: dict[str, Any], event: str, **extra: Any) -> dict[str, Any]:
    widget_key = str(extra.pop("widget_key", START_BUTTON_KEY) or START_BUTTON_KEY)
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    lifecycle = str(extra.get("lifecycle") or _resolve_lifecycle(session, room))[:64]
    checkpoint = str(extra.get("checkpoint") or extra.get("handler_source") or "")[:120]
    base: dict[str, Any] = {
        "event": event,
        "ts": time.time(),
        "deployment_sha": _deployment_sha(session),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "streamlit_session_id": _streamlit_session_id(),
        "script_run_seq": _script_run_seq(session),
        "widget_key": widget_key,
        "active_page": str(session.get("active_page") or "")[:120],
        "lifecycle": lifecycle,
        "checkpoint": checkpoint,
        "source": str(extra.get("handler_source") or extra.get("source") or "start_stage1_observability")[:120],
        **_room_snapshot(session, room),
    }
    base.update(extra)
    try:
        print(f"SOLO_STAGE1_BOUNDARY_CANARY|{json.dumps(base, default=str)}", flush=True)
    except Exception:
        pass
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        return note_stage1_event(
            session,
            event,
            st=st,
            room=room,
            widget_key=widget_key,
            extra={k: v for k, v in base.items() if k not in ("event", "ts")},
        )
    except Exception:
        return {}


def emit_start_control_rendered(
    st: Any | None,
    session: dict[str, Any],
    *,
    disabled: bool,
    help_text: str = "",
    form_context: str = "live_draft_setup_columns",
) -> dict[str, Any]:
    return _note(
        st,
        session,
        EVENT_CONTROL_RENDERED,
        button_label=START_BUTTON_LABEL,
        widget_key=START_BUTTON_KEY,
        disabled_state=bool(disabled),
        help_text=str(help_text or "")[:200],
        form_container_context=form_context,
        diagnostic_run_id=_diagnostic_run_id(session),
        setup_surface_active=True,
    )


def emit_start_button_value(
    st: Any | None,
    session: dict[str, Any],
    *,
    live_draft_branch_entered: bool,
    setup_surface_active: bool,
) -> dict[str, Any]:
    pending = bool(session.get("_start_live_draft_pending"))
    clicked = bool((session.get("_start_live_draft_trace") or {}).get("start_live_draft_clicked"))
    return _note(
        st,
        session,
        EVENT_BUTTON_VALUE,
        button_return_value=False,
        on_click_callback_armed=pending or clicked,
        start_pending=pending,
        widget_key=START_BUTTON_KEY,
        live_draft_branch_entered=bool(live_draft_branch_entered),
        setup_surface_active=bool(setup_surface_active),
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def emit_start_callback_entered(session: dict[str, Any]) -> dict[str, Any]:
    return _note(
        None,
        session,
        EVENT_CALLBACK_ENTERED,
        handler_source="on_start_new_live_draft",
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def emit_start_callback_exited(
    session: dict[str, Any],
    *,
    pending_armed: bool,
    exit_reason: str,
    gate_error: str = "",
) -> dict[str, Any]:
    return _note(
        None,
        session,
        EVENT_CALLBACK_EXITED,
        pending_armed=bool(pending_armed),
        exit_reason=str(exit_reason or "")[:200],
        gate_error=str(gate_error or "")[:500],
        start_pending_after_callback=bool(session.get("_start_live_draft_pending")),
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def emit_start_handler_entered(session: dict[str, Any], *, source: str = "on_start_new_live_draft") -> dict[str, Any]:
    session["_stage1_start_handler_t0"] = time.time()
    return _note(
        None,
        session,
        EVENT_HANDLER_ENTERED,
        handler_source=source,
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def emit_start_handler_exited(
    session: dict[str, Any],
    *,
    success: bool,
    exception: str = "",
    created_room_id: str = "",
    draft_status: str = "",
    pick_index: Any = None,
    deadline_token: str = "",
    session_state_writes: list[str] | None = None,
) -> dict[str, Any]:
    t0 = float(session.pop("_stage1_start_handler_t0", 0) or 0)
    elapsed_ms = round((time.time() - t0) * 1000, 2) if t0 else None
    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    rid = created_room_id or str(live.get("draft_room_id") or live.get("draft_id") or "")
    return _note(
        None,
        session,
        EVENT_HANDLER_EXITED,
        handler_success=bool(success),
        exception_status=str(exception or "")[:500],
        created_room_id=str(rid).upper()[:32],
        draft_status=str(draft_status or live.get("status") or ""),
        pick_index=pick_index if pick_index is not None else live.get("current_pick_index"),
        deadline_token=str(deadline_token or session.get("_solo_persistent_wake_last_token") or "")[:120],
        session_state_writes=list(session_state_writes or [])[:20],
        elapsed_ms=elapsed_ms,
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def record_pending_start_boundary_before_pop(st: Any | None, session: dict[str, Any]) -> tuple[bool, Any]:
    """Diagnostic only — does not read or mutate ``_start_live_draft_pending``."""
    key = "_start_live_draft_pending"
    room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
    common = {
        "active_page": str(session.get("active_page") or "")[:120],
        "diagnostic_run_id": _diagnostic_run_id(session),
        "script_run_seq": _script_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "room_present": isinstance(room, dict),
        "room_id": _room_snapshot(session, room).get("room_id") or "",
        "lifecycle": _resolve_lifecycle(session, room),
    }
    if key not in session:
        _note(st, session, EVENT_PENDING_ABSENT, **common, pending_key_present=False)
        return False, None
    raw = session.get(key)
    _note(
        st,
        session,
        EVENT_PENDING_OBSERVED,
        **common,
        pending_key_present=True,
        pending_raw_value=repr(raw)[:80],
        pending_truthy=bool(raw),
    )
    return True, raw


def record_pending_start_boundary_after_pop(
    st: Any | None,
    session: dict[str, Any],
    *,
    was_present: bool,
    will_execute: bool,
) -> dict[str, Any]:
    if not was_present and not will_execute:
        return {}
    return _note(
        st,
        session,
        EVENT_PENDING_CONSUMED,
        was_present_before_pop=bool(was_present),
        will_execute_pending_handler=bool(will_execute),
        active_page=str(session.get("active_page") or "")[:120],
        diagnostic_run_id=_diagnostic_run_id(session),
        script_run_seq=_script_run_seq(session),
        streamlit_session_id=_streamlit_session_id(),
    )


def emit_room_creation_entered(session: dict[str, Any], *, mode: str = "new") -> dict[str, Any]:
    session["_stage1_room_creation_t0"] = time.time()
    return _note(
        None,
        session,
        EVENT_ROOM_CREATION_ENTERED,
        start_mode=str(mode or "new"),
        diagnostic_run_id=_diagnostic_run_id(session),
    )


def emit_room_creation_exited(
    session: dict[str, Any],
    *,
    success: bool,
    error: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    t0 = float(session.pop("_stage1_room_creation_t0", 0) or 0)
    elapsed_ms = round((time.time() - t0) * 1000, 2) if t0 else None
    return _note(
        None,
        session,
        EVENT_ROOM_CREATION_EXITED,
        room_creation_success=bool(success),
        error=str(error or "")[:500],
        created_room_id=str(room_id or "").upper()[:32],
        elapsed_ms=elapsed_ms,
        diagnostic_run_id=_diagnostic_run_id(session),
    )


try:
    from live_draft_queueui_instrumentation_build import emit_instrumentation_build_loaded

    emit_instrumentation_build_loaded(__name__, __file__)
except ImportError:
    pass
