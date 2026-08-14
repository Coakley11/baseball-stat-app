"""Process-global S3 module ledgers and SessionState instance routing (diagnostic-only)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

S3_PROCESS_GLOBAL_IMPL_REV = "stage1_s3_process_global_diag_v8"

CRITICAL_SERVER_PHASES: frozenset[str] = frozenset(
    {
        "RUNTIME_BACKMSG_ENTRY",
        "APPSESSION_BACKMSG_ENTRY",
        "APPSESSION_REQUEST_RERUN_ENTRY",
        "SCRIPTRUNNER_REQUEST_RERUN_ENTRY",
        "SCRIPTRUNNER_REQUEST_RERUN_RESULT",
        "SCRIPTREQUESTS_REQUEST_RERUN_ENTRY",
        "SCRIPTREQUESTS_RERUN_STORED",
        "SCRIPTREQUESTS_RERUN_COALESCED",
        "SCRIPTREQUESTS_ON_YIELD_ENTRY",
        "SCRIPTREQUESTS_ON_YIELD_RESULT",
        "SCRIPTREQUESTS_ON_READY_ENTRY",
        "SCRIPTREQUESTS_ON_READY_RESULT",
        "SCRIPTREQUESTS_RERUN_CONSUMED",
        "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
        "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
        "SERVER_RECEIVE_ENTRY",
        "SERVER_STATE_APPLIED",
        # Sibling same-run registration / fragment-execution correlation (diagnostic retention).
        "CONTROL_CENTER_FRAGMENT_ENTRY",
        "SIBLING_RENDER_ENTRY",
        "SIBLING_BUTTON_DECLARATION_ENTRY",
        "SIBLING_BUTTON_DECLARATION_RESULT",
        "SIBLING_BUTTON_CALL_RETURNED",
        "SIBLING_POST_REGISTRATION_RETURNED",
        "REGISTER_ENTRY",
        "REGISTER_RESULT",
        "S3_OOB_CHANNEL_REGISTERED",
        "S3_OOB_CHANNEL_INIT_FAILURE",
        # Same-run Pause-preemption / sibling-callsite control-flow (diagnostic retention).
        "PAUSE_BUTTON_CALL_RETURNED",
        "PAUSE_BRANCH_ENTERED",
        "PAUSE_RERUN_REQUEST_ENTRY",
        "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL",
        "LIVE_DRAFT_RERUN_BLOCKED",
        "SIBLING_CALLSITE_ENTRY",
        # Francisco rec-card callback-only pre-mutation fence (diagnostic retention).
        "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_STOP",
        "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_MISMATCH",
        "FRANCISCO_QUEUE_CALLBACK_GATE_CONSUMED_BLOCKED",
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
    "scriptrunner_request_rerun": False,
    "scriptrunner_run_script": False,
    "scriptrequests_request_rerun": False,
    "scriptrequests_on_scriptrunner_yield": False,
    "scriptrequests_on_scriptrunner_ready": False,
    "sessionstate_on_script_will_rerun": False,
    "sessionstate_set_widgets_from_proto": False,
    "safe_sessionstate_on_script_will_rerun": False,
    "register_widget_probe": False,
}
_EXPORT_GENERATION_LOCK = threading.Lock()
_S3_EXPORT_GENERATION = 0

INGRESS_SUMMARY_PHASE_KEYS: dict[str, str] = {
    "runtime_backmsg": "RUNTIME_BACKMSG_ENTRY",
    "appsession_backmsg": "APPSESSION_BACKMSG_ENTRY",
    "appsession_request_rerun": "APPSESSION_REQUEST_RERUN_ENTRY",
    "scriptrunner_request_rerun": "SCRIPTRUNNER_REQUEST_RERUN_ENTRY",
    "scriptrequests_rerun_stored": "SCRIPTREQUESTS_RERUN_STORED",
    "scriptrequests_rerun_coalesced": "SCRIPTREQUESTS_RERUN_COALESCED",
    "scriptrequests_rerun_consumed": "SCRIPTREQUESTS_RERUN_CONSUMED",
    "scriptrunner_run_script": "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
    "safe_sessionstate_receive": "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
    "server_receive": "SERVER_RECEIVE_ENTRY",
    "server_state_applied": "SERVER_STATE_APPLIED",
}


def next_s3_export_generation() -> int:
    global _S3_EXPORT_GENERATION
    with _EXPORT_GENERATION_LOCK:
        _S3_EXPORT_GENERATION += 1
        return _S3_EXPORT_GENERATION


def current_s3_export_generation() -> int:
    with _EXPORT_GENERATION_LOCK:
        return _S3_EXPORT_GENERATION


def ledger_totals_for_session(streamlit_session_id: str) -> dict[str, int]:
    sid = str(streamlit_session_id or "").strip()[:64]
    with _LEDGER_LOCK:
        module_total = len(_MODULE_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])
        critical_by_phase = _CRITICAL_LEDGER_BY_SESSION.get(sid) or {}
        critical_total = sum(len(rows or []) for rows in critical_by_phase.values())
        unrouted_total = len(_UNROUTED_ORPHAN_LEDGER)
    return {
        "module_ledger_total_count": module_total,
        "critical_ledger_total_count": critical_total,
        "unrouted_ledger_total_count": unrouted_total,
    }


def _latest_row_for_phase(rows: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    hits = [r for r in rows if str(r.get("phase") or "") == phase]
    if not hits:
        return {}
    return max(hits, key=lambda r: float(r.get("ts") or 0))


def build_latest_ingress_summaries(streamlit_session_id: str) -> dict[str, Any]:
    sid = str(streamlit_session_id or "").strip()[:64]
    rows = module_ledger_rows(sid)
    out: dict[str, Any] = {}
    for key, phase in INGRESS_SUMMARY_PHASE_KEYS.items():
        phase_rows = [r for r in rows if str(r.get("phase") or "") == phase]
        last = _latest_row_for_phase(rows, phase)
        summary: dict[str, Any] = {
            "phase": phase,
            "total_count": len(phase_rows),
            "latest_event_id": str(last.get("event_id") or "")[:16],
            "latest_server_ts": last.get("ts"),
            "latest_routing_sid": str(last.get("routing_sid") or last.get("streamlit_session_id") or "")[:64],
            "latest_routing_source": str(last.get("routing_source") or "")[:64],
        }
        if phase == "RUNTIME_BACKMSG_ENTRY":
            summary["latest_runtime_sid"] = str(last.get("runtime_session_id") or "")[:64]
        if phase in ("APPSESSION_BACKMSG_ENTRY", "APPSESSION_REQUEST_RERUN_ENTRY"):
            summary["latest_appsession_sid"] = str(last.get("appsession_id") or "")[:64]
        out[key] = summary
    return out


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


def register_sessionstate_pair_from_wrapper(
    session_state_wrapper: Any,
    streamlit_session_id: str,
    *,
    mapping_source: str = "sessionstate_instance_map",
) -> dict[str, Any]:
    """Register wrapper + underlying SessionState to the same Streamlit session ID."""
    resolved = resolve_sessionstate_objects(session_state_wrapper)
    sid = str(streamlit_session_id or "").strip()[:64]
    if sid:
        if resolved.get("wrapper") is not None:
            register_sessionstate_instance(resolved["wrapper"], sid)
        if resolved.get("underlying") is not None:
            register_sessionstate_instance(resolved["underlying"], sid)
    resolved["mapping_source"] = str(mapping_source or "")[:64]
    resolved["streamlit_session_id"] = sid
    return resolved


def register_sessionstate_from_appsession_owner(app_session: Any) -> dict[str, Any]:
    """Register AppSession-owned SessionState against authoritative self.id."""
    sid = str(getattr(app_session, "id", "") or "").strip()[:64]
    out: dict[str, Any] = {
        "appsession_id": sid,
        "mapping_source": "appsession_owner",
        "registered": False,
    }
    if not sid:
        return out
    ss = getattr(app_session, "_session_state", None)
    if ss is None:
        return out
    resolved = register_sessionstate_pair_from_wrapper(ss, sid, mapping_source="appsession_owner")
    out.update(resolved)
    out["registered"] = True
    return out


def build_routing_provenance(
    *,
    routing_sid: str,
    routing_source: str,
    lookup_object_id: int | None = None,
    ctx_sid: str = "",
    appsession_sid: str = "",
    runtime_sid: str = "",
) -> dict[str, Any]:
    sid = str(routing_sid or "").strip()[:64]
    ctx = str(ctx_sid or "").strip()[:64]
    app = str(appsession_sid or "").strip()[:64]
    runtime = str(runtime_sid or "").strip()[:64]
    comparable = [x for x in (sid, ctx, app, runtime) if x]
    agree = len(set(comparable)) <= 1 if comparable else False
    return {
        "routing_sid": sid,
        "routing_source": str(routing_source or "unresolved")[:64],
        "lookup_object_id": lookup_object_id,
        "ctx_streamlit_session_id": ctx,
        "appsession_sid": app,
        "runtime_sid": runtime,
        "routing_ids_agree": agree,
    }


def resolve_sessionstate_routing(
    session_state_obj: Any,
    *,
    appsession_sid: str = "",
    runtime_sid: str = "",
) -> tuple[str, str, dict[str, Any]]:
    """Resolve Streamlit session for a SessionState object (map first, ctx secondary when consistent)."""
    lookup_oid = id(session_state_obj) if session_state_obj is not None else None
    ctx_sid = streamlit_session_id_from_ctx()
    mapped_sid = resolve_sessionstate_streamlit_session_id(session_state_obj)
    app_sid = str(appsession_sid or "").strip()[:64]
    run_sid = str(runtime_sid or "").strip()[:64]

    available = [x for x in (mapped_sid, app_sid, run_sid, ctx_sid) if x]
    ids_agree = len(set(available)) <= 1 if available else True

    if mapped_sid:
        if ctx_sid and mapped_sid != ctx_sid:
            ids_agree = False
        return (
            mapped_sid,
            "sessionstate_instance_map",
            build_routing_provenance(
                routing_sid=mapped_sid,
                routing_source="sessionstate_instance_map",
                lookup_object_id=lookup_oid,
                ctx_sid=ctx_sid,
                appsession_sid=app_sid,
                runtime_sid=run_sid,
            )
            | {"routing_ids_agree": ids_agree},
        )

    conflicting = False
    if ctx_sid and app_sid and ctx_sid != app_sid:
        conflicting = True
    if ctx_sid and run_sid and ctx_sid != run_sid:
        conflicting = True
    if app_sid and run_sid and app_sid != run_sid:
        conflicting = True

    if conflicting:
        return (
            "",
            "unresolved",
            build_routing_provenance(
                routing_sid="",
                routing_source="unresolved",
                lookup_object_id=lookup_oid,
                ctx_sid=ctx_sid,
                appsession_sid=app_sid,
                runtime_sid=run_sid,
            )
            | {"routing_ids_agree": False, "routing_id_conflict": True},
        )

    if ctx_sid:
        return (
            ctx_sid,
            "script_run_context",
            build_routing_provenance(
                routing_sid=ctx_sid,
                routing_source="script_run_context",
                lookup_object_id=lookup_oid,
                ctx_sid=ctx_sid,
                appsession_sid=app_sid,
                runtime_sid=run_sid,
            ),
        )
    return (
        "",
        "unresolved",
        build_routing_provenance(
            routing_sid="",
            routing_source="unresolved",
            lookup_object_id=lookup_oid,
            ctx_sid=ctx_sid,
            appsession_sid=app_sid,
            runtime_sid=run_sid,
        ),
    )


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


def critical_ledger_by_phase(streamlit_session_id: str) -> dict[str, list[dict[str, Any]]]:
    """Bounded per-phase critical tails (independent of mixed-row export order)."""
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return {}
    with _LEDGER_LOCK:
        by_phase = _CRITICAL_LEDGER_BY_SESSION.get(sid) or {}
        return {str(ph): [dict(r) for r in list(rows or [])] for ph, rows in by_phase.items()}


def critical_ledger_rows(streamlit_session_id: str) -> list[dict[str, Any]]:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return []
    by_phase = critical_ledger_by_phase(sid)
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
    appsession_sid: str = "",
    runtime_sid: str = "",
    **fields: Any,
) -> dict[str, Any]:
    routing_sid, routing_source, provenance = resolve_sessionstate_routing(
        underlying_session_state,
        appsession_sid=appsession_sid,
        runtime_sid=runtime_sid,
    )
    ctx_sid = provenance.get("ctx_streamlit_session_id") or streamlit_session_id_from_ctx()
    routing_resolved = bool(routing_sid)
    payload = {
        "underlying_sessionstate_object_id": id(underlying_session_state),
        "underlying_sessionstate_type": type(underlying_session_state).__name__,
        "routing_resolved": routing_resolved,
        "ctx_streamlit_session_id": ctx_sid,
        **provenance,
        **(extra_identity or {}),
        **fields,
    }
    if routing_sid:
        return append_module_event(routing_sid, phase, **payload)
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
