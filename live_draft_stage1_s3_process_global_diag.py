"""Process-global S3 module ledgers and SessionState instance routing (diagnostic-only)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

S3_PROCESS_GLOBAL_IMPL_REV = "stage1_s3_process_global_diag_v1"

_LEDGER_LOCK = threading.Lock()
_MODULE_LEDGER_BY_STREAMLIT_SESSION: dict[str, list[dict[str, Any]]] = {}
_SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION: dict[int, str] = {}
_GLOBAL_WRAPPERS_INSTALLED: dict[str, bool] = {
    "appsession_handle_backmsg": False,
    "appsession_request_rerun": False,
    "sessionstate_on_script_will_rerun": False,
    "sessionstate_set_widgets_from_proto": False,
    "register_widget_probe": False,
}


def streamlit_session_id_from_ctx() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def register_sessionstate_instance(session_state_obj: Any, streamlit_session_id: str) -> None:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid or session_state_obj is None:
        return
    with _LEDGER_LOCK:
        _SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION[id(session_state_obj)] = sid


def resolve_sessionstate_streamlit_session_id(session_state_obj: Any) -> str:
    with _LEDGER_LOCK:
        return str(_SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.get(id(session_state_obj), "") or "")


def append_module_event(streamlit_session_id: str, phase: str, **fields: Any) -> dict[str, Any]:
    sid = str(streamlit_session_id or "").strip()[:64]
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": str(phase or "")[:48],
        "streamlit_session_id": sid,
        **{k: v for k, v in fields.items() if v is not None},
    }
    if not sid:
        return row
    with _LEDGER_LOCK:
        book = list(_MODULE_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])
        book.append(dict(row))
        _MODULE_LEDGER_BY_STREAMLIT_SESSION[sid] = book[-96:]
    return row


def module_ledger_rows(streamlit_session_id: str) -> list[dict[str, Any]]:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return []
    with _LEDGER_LOCK:
        return list(_MODULE_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])


def module_ledger_export_for_current_ctx() -> dict[str, Any]:
    sid = streamlit_session_id_from_ctx()
    rows = module_ledger_rows(sid)
    return {
        "streamlit_session_id": sid,
        "event_count": len(rows),
        "rows": rows[-48:],
        "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV,
    }


def is_pause_sibling_widget_id(widget_id: str) -> bool:
    w = str(widget_id or "")
    return "stage1_pause_sibling_return_" in w and w.endswith("_diag")


def is_pause_widget_id(widget_id: str) -> bool:
    w = str(widget_id or "")
    return "live_draft_pause" in w or w.endswith("-live_draft_pause")


def scan_widget_states_proto(widget_states: Any, *, max_triggers: int = 12) -> dict[str, Any]:
    out: dict[str, Any] = {
        "incoming_widget_count": 0,
        "activated_triggers": [],
        "pause_sibling_present": False,
        "pause_sibling_proto": {},
        "pause_present": False,
        "pause_proto": {},
    }
    try:
        widgets = list(widget_states.widgets)
    except Exception:
        return out
    out["incoming_widget_count"] = len(widgets)
    triggers: list[dict[str, Any]] = []
    for ws in widgets:
        wid = str(getattr(ws, "id", "") or "")
        trig = bool(getattr(ws, "trigger_value", False))
        if not trig:
            continue
        row = {
            "id": wid,
            "trigger_value": True,
            "bool_value": getattr(ws, "bool_value", None),
            "string_value": str(getattr(ws, "string_value", "") or "")[:120],
        }
        triggers.append(row)
        if is_pause_sibling_widget_id(wid):
            out["pause_sibling_present"] = True
            out["pause_sibling_proto"] = dict(row)
        if is_pause_widget_id(wid):
            out["pause_present"] = True
            out["pause_proto"] = dict(row)
        if len(triggers) >= max_triggers:
            break
    out["activated_triggers"] = triggers
    return out


def s3_diag_binding_snapshot(session_state_obj: Any | None = None) -> dict[str, Any]:
    sid = streamlit_session_id_from_ctx()
    ss_id = id(session_state_obj) if session_state_obj is not None else None
    bound_sid = resolve_sessionstate_streamlit_session_id(session_state_obj) if session_state_obj is not None else ""
    return {
        "global_wrappers_installed": dict(_GLOBAL_WRAPPERS_INSTALLED),
        "streamlit_session_id": sid,
        "sessionstate_object_id": ss_id,
        "sessionstate_bound_streamlit_session_id": bound_sid,
        "sessionstate_binding_ok": bool(sid and bound_sid and sid == bound_sid),
        "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV,
    }


def mark_global_wrapper(name: str) -> None:
    _GLOBAL_WRAPPERS_INSTALLED[name] = True
