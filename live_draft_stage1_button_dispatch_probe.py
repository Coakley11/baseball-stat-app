"""Stage1 button dispatch isolation — return-value vs on_click (solo diag only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import streamlit as st

DISPATCH_IMPL_REV = "stage1_button_dispatch_probe_v1"
DISPATCH_PROBE_ELEMENT_ID = "solo-stage1-button-dispatch-probe"
DISPATCH_LEDGER_DOM_ID = "solo-stage1-button-dispatch-ledger"
DISPATCH_ROOM_SESSION_KEY = "_stage1_button_dispatch_room_id"

DISPATCH_EVENTS_KEY = "_stage1_button_dispatch_events"
DISPATCH_R0_LAST_RENDER_KEY = "_stage1_dispatch_r0_last_render"

COUNT_KEY_BY_MODE = {
    "R0": "_stage1_dispatch_r0_count",
    "O0": "_stage1_dispatch_o0_count",
    "O1": "_stage1_dispatch_o1_count",
    "O2": "_stage1_dispatch_o2_count",
}

SOURCE_BY_MODE = {
    "R0": "dispatch_r0",
    "O0": "dispatch_o0",
    "O1": "dispatch_o1",
    "O2": "dispatch_o2",
}

MODE_R0 = "R0"
MODE_O0 = "O0"
MODE_O1 = "O1"
MODE_O2 = "O2"

LABEL_R0 = "Stage1 Return-Value Probe"
LABEL_O0 = "Stage1 OnClick Direct Probe"
LABEL_O1 = "Stage1 OnClick Args Probe"
LABEL_O2 = "Stage1 OnClick Closure Probe"

MAX_DISPATCH_EVENTS = 64


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def dispatch_widget_key(mode: str, room_id: str) -> str:
    rid = str(room_id or "noroom").strip().upper()[:16]
    return f"stage1_button_dispatch_{str(mode or '').lower()}_{rid}_diag"


def _full_app_run_seq(session: Any) -> int:
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


def _count(session: dict[str, Any], mode: str) -> int:
    key = COUNT_KEY_BY_MODE.get(str(mode or "").strip().upper())
    if not key:
        return 0
    try:
        return int(session.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _increment_count(session: dict[str, Any], mode: str) -> int:
    mode_u = str(mode or "").strip().upper()
    key = COUNT_KEY_BY_MODE.get(mode_u)
    if not key:
        return 0
    n = _count(session, mode_u) + 1
    session[key] = n
    return n


def append_button_dispatch_event(
    session: dict[str, Any],
    *,
    mode: str,
    widget_key: str,
    room_id: str,
    dispatch_kind: str,
    callback_present: bool,
    callback_callable_name: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dedicated dispatch ledger — never touches recommendation fragment callback book."""
    mode_u = str(mode or "").strip().upper()
    n = _increment_count(session, mode_u)
    row: dict[str, Any] = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "mode": mode_u,
        "source": SOURCE_BY_MODE.get(mode_u, f"dispatch_{mode_u.lower()}"),
        "dispatch_kind": str(dispatch_kind or "")[:32],
        "count_after": n,
        "widget_key": str(widget_key or "").strip(),
        "room_id": str(room_id or "").strip(),
        "full_app_run_seq": _full_app_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "callback_present": bool(callback_present),
        "callback_callable_name": str(callback_callable_name or "")[:80],
    }
    if extra:
        row.update({k: v for k, v in extra.items() if k not in row})
    book = list(session.get(DISPATCH_EVENTS_KEY) or [])
    book.append(dict(row))
    session[DISPATCH_EVENTS_KEY] = book[-MAX_DISPATCH_EVENTS:]
    session["_stage1_button_dispatch_last"] = dict(row)
    return row


def dispatch_events_export(session: dict[str, Any]) -> dict[str, Any]:
    book = list(session.get(DISPATCH_EVENTS_KEY) or [])
    last = dict(session.get("_stage1_button_dispatch_last") or {})
    return {
        "event_count": len(book),
        "last": last,
        "rows": book[-16:],
        "r0_count": _count(session, MODE_R0),
        "o0_count": _count(session, MODE_O0),
        "o1_count": _count(session, MODE_O1),
        "o2_count": _count(session, MODE_O2),
        "r0_last_render": dict(session.get(DISPATCH_R0_LAST_RENDER_KEY) or {}),
    }


