"""Line-level _prod_on_change value lifecycle tracing (diagnostic only)."""

from __future__ import annotations

import inspect
import time
from typing import Any

MUTATION_EVENT = "production_stage1_session_state_mutation"
VALUE_OP_EVENT = "production_stage1_prod_on_change_value_op"
HANDOFF_EVENT = "production_stage1_post_callback_handoff_boundary"
VALUE_SNAPSHOT_EVENT = "production_stage1_prod_on_change_value_snapshot"


def value_lifecycle_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        return bool(stage1_production_ledger_enabled(st, session))
    except ImportError:
        return False


def _emit(session: dict[str, Any], event: str, *, st: Any | None, widget_key: str, extra: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        note_stage1_event(
            session,
            event,
            st=st,
            widget_key=widget_key,
            extra={"ts": time.time(), **extra},
        )
    except ImportError:
        pass


def emit_value_snapshot(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    phase: str,
    expected_token: str,
    callback_invocation_id: str = "",
    room: dict[str, Any] | None = None,
) -> None:
    if not value_lifecycle_enabled(st, session):
        return
    raw = ""
    key_exists = False
    try:
        key_exists = widget_key in st.session_state
        if key_exists:
            raw = repr(st.session_state.get(widget_key))[:800]
    except Exception:
        raw = "error"
    _emit(
        session,
        VALUE_SNAPSHOT_EVENT,
        st=st,
        widget_key=widget_key,
        extra={
            "phase": phase,
            "callback_invocation_id": callback_invocation_id,
            "expected_token": str(expected_token or "")[:400],
            "session_state_key_exists": key_exists,
            "raw_value_repr": raw,
            "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        },
    )


def trace_value_op(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    operation_label: str,
    previous_raw: Any,
    new_raw: Any,
    callback_invocation_id: str = "",
) -> None:
    if not value_lifecycle_enabled(st, session):
        return
    frame = inspect.currentframe()
    caller = frame.f_back if frame else None
    source_file = str(caller.f_code.co_filename or "")[-120:] if caller else ""
    source_line = int(caller.f_lineno or 0) if caller else 0
    _emit(
        session,
        VALUE_OP_EVENT,
        st=st,
        widget_key=widget_key,
        extra={
            "operation_label": operation_label,
            "previous_raw_value": repr(previous_raw)[:400],
            "new_raw_value": repr(new_raw)[:400],
            "callback_invocation_id": callback_invocation_id,
            "source_file": source_file,
            "source_line": source_line,
            "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        },
    )


def emit_post_callback_handoff_boundary(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    boundary: str,
    value_raw: Any,
    callback_invocation_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not value_lifecycle_enabled(st, session):
        return
    payload: dict[str, Any] = {
        "boundary": boundary[:80],
        "value_raw": repr(value_raw)[:400],
        "callback_invocation_id": callback_invocation_id,
        "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
    }
    if extra:
        payload.update(extra)
    _emit(
        session,
        HANDOFF_EVENT,
        st=st,
        widget_key=widget_key,
        extra=payload,
    )


def trace_session_mutation(
    st: Any,
    session: dict[str, Any],
    *,
    key: str,
    mutation_op: str,
    previous: Any,
    new: Any,
    reason: str,
    callback_invocation_id: str = "",
) -> None:
    if not value_lifecycle_enabled(st, session):
        return
    if "solo_countdown" not in str(key).lower() and "persistent" not in str(key).lower():
        return
    frame = inspect.currentframe()
    caller = frame.f_back if frame else None
    _emit(
        session,
        MUTATION_EVENT,
        st=st,
        widget_key=str(key)[:120],
        extra={
            "key": str(key)[:160],
            "mutation_op": mutation_op,
            "previous_value_repr": repr(previous)[:400],
            "new_value_repr": repr(new)[:400],
            "reason": reason[:120],
            "callback_invocation_id": callback_invocation_id,
            "source_file": str(caller.f_code.co_filename or "")[-120:] if caller else "",
            "source_line": int(caller.f_lineno or 0) if caller else 0,
            "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        },
    )
