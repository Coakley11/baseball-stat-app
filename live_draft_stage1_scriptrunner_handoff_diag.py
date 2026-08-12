"""ScriptRunner / ScriptRequests scheduler-handoff observability (diagnostic-only).

Instruments the invisible path after AppSession.request_rerun:

  ScriptRunner.request_rerun
  → ScriptRequests.request_rerun (store / coalesce)
  → ScriptRequests on_scriptrunner_yield / on_scriptrunner_ready (consume)
  → ScriptRunner._run_script entry
  → (existing) SafeSessionState.on_script_will_rerun

Observation only — does not alter Streamlit coalescing or product behavior.
"""

from __future__ import annotations

import threading
from typing import Any

SCRIPTRUNNER_HANDOFF_IMPL_REV = "stage1_scriptrunner_handoff_diag_v1"

_MAP_LOCK = threading.Lock()
# ScriptRequests instance id → Streamlit session id (authoritative from ScriptRunner)
_SCRIPTREQUESTS_OID_TO_SID: dict[int, str] = {}
_SCRIPTRUNNER_OID_TO_SID: dict[int, str] = {}


def _try_publish_oob(streamlit_session_id: str, publish_source: str) -> None:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return
    try:
        from live_draft_stage1_s3_oob_snapshot import publish_oob_snapshot

        publish_oob_snapshot(sid, publish_source=str(publish_source or "")[:64])
    except Exception:
        pass


def register_scriptrequests_session(script_requests: Any, streamlit_session_id: str) -> None:
    sid = str(streamlit_session_id or "").strip()[:64]
    if script_requests is None or not sid:
        return
    with _MAP_LOCK:
        _SCRIPTREQUESTS_OID_TO_SID[id(script_requests)] = sid


def register_scriptrunner_session(script_runner: Any, streamlit_session_id: str) -> None:
    sid = str(streamlit_session_id or "").strip()[:64]
    if script_runner is None or not sid:
        return
    with _MAP_LOCK:
        _SCRIPTRUNNER_OID_TO_SID[id(script_runner)] = sid
    try:
        reqs = getattr(script_runner, "_requests", None)
        if reqs is not None:
            register_scriptrequests_session(reqs, sid)
    except Exception:
        pass


def resolve_scriptrunner_sid(script_runner: Any) -> tuple[str, str]:
    """Return (sid, routing_source). Prefer ScriptRunner._session_id over ctx."""
    from live_draft_stage1_s3_process_global_diag import streamlit_session_id_from_ctx

    try:
        owned = str(getattr(script_runner, "_session_id", "") or "").strip()[:64]
        if owned:
            register_scriptrunner_session(script_runner, owned)
            return owned, "scriptrunner_session_id"
    except Exception:
        pass
    with _MAP_LOCK:
        mapped = str(_SCRIPTRUNNER_OID_TO_SID.get(id(script_runner), "") or "").strip()[:64]
    if mapped:
        return mapped, "scriptrunner_oid_map"
    ctx_sid = streamlit_session_id_from_ctx()
    if ctx_sid:
        return ctx_sid, "script_run_ctx"
    return "", "scriptrunner_sid_unresolved"


def resolve_scriptrequests_sid(script_requests: Any) -> tuple[str, str]:
    """Return (sid, routing_source). Prefer map from ScriptRunner; ctx only as fallback."""
    from live_draft_stage1_s3_process_global_diag import streamlit_session_id_from_ctx

    with _MAP_LOCK:
        mapped = str(_SCRIPTREQUESTS_OID_TO_SID.get(id(script_requests), "") or "").strip()[:64]
    if mapped:
        return mapped, "scriptrequests_oid_map"
    ctx_sid = streamlit_session_id_from_ctx()
    if ctx_sid:
        return ctx_sid, "script_run_ctx"
    return "", "scriptrequests_sid_unresolved"


