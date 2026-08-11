"""AppSession BackMsg / request_rerun ingress (process-global, keyed by self.id)."""

from __future__ import annotations

from typing import Any

APPSESSION_INGRESS_IMPL_REV = "stage1_appsession_ingress_diag_v4"
APPSESSION_PATCHED_KEY = "_stage1_appsession_ingress_patched"


def _appsession_streamlit_session_id(app_session: Any) -> str:
    return str(getattr(app_session, "id", "") or "")[:64]


def _fragment_storage_snapshot(fragment_storage: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"stored_fragment_ids": []}
    if fragment_storage is None:
        return out
    try:
        if hasattr(fragment_storage, "order_fragment_ids"):
            out["stored_fragment_ids"] = [str(x) for x in list(fragment_storage.order_fragment_ids())[:32]]
    except Exception:
        pass
    return out


def _record_backmsg(app_session: Any, msg: Any) -> None:
    from live_draft_stage1_s3_process_global_diag import (
        append_module_event,
        build_routing_provenance,
        register_sessionstate_from_appsession_owner,
        scan_widget_states_proto,
        streamlit_session_id_from_ctx,
    )

    sid = _appsession_streamlit_session_id(app_session)
    if not sid:
        return
    owner = register_sessionstate_from_appsession_owner(app_session)
    ctx_sid = streamlit_session_id_from_ctx()
    provenance = build_routing_provenance(
        routing_sid=sid,
        routing_source="appsession_self_id",
        lookup_object_id=owner.get("underlying_object_id"),
        ctx_sid=ctx_sid,
        appsession_sid=sid,
    )
    try:
        msg_type = msg.WhichOneof("type")
    except Exception:
        return
    fields: dict[str, Any] = {
        "appsession_id": sid,
        "backmsg_type": str(msg_type or ""),
        "rerun_script": msg_type == "rerun_script",
        **provenance,
        "appsession_owner_registered": bool(owner.get("registered")),
        "mapping_source": owner.get("mapping_source") or "appsession_owner",
    }
    if msg_type == "rerun_script":
        try:
            cs = msg.rerun_script
            fields["wire_rerun_target_fragment_id"] = str(getattr(cs, "fragment_id", "") or "")
            fields["page_script_hash"] = str(getattr(cs, "page_script_hash", "") or "")[:64]
            if cs.HasField("widget_states"):
                scan = scan_widget_states_proto(cs.widget_states)
                fields.update(
                    {
                        "incoming_widget_count": scan.get("incoming_widget_count"),
                        "activated_triggers": scan.get("activated_triggers"),
                        "pause_sibling_present": scan.get("pause_sibling_present"),
                        "pause_sibling_proto": scan.get("pause_sibling_proto"),
                        "pause_present": scan.get("pause_present"),
                        "pause_proto": scan.get("pause_proto"),
                    }
                )
        except Exception:
            pass
    append_module_event(sid, "APPSESSION_BACKMSG_ENTRY", **fields)


def _record_request_rerun(app_session: Any, client_state: Any | None) -> None:
    from live_draft_stage1_s3_process_global_diag import (
        append_module_event,
        build_routing_provenance,
        register_sessionstate_from_appsession_owner,
        scan_widget_states_proto,
        streamlit_session_id_from_ctx,
    )

    sid = _appsession_streamlit_session_id(app_session)
    if not sid:
        return
    owner = register_sessionstate_from_appsession_owner(app_session)
    ctx_sid = streamlit_session_id_from_ctx()
    provenance = build_routing_provenance(
        routing_sid=sid,
        routing_source="appsession_self_id",
        lookup_object_id=owner.get("underlying_object_id"),
        ctx_sid=ctx_sid,
        appsession_sid=sid,
    )
    frag_id = ""
    page_hash = ""
    target_exists = False
    would_fail = False
    storage_ids: list[str] = []
    scan: dict[str, Any] = {}
    if client_state is not None:
        try:
            frag_id = str(getattr(client_state, "fragment_id", "") or "")
            page_hash = str(getattr(client_state, "page_script_hash", "") or "")[:64]
        except Exception:
            pass
        try:
            if client_state.HasField("widget_states"):
                scan = scan_widget_states_proto(client_state.widget_states)
        except Exception:
            pass
        try:
            fs = getattr(app_session, "_fragment_storage", None)
            storage_ids = _fragment_storage_snapshot(fs).get("stored_fragment_ids") or []
            if frag_id and fs is not None and hasattr(fs, "contains"):
                target_exists = bool(fs.contains(frag_id))
                would_fail = bool(frag_id) and not fs.contains(frag_id)
        except Exception:
            pass
    append_module_event(
        sid,
        "APPSESSION_REQUEST_RERUN_ENTRY",
        appsession_id=sid,
        client_state_fragment_id=frag_id,
        page_script_hash=page_hash,
        target_fragment_exists=target_exists,
        would_fail_streamlit_fragment_storage_guard=would_fail,
        fragment_storage_ids=storage_ids,
        incoming_widget_count=scan.get("incoming_widget_count"),
        pause_sibling_present=scan.get("pause_sibling_present"),
        pause_sibling_proto=scan.get("pause_sibling_proto"),
        pause_present=scan.get("pause_present"),
        pause_proto=scan.get("pause_proto"),
        activated_triggers=scan.get("activated_triggers"),
        **provenance,
        appsession_owner_registered=bool(owner.get("registered")),
        mapping_source=owner.get("mapping_source") or "appsession_owner",
    )


def install_appsession_probes(st: Any | None, session: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    try:
        from streamlit.runtime.app_session import AppSession
    except ImportError:
        return

    from live_draft_stage1_s3_process_global_diag import mark_global_wrapper

    if not getattr(AppSession.handle_backmsg, "_solo_appsession_backmsg_wrapped", False):
        orig_backmsg = AppSession.handle_backmsg

        def wrapped_handle_backmsg(self: Any, msg: Any) -> Any:
            try:
                _record_backmsg(self, msg)
            except Exception:
                pass
            return orig_backmsg(self, msg)

        wrapped_handle_backmsg._solo_appsession_backmsg_wrapped = True  # type: ignore[attr-defined]
        AppSession.handle_backmsg = wrapped_handle_backmsg  # type: ignore[method-assign]
        mark_global_wrapper("appsession_handle_backmsg")

    if not getattr(AppSession.request_rerun, "_solo_appsession_rerun_wrapped", False):
        orig_rerun = AppSession.request_rerun

        def wrapped_request_rerun(self: Any, client_state: Any | None = None) -> Any:
            try:
                _record_request_rerun(self, client_state)
            except Exception:
                pass
            return orig_rerun(self, client_state)

        wrapped_request_rerun._solo_appsession_rerun_wrapped = True  # type: ignore[attr-defined]
        AppSession.request_rerun = wrapped_request_rerun  # type: ignore[method-assign]
        mark_global_wrapper("appsession_request_rerun")

    session[APPSESSION_PATCHED_KEY] = True


def appsession_ingress_export(session: dict[str, Any] | None = None) -> dict[str, Any]:
    from live_draft_stage1_s3_process_global_diag import critical_ledger_rows, streamlit_session_id_from_ctx

    sid = streamlit_session_id_from_ctx()
    critical = critical_ledger_rows(sid)
    rows = [r for r in critical if str(r.get("phase") or "").startswith("APPSESSION_")]
    return {
        "streamlit_session_id": sid,
        "event_count": len(rows),
        "rows": rows,
        "source": "critical_ledger",
        "impl_rev": APPSESSION_INGRESS_IMPL_REV,
    }