def on_stage1_direct_callback_probe() -> None:
    session = st.session_state
    room_id = str(session.get(DISPATCH_ROOM_SESSION_KEY) or "")
    wk = dispatch_widget_key(MODE_O0, room_id)
    append_button_dispatch_event(
        session,
        mode=MODE_O0,
        widget_key=wk,
        room_id=room_id,
        dispatch_kind="on_click_direct",
        callback_present=True,
        callback_callable_name="on_stage1_direct_callback_probe",
    )


def on_stage1_args_callback_probe(control_id: str, room_id: str) -> None:
    session = st.session_state
    wk = dispatch_widget_key(MODE_O1, room_id)
    append_button_dispatch_event(
        session,
        mode=MODE_O1,
        widget_key=wk,
        room_id=str(room_id or ""),
        dispatch_kind="on_click_args",
        callback_present=True,
        callback_callable_name="on_stage1_args_callback_probe",
        extra={"control_id": str(control_id or "")[:16]},
    )


def _emit_per_control_probe(
    *,
    mode: str,
    label: str,
    widget_key: str,
    room_id: str,
    callback_present: bool,
    callback_callable_name: str,
    identity: dict[str, Any],
    r0_meta: dict[str, Any] | None = None,
) -> None:
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    meta = identity.get("widget_metadata") if isinstance(identity.get("widget_metadata"), dict) else {}
    r0 = r0_meta or {}
    st.markdown(
        f'<div class="stage1-button-dispatch-control-probe" '
        f'data-probe-element="{DISPATCH_PROBE_ELEMENT_ID}" '
        f'data-mode="{safe(mode)}" '
        f'data-label="{safe(label)}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-room-id="{safe(room_id)}" '
        f'data-callback-present="{1 if callback_present else 0}" '
        f'data-callback-callable-name="{safe(callback_callable_name)}" '
        f'data-thread-fragment-id="{safe(identity.get("thread_state_fragment_id"))}" '
        f'data-metadata-fragment-id="{safe(meta.get("fragment_id"))}" '
        f'data-delta-path="{safe(json.dumps(identity.get("thread_state_delta_path") or []))}" '
        f'data-r0-rendered="{1 if r0.get("rendered") else 0}" '
        f'data-r0-returned-true="{1 if r0.get("returned_true") else 0}" '
        f'data-r0-branch-entered="{1 if r0.get("branch_entered") else 0}" '
        f'data-r0-count-before="{safe(r0.get("count_before"))}" '
        f'data-r0-count-after="{safe(r0.get("count_after"))}" '
        f'data-impl-rev="{DISPATCH_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )


def _emit_aggregate_dispatch_probe(st: Any, session: dict[str, Any]) -> None:
    export = dispatch_events_export(session)
    safe = lambda s: str(s or "").replace('"', "'")[:200]
    last = dict(export.get("last") or {})
    payload = json.dumps(export, default=str)[:16000]
    st.markdown(
        f'<div id="{DISPATCH_LEDGER_DOM_ID}" '
        f'data-probe-element="{DISPATCH_PROBE_ELEMENT_ID}" '
        f'data-r0-count="{export.get("r0_count")}" '
        f'data-o0-count="{export.get("o0_count")}" '
        f'data-o1-count="{export.get("o1_count")}" '
        f'data-o2-count="{export.get("o2_count")}" '
        f'data-event-count="{export.get("event_count")}" '
        f'data-last-source="{safe(last.get("source"))}" '
        f'data-last-mode="{safe(last.get("mode"))}" '
        f'data-last-event-id="{safe(last.get("event_id"))}" '
        f'data-full-app-run-seq="{_full_app_run_seq(session)}" '
        f'data-streamlit-session-id="{safe(_streamlit_session_id())}" '
        f'data-impl-rev="{DISPATCH_IMPL_REV}" '
        f'data-json="{payload.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def render_stage1_button_dispatch_probe(st: Any, session: dict[str, Any], room_id: str) -> None:
    """Four buttons in one container — return-value vs on_click modes."""
    if not _solo_diag_enabled(st, session):
        return
    rid = str(room_id or "").strip()
    session[DISPATCH_ROOM_SESSION_KEY] = rid
    try:
        st.session_state[DISPATCH_ROOM_SESSION_KEY] = rid
    except Exception:
        pass

    st.caption("Stage1 button dispatch probe (R0/O0/O1/O2) — dedicated counters; no queue mutation.")

    try:
        from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity
    except ImportError:

        def snapshot_fragment_identity(**_kwargs: Any) -> dict[str, Any]:
            return {}

    with st.container():
        # R0 — return-value branch (Pause analogue)
        wk_r0 = dispatch_widget_key(MODE_R0, rid)
        identity_r0 = snapshot_fragment_identity(phase="render", widget_user_key=wk_r0)
        count_before = _count(session, MODE_R0)
        returned = st.button(LABEL_R0, key=wk_r0, use_container_width=True)
        branch_entered = bool(returned)
        count_after = count_before
        if returned:
            append_button_dispatch_event(
                session,
                mode=MODE_R0,
                widget_key=wk_r0,
                room_id=rid,
                dispatch_kind="return_value",
                callback_present=False,
                callback_callable_name="",
                extra={"returned_true": True, "branch_entered": True},
            )
            count_after = _count(session, MODE_R0)
        r0_meta = {
            "rendered": True,
            "returned_true": bool(returned),
            "branch_entered": branch_entered,
            "count_before": count_before,
            "count_after": count_after,
        }
        session[DISPATCH_R0_LAST_RENDER_KEY] = dict(r0_meta)
        _emit_per_control_probe(
            mode=MODE_R0,
            label=LABEL_R0,
            widget_key=wk_r0,
            room_id=rid,
            callback_present=False,
            callback_callable_name="",
            identity=identity_r0,
            r0_meta=r0_meta,
        )

        # O0 — module-level on_click, no args
        wk_o0 = dispatch_widget_key(MODE_O0, rid)
        identity_o0 = snapshot_fragment_identity(phase="render", widget_user_key=wk_o0)
        st.button(
            LABEL_O0,
            key=wk_o0,
            use_container_width=True,
            on_click=on_stage1_direct_callback_probe,
        )
        _emit_per_control_probe(
            mode=MODE_O0,
            label=LABEL_O0,
            widget_key=wk_o0,
            room_id=rid,
            callback_present=True,
            callback_callable_name="on_stage1_direct_callback_probe",
            identity=identity_o0,
        )

        # O1 — module-level on_click with primitive args
        wk_o1 = dispatch_widget_key(MODE_O1, rid)
        identity_o1 = snapshot_fragment_identity(phase="render", widget_user_key=wk_o1)
        st.button(
            LABEL_O1,
            key=wk_o1,
            use_container_width=True,
            on_click=on_stage1_args_callback_probe,
            args=(MODE_O1, rid),
        )
        _emit_per_control_probe(
            mode=MODE_O1,
            label=LABEL_O1,
            widget_key=wk_o1,
            room_id=rid,
            callback_present=True,
            callback_callable_name="on_stage1_args_callback_probe",
            identity=identity_o1,
        )

        # O2 — nested closure on_click (C3 pattern)
        wk_o2 = dispatch_widget_key(MODE_O2, rid)
        identity_o2 = snapshot_fragment_identity(phase="render", widget_user_key=wk_o2)

        def _closure_click() -> None:
            append_button_dispatch_event(
                st.session_state,
                mode=MODE_O2,
                widget_key=wk_o2,
                room_id=rid,
                dispatch_kind="on_click_closure",
                callback_present=True,
                callback_callable_name="_closure_click",
            )

        st.button(LABEL_O2, key=wk_o2, use_container_width=True, on_click=_closure_click)
        _emit_per_control_probe(
            mode=MODE_O2,
            label=LABEL_O2,
            widget_key=wk_o2,
            room_id=rid,
            callback_present=True,
            callback_callable_name="_closure_click",
            identity=identity_o2,
        )

    _emit_aggregate_dispatch_probe(st, session)