def scan_rerun_data(rerun_data: Any) -> dict[str, Any]:
    from live_draft_stage1_s3_process_global_diag import scan_widget_states_proto

    widget_states = None
    try:
        widget_states = getattr(rerun_data, "widget_states", None)
    except Exception:
        widget_states = None
    scan = scan_widget_states_proto(widget_states)
    frag_id = None
    frag_queue: list[str] = []
    try:
        raw_fid = getattr(rerun_data, "fragment_id", None)
        frag_id = str(raw_fid) if raw_fid else None
    except Exception:
        frag_id = None
    try:
        frag_queue = [str(x) for x in list(getattr(rerun_data, "fragment_id_queue", None) or [])[:32]]
    except Exception:
        frag_queue = []
    return {
        "incoming_widget_count": scan.get("incoming_widget_count"),
        "activated_triggers": scan.get("activated_triggers"),
        "pause_present": scan.get("pause_present"),
        "pause_proto": scan.get("pause_proto"),
        "pause_sibling_present": scan.get("pause_sibling_present"),
        "pause_sibling_proto": scan.get("pause_sibling_proto"),
        "fragment_id": frag_id,
        "fragment_id_queue": frag_queue,
        "is_fragment_scoped_rerun": bool(getattr(rerun_data, "is_fragment_scoped_rerun", False)),
        "is_auto_rerun": bool(getattr(rerun_data, "is_auto_rerun", False)),
    }


def _emit_routed_or_unrouted(
    sid: str,
    routing_source: str,
    phase: str,
    *,
    routing_failure_reason: str,
    **fields: Any,
) -> None:
    from live_draft_stage1_s3_process_global_diag import append_module_event, append_unrouted_event

    payload = {
        "routing_source": routing_source,
        "thread_id": threading.get_ident(),
        **fields,
    }
    if sid:
        append_module_event(sid, phase, **payload)
    else:
        append_unrouted_event(
            phase,
            routing_failure_reason=routing_failure_reason,
            attempted_sid="",
            **payload,
        )


def record_scriptrunner_run_script_entry(script_runner: Any, rerun_data: Any) -> dict[str, Any]:
    """Public recorder for SCRIPTRUNNER_RUN_SCRIPT_ENTRY (also used by tests)."""
    sid, routing_source = resolve_scriptrunner_sid(script_runner)
    scan = scan_rerun_data(rerun_data)
    fields = {
        "scriptrunner_object_id": id(script_runner),
        **scan,
    }
    _emit_routed_or_unrouted(
        sid,
        routing_source,
        "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
        routing_failure_reason="scriptrunner_run_script_sid_unresolved",
        **fields,
    )
    if sid:
        _try_publish_oob(sid, "scriptrunner_run_script_entry")
    return {"streamlit_session_id": sid, "routing_source": routing_source, **scan}


def _record_rerun_consumed(
    script_requests: Any,
    request: Any,
    *,
    consume_api: str,
) -> None:
    from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequestType

    if request is None:
        return
    try:
        if getattr(request, "type", None) != ScriptRequestType.RERUN:
            return
        rerun_data = request.rerun_data
    except Exception:
        return
    sid, routing_source = resolve_scriptrequests_sid(script_requests)
    scan = scan_rerun_data(rerun_data)
    _emit_routed_or_unrouted(
        sid,
        routing_source,
        "SCRIPTREQUESTS_RERUN_CONSUMED",
        routing_failure_reason="scriptrequests_consume_sid_unresolved",
        scriptrequests_object_id=id(script_requests),
        consume_api=consume_api,
        **scan,
    )
    if sid:
        _try_publish_oob(sid, "scriptrequests_rerun_consumed")


