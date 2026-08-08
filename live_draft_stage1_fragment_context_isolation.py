"""Stage1 fragment context isolation — C0–C3 + top-level S0 A/B (solo diag only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import streamlit as st

from live_draft_stage1_fragment_identity_runtime import snapshot_fragment_identity

CONTEXT_IMPL_REV = "stage1_fragment_context_isolation_v1"
CONTEXT_PROBE_ELEMENT_ID = "solo-stage1-fragment-context-probe"
CONTEXT_ROOM_SESSION_KEY = "_stage1_fragment_context_room_id"
CONTEXT_EXPANDER_TITLE = "Stage1 fragment context isolation (diag)"

CONTEXT_C0 = "C0"
CONTEXT_C1 = "C1"
CONTEXT_C2 = "C2"
CONTEXT_C3 = "C3"

LABEL_C0 = "Stage1 Top-Level Fragment Probe"
LABEL_C1 = "Stage1 Expander Fragment Probe"
LABEL_C2 = "Stage1 Expander Normal Button Probe"
LABEL_C3 = "Stage1 Top-Level Normal Button Probe"

SOURCE_BY_CONTEXT = {
    CONTEXT_C0: "fragment_context_c0",
    CONTEXT_C1: "fragment_context_c1",
    CONTEXT_C2: "fragment_context_c2",
    CONTEXT_C3: "fragment_context_c3",
}


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def context_widget_key(context_id: str, room_id: str) -> str:
    rid = str(room_id or "noroom").strip().upper()[:16]
    return f"stage1_fragment_context_{context_id.lower()}_{rid}_diag"


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


def on_stage1_context_probe_click(
    session: Any,
    *,
    context_id: str,
    widget_key: str,
    mount_kind: str,
    is_fragment: bool,
) -> None:
    """Single trivial callback for all context probes."""
    from live_draft_rec_fragment_exec_diag import append_fragment_callback_ledger

    cid = str(context_id or "").strip().upper()[:3]
    identity = snapshot_fragment_identity(phase="callback", widget_user_key=widget_key)
    row = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "callback_id": "on_stage1_context_probe_click",
        "callback_entered": True,
        "source": SOURCE_BY_CONTEXT.get(cid, f"fragment_context_{cid.lower()}"),
        "context_id": cid,
        "mount_kind": str(mount_kind or "")[:32],
        "is_fragment_surface": bool(is_fragment),
        "widget_key": str(widget_key or "").strip(),
        "full_app_run_seq": _full_app_run_seq(session),
        "streamlit_session_id": _streamlit_session_id(),
        "fragment_identity": identity,
    }
    append_fragment_callback_ledger(session, row)


def _emit_context_dom_probe(
    *,
    context_id: str,
    mount_kind: str,
    is_fragment: bool,
    label: str,
    widget_key: str,
    identity: dict[str, Any],
) -> None:
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    storage = identity.get("fragment_storage") if isinstance(identity.get("fragment_storage"), dict) else {}
    in_storage = identity.get("render_fragment_in_storage")
    in_storage_attr = "1" if in_storage is True else "0" if in_storage is False else ""
    meta = identity.get("widget_metadata") if isinstance(identity.get("widget_metadata"), dict) else {}
    owner = identity.get("widget_owner_fragment_current")
    owner_attr = "1" if owner is True else "0" if owner is False else ""
    st.markdown(
        f'<div class="stage1-fragment-context-probe" data-probe-element="{CONTEXT_PROBE_ELEMENT_ID}" '
        f'data-context-id="{safe(context_id)}" '
        f'data-mount-kind="{safe(mount_kind)}" '
        f'data-is-fragment="{1 if is_fragment else 0}" '
        f'data-label="{safe(label)}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-thread-fragment-id="{safe(identity.get("thread_state_fragment_id"))}" '
        f'data-metadata-fragment-id="{safe(meta.get("fragment_id"))}" '
        f'data-widget-owner-fragment-current="{owner_attr}" '
        f'data-ownership-subcode="{safe(identity.get("ownership_subcode"))}" '
        f'data-fragment-ids-this-run="{safe(json.dumps(identity.get("fragment_ids_this_run") or []))}" '
        f'data-delta-path="{safe(json.dumps(identity.get("thread_state_delta_path") or []))}" '
        f'data-render-fragment-in-storage="{in_storage_attr}" '
        f'data-stored-fragment-id-count="{len(storage.get("stored_fragment_ids") or [])}" '
        f'data-impl-rev="{CONTEXT_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )


def _render_context_button(*, context_id: str, label: str, mount_kind: str, is_fragment: bool) -> None:
    session = st.session_state
    room_id = str(session.get(CONTEXT_ROOM_SESSION_KEY) or "")
    wk = context_widget_key(context_id, room_id)
    identity = snapshot_fragment_identity(phase="render", widget_user_key=wk)

    def _click() -> None:
        on_stage1_context_probe_click(
            st.session_state,
            context_id=context_id,
            widget_key=wk,
            mount_kind=mount_kind,
            is_fragment=is_fragment,
        )

    st.button(label, key=wk, use_container_width=True, on_click=_click)
    _emit_context_dom_probe(
        context_id=context_id,
        mount_kind=mount_kind,
        is_fragment=is_fragment,
        label=label,
        widget_key=wk,
        identity=identity,
    )


@st.fragment
def stage1_context_probe_fragment(context_id: str, label: str, mount_kind: str) -> None:
    _render_context_button(context_id=context_id, label=label, mount_kind=mount_kind, is_fragment=True)


def render_stage1_fragment_context_isolation(st: Any, session: dict[str, Any], room_id: str) -> None:
    """Mount C0/C3 top-level; C1/C2 in expander; matrix S0 duplicate top-level."""
    if not _solo_diag_enabled(st, session):
        return
    rid = str(room_id or "").strip()
    session[CONTEXT_ROOM_SESSION_KEY] = rid
    try:
        st.session_state[CONTEXT_ROOM_SESSION_KEY] = rid
    except Exception:
        pass

    st.caption("Stage1 fragment context isolation (C0–C3) — diagnostics only; no queue/room mutation.")

    _render_context_button(
        context_id=CONTEXT_C3,
        label=LABEL_C3,
        mount_kind="top_level_normal",
        is_fragment=False,
    )
    stage1_context_probe_fragment(CONTEXT_C0, LABEL_C0, "top_level_fragment")

    try:
        from live_draft_stage1_fragment_identity_matrix import render_s0_outside_matrix_expander

        render_s0_outside_matrix_expander(st, session, rid)
    except ImportError:
        pass

    with st.expander(CONTEXT_EXPANDER_TITLE, expanded=False):
        _render_context_button(
            context_id=CONTEXT_C2,
            label=LABEL_C2,
            mount_kind="expander_normal",
            is_fragment=False,
        )
        stage1_context_probe_fragment(CONTEXT_C1, LABEL_C1, "expander_fragment")

    try:
        from live_draft_rec_fragment_exec_diag import render_fragment_callback_ledger_probe

        render_fragment_callback_ledger_probe(st, session)
    except ImportError:
        pass
