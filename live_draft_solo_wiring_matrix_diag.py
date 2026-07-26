"""Synthetic component wiring 2×2 matrix — early LDR hook, no real draft, st.stop page."""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

MATRIX_LOG_KEY = "_solo_wiring_matrix_log"
MATRIX_META_KEY = "_solo_wiring_matrix_meta"
MATRIX_PROBE_ID = "solo-wiring-matrix-diag"
MATRIX_CALLBACKS_KEY = "_solo_wiring_matrix_callbacks"
MATRIX_BROWSER_SEND_TS_KEY = "_solo_wiring_matrix_browser_send_ts"
MATRIX_STOP_PAGE_KEY = "_solo_wiring_matrix_stop_page"
MATRIX_MOUNTED_KEY = "_solo_wiring_matrix_component_mounted"
SYNTHETIC_SECONDS = 10
VALID_CELLS = frozenset({"A1", "B1", "A2", "B2"})


def _qp_get(st: Any | None, name: str) -> str:
    if st is None:
        return ""
    try:
        from live_draft_cloud_diagnostics import _qp_get as get_qp

        return get_qp(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any | None, name: str) -> bool:
    if st is None:
        return False
    try:
        from live_draft_cloud_diagnostics import _qp_flag as flag

        return flag(st, name)
    except ImportError:
        return False


def wiring_matrix_cell(st: Any | None, session: dict[str, Any]) -> str:
    cached = str(session.get("_solo_wiring_matrix_cell") or "").strip().upper()
    if cached in VALID_CELLS:
        return cached
    raw = _qp_get(st, "solo_wiring_matrix").strip().upper()
    if raw in VALID_CELLS:
        session["_solo_wiring_matrix_cell"] = raw
        return raw
    return ""


def wiring_matrix_synthetic(session: dict[str, Any]) -> bool:
    if session.get("_solo_wiring_matrix_synthetic"):
        return True
    return False


