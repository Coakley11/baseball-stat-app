"""Stage 1 component wiring 2×2 matrix (diag-only, fresh keys, no pick delivery)."""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

MATRIX_LOG_KEY = "_solo_wiring_matrix_log"
MATRIX_META_KEY = "_solo_wiring_matrix_meta"
MATRIX_PROBE_ID = "solo-wiring-matrix-diag"
VALID_CELLS = frozenset({"A1", "B1", "A2", "B2"})


def _qp_get(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def wiring_matrix_cell(st: Any | None, session: dict[str, Any]) -> str:
    cached = str(session.get("_solo_wiring_matrix_cell") or "").strip().upper()
    if cached in VALID_CELLS:
        return cached
    raw = _qp_get(st, "solo_wiring_matrix").strip().upper()
    if raw in VALID_CELLS:
        session["_solo_wiring_matrix_cell"] = raw
        return raw
    return ""


def wiring_matrix_active(st: Any | None, session: dict[str, Any]) -> bool:
    return wiring_matrix_cell(st, session) in VALID_CELLS


def resolve_matrix_widget_key(st: Any | None, session: dict[str, Any], cell: str) -> str:
    existing = str(session.get("_solo_wiring_matrix_widget_key") or "").strip()
    if existing:
        return existing
    qp = _qp_get(st, "solo_wiring_key").strip()
    if qp:
        key = qp[:120]
    else:
        key = f"solo_wiring_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    session["_solo_wiring_matrix_widget_key"] = key
    return key


def _append_log(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(MATRIX_LOG_KEY) or [])
    log.append(row)
    session[MATRIX_LOG_KEY] = log[-200:]


def _matrix_token(room: dict[str, Any]) -> str:
    try:
        from solo_countdown_component import build_solo_expire_token

        return build_solo_expire_token(room)
    except ImportError:
        did = str(room.get("draft_room_id") or room.get("draft_id") or "solo")
        return f"{did}|0|{time.time():.3f}"


def _simple_matrix_deliver(st: Any, session: dict[str, Any], raw: Any, key: str, *, cell: str) -> None:
    session[f"{key}_matrix_callback_count"] = int(session.get(f"{key}_matrix_callback_count") or 0) + 1
    _append_log(
        session,
        "matrix_callback",
        cell=cell,
        widget_key=key,
        raw_type=type(raw).__name__ if raw is not None else "NoneType",
        raw_repr=str(raw)[:400],
    )


def _mount_a1_minimal_direct(st: Any, session: dict[str, Any], *, key: str, token: str, cell: str) -> Any:
    from minimal_component_wake_repro_core import mount_single_for_transport

    def _on_change() -> None:
        raw = st.session_state.get(key)
        _simple_matrix_deliver(st, session, raw, key, cell=cell)

    return mount_single_for_transport(
        st,
        widget_key=key,
        expire_token=token,
        on_change=_on_change,
    )


def _mount_b1_production_direct(st: Any, session: dict[str, Any], room: dict[str, Any], *, key: str, token: str, cell: str) -> Any:
    from solo_countdown_component import mount_solo_countdown_wake_direct

    def _on_change() -> None:
        raw = st.session_state.get(key)
        _simple_matrix_deliver(st, session, raw, key, cell=cell)

    return mount_solo_countdown_wake_direct(
        room,
        key=key,
        expire_token=token,
        on_change=_on_change,
        actionable=True,
    )


def _mount_a2_minimal_micro_wrapper(
    st: Any, session: dict[str, Any], room: dict[str, Any], *, key: str, token: str, cell: str
) -> Any:
    """Minimal frontend with production micro-isolation-style callback wrapper (no pick deliver)."""
    from minimal_component_wake_repro_core import coerce_token, mount_single_for_transport

    prefix = f"_solo_wiring_micro_{cell}_"
    session[f"{prefix}mounted"] = session.get(f"{prefix}mounted")

    def _on_change() -> None:
        raw = st.session_state.get(key)
        _append_log(
            session,
            "micro_wrapper_on_change_entry",
            cell=cell,
            widget_key=key,
            raw_session_state=repr(raw)[:800],
        )
        tok = coerce_token(raw, token)
        _simple_matrix_deliver(st, session, raw, key, cell=cell)
        if tok:
            _append_log(session, "micro_wrapper_delivery_complete", token=tok[:400])

    if not session.get(f"{prefix}mounted"):
        _append_log(
            session,
            "component_declaration_loaded",
            cell=cell,
            frontend="minimal_wake_repro",
            python_declaration="minimal_micro_wrapper",
            widget_key=key,
            expire_token=token[:400],
        )
        ret = mount_single_for_transport(
            st,
            widget_key=key,
            expire_token=token,
            on_change=_on_change,
        )
        session[f"{prefix}mounted"] = True
        return ret
    return st.session_state.get(key) if key in st.session_state else None


def _mount_b2_production_micro(
    st: Any, session: dict[str, Any], room: dict[str, Any], *, key: str, token: str, cell: str
) -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    def _deliver(st2: Any, sess: dict[str, Any], raw: Any, k: str) -> None:
        _simple_matrix_deliver(st2, sess, raw, k, cell=cell)

    render_micro_isolation_once(
        st,
        session,
        placement=cell,
        location="wiring_matrix_b2_micro",
        draft_id=str(room.get("draft_room_id") or room.get("draft_id") or ""),
        route=True,
        persistent=False,
        session_prefix=f"_solo_wiring_micro_{cell}_",
        widget_key=key,
        production_room=room,
        production_expire_token=token,
        production_actionable=True,
        production_delivery_only=False,
        deliver_callback=_deliver,
        suppress_immediate_session_on_change=True,
        chain_persist_key="",
    )


def try_wiring_matrix_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    cell = wiring_matrix_cell(st, session)
    if not cell:
        return False
    room_dict = room if isinstance(room, dict) else session.get("live_draft_room")
    if not isinstance(room_dict, dict) or str(room_dict.get("status") or "") != "in_progress":
        return False

    try:
        from live_draft_solo_transport_boundary_diag import (
            bootstrap_transport_diagnostics,
            record_transport_python_run,
            render_transport_boundary_probe,
            render_transport_parent_listener,
            transport_logging_active,
        )
    except ImportError:
        bootstrap_transport_diagnostics = lambda *a, **k: None  # type: ignore[assignment,misc]
        render_transport_parent_listener = lambda _st: None  # type: ignore[assignment,misc]
        render_transport_boundary_probe = lambda *a, **k: None  # type: ignore[assignment,misc]
        record_transport_python_run = lambda *a, **k: None  # type: ignore[assignment,misc]
        transport_logging_active = lambda *a, **k: False  # type: ignore[assignment,misc]

    bootstrap_transport_diagnostics(st, session)
    session["_solo_persistent_wake_flush_disabled"] = True

    key = resolve_matrix_widget_key(st, session, cell)
    token = _matrix_token(room_dict)
    session[MATRIX_META_KEY] = {
        "cell": cell,
        "widget_key": key,
        "expire_token": token,
        "default": None,
        "frontend": {
            "A1": "minimal_wake_repro",
            "B1": "solo_countdown_wake",
            "A2": "minimal_wake_repro",
            "B2": "solo_countdown_wake",
        }.get(cell, ""),
        "python_declaration": {
            "A1": "minimal_component_wake_repro_core.mount_single_for_transport",
            "B1": "solo_countdown_component.mount_solo_countdown_wake_direct",
            "A2": "minimal_frontend + micro_isolation_callback_wrapper",
            "B2": "solo_countdown_wake_micro_core.render_micro_isolation_once",
        }.get(cell, ""),
    }

    if transport_logging_active(st, session):
        render_transport_parent_listener(st)

    record_transport_python_run(
        st,
        session,
        production_key=key,
        expected_token=token,
        phase=f"wiring_matrix_{cell}_pre_mount",
        on_change_registered=True,
    )

    comp_return: Any = None
    if cell == "A1":
        comp_return = _mount_a1_minimal_direct(st, session, key=key, token=token, cell=cell)
    elif cell == "B1":
        comp_return = _mount_b1_production_direct(st, session, room_dict, key=key, token=token, cell=cell)
    elif cell == "A2":
        comp_return = _mount_a2_minimal_micro_wrapper(st, session, room_dict, key=key, token=token, cell=cell)
    elif cell == "B2":
        _mount_b2_production_micro(st, session, room_dict, key=key, token=token, cell=cell)
        comp_return = st.session_state.get(key) if key in st.session_state else None

    meta = dict(session.get(MATRIX_META_KEY) or {})
    meta["component_return"] = repr(comp_return)[:400]
    meta["session_state_value"] = repr(st.session_state.get(key))[:400] if key in st.session_state else ""
    meta["callback_count"] = int(session.get(f"{key}_matrix_callback_count") or 0)
    session[MATRIX_META_KEY] = meta

    _append_log(
        session,
        "matrix_mount_complete",
        cell=cell,
        widget_key=key,
        expire_token=token[:400],
        component_return=meta["component_return"],
    )

    record_transport_python_run(
        st,
        session,
        production_key=key,
        expected_token=token,
        phase=f"wiring_matrix_{cell}_post_mount",
        on_change_registered=True,
    )
    render_wiring_matrix_probe(st, session)
    if transport_logging_active(st, session):
        render_transport_boundary_probe(st, session)
    return True


def render_wiring_matrix_probe(st: Any, session: dict[str, Any]) -> None:
    meta = dict(session.get(MATRIX_META_KEY) or {})
    log = list(session.get(MATRIX_LOG_KEY) or [])
    payload = json.dumps({"meta": meta, "log_tail": log[-40:]}, default=str)[:12000]
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    cell = str(meta.get("cell") or "")
    key = str(meta.get("widget_key") or "")
    st.markdown(
        f'<div id="{MATRIX_PROBE_ID}" '
        f'data-cell="{cell}" '
        f'data-key="{key.replace(chr(34), chr(39))}" '
        f'data-callbacks="{int(meta.get("callback_count") or 0)}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )


def matrix_summary(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": dict(session.get(MATRIX_META_KEY) or {}),
        "log": list(session.get(MATRIX_LOG_KEY) or []),
    }
