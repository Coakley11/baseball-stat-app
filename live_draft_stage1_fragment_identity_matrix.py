"""Stage1 fragment identity matrix — S0/S1/D0/D1 trivial callback probes (solo diag only)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable

import streamlit as st

from live_draft_stage1_fragment_identity_runtime import (
    MATRIX_IDENTITY_IMPL_REV,
    snapshot_fragment_identity,
)

MATRIX_ROOM_SESSION_KEY = "_stage1_fragment_matrix_room_id"
MATRIX_INVOCATION_KEY = "_stage1_fragment_matrix_invocation_counts"
MATRIX_PROBE_ELEMENT_ID = "solo-stage1-fragment-identity-matrix-probe"
MATRIX_IMPL_REV = "stage1_fragment_identity_matrix_v1"

CONTROL_S0 = "S0"
CONTROL_S1 = "S1"
CONTROL_D0 = "D0"
CONTROL_D1 = "D1"

_LABELS = {
    CONTROL_S0: "Stage1 Static Fragment Probe",
    CONTROL_S1: "Stage1 Static Timed Fragment Probe",
    CONTROL_D0: "Stage1 Dynamic Fragment Probe",
    CONTROL_D1: "Stage1 Dynamic Timed Fragment Probe",
}

_CONSTRUCTION = {
    CONTROL_S0: "static_module_no_timer",
    CONTROL_S1: "static_module_timer",
    CONTROL_D0: "dynamic_nested_no_timer",
    CONTROL_D1: "dynamic_nested_timer",
}

_RUN_EVERY = {
    CONTROL_S0: None,
    CONTROL_S1: 1,
    CONTROL_D0: None,
    CONTROL_D1: 1,
}


def _solo_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    try:
        from live_draft_solo_component_diagnostics import solo_component_diag_enabled

        return bool(solo_component_diag_enabled(st, session))
    except ImportError:
        return bool(session.get("_solo_component_diag_enabled"))


def matrix_widget_key(control: str, room_id: str) -> str:
    rid = str(room_id or "noroom").strip().upper()[:16]
    return f"stage1_fragment_matrix_{control.lower()}_{rid}_diag"


def _full_app_run_seq(session: Any) -> int:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _bump_invocation(session: Any, control: str) -> int:
    counts = dict(session.get(MATRIX_INVOCATION_KEY) or {})
    n = int(counts.get(control) or 0) + 1
    counts[control] = n
    session[MATRIX_INVOCATION_KEY] = counts
    return n


def on_fragment_matrix_probe_click(
    session: Any,
    *,
    control: str,
    room_id: str,
    widget_key: str,
) -> None:
    """Trivial callback — ledger + identity snapshot only."""
    from live_draft_rec_fragment_exec_diag import append_fragment_callback_ledger

    ctrl = str(control or "").strip().upper()[:2]
    identity = snapshot_fragment_identity(phase="callback", widget_user_key=widget_key)
    row = {
        "event_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "callback_id": "on_fragment_matrix_probe_click",
        "callback_entered": True,
        "source": f"fragment_matrix_{ctrl.lower()}",
        "control": ctrl,
        "room_id": str(room_id or "").strip(),
        "widget_key": str(widget_key or "").strip(),
        "full_app_run_seq": _full_app_run_seq(session),
        "construction": _CONSTRUCTION.get(ctrl, ""),
        "run_every": _RUN_EVERY.get(ctrl),
        "fragment_identity": identity,
    }
    append_fragment_callback_ledger(session, row)


def _render_matrix_control(*, control: str, run_every: int | None) -> None:
    session = st.session_state
    if not _solo_diag_enabled(st, session):
        return
    room_id = str(session.get(MATRIX_ROOM_SESSION_KEY) or "")
    wk = matrix_widget_key(control, room_id)
    inv = _bump_invocation(session, control)
    identity = snapshot_fragment_identity(phase="render", widget_user_key=wk)
    session["_stage1_fragment_matrix_last_render"] = {
        "control": control,
        "invocation": inv,
        "identity": identity,
        "ts": time.time(),
    }

    def _click() -> None:
        on_fragment_matrix_probe_click(
            st.session_state,
            control=control,
            room_id=room_id,
            widget_key=wk,
        )

    st.button(
        _LABELS[control],
        key=wk,
        use_container_width=True,
        on_click=_click,
    )
    _emit_matrix_dom_probe(
        control=control,
        room_id=room_id,
        widget_key=wk,
        invocation=inv,
        identity=identity,
        run_every=run_every,
    )


def _emit_matrix_dom_probe(
    *,
    control: str,
    room_id: str,
    widget_key: str,
    invocation: int,
    identity: dict[str, Any],
    run_every: int | None,
) -> None:
    safe = lambda s: str(s or "").replace('"', "'")[:160]
    storage = identity.get("fragment_storage") if isinstance(identity.get("fragment_storage"), dict) else {}
    in_storage = identity.get("render_fragment_in_storage")
    in_storage_attr = (
        "1" if in_storage is True else "0" if in_storage is False else ""
    )
    meta = identity.get("widget_metadata") if isinstance(identity.get("widget_metadata"), dict) else {}
    meta_fid = str(meta.get("fragment_id") or "")
    owner = identity.get("widget_owner_fragment_current")
    owner_attr = "1" if owner is True else "0" if owner is False else ""
    st.markdown(
        f'<div class="stage1-fragment-matrix-probe" data-probe-element="{MATRIX_PROBE_ELEMENT_ID}" '
        f'data-control="{safe(control)}" '
        f'data-construction="{safe(_CONSTRUCTION.get(control))}" '
        f'data-run-every="{safe(run_every)}" '
        f'data-room-id="{safe(room_id)}" '
        f'data-widget-key="{safe(widget_key)}" '
        f'data-invocation="{int(invocation)}" '
        f'data-thread-fragment-id="{safe(identity.get("thread_state_fragment_id"))}" '
        f'data-metadata-fragment-id="{safe(meta_fid)}" '
        f'data-widget-owner-fragment-current="{owner_attr}" '
        f'data-ownership-subcode="{safe(identity.get("ownership_subcode"))}" '
        f'data-fragment-ids-this-run="{safe(json.dumps(identity.get("fragment_ids_this_run") or []))}" '
        f'data-render-fragment-in-storage="{in_storage_attr}" '
        f'data-metadata-fragment-in-storage="{1 if identity.get("metadata_fragment_in_storage") is True else 0 if identity.get("metadata_fragment_in_storage") is False else ""}" '
        f'data-stored-fragment-id-count="{len(storage.get("stored_fragment_ids") or [])}" '
        f'data-impl-rev="{MATRIX_IMPL_REV}"></div>',
        unsafe_allow_html=True,
    )


@st.fragment
def stage1_static_fragment_no_timer() -> None:
    _render_matrix_control(control=CONTROL_S0, run_every=None)


@st.fragment(run_every=1)
def stage1_static_fragment_timer() -> None:
    _render_matrix_control(control=CONTROL_S1, run_every=1)


def _mount_dynamic_fragment(st: Any, body: Callable[[], None], *, run_every: int | None) -> None:
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        body()
        return
    if run_every is None:
        fragment(body)()
        return
    fragment(run_every=run_every)(body)()


def render_stage1_fragment_identity_matrix(st: Any, session: dict[str, Any], room_id: str) -> None:
    """Mount S0/S1/D0/D1 probes — solo component diagnostics only."""
    if not _solo_diag_enabled(st, session):
        return
    rid = str(room_id or "").strip()
    session[MATRIX_ROOM_SESSION_KEY] = rid
    try:
        st.session_state[MATRIX_ROOM_SESSION_KEY] = rid
    except Exception:
        pass

    with st.expander("Stage1 fragment identity matrix (diag)", expanded=False):
        st.caption("S0/S1 = module-level @st.fragment; D0/D1 = dynamic nested pattern (recommendation wrapper).")
        stage1_static_fragment_no_timer()
        stage1_static_fragment_timer()

        def _d0() -> None:
            _render_matrix_control(control=CONTROL_D0, run_every=None)

        def _d1() -> None:
            _render_matrix_control(control=CONTROL_D1, run_every=1)

        _mount_dynamic_fragment(st, _d0, run_every=None)
        _mount_dynamic_fragment(st, _d1, run_every=1)

        try:
            from live_draft_rec_fragment_exec_diag import render_fragment_callback_ledger_probe

            render_fragment_callback_ledger_probe(st, session)
        except ImportError:
            pass

        rec_identity = snapshot_fragment_identity(phase="recommendation_mount_context")
        st.markdown(
            f'<div id="solo-stage1-recommendation-fragment-identity" '
            f'data-impl-rev="{MATRIX_IDENTITY_IMPL_REV}" '
            f'data-json="{json.dumps(rec_identity, default=str)[:12000].replace(chr(34), chr(39))}"></div>',
            unsafe_allow_html=True,
        )