def wiring_matrix_synthetic_from_query(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get("_solo_wiring_matrix_synthetic_latched"):
        return bool(session.get("_solo_wiring_matrix_synthetic"))
    latched = False
    if wiring_matrix_cell(st, session):
        if _qp_flag(st, "solo_wiring_synthetic"):
            latched = True
        elif _qp_get(st, "solo_wiring_matrix").strip():
            latched = True
    session["_solo_wiring_matrix_synthetic_latched"] = True
    session["_solo_wiring_matrix_synthetic"] = latched
    return latched


def wiring_matrix_active(st: Any | None, session: dict[str, Any]) -> bool:
    return wiring_matrix_cell(st, session) in VALID_CELLS


def wiring_matrix_should_stop_page(session: dict[str, Any]) -> bool:
    return bool(session.get(MATRIX_STOP_PAGE_KEY))


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


def build_synthetic_matrix_token(cell: str) -> tuple[str, float]:
    """Token WIRING_A1|0|<deadline> with deadline 10s after mount (actionable)."""
    deadline = time.time() + float(SYNTHETIC_SECONDS)
    token = f"WIRING_{cell.upper()}|0|{deadline:.3f}"
    return token, deadline


def _synthetic_stub_room() -> dict[str, Any]:
    return {
        "draft_room_id": "SYNTH",
        "draft_id": "SYNTH",
        "status": "synthetic",
        "current_pick_index": 0,
        "config": {"timer_seconds": SYNTHETIC_SECONDS},
    }


def coerce_token_matches(raw: Any, expected_token: str) -> bool:
    if not expected_token:
        return False
    val = raw
    if isinstance(val, str):
        val = val.strip("'\"")
    return str(val or "").strip() == expected_token.strip()


def _append_log(session: dict[str, Any], stage: str, **fields: Any) -> None:
    row = {"ts": time.time(), "stage": stage, **fields}
    log = list(session.get(MATRIX_LOG_KEY) or [])
    log.append(row)
    session[MATRIX_LOG_KEY] = log[-200:]


def resolve_matrix_ls_key(st: Any | None, session: dict[str, Any], cell: str) -> str:
    existing = str(session.get("_solo_wiring_matrix_ls_key") or "").strip()
    if existing:
        return existing
    qp = _qp_get(st, "solo_wiring_ls_key").strip()
    if qp:
        ls = qp[:120]
    else:
        ls = f"solo_wiring_ls_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    session["_solo_wiring_matrix_ls_key"] = ls
    return ls


def _clear_widget_session_value(st: Any, session: dict[str, Any], key: str) -> None:
    """Ensure Python never seeds the widget value before iframe send."""
    had = key in st.session_state
    prior = repr(st.session_state.get(key))[:200] if had else ""
    try:
        del st.session_state[key]
    except Exception:
        try:
            st.session_state.pop(key, None)
        except Exception:
            pass
    _append_log(
        session,
        "widget_key_cleared_pre_mount",
        widget_key=key,
        had_prior=had,
        prior_raw=prior,
    )


def _matrix_on_change(
    st: Any,
    session: dict[str, Any],
    *,
    key: str,
    cell: str,
    expected_token: str,
    source: str,
) -> None:
    seq = int(session.get(f"{key}_matrix_callback_seq") or 0) + 1
    session[f"{key}_matrix_callback_seq"] = seq
    raw = st.session_state.get(key)
    now = time.time()
    had_prior_send = session.get(MATRIX_BROWSER_SEND_TS_KEY) is not None
    browser_ts = session.get(MATRIX_BROWSER_SEND_TS_KEY)
    if browser_ts is None and coerce_token_matches(raw, expected_token):
        session[MATRIX_BROWSER_SEND_TS_KEY] = now
        browser_ts = now
    row = {
        "ts": now,
        "seq": seq,
        "expected_token": expected_token,
        "actual_raw": repr(raw)[:400],
        "source": source,
        "browser_send_ts": browser_ts,
        "browser_send_had_occurred": had_prior_send,
    }
    callbacks = list(session.get(MATRIX_CALLBACKS_KEY) or [])
    callbacks.append(row)
    session[MATRIX_CALLBACKS_KEY] = callbacks[-50:]
    session[f"{key}_matrix_callback_count"] = seq
    _append_log(session, "matrix_callback", cell=cell, widget_key=key, **row)


def _simple_matrix_deliver(st: Any, session: dict[str, Any], raw: Any, key: str, *, cell: str) -> None:
    expected = str(session.get("_solo_wiring_matrix_expected_token") or "")
    _matrix_on_change(st, session, key=key, cell=cell, expected_token=expected, source="streamlit_on_change")


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


def _mount_b1_production_direct(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    key: str,
    token: str,
    cell: str,
    chain_persist_key: str = "",
) -> Any:
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
        chain_persist_key=chain_persist_key,
    )


def _mount_a2_minimal_micro_wrapper(
    st: Any, session: dict[str, Any], room: dict[str, Any], *, key: str, token: str, cell: str
) -> Any:
    from minimal_component_wake_repro_core import coerce_token, mount_single_for_transport

    prefix = f"_solo_wiring_micro_{cell}_"

    def _on_change() -> None:
        raw = st.session_state.get(key)
        _append_log(
            session,
            "micro_wrapper_on_change_entry",
            cell=cell,
            widget_key=key,
            raw_session_state=repr(raw)[:800],
        )
        _ = coerce_token(raw, token)
        _simple_matrix_deliver(st, session, raw, key, cell=cell)

    _append_log(
        session,
        "component_declaration_loaded",
        cell=cell,
        frontend="minimal_wake_repro",
        python_declaration="micro_isolation_callback_wrapper",
        widget_key=key,
        expire_token=token[:400],
    )
    return mount_single_for_transport(
        st,
        widget_key=key,
        expire_token=token,
        on_change=_on_change,
    )