def ensure_scriptrunner_handoff_wrappers() -> None:
    """Install ScriptRunner / ScriptRequests observation wrappers (idempotent)."""
    from live_draft_stage1_s3_process_global_diag import mark_global_wrapper
    from streamlit.runtime.scriptrunner.script_runner import ScriptRunner
    from streamlit.runtime.scriptrunner_utils.script_requests import ScriptRequestType, ScriptRequests

    # --- ScriptRunner.request_rerun ---
    if not getattr(ScriptRunner.request_rerun, "_solo_scriptrunner_rerun_wrapped", False):
        orig_sr_rerun = ScriptRunner.request_rerun

        def wrapped_scriptrunner_request_rerun(self: Any, rerun_data: Any) -> bool:
            sid, routing_source = resolve_scriptrunner_sid(self)
            scan = scan_rerun_data(rerun_data)
            try:
                register_scriptrunner_session(self, sid)
            except Exception:
                pass
            reqs = getattr(self, "_requests", None)
            reqs_oid = id(reqs) if reqs is not None else None
            _emit_routed_or_unrouted(
                sid,
                routing_source,
                "SCRIPTRUNNER_REQUEST_RERUN_ENTRY",
                routing_failure_reason="scriptrunner_request_rerun_sid_unresolved",
                scriptrunner_object_id=id(self),
                scriptrequests_object_id=reqs_oid,
                **scan,
            )
            accepted = False
            try:
                accepted = bool(orig_sr_rerun(self, rerun_data))
            except Exception:
                _emit_routed_or_unrouted(
                    sid,
                    routing_source,
                    "SCRIPTRUNNER_REQUEST_RERUN_RESULT",
                    routing_failure_reason="scriptrunner_request_rerun_sid_unresolved",
                    scriptrunner_object_id=id(self),
                    accepted=False,
                    raised=True,
                    **scan,
                )
                raise
            _emit_routed_or_unrouted(
                sid,
                routing_source,
                "SCRIPTRUNNER_REQUEST_RERUN_RESULT",
                routing_failure_reason="scriptrunner_request_rerun_sid_unresolved",
                scriptrunner_object_id=id(self),
                scriptrequests_object_id=reqs_oid,
                accepted=accepted,
                **scan,
            )
            return accepted

        wrapped_scriptrunner_request_rerun._solo_scriptrunner_rerun_wrapped = True  # type: ignore[attr-defined]
        ScriptRunner.request_rerun = wrapped_scriptrunner_request_rerun  # type: ignore[method-assign]
        mark_global_wrapper("scriptrunner_request_rerun")

    # --- ScriptRunner._run_script ---
    if not getattr(ScriptRunner._run_script, "_solo_scriptrunner_run_script_wrapped", False):
        orig_run_script = ScriptRunner._run_script

        def wrapped_scriptrunner_run_script(self: Any, rerun_data: Any) -> Any:
            try:
                record_scriptrunner_run_script_entry(self, rerun_data)
            except Exception:
                pass
            return orig_run_script(self, rerun_data)

        wrapped_scriptrunner_run_script._solo_scriptrunner_run_script_wrapped = True  # type: ignore[attr-defined]
        ScriptRunner._run_script = wrapped_scriptrunner_run_script  # type: ignore[method-assign]
        mark_global_wrapper("scriptrunner_run_script")

    # --- ScriptRequests.request_rerun ---
    if not getattr(ScriptRequests.request_rerun, "_solo_scriptrequests_rerun_wrapped", False):
        orig_req_rerun = ScriptRequests.request_rerun

        def wrapped_scriptrequests_request_rerun(self: Any, new_data: Any) -> bool:
            sid, routing_source = resolve_scriptrequests_sid(self)
            new_scan = scan_rerun_data(new_data)
            try:
                prior_state = self._state
                prior_data = self._rerun_data
            except Exception:
                prior_state = None
                prior_data = None
            prior_scan = scan_rerun_data(prior_data) if prior_data is not None else {}
            _emit_routed_or_unrouted(
                sid,
                routing_source,
                "SCRIPTREQUESTS_REQUEST_RERUN_ENTRY",
                routing_failure_reason="scriptrequests_request_rerun_sid_unresolved",
                scriptrequests_object_id=id(self),
                prior_state=str(getattr(prior_state, "name", prior_state) or ""),
                pause_present=new_scan.get("pause_present"),
                pause_proto=new_scan.get("pause_proto"),
                pause_sibling_present=new_scan.get("pause_sibling_present"),
                pause_sibling_proto=new_scan.get("pause_sibling_proto"),
                incoming_widget_count=new_scan.get("incoming_widget_count"),
                activated_triggers=new_scan.get("activated_triggers"),
                fragment_id=new_scan.get("fragment_id"),
                fragment_id_queue=new_scan.get("fragment_id_queue"),
                is_fragment_scoped_rerun=new_scan.get("is_fragment_scoped_rerun"),
                is_auto_rerun=new_scan.get("is_auto_rerun"),
            )
            accepted = bool(orig_req_rerun(self, new_data))
            try:
                result_data = self._rerun_data
                result_state = self._state
            except Exception:
                result_data = None
                result_state = None
            result_scan = scan_rerun_data(result_data) if result_data is not None else {}
            if accepted and prior_state == ScriptRequestType.CONTINUE:
                _emit_routed_or_unrouted(
                    sid,
                    routing_source,
                    "SCRIPTREQUESTS_RERUN_STORED",
                    routing_failure_reason="scriptrequests_store_sid_unresolved",
                    scriptrequests_object_id=id(self),
                    prior_state="CONTINUE",
                    result_state=str(getattr(result_state, "name", result_state) or ""),
                    **result_scan,
                )
            elif accepted and prior_state == ScriptRequestType.RERUN:
                _emit_routed_or_unrouted(
                    sid,
                    routing_source,
                    "SCRIPTREQUESTS_RERUN_COALESCED",
                    routing_failure_reason="scriptrequests_coalesce_sid_unresolved",
                    scriptrequests_object_id=id(self),
                    prior_state="RERUN",
                    result_state=str(getattr(result_state, "name", result_state) or ""),
                    previous_pause_present=bool(prior_scan.get("pause_present")),
                    previous_pause_proto=prior_scan.get("pause_proto"),
                    previous_fragment_id_queue=prior_scan.get("fragment_id_queue"),
                    previous_incoming_widget_count=prior_scan.get("incoming_widget_count"),
                    new_pause_present=bool(new_scan.get("pause_present")),
                    new_pause_proto=new_scan.get("pause_proto"),
                    new_fragment_id=new_scan.get("fragment_id"),
                    new_fragment_id_queue=new_scan.get("fragment_id_queue"),
                    new_incoming_widget_count=new_scan.get("incoming_widget_count"),
                    pause_present=result_scan.get("pause_present"),
                    pause_proto=result_scan.get("pause_proto"),
                    pause_sibling_present=result_scan.get("pause_sibling_present"),
                    pause_sibling_proto=result_scan.get("pause_sibling_proto"),
                    incoming_widget_count=result_scan.get("incoming_widget_count"),
                    activated_triggers=result_scan.get("activated_triggers"),
                    fragment_id=result_scan.get("fragment_id"),
                    fragment_id_queue=result_scan.get("fragment_id_queue"),
                    pause_retained_from_previous=bool(prior_scan.get("pause_present"))
                    and bool(result_scan.get("pause_present")),
                    pause_introduced_by_new=bool(new_scan.get("pause_present"))
                    and bool(result_scan.get("pause_present")),
                )
            return accepted

        wrapped_scriptrequests_request_rerun._solo_scriptrequests_rerun_wrapped = True  # type: ignore[attr-defined]
        ScriptRequests.request_rerun = wrapped_scriptrequests_request_rerun  # type: ignore[method-assign]
        mark_global_wrapper("scriptrequests_request_rerun")

    # --- ScriptRequests.on_scriptrunner_yield ---
    if not getattr(ScriptRequests.on_scriptrunner_yield, "_solo_scriptrequests_yield_wrapped", False):
        orig_yield = ScriptRequests.on_scriptrunner_yield

        def wrapped_on_scriptrunner_yield(self: Any) -> Any:
            result = orig_yield(self)
            try:
                _record_rerun_consumed(self, result, consume_api="on_scriptrunner_yield")
            except Exception:
                pass
            return result

        wrapped_on_scriptrunner_yield._solo_scriptrequests_yield_wrapped = True  # type: ignore[attr-defined]
        ScriptRequests.on_scriptrunner_yield = wrapped_on_scriptrunner_yield  # type: ignore[method-assign]
        mark_global_wrapper("scriptrequests_on_scriptrunner_yield")

    # --- ScriptRequests.on_scriptrunner_ready ---
    if not getattr(ScriptRequests.on_scriptrunner_ready, "_solo_scriptrequests_ready_wrapped", False):
        orig_ready = ScriptRequests.on_scriptrunner_ready

        def wrapped_on_scriptrunner_ready(self: Any) -> Any:
            result = orig_ready(self)
            try:
                _record_rerun_consumed(self, result, consume_api="on_scriptrunner_ready")
            except Exception:
                pass
            return result

        wrapped_on_scriptrunner_ready._solo_scriptrequests_ready_wrapped = True  # type: ignore[attr-defined]
        ScriptRequests.on_scriptrunner_ready = wrapped_on_scriptrunner_ready  # type: ignore[method-assign]
        mark_global_wrapper("scriptrequests_on_scriptrunner_ready")


def install_scriptrunner_handoff_probes(st: Any | None, session: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    ensure_scriptrunner_handoff_wrappers()
