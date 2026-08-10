"""Process-global S3 module ledgers and SessionState instance routing (diagnostic-only)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

S3_PROCESS_GLOBAL_IMPL_REV = "stage1_s3_process_global_diag_v3"

CRITICAL_SERVER_PHASES: frozenset[str] = frozenset(
    {
        "RUNTIME_BACKMSG_ENTRY",
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
    }
)
_CRITICAL_EVENTS_PER_PHASE = 8

_LEDGER_LOCK = threading.Lock()
_MODULE_LEDGER_BY_STREAMLIT_SESSION: dict[str, list[dict[str, Any]]] = {}
_CRITICAL_LEDGER_BY_SESSION: dict[str, dict[str, list[dict[str, Any]]]] = {}
_UNROUTED_ORPHAN_LEDGER: list[dict[str, Any]] = []
_MAX_UNROUTED = 32
_SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION: dict[int, str] = {}
_GLOBAL_WRAPPERS_INSTALLED: dict[str, bool] = {
    "runtime_handle_backmsg": False,
    "appsession_handle_backmsg": False,
    "appsession_request_rerun": False,
    "sessionstate_on_script_will_rerun": False,
    "sessionstate_set_widgets_from_proto": False,
    "safe_sessionstate_on_script_will_rerun": False,
    "register_widget_probe": False,
}


def streamlit_session_id_from_ctx() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def resolve_sessionstate_objects(obj: Any | None) -> dict[str, Any]:
    """Resolve SafeSessionState wrapper vs underlying SessionState."""
    wrapper = obj
    wrapper_type = type(wrapper).__name__ if wrapper is not None else ""
    underlying: Any | None = None
    unwrap_source = "none"
    if wrapper is not None:
        try:
            st = object.__getattribute__(wrapper, "_state")
            if st is not None:
                underlying = st
                unwrap_source = "_state"
        except Exception:
            underlying = None
        if underlying is None and hasattr(wrapper, "_new_widget_state"):
            underlying = wrapper
            if unwrap_source == "none":
                unwrap_source = "direct_sessionstate"
        if underlying is None:
            underlying = wrapper
            if unwrap_source == "none":
                unwrap_source = "passthrough"
    same = wrapper is not None and underlying is not None and id(wrapper) == id(underlying)
    return {
        "wrapper": wrapper,
        "underlying": underlying,
        "wrapper_type": wrapper_type,
        "underlying_type": type(underlying).__name__ if underlying is not None else "",
        "wrapper_object_id": id(wrapper) if wrapper is not None else None,
        "underlying_object_id": id(underlying) if underlying is not None else None,
        "wrapper_and_underlying_same_object": bool(same),
        "unwrap_source": unwrap_source,
    }


def register_sessionstate_instance(session_state_obj: Any, streamlit_session_id: str) -> None:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid or session_state_obj is None:
        return
    with _LEDGER_LOCK:
        _SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION[id(session_state_obj)] = sid


def register_sessionstate_pair_from_wrapper(session_state_wrapper: Any, streamlit_session_id: str) -> dict[str, Any]:
    """Register wrapper + underlying SessionState to the same Streamlit session ID."""
    resolved = resolve_sessionstate_objects(session_state_wrapper)
    sid = str(streamlit_session_id or "").strip()[:64]
    if sid:
        if resolved.get("wrapper") is not None:
            register_sessionstate_instance(resolved["wrapper"], sid)
        if resolved.get("underlying") is not None:
            register_sessionstate_instance(resolved["underlying"], sid)
    return resolved


def resolve_sessionstate_streamlit_session_id(session_state_obj: Any) -> str:
    with _LEDGER_LOCK:
        return str(_SESSIONSTATE_INSTANCE_TO_STREAMLIT_SESSION.get(id(session_state_obj), "") or "")


def append_unrouted_event(phase: str, *, routing_failure_reason: str = "", **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": str(phase or "")[:48],
        "routing_failure_reason": str(routing_failure_reason or "")[:120],
        "ctx_streamlit_session_id": streamlit_session_id_from_ctx(),
        "thread_id": threading.get_ident(),
        **{k: v for k, v in fields.items() if v is not None},
    }
    with _LEDGER_LOCK:
        _UNROUTED_ORPHAN_LEDGER.append(dict(row))
        if len(_UNROUTED_ORPHAN_LEDGER) > _MAX_UNROUTED:
            del _UNROUTED_ORPHAN_LEDGER[: len(_UNROUTED_ORPHAN_LEDGER) - _MAX_UNROUTED]
    return row


def unrouted_ledger_export() -> dict[str, Any]:
    with _LEDGER_LOCK:
        rows = list(_UNROUTED_ORPHAN_LEDGER)
    return {"event_count": len(rows), "rows": rows[-24:], "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV}


def _append_critical_row_locked(sid: str, phase: str, row: dict[str, Any]) -> None:
    ph = str(phase or "")[:48]
    if ph not in CRITICAL_SERVER_PHASES:
        return
    by_phase = _CRITICAL_LEDGER_BY_SESSION.setdefault(sid, {})
    bucket = list(by_phase.get(ph) or [])
    bucket.append(dict(row))
    by_phase[ph] = bucket[-_CRITICAL_EVENTS_PER_PHASE:]


def critical_ledger_rows(streamlit_session_id: str) -> list[dict[str, Any]]:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return []
    with _LEDGER_LOCK:
        by_phase = _CRITICAL_LEDGER_BY_SESSION.get(sid) or {}
        flat: list[dict[str, Any]] = []
        for ph in sorted(by_phase.keys()):
            flat.extend(by_phase[ph])
    return sorted(flat, key=lambda r: float(r.get("ts") or 0))


def critical_ledger_export(streamlit_session_id: str | None = None) -> dict[str, Any]:
    sid = str(streamlit_session_id or streamlit_session_id_from_ctx() or "").strip()[:64]
    rows = critical_ledger_rows(sid)
    return {
        "streamlit_session_id": sid,
        "event_count": len(rows),
        "rows": rows,
        "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV,
    }


def append_module_event(streamlit_session_id: str, phase: str, **fields: Any) -> dict[str, Any]:
    sid = str(streamlit_session_id or "").strip()[:64]
    ph = str(phase or "")[:48]
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": ph,
        "streamlit_session_id": sid,
        **{k: v for k, v in fields.items() if v is not None},
    }
    if not sid:
        append_unrouted_event(
            ph,
            routing_failure_reason="empty_streamlit_session_id",
            attempted_sid="",
            **{k: v for k, v in fields.items() if k not in ("streamlit_session_id",)},
        )
        return row
    with _LEDGER_LOCK:
        book = list(_MODULE_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])
        book.append(dict(row))
        _MODULE_LEDGER_BY_STREAMLIT_SESSION[sid] = book[-96:]
        _append_critical_row_locked(sid, ph, row)
    return row


def append_module_event_for_underlying_sessionstate(
    underlying_session_state: Any,
    phase: str,
    *,
    extra_identity: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    mapped_sid = resolve_sessionstate_streamlit_session_id(underlying_session_state)
    ctx_sid = streamlit_session_id_from_ctx()
    routing_resolved = bool(mapped_sid)
    payload = {
        "underlying_sessionstate_object_id": id(underlying_session_state),
        "underlying_sessionstate_type": type(underlying_session_state).__name__,
        "routing_resolved": routing_resolved,
        "ctx_streamlit_session_id": ctx_sid,
        **(extra_identity or {}),
        **fields,
    }
    if mapped_sid:
        return append_module_event(mapped_sid, phase, **payload)
    append_unrouted_event(
        phase,
        routing_failure_reason="underlying_sessionstate_not_mapped",
        sessionstate_object_id=id(underlying_session_state),
        object_type=type(underlying_session_state).__name__,
        attempted_sid=ctx_sid,
        **payload,
    )
    return payload


def module_ledger_rows(streamlit_session_id: str) -> list[dict[str, Any]]:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return []
    with _LEDGER_LOCK:
        return list(_MODULE_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])


def module_ledger_export_for_current_ctx(*, include_full_module_rows: bool = False) -> dict[str, Any]:
    sid = streamlit_session_id_from_ctx()
    rows = module_ledger_rows(sid)
    return {
        "streamlit_session_id": sid,
        "event_count": len(rows),
        "module_row_count_before_tail": len(rows),
        "rows": rows if include_full_module_rows else rows[-48:],
        "module_rows": rows,
        "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV,
        "unrouted_events": unrouted_ledger_export(),
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


def s3_diag_binding_snapshot(session_state_wrapper: Any | None = None) -> dict[str, Any]:
    from live_draft_stage1_server_evidence import live_server_wrapper_integrity_snapshot

    sid = streamlit_session_id_from_ctx()
    integrity = live_server_wrapper_integrity_snapshot()
    resolved = resolve_sessionstate_objects(session_state_wrapper)
    wrapper = resolved.get("wrapper")
    underlying = resolved.get("underlying")
    wrapper_bound = resolve_sessionstate_streamlit_session_id(wrapper) if wrapper is not None else ""
    underlying_bound = resolve_sessionstate_streamlit_session_id(underlying) if underlying is not None else ""
    wrapper_ok = bool(sid and wrapper_bound and sid == wrapper_bound)
    underlying_ok = bool(sid and underlying_bound and sid == underlying_bound)
    return {
        "global_wrappers_installed": dict(_GLOBAL_WRAPPERS_INSTALLED),
        "server_wrapper_integrity_ok": bool(integrity.get("server_wrapper_integrity_ok")),
        "server_wrapper_integrity": integrity,
        "streamlit_session_id": sid,
        "context_session_state_type": resolved.get("wrapper_type") or "",
        "context_session_state_object_id": resolved.get("wrapper_object_id"),
        "sessionstate_wrapper_bound_streamlit_session_id": wrapper_bound,
        "underlying_sessionstate_type": resolved.get("underlying_type") or "",
        "underlying_sessionstate_object_id": resolved.get("underlying_object_id"),
        "underlying_sessionstate_bound_streamlit_session_id": underlying_bound,
        "sessionstate_wrapper_binding_ok": wrapper_ok,
        "sessionstate_binding_ok": underlying_ok,
        "wrapper_and_underlying_same_object": resolved.get("wrapper_and_underlying_same_object"),
        "unwrap_source": resolved.get("unwrap_source") or "",
        "sessionstate_object_id": resolved.get("wrapper_object_id"),
        "sessionstate_bound_streamlit_session_id": wrapper_bound,
        "impl_rev": S3_PROCESS_GLOBAL_IMPL_REV,
    }


def mark_global_wrapper(name: str) -> None:
    _GLOBAL_WRAPPERS_INSTALLED[name] = True
