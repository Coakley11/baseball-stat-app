"""Pause-sibling return-value probe — Control Center fragment only (solo diag)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

PAUSE_SIBLING_IMPL_REV = "stage1_pause_sibling_probe_v3"
PAUSE_SIBLING_PROBE_ELEMENT_ID = "solo-stage1-pause-sibling-probe"
PAUSE_SIBLING_LEDGER_DOM_ID = "solo-stage1-pause-sibling-ledger"
PAUSE_SIBLING_ENTRY_DOM_ID = "solo-stage1-pause-sibling-entry"
PAUSE_SIBLING_DECL_DOM_ID = "solo-stage1-pause-sibling-declaration"

PAUSE_SIBLING_COUNT_KEY = "_stage1_pause_sibling_count"
PAUSE_SIBLING_EVENTS_KEY = "_stage1_pause_sibling_events"
PAUSE_SIBLING_LAST_RENDER_KEY = "_stage1_pause_sibling_last_render"
PAUSE_SIBLING_PRE_DECL_KEY = "_stage1_pause_sibling_pre_declaration"
PAUSE_SIBLING_POST_REG_KEY = "_stage1_pause_sibling_post_registration"

LABEL_PAUSE_SIBLING = "Stage1 Pause-Sibling Return Probe"
MAX_EVENTS = 32


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def pause_sibling_widget_key(room_id: str) -> str:
    rid = str(room_id or "noroom").strip().upper()[:16]
    return f"stage1_pause_sibling_return_{rid}_diag"


def _full_app_run_seq(session: dict[str, Any]) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def append_pause_sibling_event(
    session: dict[str, Any],
    *,
    room_id: str,
    widget_key: str,
    returned_true: bool,
    branch_entered: bool,
    fragment_id: str = "",
    delta_path: list[Any] | None = None,
    register_widget_result_value: bool | None = None,
    st_button_returned: bool | None = None,
) -> dict[str, Any]:
    n = int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0) + 1
    session[PAUSE_SIBLING_COUNT_KEY] = n
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "room_id": str(room_id or "").strip(),
        "streamlit_session_id": _streamlit_session_id(),
        "full_app_run_seq": _full_app_run_seq(session),
        "widget_key": str(widget_key or "").strip(),
        "returned_true": bool(returned_true),
        "branch_entered": bool(branch_entered),
        "fragment_id": str(fragment_id or "")[:64],
        "delta_path": list(delta_path or [])[:24],
    }
    if register_widget_result_value is not None:
        row["register_widget_result_value"] = bool(register_widget_result_value)
    if st_button_returned is not None:
        row["st_button_returned"] = bool(st_button_returned)
    book = list(session.get(PAUSE_SIBLING_EVENTS_KEY) or [])
    book.append(dict(row))
    session[PAUSE_SIBLING_EVENTS_KEY] = book[-MAX_EVENTS:]
    session["_stage1_pause_sibling_last"] = dict(row)
    return row


def pause_sibling_export(session: dict[str, Any]) -> dict[str, Any]:
    book = list(session.get(PAUSE_SIBLING_EVENTS_KEY) or [])
    return {
        "count": int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0),
        "event_count": len(book),
        "last": dict(session.get("_stage1_pause_sibling_last") or {}),
        "rows": book[-12:],
        "last_render": dict(session.get(PAUSE_SIBLING_LAST_RENDER_KEY) or {}),
        "pre_declaration": dict(session.get(PAUSE_SIBLING_PRE_DECL_KEY) or {}),
        "post_registration": dict(session.get(PAUSE_SIBLING_POST_REG_KEY) or {}),
    }


def _emit_pause_sibling_probes(
    st: Any,
    session: dict[str, Any],
    *,
    widget_key: str,
    room_id: str,
    render_meta: dict[str, Any],
    identity_post: dict[str, Any],
) -> None:
    export = pause_sibling_export(session)
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    payload = json.dumps(export, default=str)[:12000]
    meta = identity_post.get("widget_metadata") if isinstance(identity_post.get("widget_metadata"), dict) else {}
    st.markdown(
        f'<div id="{PAUSE_SIBLING_LEDGER_DOM_ID}" '
        f'data-probe-element="{PAUSE_SIBLING_PROBE_ELEMENT_ID}" '
        f'data-count="{export.get("count")}" '
        f'data-event-count="{export.get("event_count")}" '
        f'data-last-event-id="{safe((export.get("last") or {}).get("event_id"))}" '
        f'data-streamlit-session-id="{safe(_streamlit_session_id())}" '
        f'data-full-app-run-seq="{_full_app_run_seq(session)}" '
        f'data-impl-rev="{PAUSE_SIBLING_IMPL_REV}" '
        f'data-registered-widget-id="{safe(identity_post.get("registered_widget_id"))}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="stage1-pause-sibling-control-probe" '
        f'data-probe-element="{PAUSE_SIBLING_PROBE_ELEMENT_ID}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-rendered="{1 if render_meta.get("rendered") else 0}" '
        f'data-returned-true="{1 if render_meta.get("returned_true") else 0}" '
        f'data-branch-entered="{1 if render_meta.get("branch_entered") else 0}" '
        f'data-count="{export.get("count")}" '
        f'data-thread-fragment-id="{safe(identity_post.get("thread_state_fragment_id"))}" '
        f'data-metadata-fragment-id="{safe(meta.get("fragment_id"))}" '
        f'data-post-registration-fragment-id="{safe(identity_post.get("thread_state_fragment_id"))}" '
        f'data-delta-path="{safe(json.dumps(identity_post.get("thread_state_delta_path") or []))}" '
        f'data-impl-rev="{PAUSE_SIBLING_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )
    try:
        from live_draft_stage1_s3_server_diag import emit_s3_dom_ledger

        emit_s3_dom_ledger(st, session)
    except ImportError:
        pass


def _solo_diag_evidence(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    raw = ""
    qp_flag = False
    session_latched = bool(session.get("_solo_component_diag_enabled"))
    mount_diag_present = False
    mount_diag_value: Any = None
    try:
        from live_draft_solo_component_diagnostics import (
            SOLO_DIAG_ENABLED_KEY,
            SOLO_MOUNT_DIAG_KEY,
            _qp_flag,
            _qp_get,
            solo_component_diag_enabled,
        )

        raw = _qp_get(st, "solo_component_diag") if st is not None else ""
        qp_flag = bool(st is not None and _qp_flag(st, "solo_component_diag"))
        session_latched = bool(session.get(SOLO_DIAG_ENABLED_KEY) or session_latched)
        if SOLO_MOUNT_DIAG_KEY in session:
            mount_diag_present = True
            mount_diag_value = session.get(SOLO_MOUNT_DIAG_KEY)
        final = bool(solo_component_diag_enabled(st, session))
    except ImportError:
        final = bool(_solo_diag_enabled(st, session))
    return {
        "solo_component_diag_raw": str(raw)[:32],
        "solo_component_diag_qp_flag": qp_flag,
        "session_solo_component_diag_enabled": session_latched,
        "solo_mount_diag_key_present": mount_diag_present,
        "solo_mount_diag_key_value": mount_diag_value,
        "solo_diag_enabled_final": final,
    }


def _emit_sibling_render_entry(
    st: Any,
    session: dict[str, Any],
    *,
    room_id: str,
    widget_key: str,
    evidence: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "event": "SIBLING_RENDER_ENTRY",
        "called": True,
        "ts": time.time(),
        "room_id": room_id,
        "widget_user_key": widget_key,
        "streamlit_session_id": _streamlit_session_id(),
        "full_app_run_seq": _full_app_run_seq(session),
        **evidence,
    }
    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity

        snap = snapshot_fragment_identity(phase="SIBLING_RENDER_ENTRY", widget_user_key=widget_key)
        payload["thread_state_fragment_id"] = str(snap.get("thread_state_fragment_id") or "")[:64]
    except ImportError:
        payload["thread_state_fragment_id"] = ""
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    blob = json.dumps(payload, default=str)[:12000].replace('"', "'")
    en = evidence.get("solo_diag_enabled_final")
    st.markdown(
        f'<div id="{PAUSE_SIBLING_ENTRY_DOM_ID}" '
        f'data-event="SIBLING_RENDER_ENTRY" '
        f'data-diag-enabled="{1 if en else 0}" '
        f'data-called="1" '
        f'data-room-id="{safe(room_id)}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-streamlit-session-id="{safe(_streamlit_session_id())}" '
        f'data-impl-rev="{PAUSE_SIBLING_IMPL_REV}" '
        f'data-json="{blob}"></div>',
        unsafe_allow_html=True,
    )


def _emit_sibling_declaration(
    st: Any,
    *,
    phase: str,
    room_id: str,
    widget_key: str,
    data: dict[str, Any],
) -> None:
    payload = {
        "event": phase,
        "ts": time.time(),
        "room_id": room_id,
        "widget_key": widget_key,
        **data,
    }
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    blob = json.dumps(payload, default=str)[:8000].replace('"', "'")
    reached = 1 if data.get("declaration_reached") else 0
    st.markdown(
        f'<div id="{PAUSE_SIBLING_DECL_DOM_ID}" '
        f'data-event="{safe(phase)}" '
        f'data-declaration-reached="{reached}" '
        f'data-json="{blob}"></div>',
        unsafe_allow_html=True,
    )


def render_stage1_pause_sibling_return_probe(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
) -> None:
    """Return-value button adjacent to Pause — Control Center path only."""
    room_id = str(room.get("draft_room_id") or room.get("room_id") or "").strip()
    wk = pause_sibling_widget_key(room_id)
    evidence = _solo_diag_evidence(st, session)
    _emit_sibling_render_entry(st, session, room_id=room_id, widget_key=wk, evidence=evidence)
    if not evidence.get("solo_diag_enabled_final"):
        return
    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity
    except ImportError:

        def snapshot_fragment_identity(**_kwargs: Any) -> dict[str, Any]:
            return {}

    try:
        from live_draft_stage1_s3_server_diag import S3_WATCH_KEY, install_s3_server_diagnostics
        from live_draft_streamlit_widget_metadata_diag import install_streamlit_register_widget_probe

        install_streamlit_register_widget_probe(st, session)
        session[S3_WATCH_KEY] = wk
        install_s3_server_diagnostics(st, session)
    except ImportError:
        pass

    pre_identity = snapshot_fragment_identity(phase="PRE_DECLARATION", widget_user_key=wk)
    session[PAUSE_SIBLING_PRE_DECL_KEY] = dict(pre_identity)

    count_before = int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0)
    _emit_sibling_declaration(
        st,
        phase="SIBLING_BUTTON_DECLARATION_ENTRY",
        room_id=room_id,
        widget_key=wk,
        data={"declaration_reached": True},
    )
    returned = st.button(
        LABEL_PAUSE_SIBLING,
        key=wk,
        use_container_width=True,
        disabled=False,
    )
    reg_result = session.get("_stage1_pause_sibling_register_result_value")
    try:
        from live_draft_stage1_s3_server_diag import post_registration_server_snapshot

        post_identity = post_registration_server_snapshot(st, wk)
    except ImportError:
        post_identity = snapshot_fragment_identity(phase="POST_REGISTRATION", widget_user_key=wk)
    session[PAUSE_SIBLING_POST_REG_KEY] = dict(post_identity)

    _emit_sibling_declaration(
        st,
        phase="SIBLING_BUTTON_DECLARATION_RESULT",
        room_id=room_id,
        widget_key=wk,
        data={
            "declaration_reached": True,
            "returned_value": bool(returned),
            "registered_widget_id": str(post_identity.get("registered_widget_id") or "")[:96],
            "thread_state_fragment_id": str(post_identity.get("thread_state_fragment_id") or "")[:64],
        },
    )

    branch_entered = bool(returned)
    count_after = count_before
    post_fid = str(post_identity.get("thread_state_fragment_id") or "")
    if returned:
        append_pause_sibling_event(
            session,
            room_id=room_id,
            widget_key=wk,
            returned_true=True,
            branch_entered=True,
            fragment_id=post_fid,
            delta_path=list(post_identity.get("thread_state_delta_path") or []),
            register_widget_result_value=reg_result if isinstance(reg_result, bool) else None,
            st_button_returned=bool(returned),
        )
        count_after = int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0)
    render_meta = {
        "rendered": True,
        "returned_true": bool(returned),
        "branch_entered": branch_entered,
        "count_before": count_before,
        "count_after": count_after,
        "register_widget_result_value": reg_result,
        "st_button_returned": bool(returned),
    }
    session[PAUSE_SIBLING_LAST_RENDER_KEY] = dict(render_meta)
    _emit_pause_sibling_probes(
        st,
        session,
        widget_key=wk,
        room_id=room_id,
        render_meta=render_meta,
        identity_post=post_identity,
    )
