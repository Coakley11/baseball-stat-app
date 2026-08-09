"""S3 server-side registration / state-apply diagnostics (solo diag, read-only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

S3_SERVER_DIAG_IMPL_REV = "stage1_s3_server_diag_v1"
S3_LEDGER_DOM_ID = "solo-stage1-s3-server-diag-ledger"
S3_SESSION_LEDGER_KEY = "_stage1_s3_server_diag_ledger"
S3_PATCHED_KEY = "_stage1_s3_server_diag_patched"
S3_WATCH_KEY = "_stage1_s3_server_watch_user_key"

_S3_LEDGER_BY_STREAMLIT_SESSION: dict[str, list[dict[str, Any]]] = {}


def is_pause_sibling_user_key(user_key: str) -> bool:
    return str(user_key or "").startswith("stage1_pause_sibling_return_") and str(user_key or "").endswith("_diag")


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def append_s3_event(session: dict[str, Any], phase: str, **fields: Any) -> dict[str, Any]:
    sid = _streamlit_session_id()
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "phase": str(phase or "")[:48],
        "streamlit_session_id": sid,
        **{k: v for k, v in fields.items() if v is not None},
    }
    book = list(session.get(S3_SESSION_LEDGER_KEY) or [])
    book.append(dict(row))
    session[S3_SESSION_LEDGER_KEY] = book[-64:]
    if sid:
        mod = list(_S3_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])
        mod.append(dict(row))
        _S3_LEDGER_BY_STREAMLIT_SESSION[sid] = mod[-64:]
    return row


def s3_ledger_export(session: dict[str, Any]) -> dict[str, Any]:
    sid = _streamlit_session_id()
    rows = list(session.get(S3_SESSION_LEDGER_KEY) or [])
    if sid and sid in _S3_LEDGER_BY_STREAMLIT_SESSION:
        merged = list(_S3_LEDGER_BY_STREAMLIT_SESSION.get(sid) or [])
        if len(merged) > len(rows):
            rows = merged
    return {"event_count": len(rows), "rows": rows[-32:], "impl_rev": S3_SERVER_DIAG_IMPL_REV}


def post_registration_server_snapshot(st: Any, user_key: str) -> dict[str, Any]:
    """Authoritative POST-declaration registration evidence."""
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


def _widget_state_row_from_proto(ws: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(ws, "id", "") or ""),
        "trigger_value": bool(getattr(ws, "trigger_value", False)),
        "bool_value": getattr(ws, "bool_value", None),
        "string_value": str(getattr(ws, "string_value", "") or "")[:120],
    }


def _find_sibling_in_proto(widget_states: Any, *, user_key: str, exact_id: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "incoming_widget_count": 0,
        "sibling_present": False,
        "matched_by": "",
        "sibling_proto": {},
    }
    try:
        widgets = list(widget_states.widgets)
    except Exception:
        return out
    out["incoming_widget_count"] = len(widgets)
    suffix = f"-{user_key}" if user_key else ""
    for ws in widgets:
        wid = str(getattr(ws, "id", "") or "")
        if exact_id and wid == exact_id:
            out["sibling_present"] = True
            out["matched_by"] = "exact_id"
            out["sibling_proto"] = _widget_state_row_from_proto(ws)
            return out
        if suffix and (wid.endswith(suffix) or suffix in wid):
            out["sibling_present"] = True
            out["matched_by"] = "user_key_suffix"
            out["sibling_proto"] = _widget_state_row_from_proto(ws)
            return out
    return out


def install_s3_server_diagnostics(st: Any | None, session: dict[str, Any]) -> None:
    if session.get(S3_PATCHED_KEY):
        return
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    try:
        from streamlit.runtime.state.session_state import SessionState
    except ImportError:
        return

    watch_key = str(session.get(S3_WATCH_KEY) or "")
    try:
        from live_draft_streamlit_widget_metadata_diag import install_streamlit_register_widget_probe

        install_streamlit_register_widget_probe(st, session)
    except ImportError:
        pass

    if not getattr(SessionState.on_script_will_rerun, "_solo_s3_wrapped", False):
        orig_rerun = SessionState.on_script_will_rerun

        def wrapped_on_script_will_rerun(self: Any, latest_widget_states: Any) -> None:
            uk = str(session.get(S3_WATCH_KEY) or watch_key or "")
            exact = str(session.get("_stage1_s3_strict_wire_widget_id") or "")
            found = _find_sibling_in_proto(latest_widget_states, user_key=uk, exact_id=exact)
            append_s3_event(
                session,
                "SERVER_RECEIVE_ENTRY",
                user_key=uk,
                on_script_will_rerun_executed=True,
                **found,
            )
            return orig_rerun(self, latest_widget_states)

        wrapped_on_script_will_rerun._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.on_script_will_rerun = wrapped_on_script_will_rerun  # type: ignore[method-assign]

    if not getattr(SessionState.set_widgets_from_proto, "_solo_s3_wrapped", False):
        orig_set = SessionState.set_widgets_from_proto

        def wrapped_set_widgets_from_proto(self: Any, widget_states: Any) -> None:
            uk = str(session.get(S3_WATCH_KEY) or watch_key or "")
            exact = str(session.get("_stage1_s3_strict_wire_widget_id") or "")
            pre_found = _find_sibling_in_proto(widget_states, user_key=uk, exact_id=exact)
            exact_use = exact or str((pre_found.get("sibling_proto") or {}).get("id") or "")
            orig_set(self, widget_states)
            try:
                from live_draft_streamlit_widget_metadata_diag import get_streamlit_session_state

                ss = get_streamlit_session_state(st)
            except Exception:
                ss = None
            applied: dict[str, Any] = {"present_in_new_widget_state": False}
            if ss and exact_use:
                try:
                    applied["present_in_new_widget_state"] = exact_use in ss._new_widget_state.states
                    applied["deserialized_value_repr"] = repr(ss._new_widget_state.get(exact_use))[:200]
                    applied["trigger_from_deserialized"] = bool(ss._new_widget_state.get(exact_use))
                except Exception:
                    pass
            append_s3_event(
                session,
                "SERVER_STATE_APPLIED",
                user_key=uk,
                exact_widget_id=exact_use,
                sibling_present=bool(pre_found.get("sibling_present")),
                **applied,
            )

        wrapped_set_widgets_from_proto._solo_s3_wrapped = True  # type: ignore[attr-defined]
        SessionState.set_widgets_from_proto = wrapped_set_widgets_from_proto  # type: ignore[method-assign]

    session[S3_PATCHED_KEY] = True
    append_s3_event(session, "S3_DIAG_INSTALLED", user_key=watch_key)


def emit_s3_dom_ledger(st: Any, session: dict[str, Any]) -> None:
    export = s3_ledger_export(session)
    post = session.get("_stage1_pause_sibling_post_registration") or {}
    pre = session.get("_stage1_pause_sibling_pre_declaration") or {}
    payload = json.dumps(
        {"ledger": export, "pre_declaration": pre, "post_registration": post},
        default=str,
    )[:24000]
    safe = payload.replace('"', "'")
    st.markdown(
        f'<div id="{S3_LEDGER_DOM_ID}" '
        f'data-impl-rev="{S3_SERVER_DIAG_IMPL_REV}" '
        f'data-streamlit-session-id="{_streamlit_session_id()}" '
        f'data-json="{safe}"></div>',
        unsafe_allow_html=True,
    )
