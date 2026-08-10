"""S3 server-side registration / state-apply diagnostics (solo diag, read-only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

S3_SERVER_DIAG_IMPL_REV = "stage1_s3_server_diag_v3"
S3_LEDGER_DOM_ID = "solo-stage1-s3-server-diag-ledger"
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
    from live_draft_stage1_s3_process_global_diag import append_module_event, streamlit_session_id_from_ctx

    sid = streamlit_session_id_from_ctx()
    extra = dict(fields)
    extra.pop("streamlit_session_id", None)
    row = append_module_event(sid, phase, **extra)
    if isinstance(session, dict) and sid:
        book = list(session.get(S3_SESSION_LEDGER_KEY) or [])
        book.append(dict(row))
        session[S3_SESSION_LEDGER_KEY] = book[-64:]
    return row


def s3_ledger_export(session: dict[str, Any] | None = None) -> dict[str, Any]:
    from live_draft_stage1_s3_process_global_diag import module_ledger_export_for_current_ctx

    exp = module_ledger_export_for_current_ctx()
    rows = list(exp.get("rows") or [])
    if isinstance(session, dict):
        local = list(session.get(S3_SESSION_LEDGER_KEY) or [])
        if len(local) > len(rows):
            rows = local
    return {"event_count": len(rows), "rows": rows[-48:], "impl_rev": S3_SERVER_DIAG_IMPL_REV}


def post_registration_server_snapshot(st: Any, user_key: str) -> dict[str, Any]:
    from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity
    from live_draft_streamlit_widget_metadata_diag import (
        get_streamlit_session_state,
        resolve_authoritative_widget_id,
        snapshot_backend_widget_state,
        snapshot_widget_metadata,
    )

    snap = snapshot_fragment_identity(phase="POST_REGISTRATION", widget_user_key=user_key)
    wid, src = resolve_authoritative_widget_id(st, user_key)
    snap["registered_widget_id"] = wid
    snap["registered_widget_id_source"] = src
    snap["user_key"] = user_key
    ss = get_streamlit_session_state(st)
    if ss and wid:
        snap["widget_metadata"] = snapshot_widget_metadata(ss, wid)
        snap["backend_widget_state"] = snapshot_backend_widget_state(ss, wid)
    return snap


def _ensure_global_sessionstate_wrappers() -> None:
    from live_draft_stage1_s3_process_global_diag import (
        append_module_event,
        mark_global_wrapper,
        resolve_sessionstate_streamlit_session_id,
        scan_widget_states_proto,
    )

    try:
        from streamlit.runtime.state.session_state import SessionState
    except ImportError:
        return

    if not getattr(SessionState.on_script_will_rerun, "_solo_s3_wrapped", False):
        orig_rerun = SessionState.on_script_will_rerun

        def wrapped_on_script_will_rerun(self: Any, latest_widget_states: Any) -> None:
            sid = resolve_sessionstate_streamlit_session_id(self) or ""
            scan = scan_widget_states_proto(latest_widget_states)
            append_module_event(
                sid,
                "SERVER_RECEIVE_ENTRY",
                on_script_will_rerun_executed=True,
                sibling_present=scan.get("pause_sibling_present"),
                sibling_proto=scan.get("pause_sibling_proto"),
                pause_present=scan.get("pause_present"),
                pause_proto=scan.get("pause_proto"),
                incoming_widget_count=scan.get("incoming_widget_count"),
                activated_triggers=scan.get("activated_triggers"),
            )
            return orig_rerun(self, latest_widget_states)

        wrapped_on_script_will_rerun._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.on_script_will_rerun = wrapped_on_script_will_rerun  # type: ignore[method-assign]
        mark_global_wrapper("sessionstate_on_script_will_rerun")

    if not getattr(SessionState.set_widgets_from_proto, "_solo_s3_wrapped", False):
        orig_set = SessionState.set_widgets_from_proto

        def wrapped_set_widgets_from_proto(self: Any, widget_states: Any) -> None:
            sid = resolve_sessionstate_streamlit_session_id(self) or ""
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
            append_module_event(
                sid,
                "SERVER_STATE_APPLIED",
                exact_widget_id=sib_id or None,
                sibling_present=bool(pre_scan.get("pause_sibling_present")),
                pause_present=bool(pre_scan.get("pause_present")),
                **applied,
                **pause_applied,
            )

        wrapped_set_widgets_from_proto._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.set_widgets_from_proto = wrapped_set_widgets_from_proto  # type: ignore[method-assign]
        mark_global_wrapper("sessionstate_set_widgets_from_proto")


def install_s3_server_diagnostics(st: Any | None, session: dict[str, Any]) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return

    from live_draft_stage1_s3_process_global_diag import (
        register_sessionstate_instance,
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

    try:
        from live_draft_streamlit_widget_metadata_diag import get_streamlit_session_state

        ss = get_streamlit_session_state(st)
        sid = streamlit_session_id_from_ctx()
        if ss and sid:
            register_sessionstate_instance(ss, sid)
    except Exception:
        ss = None
        sid = streamlit_session_id_from_ctx()

    try:
        from live_draft_stage1_appsession_ingress_diag import install_appsession_probes

        install_appsession_probes(st, session)
    except ImportError:
        pass

    binding = s3_diag_binding_snapshot(ss)
    session[S3_BINDING_KEY] = dict(binding)
    append_s3_event(session, "S3_DIAG_BINDING", **binding)
    session[S3_PATCHED_KEY] = True
    if not session.get("_stage1_s3_diag_installed_once"):
        append_s3_event(session, "S3_DIAG_INSTALLED", user_key=watch_key)
        session["_stage1_s3_diag_installed_once"] = True


def emit_s3_dom_ledger(st: Any, session: dict[str, Any]) -> None:
    export = s3_ledger_export(session)
    try:
        from live_draft_stage1_appsession_ingress_diag import appsession_ingress_export

        ingress = appsession_ingress_export(session)
    except ImportError:
        ingress = {"rows": []}
    try:
        from live_draft_cloud_diagnostics import FRAGMENT_OWNER_HISTORY_KEY

        owner_hist = list(session.get(FRAGMENT_OWNER_HISTORY_KEY) or [])[-16:]
    except ImportError:
        owner_hist = []
    binding = dict(session.get(S3_BINDING_KEY) or {})
    post = session.get("_stage1_pause_sibling_post_registration") or {}
    pre = session.get("_stage1_pause_sibling_pre_declaration") or {}
    payload = json.dumps(
        {
            "ledger": export,
            "appsession_ingress": ingress,
            "s3_diag_binding": binding,
            "fragment_owner_history": owner_hist,
            "pre_declaration": pre,
            "post_registration": post,
        },
        default=str,
    )[:36000]
    safe = payload.replace('"', "'")
    st.markdown(
        f'<div id="{S3_LEDGER_DOM_ID}" '
        f'data-impl-rev="{S3_SERVER_DIAG_IMPL_REV}" '
        f'data-streamlit-session-id="{_streamlit_session_id()}" '
        f'data-json="{safe}"></div>',
        unsafe_allow_html=True,
    )
