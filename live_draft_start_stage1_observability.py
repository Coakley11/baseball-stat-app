"""Durable Stage-1 ledger events for Live Draft start pipeline (observability only)."""

from __future__ import annotations

import time
from typing import Any

START_BUTTON_KEY = "live_draft_start_btn"
START_BUTTON_LABEL = "Start New Live Draft"

EVENT_CONTROL_RENDERED = "production_stage1_start_control_rendered"
EVENT_BUTTON_VALUE = "production_stage1_start_button_value"
EVENT_HANDLER_ENTERED = "production_stage1_start_handler_entered"
EVENT_HANDLER_EXITED = "production_stage1_start_handler_exited"
EVENT_ROOM_CREATION_ENTERED = "production_stage1_room_creation_entered"
EVENT_ROOM_CREATION_EXITED = "production_stage1_room_creation_exited"

START_EXPORT_PINNED = frozenset(
    {
        EVENT_CONTROL_RENDERED,
        EVENT_BUTTON_VALUE,
        EVENT_HANDLER_ENTERED,
        EVENT_HANDLER_EXITED,
        EVENT_ROOM_CREATION_ENTERED,
        EVENT_ROOM_CREATION_EXITED,
        "production_live_draft_branch_canary",
        "production_global_script_run_canary",
    }
)


def _note(st: Any | None, session: dict[str, Any], event: str, **extra: Any) -> dict[str, Any]:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        room = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else None
        return note_stage1_event(
            session,
            event,
            st=st,
            room=room,
            widget_key=str(extra.pop("widget_key", START_BUTTON_KEY) or START_BUTTON_KEY),
            extra=extra or None,
        )
    except Exception:
        return {}


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id

        return str(ensure_stage1_run_id(session) or "")[:32]
    except Exception:
        return ""


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