def _mount_b2_production_micro(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    key: str,
    token: str,
    cell: str,
    chain_persist_key: str = "",
) -> None:
    from solo_countdown_wake_micro_core import render_micro_isolation_once

    def _deliver(st2: Any, sess: dict[str, Any], raw: Any, k: str) -> None:
        _simple_matrix_deliver(st2, sess, raw, k, cell=cell)

    render_micro_isolation_once(
        st,
        session,
        placement=cell,
        location="wiring_matrix_b2_micro",
        draft_id="SYNTH",
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
        chain_persist_key=chain_persist_key,
    )


def try_wiring_matrix_ldr_entry(st: Any, session: dict[str, Any], room: Any) -> bool:
    cell = wiring_matrix_cell(st, session)
    if not cell:
        return False

    wiring_matrix_synthetic_from_query(st, session)
    if not wiring_matrix_synthetic(session):
        return False

    room_dict = _synthetic_stub_room()

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
    session[MATRIX_STOP_PAGE_KEY] = True

    key = resolve_matrix_widget_key(st, session, cell)
    latched = str(session.get("_solo_wiring_matrix_expected_token") or "").strip()
    if latched:
        token = latched
        try:
            deadline = float(token.split("|")[2])
        except (IndexError, ValueError):
            token, deadline = build_synthetic_matrix_token(cell)
            session["_solo_wiring_matrix_expected_token"] = token
    else:
        token, deadline = build_synthetic_matrix_token(cell)
        session["_solo_wiring_matrix_expected_token"] = token

    ls_key = resolve_matrix_ls_key(st, session, cell)
    session[MATRIX_META_KEY] = {
        "mode": "synthetic",
        "cell": cell,
        "widget_key": key,
        "local_storage_key": ls_key,
        "expire_token": token,
        "deadline_unix": deadline,
        "actionable": True,
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

    _append_log(
        session,
        "synthetic_matrix_mount",
        cell=cell,
        widget_key=key,
        expire_token=token,
        deadline_unix=deadline,
    )

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

    already_mounted = bool(session.get(MATRIX_MOUNTED_KEY))
    delivered = key in st.session_state and coerce_token_matches(st.session_state.get(key), token)

    if not already_mounted and not delivered:
        _clear_widget_session_value(st, session, key)

    comp_return: Any = None
    if not delivered:
        if cell == "A1":
            comp_return = _mount_a1_minimal_direct(st, session, key=key, token=token, cell=cell)
        elif cell == "B1":
            comp_return = _mount_b1_production_direct(
                st, session, room_dict, key=key, token=token, cell=cell, chain_persist_key=ls_key
            )
        elif cell == "A2":
            comp_return = _mount_a2_minimal_micro_wrapper(st, session, room_dict, key=key, token=token, cell=cell)
        elif cell == "B2":
            _mount_b2_production_micro(
                st, session, room_dict, key=key, token=token, cell=cell, chain_persist_key=ls_key
            )
            comp_return = st.session_state.get(key) if key in st.session_state else None
        session[MATRIX_MOUNTED_KEY] = True
    else:
        comp_return = st.session_state.get(key) if key in st.session_state else None

    meta = dict(session.get(MATRIX_META_KEY) or {})
    meta["component_return"] = repr(comp_return)[:400]
    meta["session_state_value"] = repr(st.session_state.get(key))[:400] if key in st.session_state else ""
    meta["callback_count"] = int(session.get(f"{key}_matrix_callback_count") or 0)
    meta["callback_log"] = list(session.get(MATRIX_CALLBACKS_KEY) or [])
    session[MATRIX_META_KEY] = meta

    _append_log(session, "matrix_mount_complete", cell=cell, widget_key=key, expire_token=token[:400])

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
    token = str(meta.get("expire_token") or "")
    st.markdown(
        f'<div id="{MATRIX_PROBE_ID}" '
        f'data-synthetic="1" '
        f'data-cell="{cell}" '
        f'data-key="{key.replace(chr(34), chr(39))}" '
        f'data-expected-token="{token.replace(chr(34), chr(39))[:200]}" '
        f'data-callbacks="{int(meta.get("callback_count") or 0)}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )


def matrix_summary(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": dict(session.get(MATRIX_META_KEY) or {}),
        "log": list(session.get(MATRIX_LOG_KEY) or []),
    }
