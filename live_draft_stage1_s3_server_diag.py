"""S3 server-side registration / state-apply diagnostics (solo diag, read-only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

S3_SERVER_DIAG_IMPL_REV = "stage1_s3_server_diag_v9"
S3_LEDGER_DOM_ID = "solo-stage1-s3-server-diag-ledger"
S3_READINESS_DOM_ID = "solo-stage1-s3-server-diag-readiness"
S3_DOM_PAYLOAD_SCHEMA_REV = "stage1_s3_dom_payload_v3"
S3_SESSION_LEDGER_KEY = "_stage1_s3_server_diag_ledger"
S3_PATCHED_KEY = "_stage1_s3_server_diag_patched"
S3_WATCH_KEY = "_stage1_s3_server_watch_user_key"
S3_BINDING_KEY = "_stage1_s3_diag_binding"


def is_pause_sibling_user_key(user_key: str) -> bool:
    return str(user_key or "").startswith("stage1_pause_sibling_return_") and str(user_key or "").endswith("_diag")


def _streamlit_session_id() -> str:
    from live_draft_stage1_s3_process_global_diag import streamlit_session_id_from_ctx

    return streamlit_session_id_from_ctx()


def append_s3_event(session: dict[str, Any] | None, phase: str, **fields: Any) -> dict[str, Any]:
    from live_draft_stage1_s3_oob_snapshot import _session_mapping
    from live_draft_stage1_s3_process_global_diag import append_module_event, streamlit_session_id_from_ctx

    sid = streamlit_session_id_from_ctx()
    extra = dict(fields)
    extra.pop("streamlit_session_id", None)
    row = append_module_event(sid, phase, **extra)
    mapping = _session_mapping(session)
    if mapping is not None and sid:
        book = list(mapping.get(S3_SESSION_LEDGER_KEY) or [])
        book.append(dict(row))
        mapping[S3_SESSION_LEDGER_KEY] = book[-64:]
    return row


def s3_ledger_export(session: dict[str, Any] | None = None) -> dict[str, Any]:
    from live_draft_stage1_s3_process_global_diag import (
        critical_ledger_export,
        module_ledger_export_for_current_ctx,
        streamlit_session_id_from_ctx,
        unrouted_ledger_export,
    )
    from live_draft_stage1_server_evidence import merge_authoritative_server_rows

    sid = streamlit_session_id_from_ctx()
    mod_exp = module_ledger_export_for_current_ctx(include_full_module_rows=True)
    module_rows = list(mod_exp.get("module_rows") or [])
    local_rows: list[dict[str, Any]] = []
    from live_draft_stage1_s3_oob_snapshot import _session_mapping

    mapping = _session_mapping(session)
    if mapping is not None:
        local_rows = list(mapping.get(S3_SESSION_LEDGER_KEY) or [])
    critical_rows = list(critical_ledger_export(sid).get("rows") or [])
    merge = merge_authoritative_server_rows(module_rows=module_rows, local_rows=local_rows, critical_rows=critical_rows)
    merged_rows = list(merge.get("merged_rows") or [])
    unrouted = unrouted_ledger_export()
    return {
        "streamlit_session_id": sid,
        "event_count": len(merged_rows),
        "rows": merged_rows[-96:],
        "module_rows": module_rows,
        "local_rows": local_rows,
        "critical_server_rows": critical_rows,
        "merged_rows": merged_rows,
        "unrouted_rows": list(unrouted.get("rows") or []),
        "merge_stats": {
            "module_row_count": merge.get("module_row_count"),
            "local_row_count": merge.get("local_row_count"),
            "critical_row_count": merge.get("critical_row_count"),
            "merged_row_count": merge.get("merged_row_count"),
            "duplicate_event_id_count": merge.get("duplicate_event_id_count"),
            "oldest_ts": merge.get("oldest_ts"),
            "newest_ts": merge.get("newest_ts"),
            "phase_counts": merge.get("phase_counts"),
        },
        "module_row_count_before_tail": len(module_rows),
        "impl_rev": S3_SERVER_DIAG_IMPL_REV,
    }


_S3_DOM_ROW_LIMITS = {
    "ledger_rows": 96,
    "module_rows": 48,
    "local_rows": 48,
    "critical_server_rows": 96,
    "merged_rows": 96,
    "ingress_rows": 48,
    "unrouted_rows": 32,
    "fragment_owner_history": 16,
}

_PRESERVE_PHASE_PREFIXES = (
    "APPSESSION_",
    "SCRIPTRUNNER_",
    "SCRIPTREQUESTS_",
    "SAFE_SESSIONSTATE_",
    "SERVER_",
    "RUNTIME_BACKMSG",
    "S3_DIAG_",
    "S3_OOB_",
    "REGISTER_",
)


def _row_phase(row: dict[str, Any]) -> str:
    return str(row.get("phase") or row.get("event") or "")[:80]


def _is_priority_row(row: dict[str, Any]) -> bool:
    ph = _row_phase(row)
    if is_pause_sibling_user_key(str(row.get("user_key") or row.get("widget_key") or "")):
        return True
    if "pause" in ph.lower() or "sibling" in ph.lower():
        return True
    return any(ph.startswith(p) for p in _PRESERVE_PHASE_PREFIXES)


def _bound_row_list(
    rows: list[dict[str, Any]],
    limit: int,
    *,
    label: str,
    bounds_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    src = list(rows or [])
    before = len(src)
    if before <= limit:
        return src
    priority = [r for r in src if _is_priority_row(r)]
    tail = src[-limit:]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in priority + tail:
        eid = str(r.get("event_id") or id(r))
        if eid in seen:
            continue
        seen.add(eid)
        out.append(r)
        if len(out) >= limit:
            break
    bounds_log.append({"collection": label, "before": before, "after": len(out), "limit": limit})
    return out


def _session_export_identity(session: dict[str, Any]) -> dict[str, Any]:
    script_run_seq = 0
    diagnostic_run_id = ""
    try:
        from live_draft_stage1_pause_sibling_probe import _full_app_run_seq

        script_run_seq = int(_full_app_run_seq(session))
    except Exception:
        script_run_seq = int(session.get("_full_app_run_seq") or session.get("full_app_run_seq") or 0)
    diagnostic_run_id = str(
        session.get("diagnostic_run_id")
        or session.get("application_diagnostic_run_id")
        or session.get("run_id")
        or ""
    )[:64]
    return {"script_run_seq": script_run_seq, "diagnostic_run_id": diagnostic_run_id}


def build_s3_dom_payload(
    session: dict[str, Any],
    *,
    export: dict[str, Any] | None = None,
    ingress: dict[str, Any] | None = None,
    unrouted: dict[str, Any] | None = None,
    owner_hist: list[dict[str, Any]] | None = None,
    export_generation: int | None = None,
    export_generated_server_ts: float | None = None,
) -> dict[str, Any]:
    """Build a complete, JSON-serializable S3 DOM payload (setup fields always included)."""
    export = dict(export if export is not None else s3_ledger_export(session))
    binding = dict(session.get(S3_BINDING_KEY) or {})
    post = dict(session.get("_stage1_pause_sibling_post_registration") or {})
    pre = dict(session.get("_stage1_pause_sibling_pre_declaration") or {})
    if ingress is None:
        try:
            from live_draft_stage1_appsession_ingress_diag import appsession_ingress_export

            ingress = appsession_ingress_export(session)
        except ImportError:
            ingress = {"rows": []}
    if unrouted is None:
        try:
            from live_draft_stage1_s3_process_global_diag import unrouted_ledger_export

            unrouted = unrouted_ledger_export()
        except ImportError:
            unrouted = {"rows": []}
    if owner_hist is None:
        try:
            from live_draft_cloud_diagnostics import FRAGMENT_OWNER_HISTORY_KEY

            owner_hist = list(session.get(FRAGMENT_OWNER_HISTORY_KEY) or [])
        except ImportError:
            owner_hist = []

    bounds_log: list[dict[str, Any]] = []
    lim = _S3_DOM_ROW_LIMITS
    ledger_slim = {
        "streamlit_session_id": export.get("streamlit_session_id"),
        "event_count": export.get("event_count"),
        "impl_rev": export.get("impl_rev"),
        "rows": _bound_row_list(list(export.get("rows") or []), lim["ledger_rows"], label="ledger.rows", bounds_log=bounds_log),
        "module_rows": _bound_row_list(
            list(export.get("module_rows") or []), lim["module_rows"], label="ledger.module_rows", bounds_log=bounds_log
        ),
        "local_rows": _bound_row_list(
            list(export.get("local_rows") or []), lim["local_rows"], label="ledger.local_rows", bounds_log=bounds_log
        ),
        "critical_server_rows": _bound_row_list(
            list(export.get("critical_server_rows") or []),
            lim["critical_server_rows"],
            label="ledger.critical_server_rows",
            bounds_log=bounds_log,
        ),
        "merged_rows": _bound_row_list(
            list(export.get("merged_rows") or []), lim["merged_rows"], label="ledger.merged_rows", bounds_log=bounds_log
        ),
        "merge_stats": export.get("merge_stats"),
        "module_row_count_before_tail": export.get("module_row_count_before_tail"),
    }
    ingress_rows = _bound_row_list(
        list((ingress or {}).get("rows") or []), lim["ingress_rows"], label="appsession_ingress.rows", bounds_log=bounds_log
    )
    unrouted_rows = _bound_row_list(
        list((unrouted or {}).get("rows") or []), lim["unrouted_rows"], label="unrouted_events.rows", bounds_log=bounds_log
    )
    owner_bounded = list(owner_hist or [])[-lim["fragment_owner_history"] :]
    if len(owner_hist or []) > len(owner_bounded):
        bounds_log.append(
            {
                "collection": "fragment_owner_history",
                "before": len(owner_hist or []),
                "after": len(owner_bounded),
                "limit": lim["fragment_owner_history"],
            }
        )

    before_counts = {
        "ledger.rows": len(export.get("rows") or []),
        "ledger.module_rows": len(export.get("module_rows") or []),
        "ledger.local_rows": len(export.get("local_rows") or []),
        "ledger.critical_server_rows": len(export.get("critical_server_rows") or []),
        "ledger.merged_rows": len(export.get("merged_rows") or []),
        "appsession_ingress.rows": len((ingress or {}).get("rows") or []),
        "unrouted_events.rows": len((unrouted or {}).get("rows") or []),
        "fragment_owner_history": len(owner_hist or []),
    }
    exported_counts = {
        "ledger.rows": len(ledger_slim["rows"]),
        "ledger.module_rows": len(ledger_slim["module_rows"]),
        "ledger.local_rows": len(ledger_slim["local_rows"]),
        "ledger.critical_server_rows": len(ledger_slim["critical_server_rows"]),
        "ledger.merged_rows": len(ledger_slim["merged_rows"]),
        "appsession_ingress.rows": len(ingress_rows),
        "unrouted_events.rows": len(unrouted_rows),
        "fragment_owner_history": len(owner_bounded),
    }
    rows_bounded = bool(bounds_log)
    sid = _streamlit_session_id()
    identity = _session_export_identity(session)
    from live_draft_stage1_s3_process_global_diag import build_latest_ingress_summaries, ledger_totals_for_session

    ledger_totals = ledger_totals_for_session(sid)
    ingress_summaries = build_latest_ingress_summaries(sid)
    gen = int(export_generation or 0)
    server_ts = float(export_generated_server_ts or time.time())
    payload: dict[str, Any] = {
        "payload_schema_rev": S3_DOM_PAYLOAD_SCHEMA_REV,
        "impl_rev": S3_SERVER_DIAG_IMPL_REV,
        "streamlit_session_id": sid,
        "export_generation": gen,
        "export_generated_server_ts": server_ts,
        "script_run_seq": identity.get("script_run_seq"),
        "diagnostic_run_id": identity.get("diagnostic_run_id"),
        "module_ledger_total_count": ledger_totals.get("module_ledger_total_count"),
        "critical_ledger_total_count": ledger_totals.get("critical_ledger_total_count"),
        "unrouted_ledger_total_count": ledger_totals.get("unrouted_ledger_total_count"),
        "latest_ingress_summaries": ingress_summaries,
        "s3_diag_binding": binding,
        "pre_declaration": pre,
        "post_registration": post,
        "ledger": ledger_slim,
        "appsession_ingress": {**(dict(ingress) if isinstance(ingress, dict) else {}), "rows": ingress_rows},
        "unrouted_events": {**(dict(unrouted) if isinstance(unrouted, dict) else {}), "rows": unrouted_rows},
        "fragment_owner_history": owner_bounded,
        "export_meta": {
            "payload_complete": True,
            "payload_truncated": False,
            "rows_bounded": rows_bounded,
            "bounds_applied": bounds_log,
            "row_counts_before_bounding": before_counts,
            "row_counts_exported": exported_counts,
            "export_generation": gen,
            "export_generated_server_ts": server_ts,
            "streamlit_session_id": sid,
            "script_run_seq": identity.get("script_run_seq"),
            "diagnostic_run_id": identity.get("diagnostic_run_id"),
            "module_ledger_total_count": ledger_totals.get("module_ledger_total_count"),
            "critical_ledger_total_count": ledger_totals.get("critical_ledger_total_count"),
            "unrouted_ledger_total_count": ledger_totals.get("unrouted_ledger_total_count"),
        },
    }
    text = json.dumps(payload, default=str)
    payload["export_meta"]["payload_json_length"] = len(text)
    return payload


def build_s3_readiness_payload(session: dict[str, Any]) -> dict[str, Any]:
    binding = dict(session.get(S3_BINDING_KEY) or {})
    post = dict(session.get("_stage1_pause_sibling_post_registration") or {})
    watch_key = str(session.get(S3_WATCH_KEY) or "")
    reg_id = str(post.get("registered_widget_id") or "")
    try:
        from live_draft_stage1_s3_oob_snapshot import oob_channel_export

        oob_channel = oob_channel_export(session)
    except ImportError:
        oob_channel = {"registered": False}
    return {
        "payload_schema_rev": S3_DOM_PAYLOAD_SCHEMA_REV,
        "impl_rev": S3_SERVER_DIAG_IMPL_REV,
        "streamlit_session_id": _streamlit_session_id(),
        "watched_widget_key": watch_key,
        "registered_widget_id": reg_id,
        "post_registration": post,
        "s3_diag_binding": binding,
        "server_wrapper_integrity_ok": binding.get("server_wrapper_integrity_ok"),
        "oob_channel": oob_channel,
    }


def serialize_s3_dom_json(payload: dict[str, Any]) -> str:
    """Serialize without mid-string truncation; re-measure length on export_meta."""
    text = json.dumps(payload, default=str)
    meta = payload.get("export_meta")
    if isinstance(meta, dict):
        meta["payload_json_length"] = len(text)
        meta["payload_complete"] = True
        meta["payload_truncated"] = False
        text = json.dumps(payload, default=str)
        meta["payload_json_length"] = len(text)
    return text


def _html_attr_json(raw_json: str) -> str:
    return raw_json.replace('"', "'")


def emit_s3_dom_ledger(st: Any, session: dict[str, Any]) -> None:
    from live_draft_stage1_s3_process_global_diag import next_s3_export_generation

    export_generation = next_s3_export_generation()
    export_generated_server_ts = time.time()
    payload = build_s3_dom_payload(
        session,
        export_generation=export_generation,
        export_generated_server_ts=export_generated_server_ts,
    )
    payload_text = serialize_s3_dom_json(payload)
    readiness = build_s3_readiness_payload(session)
    readiness_text = json.dumps(readiness, default=str)
    sid = _streamlit_session_id()
    st.markdown(
        f'<div id="{S3_READINESS_DOM_ID}" '
        f'data-impl-rev="{S3_SERVER_DIAG_IMPL_REV}" '
        f'data-streamlit-session-id="{sid}" '
        f'data-json="{_html_attr_json(readiness_text)}"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div id="{S3_LEDGER_DOM_ID}" '
        f'data-impl-rev="{S3_SERVER_DIAG_IMPL_REV}" '
        f'data-streamlit-session-id="{sid}" '
        f'data-export-generation="{export_generation}" '
        f'data-export-generated-server-ts="{export_generated_server_ts}" '
        f'data-json="{_html_attr_json(payload_text)}"></div>',
        unsafe_allow_html=True,
    )


def post_registration_server_snapshot(st: Any, user_key: str) -> dict[str, Any]:
    from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity
    from live_draft_streamlit_widget_metadata_diag import (
        get_underlying_streamlit_session_state,
        resolve_authoritative_widget_id,
        snapshot_backend_widget_state,
        snapshot_widget_metadata,
    )

    snap = snapshot_fragment_identity(phase="POST_REGISTRATION", widget_user_key=user_key)
    wid, src = resolve_authoritative_widget_id(st, user_key)
    snap["registered_widget_id"] = wid
    snap["registered_widget_id_source"] = src
    snap["user_key"] = user_key
    ss = get_underlying_streamlit_session_state(st)
    if ss and wid:
        snap["widget_metadata"] = snapshot_widget_metadata(ss, wid)
        snap["backend_widget_state"] = snapshot_backend_widget_state(ss, wid)
    return snap


def _ensure_global_sessionstate_wrappers() -> None:
    from live_draft_stage1_s3_process_global_diag import (
        append_module_event_for_underlying_sessionstate,
        mark_global_wrapper,
        resolve_sessionstate_objects,
        scan_widget_states_proto,
    )

    try:
        from streamlit.runtime.state.session_state import SessionState
    except ImportError:
        return

    if not getattr(SessionState.on_script_will_rerun, "_solo_s3_wrapped", False):
        orig_rerun = SessionState.on_script_will_rerun

        def wrapped_on_script_will_rerun(self: Any, latest_widget_states: Any) -> None:
            scan = scan_widget_states_proto(latest_widget_states)
            row = append_module_event_for_underlying_sessionstate(
                self,
                "SERVER_RECEIVE_ENTRY",
                on_script_will_rerun_executed=True,
                sibling_present=scan.get("pause_sibling_present"),
                sibling_proto=scan.get("pause_sibling_proto"),
                pause_present=scan.get("pause_present"),
                pause_proto=scan.get("pause_proto"),
                incoming_widget_count=scan.get("incoming_widget_count"),
                activated_triggers=scan.get("activated_triggers"),
            )
            try:
                from live_draft_stage1_s3_oob_snapshot import publish_oob_snapshot

                pub_sid = str((row or {}).get("streamlit_session_id") or "")[:64]
                if pub_sid:
                    publish_oob_snapshot(pub_sid, publish_source="sessionstate_receive")
            except Exception:
                pass
            return orig_rerun(self, latest_widget_states)

        wrapped_on_script_will_rerun._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.on_script_will_rerun = wrapped_on_script_will_rerun  # type: ignore[method-assign]
        mark_global_wrapper("sessionstate_on_script_will_rerun")

    if not getattr(SessionState.set_widgets_from_proto, "_solo_s3_wrapped", False):
        orig_set = SessionState.set_widgets_from_proto

        def wrapped_set_widgets_from_proto(self: Any, widget_states: Any) -> None:
            pre_scan = scan_widget_states_proto(widget_states)
            sib_id = str((pre_scan.get("pause_sibling_proto") or {}).get("id") or "")
            orig_set(self, widget_states)
            applied: dict[str, Any] = {
                "present_in_new_widget_state": False,
                "trigger_from_deserialized": False,
            }
            if sib_id:
                try:
                    applied["present_in_new_widget_state"] = sib_id in self._new_widget_state.states
                    applied["deserialized_value_repr"] = repr(self._new_widget_state.get(sib_id))[:200]
                    applied["trigger_from_deserialized"] = bool(self._new_widget_state.get(sib_id))
                except Exception:
                    pass
            pause_id = str((pre_scan.get("pause_proto") or {}).get("id") or "")
            pause_applied = {}
            if pause_id:
                try:
                    pause_applied = {
                        "pause_present_in_new_widget_state": pause_id in self._new_widget_state.states,
                        "pause_trigger_from_deserialized": bool(self._new_widget_state.get(pause_id)),
                    }
                except Exception:
                    pass
            row = append_module_event_for_underlying_sessionstate(
                self,
                "SERVER_STATE_APPLIED",
                exact_widget_id=sib_id or None,
                sibling_present=bool(pre_scan.get("pause_sibling_present")),
                pause_present=bool(pre_scan.get("pause_present")),
                **applied,
                **pause_applied,
            )
            try:
                from live_draft_stage1_s3_oob_snapshot import publish_oob_snapshot

                pub_sid = str((row or {}).get("streamlit_session_id") or "")[:64]
                if pub_sid:
                    publish_oob_snapshot(pub_sid, publish_source="sessionstate_applied")
            except Exception:
                pass

        wrapped_set_widgets_from_proto._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.set_widgets_from_proto = wrapped_set_widgets_from_proto  # type: ignore[method-assign]
        mark_global_wrapper("sessionstate_set_widgets_from_proto")


def _ensure_safe_sessionstate_wrappers() -> None:
    from live_draft_stage1_s3_process_global_diag import (
        append_module_event,
        mark_global_wrapper,
        resolve_sessionstate_objects,
        resolve_sessionstate_routing,
        scan_widget_states_proto,
        streamlit_session_id_from_ctx,
        append_unrouted_event,
    )

    try:
        from streamlit.runtime.state.safe_session_state import SafeSessionState
    except ImportError:
        return

    if getattr(SafeSessionState.on_script_will_rerun, "_solo_s3_safe_wrapped", False):
        return
    orig_safe = SafeSessionState.on_script_will_rerun

    def wrapped_safe_on_script_will_rerun(self: Any, latest_widget_states: Any) -> None:
        resolved = resolve_sessionstate_objects(self)
        scan = scan_widget_states_proto(latest_widget_states)
        underlying = resolved.get("underlying")
        wrapper_id = resolved.get("wrapper_object_id")
        underlying_id = resolved.get("underlying_object_id")
        route_obj = underlying if underlying is not None else self
        routing_sid, routing_source, provenance = resolve_sessionstate_routing(route_obj)
        ctx_sid = streamlit_session_id_from_ctx()
        payload = {
            "safe_sessionstate_object_id": wrapper_id,
            "underlying_sessionstate_object_id": underlying_id,
            "ctx_streamlit_session_id": ctx_sid,
            "routing_resolved": bool(routing_sid),
            "routing_source": routing_source,
            "pause_present": scan.get("pause_present"),
            "pause_proto": scan.get("pause_proto"),
            "pause_sibling_present": scan.get("pause_sibling_present"),
            "pause_sibling_proto": scan.get("pause_sibling_proto"),
            "incoming_widget_count": scan.get("incoming_widget_count"),
            **provenance,
        }
        if routing_sid:
            append_module_event(routing_sid, "SAFE_SESSIONSTATE_RECEIVE_ENTRY", **payload)
            try:
                from live_draft_stage1_s3_oob_snapshot import publish_oob_snapshot

                publish_oob_snapshot(routing_sid, publish_source="safe_sessionstate_receive")
            except Exception:
                pass
        else:
            append_unrouted_event(
                "SAFE_SESSIONSTATE_RECEIVE_ENTRY",
                routing_failure_reason="safe_sessionstate_sid_unmapped",
                sessionstate_object_id=wrapper_id,
                object_type="SafeSessionState",
                **payload,
            )
        return orig_safe(self, latest_widget_states)

    wrapped_safe_on_script_will_rerun._solo_s3_safe_wrapped = True  # type: ignore[attr-defined]
    SafeSessionState.on_script_will_rerun = wrapped_safe_on_script_will_rerun  # type: ignore[method-assign]
    mark_global_wrapper("safe_sessionstate_on_script_will_rerun")


def _oob_session_type_meta(session: Any, sid: str) -> dict[str, Any]:
    from live_draft_stage1_s3_oob_snapshot import _session_mapping

    mapping = _session_mapping(session)
    return {
        "streamlit_session_id": str(sid or "")[:64],
        "session_type": type(session).__name__ if session is not None else "",
        "session_is_mutable_mapping": mapping is not None,
    }


def record_oob_initialization_result(
    session: Any,
    sid: str,
    *,
    oob: dict[str, Any] | None = None,
    exc: BaseException | None = None,
    initialization_stage: str = "publish_initial_oob_snapshot",
) -> str:
    """Emit REGISTERED or INIT_FAILURE. Never raises into product UI."""
    meta = _oob_session_type_meta(session, sid)
    try:
        if exc is not None:
            append_s3_event(
                session,
                "S3_OOB_CHANNEL_INIT_FAILURE",
                exception_type=type(exc).__name__,
                exception_message=str(exc)[:400],
                initialization_stage=initialization_stage,
                registered=False,
                published=False,
                **meta,
            )
            return "S3_OOB_CHANNEL_INIT_FAILURE"
        result = dict(oob or {})
        registered = bool(result.get("registered"))
        published = bool(result.get("published"))
        token = str(result.get("diagnostic_token") or "").strip()
        path = str(result.get("static_url_path") or "").strip()
        if registered and published and token and path:
            append_s3_event(
                session,
                "S3_OOB_CHANNEL_REGISTERED",
                **{k: v for k, v in result.items() if k != "module_ledger_rows"},
            )
            return "S3_OOB_CHANNEL_REGISTERED"
        append_s3_event(
            session,
            "S3_OOB_CHANNEL_INIT_FAILURE",
            registered=registered,
            published=published,
            reason=str(result.get("reason") or "oob_init_incomplete"),
            diagnostic_token=token,
            static_url_path=path,
            initialization_stage=initialization_stage,
            **meta,
        )
        return "S3_OOB_CHANNEL_INIT_FAILURE"
    except Exception:
        return "S3_OOB_CHANNEL_INIT_FAILURE_UNRECORDED"


def initialize_oob_channel_safely(session: Any, sid: str) -> str:
    """Fail-safe OOB init. Never raises into product UI. Returns emitted phase."""
    try:
        from live_draft_stage1_s3_oob_snapshot import publish_initial_oob_snapshot

        oob = publish_initial_oob_snapshot(sid, session)
        return record_oob_initialization_result(session, sid, oob=oob)
    except Exception as exc:
        return record_oob_initialization_result(session, sid, exc=exc)


def install_s3_server_diagnostics(st: Any | None, session: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return

    from live_draft_stage1_s3_process_global_diag import (
        register_sessionstate_pair_from_wrapper,
        s3_diag_binding_snapshot,
        streamlit_session_id_from_ctx,
    )

    watch_key = str(session.get(S3_WATCH_KEY) or "")
    try:
        from live_draft_streamlit_widget_metadata_diag import install_streamlit_register_widget_probe

        install_streamlit_register_widget_probe(st, session)
    except ImportError:
        pass

    _ensure_global_sessionstate_wrappers()
    _ensure_safe_sessionstate_wrappers()

    try:
        from live_draft_stage1_scriptrunner_handoff_diag import ensure_scriptrunner_handoff_wrappers

        ensure_scriptrunner_handoff_wrappers()
    except ImportError:
        pass

    ss_wrapper = None
    try:
        from live_draft_streamlit_widget_metadata_diag import get_streamlit_session_state

        ss_wrapper = get_streamlit_session_state(st)
        sid = streamlit_session_id_from_ctx()
        if ss_wrapper and sid:
            register_sessionstate_pair_from_wrapper(ss_wrapper, sid, mapping_source="script_run_context")
    except Exception:
        ss_wrapper = None
        sid = streamlit_session_id_from_ctx()

    try:
        from live_draft_stage1_runtime_backmsg_diag import install_runtime_backmsg_probe

        install_runtime_backmsg_probe(st, session)
    except ImportError:
        pass

    try:
        from live_draft_stage1_appsession_ingress_diag import install_appsession_probes

        install_appsession_probes(st, session)
    except ImportError:
        pass

    binding = s3_diag_binding_snapshot(ss_wrapper)
    session[S3_BINDING_KEY] = dict(binding)
    append_s3_event(session, "S3_DIAG_BINDING", **binding)
    initialize_oob_channel_safely(session, sid)
    session[S3_PATCHED_KEY] = True
    if not session.get("_stage1_s3_diag_installed_once"):
        append_s3_event(session, "S3_DIAG_INSTALLED", user_key=watch_key)
        session["_stage1_s3_diag_installed_once"] = True
