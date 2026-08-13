"""Pause-sibling return-value probe — Control Center fragment only (solo diag)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

PAUSE_SIBLING_IMPL_REV = "stage1_pause_sibling_probe_v6"
PAUSE_SIBLING_PROBE_ELEMENT_ID = "solo-stage1-pause-sibling-probe"
PAUSE_SIBLING_LEDGER_DOM_ID = "solo-stage1-pause-sibling-ledger"
PAUSE_SIBLING_ENTRY_DOM_ID = "solo-stage1-pause-sibling-entry"
PAUSE_SIBLING_DECL_DOM_ID = "solo-stage1-pause-sibling-declaration"
PAUSE_SIBLING_DECL_PRE_DOM_ID = "solo-stage1-pause-sibling-declaration-pre"
PAUSE_SIBLING_DECL_POST_DOM_ID = "solo-stage1-pause-sibling-declaration-post"
PAUSE_SIBLING_SETUP_CHECKPOINT_DOM_ID = "solo-stage1-pause-sibling-setup-checkpoint"
PAUSE_SIBLING_SETUP_CHECKPOINTS_KEY = "_stage1_pause_sibling_setup_checkpoints"

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


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_stage1_run_id")
        or session.get("diagnostic_run_id")
        or session.get("application_diagnostic_run_id")
        or ""
    )[:64]


def _ctx_fragment_fields() -> dict[str, Any]:
    out: dict[str, Any] = {
        "current_fragment_id_ctx": "",
        "fragment_ids_this_run": [],
    }
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx is not None:
            out["current_fragment_id_ctx"] = str(getattr(ctx, "current_fragment_id", "") or "")[:80]
            out["fragment_ids_this_run"] = [str(x) for x in list(getattr(ctx, "fragment_ids_this_run", None) or [])][:32]
    except Exception:
        pass
    return out


def sibling_execution_identity(
    session: dict[str, Any],
    *,
    widget_key: str = "",
    declaration_invocation_id: str = "",
    authoritative_widget_id: str = "",
) -> dict[str, Any]:
    """Run-correlated identity fields for sibling diagnostic events."""
    seq = _full_app_run_seq(session)
    frag = _ctx_fragment_fields()
    thread_fid = ""
    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity

        snap = snapshot_fragment_identity(phase="SIBLING_IDENTITY", widget_user_key=widget_key)
        thread_fid = str(snap.get("thread_state_fragment_id") or "")[:64]
        if not authoritative_widget_id:
            meta = snap.get("widget_metadata") if isinstance(snap.get("widget_metadata"), dict) else {}
            authoritative_widget_id = str(meta.get("id") or meta.get("authoritative_widget_id") or "")[:200]
    except Exception:
        pass
    return {
        "streamlit_session_id": _streamlit_session_id(),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "script_run_seq": seq,
        "full_app_run_seq": seq,
        "fragment_id": str(frag.get("current_fragment_id_ctx") or thread_fid or "")[:80],
        "thread_state_fragment_id": thread_fid,
        "current_fragment_id_ctx": str(frag.get("current_fragment_id_ctx") or "")[:80],
        "fragment_ids_this_run": list(frag.get("fragment_ids_this_run") or []),
        "widget_key": str(widget_key or "").strip()[:160],
        "widget_user_key": str(widget_key or "").strip()[:160],
        "authoritative_widget_id": str(authoritative_widget_id or "")[:200],
        "declaration_invocation_id": str(declaration_invocation_id or "")[:64],
    }


def _append_sibling_module_event(session: dict[str, Any], phase: str, **fields: Any) -> dict[str, Any]:
    try:
        from live_draft_stage1_s3_process_global_diag import append_module_event

        return append_module_event(_streamlit_session_id(), str(phase or "")[:48], **fields)
    except ImportError:
        return {"phase": phase, **fields}


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
    declaration_invocation_id: str = "",
    authoritative_widget_id: str = "",
) -> dict[str, Any]:
    n = int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0) + 1
    session[PAUSE_SIBLING_COUNT_KEY] = n
    identity = sibling_execution_identity(
        session,
        widget_key=widget_key,
        declaration_invocation_id=declaration_invocation_id,
        authoritative_widget_id=authoritative_widget_id,
    )
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "room_id": str(room_id or "").strip(),
        **identity,
        "returned_true": bool(returned_true),
        "branch_entered": bool(branch_entered),
        "fragment_id": str(fragment_id or identity.get("fragment_id") or "")[:64],
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
    identity = sibling_execution_identity(session, widget_key=widget_key)
    payload: dict[str, Any] = {
        "event": "SIBLING_RENDER_ENTRY",
        "called": True,
        "ts": time.time(),
        "room_id": room_id,
        **identity,
        **evidence,
    }
    _append_sibling_module_event(
        session,
        "SIBLING_RENDER_ENTRY",
        room_id=room_id,
        called=True,
        **{k: v for k, v in identity.items() if k != "streamlit_session_id"},
    )
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
    session: dict[str, Any],
    *,
    phase: str,
    room_id: str,
    widget_key: str,
    data: dict[str, Any],
) -> None:
    identity = sibling_execution_identity(
        session,
        widget_key=widget_key,
        declaration_invocation_id=str(data.get("declaration_invocation_id") or ""),
        authoritative_widget_id=str(data.get("registered_widget_id") or data.get("authoritative_widget_id") or ""),
    )
    payload = {
        "event": phase,
        "ts": time.time(),
        "room_id": room_id,
        **identity,
        **data,
    }
    _append_sibling_module_event(
        session,
        str(phase or "")[:48],
        room_id=room_id,
        **{k: v for k, v in payload.items() if k not in ("event", "streamlit_session_id") and v is not None},
    )
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    blob = json.dumps(payload, default=str)[:8000].replace('"', "'")
    reached = 1 if data.get("declaration_reached") else 0
    dom_id = (
        PAUSE_SIBLING_DECL_PRE_DOM_ID
        if phase == "SIBLING_BUTTON_DECLARATION_ENTRY"
        else PAUSE_SIBLING_DECL_POST_DOM_ID
    )
    st.markdown(
        f'<div id="{dom_id}" '
        f'class="solo-stage1-pause-sibling-declaration" '
        f'data-sibling-declaration-phase="{safe(phase)}" '
        f'data-dom-id-legacy="{PAUSE_SIBLING_DECL_DOM_ID}" '
        f'data-event="{safe(phase)}" '
        f'data-declaration-reached="{reached}" '
        f'data-json="{blob}"></div>',
        unsafe_allow_html=True,
    )


def _emit_setup_checkpoint(
    st: Any,
    session: dict[str, Any],
    *,
    event: str,
    room_id: str,
    widget_key: str,
    extra: dict[str, Any] | None = None,
) -> None:
    identity = sibling_execution_identity(
        session,
        widget_key=widget_key,
        declaration_invocation_id=str((extra or {}).get("declaration_invocation_id") or ""),
        authoritative_widget_id=str((extra or {}).get("registered_widget_id") or (extra or {}).get("authoritative_widget_id") or ""),
    )
    payload: dict[str, Any] = {
        "event": str(event or "")[:80],
        "ts": time.time(),
        "room_id": str(room_id or "").strip(),
        **identity,
    }
    if extra:
        payload.update(extra)
    book = list(session.get(PAUSE_SIBLING_SETUP_CHECKPOINTS_KEY) or [])
    book.append(dict(payload))
    session[PAUSE_SIBLING_SETUP_CHECKPOINTS_KEY] = book[-32:]
    _append_sibling_module_event(
        session,
        str(event or "")[:48],
        room_id=str(room_id or "").strip(),
        **{k: v for k, v in payload.items() if k not in ("event", "streamlit_session_id", "ts") and v is not None},
    )
    try:
        print(f"SOLO_SIBLING_SETUP_CHECKPOINT {json.dumps(payload, default=str)[:4000]}", flush=True)
    except Exception:
        pass
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    blob = json.dumps(payload, default=str)[:8000].replace('"', "'")
    st.markdown(
        f'<div id="{PAUSE_SIBLING_SETUP_CHECKPOINT_DOM_ID}" '
        f'class="solo-stage1-pause-sibling-setup-checkpoint" '
        f'data-event="{safe(event)}" '
        f'data-json="{blob}"></div>',
        unsafe_allow_html=True,
    )


def emit_sibling_setup_checkpoint(
    st: Any,
    session: dict[str, Any],
    *,
    event: str,
    room_id: str,
    widget_key: str,
    extra: dict[str, Any] | None = None,
) -> None:
    _emit_setup_checkpoint(st, session, event=event, room_id=room_id, widget_key=widget_key, extra=extra)


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
    declaration_invocation_id = uuid.uuid4().hex[:16]
    session["_stage1_pause_sibling_active_declaration_invocation_id"] = declaration_invocation_id
    _emit_sibling_declaration(
        st,
        session,
        phase="SIBLING_BUTTON_DECLARATION_ENTRY",
        room_id=room_id,
        widget_key=wk,
        data={
            "declaration_reached": True,
            "declaration_invocation_id": declaration_invocation_id,
        },
    )
    returned = False
    # Legacy pre-button scalar is explicitly non-authoritative for this render.
    legacy_reg_result = session.get("_stage1_pause_sibling_register_result_value")
    post_identity: dict[str, Any] = {}
    try:
        returned = st.button(
            LABEL_PAUSE_SIBLING,
            key=wk,
            use_container_width=True,
            disabled=False,
        )
    except Exception as exc:
        _emit_setup_checkpoint(
            st,
            session,
            event="SIBLING_BUTTON_CALL_EXCEPTION",
            room_id=room_id,
            widget_key=wk,
            extra={
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)[:400],
                "declaration_invocation_id": declaration_invocation_id,
            },
        )
        raise
    # Resolve RegisterWidgetResult for THIS declaration_invocation_id (not legacy scalar).
    by_inv = dict(session.get("_stage1_pause_sibling_register_by_invocation") or {})
    current_reg = dict(by_inv.get(declaration_invocation_id) or session.get("_stage1_pause_sibling_current_register_result") or {})
    if str(current_reg.get("declaration_invocation_id") or "") != declaration_invocation_id:
        current_reg = dict(by_inv.get(declaration_invocation_id) or {})
    reg_result = current_reg.get("register_widget_result_value")
    if not isinstance(reg_result, bool):
        reg_result = None
    registered_widget_id = str(current_reg.get("metadata_id") or "")[:200]
    _emit_setup_checkpoint(
        st,
        session,
        event="SIBLING_BUTTON_CALL_RETURNED",
        room_id=room_id,
        widget_key=wk,
        extra={
            "declaration_invocation_id": declaration_invocation_id,
            "returned_value": bool(returned),
            "st_button_returned": bool(returned),
            "register_widget_result_value": reg_result,
            "register_widget_result_value_legacy": legacy_reg_result if isinstance(legacy_reg_result, bool) else None,
            "registered_widget_id": registered_widget_id,
            "authoritative_widget_id": registered_widget_id,
        },
    )
    try:
        from live_draft_stage1_s3_server_diag import post_registration_server_snapshot

        post_identity = post_registration_server_snapshot(st, wk)
    except ImportError:
        post_identity = snapshot_fragment_identity(phase="POST_REGISTRATION", widget_user_key=wk)
    except Exception as exc:
        _emit_setup_checkpoint(
            st,
            session,
            event="SIBLING_POST_REGISTRATION_EXCEPTION",
            room_id=room_id,
            widget_key=wk,
            extra={
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)[:400],
                "declaration_invocation_id": declaration_invocation_id,
            },
        )
        raise
    session[PAUSE_SIBLING_POST_REG_KEY] = dict(post_identity)
    meta = post_identity.get("widget_metadata") if isinstance(post_identity.get("widget_metadata"), dict) else {}
    if not registered_widget_id:
        registered_widget_id = str(post_identity.get("registered_widget_id") or meta.get("id") or "")[:200]
    _emit_setup_checkpoint(
        st,
        session,
        event="SIBLING_POST_REGISTRATION_RETURNED",
        room_id=room_id,
        widget_key=wk,
        extra={
            "declaration_invocation_id": declaration_invocation_id,
            "registered_widget_id": registered_widget_id[:96],
            "authoritative_widget_id": registered_widget_id[:200],
            "metadata_fragment_id": str(meta.get("fragment_id") or "")[:64],
            "thread_state_fragment_id": str(post_identity.get("thread_state_fragment_id") or "")[:64],
            "register_widget_result_value": reg_result,
            "register_widget_result_value_legacy": legacy_reg_result if isinstance(legacy_reg_result, bool) else None,
            "st_button_returned": bool(returned),
        },
    )

    _emit_sibling_declaration(
        st,
        session,
        phase="SIBLING_BUTTON_DECLARATION_RESULT",
        room_id=room_id,
        widget_key=wk,
        data={
            "declaration_reached": True,
            "declaration_invocation_id": declaration_invocation_id,
            "returned_value": bool(returned),
            "st_button_returned": bool(returned),
            "register_widget_result_value": reg_result,
            "registered_widget_id": registered_widget_id[:96],
            "authoritative_widget_id": registered_widget_id[:200],
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
            declaration_invocation_id=declaration_invocation_id,
            authoritative_widget_id=registered_widget_id,
        )
        count_after = int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0)
    render_meta = {
        "rendered": True,
        "returned_true": bool(returned),
        "branch_entered": branch_entered,
        "count_before": count_before,
        "count_after": count_after,
        "declaration_invocation_id": declaration_invocation_id,
        "register_widget_result_value": reg_result,
        "register_widget_result_value_legacy": legacy_reg_result if isinstance(legacy_reg_result, bool) else None,
        "st_button_returned": bool(returned),
        "script_run_seq": _full_app_run_seq(session),
        "diagnostic_run_id": _diagnostic_run_id(session),
    }
    session.pop("_stage1_pause_sibling_active_declaration_invocation_id", None)
    session[PAUSE_SIBLING_LAST_RENDER_KEY] = dict(render_meta)
    _emit_pause_sibling_probes(
        st,
        session,
        widget_key=wk,
        room_id=room_id,
        render_meta=render_meta,
        identity_post=post_identity,
    )
    _emit_setup_checkpoint(
        st,
        session,
        event="SIBLING_SETUP_EXPORT_COMPLETE",
        room_id=room_id,
        widget_key=wk,
        extra={"export_event_count": int(session.get(PAUSE_SIBLING_COUNT_KEY) or 0)},
    )
