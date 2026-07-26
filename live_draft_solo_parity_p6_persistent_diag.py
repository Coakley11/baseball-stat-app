"""Process-wide P6 parity ledger — survives reruns, st.stop, and session_state loss."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
)

PARITY_QP = "solo_persistent_parity"
P6_PERSISTENT_PROBE_ID = "solo-persistent-parity-diag"
_MAX_ROWS = 400

_P6_LEDGERS: dict[str, list[dict[str, Any]]] = {}
_P6_SCRIPT_RUN: dict[str, int] = {}
_P6_DELIVERY_SEEN: dict[str, bool] = {}


def _ledger_store() -> dict[str, list[dict[str, Any]]]:
    try:
        import streamlit as st

        @st.cache_resource
        def _cached_p6_store() -> dict[str, list[dict[str, Any]]]:
            return _P6_LEDGERS

        store = _cached_p6_store()
        if store is not _P6_LEDGERS:
            for sid, rows in _P6_LEDGERS.items():
                if sid not in store:
                    store[sid] = list(rows)
                else:
                    store[sid].extend(rows)
                    store[sid] = store[sid][-_MAX_ROWS:]
        return store
    except Exception:
        return _P6_LEDGERS


def _streamlit_session_id() -> str:
    try:
        from live_draft_callback_boundary_diag import _streamlit_session_id as sid_fn

        return sid_fn()
    except ImportError:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx

            ctx = get_script_run_ctx()
            return str(getattr(ctx, "session_id", "") or "")
        except Exception:
            return ""


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


def parity_p6_active(session: dict[str, Any]) -> bool:
    return str(session.get("_solo_parity_ladder_control") or "").strip().upper() == "P6"


def parity_p6_pick_processing_disabled(session: dict[str, Any]) -> bool:
    return parity_p6_active(session) and bool(session.get("_solo_parity_p6_disable_pick_processing"))


def p6_persistent_diag_active(st: Any | None, session: dict[str, Any]) -> bool:
    if session.get("_solo_parity_p6_persistent_diag"):
        return True
    if st is not None and _qp_get(st, PARITY_QP).strip().upper() == "P6":
        return True
    return parity_p6_active(session)


def enable_p6_persistent_diag_from_query(st: Any, session: dict[str, Any]) -> None:
    if _qp_get(st, PARITY_QP).strip().upper() == "P6":
        session["_solo_parity_p6_persistent_diag"] = True
        session["_solo_delivery_diag_enabled"] = True
        if _qp_flag(st, "solo_transport_probe"):
            try:
                from live_draft_solo_transport_boundary_diag import bootstrap_transport_diagnostics

                bootstrap_transport_diagnostics(st, session)
            except ImportError:
                pass


def append_p6_ledger_row(session: dict[str, Any], stage: str, **fields: Any) -> dict[str, Any]:
    if not p6_persistent_diag_active(None, session) and not parity_p6_active(session):
        return {}
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    if not sid:
        sid = "unknown"
    session["_solo_parity_p6_streamlit_session_id"] = sid
    run_n = int(_P6_SCRIPT_RUN.get(sid) or 0)
    row: dict[str, Any] = {
        "ts": time.time(),
        "stage": str(stage),
        "streamlit_session_id": sid,
        "script_run": run_n,
        **fields,
    }
    store = _ledger_store()
    ledger = list(store.get(sid) or [])
    row["seq"] = len(ledger) + 1
    ledger.append(row)
    store[sid] = ledger[-_MAX_ROWS:]
    return row


def bump_p6_script_run(session: dict[str, Any]) -> int:
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "unknown")
    session["_solo_parity_p6_streamlit_session_id"] = sid
    n = int(_P6_SCRIPT_RUN.get(sid) or 0) + 1
    _P6_SCRIPT_RUN[sid] = n
    if _P6_DELIVERY_SEEN.get(sid):
        append_p6_ledger_row(
            session,
            "script_run_after_delivery",
            prior_delivery_seen=True,
            script_run=n,
        )
    return n


def note_p6_delivery_completed(session: dict[str, Any], *, token: str = "") -> None:
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "unknown")
    _P6_DELIVERY_SEEN[sid] = True
    append_p6_ledger_row(session, "delivery_completed_marker", token=str(token or "")[:400])


def on_ultra_early_script_run(st: Any, session: dict[str, Any]) -> None:
    if not p6_persistent_diag_active(st, session):
        return
    run_n = bump_p6_script_run(session)
    expected = str(session.get("_solo_parity_expected_token") or session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or "")
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    raw = ""
    try:
        raw = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else ""
    except Exception:
        raw = ""
    append_p6_ledger_row(
        session,
        "script_beginning",
        expected_token=expected[:400],
        widget_key=widget_key,
        raw_widget_value=raw,
        script_run=run_n,
        active_page=str(session.get("active_page") or ""),
    )


def record_p6_component_declaration(
    session: dict[str, Any],
    *,
    widget_key: str,
    expire_token: str,
    component_return: Any = None,
    mount_location: str = "",
) -> None:
    append_p6_ledger_row(
        session,
        "component_declaration",
        widget_key=widget_key,
        expected_token=str(expire_token or "")[:400],
        component_return=repr(component_return)[:400],
        mount_location=mount_location,
    )


def record_p6_callback_entry(session: dict[str, Any], *, raw: Any, widget_key: str, expected_token: str = "") -> None:
    append_p6_ledger_row(
        session,
        "on_change_callback_entry",
        raw_widget_value=repr(raw)[:400],
        widget_key=widget_key,
        expected_token=(expected_token or str(session.get("_solo_parity_expected_token") or ""))[:400],
    )


def record_p6_ownership_claim(
    session: dict[str, Any],
    *,
    attempted: bool,
    accepted: bool | None,
    reject_code: str = "",
    token: str = "",
    delivery_via: str = "",
) -> None:
    append_p6_ledger_row(
        session,
        "ownership_claim_accepted" if accepted else "ownership_claim_rejected",
        ownership_claim_attempted=attempted,
        ownership_claim_accepted=accepted,
        reject_code=str(reject_code or "")[:120],
        expected_token=str(token or "")[:400],
        delivery_via=delivery_via,
    )


def record_p6_callback_return(
    session: dict[str, Any],
    *,
    reason: str,
    pick_processing_skipped: bool = False,
    raw: Any = None,
) -> None:
    append_p6_ledger_row(
        session,
        "callback_return",
        callback_return_reason=str(reason or "")[:200],
        pick_processing_intentionally_skipped=bool(pick_processing_skipped),
        raw_widget_value=repr(raw)[:400] if raw is not None else "",
    )


def get_p6_ledger(session_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    return list(_ledger_store().get(session_id) or [])


def _production_callback_flag(session: dict[str, Any]) -> tuple[int, bool]:
    try:
        from live_draft_solo_transport_boundary_diag import PRODUCTION_CALLBACK_FLAG

        return (
            int(session.get(f"{PRODUCTION_CALLBACK_FLAG}_count") or 0),
            bool(session.get(PRODUCTION_CALLBACK_FLAG)),
        )
    except ImportError:
        return 0, False


def build_p6_probe_payload(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    raw = ""
    try:
        raw = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else ""
    except Exception:
        pass
    expected = str(
        session.get("_solo_parity_expected_token") or session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""
    )[:400]
    prod_count, prod_reg = _production_callback_flag(session)
    stage1: dict[str, Any] = {}
    try:
        from live_draft_stage1_expire_audit import stage1_audit_summary

        stage1 = stage1_audit_summary(session)
    except ImportError:
        pass
    owners = session.get("_solo_token_delivery_owner")
    return {
        "streamlit_session_id": sid,
        "script_run_counter": int(_P6_SCRIPT_RUN.get(sid) or 0),
        "expected_token": expected,
        "raw_session_state_value": raw,
        "widget_key": widget_key,
        "callback_rows": get_p6_ledger(sid),
        "ownership_rows": [r for r in get_p6_ledger(sid) if "ownership_claim" in str(r.get("stage") or "")],
        "production_callback_flag_count": prod_count,
        "production_callback_registered": prod_reg,
        "stage1_audit": stage1,
        "delivery_owner_tokens": dict(owners) if isinstance(owners, dict) else owners,
        "pick_processing_disabled": parity_p6_pick_processing_disabled(session),
    }


def render_p6_persistent_probe(st: Any, session: dict[str, Any]) -> None:
    if not p6_persistent_diag_active(st, session):
        return
    payload = build_p6_probe_payload(st, session)
    raw_json = json.dumps(payload, default=str)
    if len(raw_json) > 16000:
        raw_json = raw_json[:16000]
    b64 = base64.b64encode(raw_json.encode("utf-8")).decode("ascii")
    token = str(payload.get("expected_token") or "")
    st.markdown(
        f'<div id="{P6_PERSISTENT_PROBE_ID}" '
        f'data-control="P6" '
        f'data-key="{SOLO_PERSISTENT_WAKE_WIDGET_KEY}" '
        f'data-expected-token="{token.replace(chr(34), chr(39))[:200]}" '
        f'data-session-id="{str(payload.get("streamlit_session_id") or "").replace(chr(34), chr(39))}" '
        f'data-b64="{b64}"></div>',
        unsafe_allow_html=True,
    )


def first_nonempty_p6_snapshot_criteria(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    has_entry = any(isinstance(r, dict) and r.get("stage") == "on_change_callback_entry" for r in rows)
    has_owner = any(
        isinstance(r, dict) and str(r.get("stage") or "").startswith("ownership_claim") for r in rows
    )
    return has_entry and has_owner


def python_receipt_from_payload(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    raw = str(payload.get("raw_session_state_value") or "").strip("'\"")
    if expected in raw or raw.strip("'") == expected:
        return True
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    if any(isinstance(r, dict) and r.get("stage") == "on_change_callback_entry" for r in rows):
        return True
    owners = payload.get("delivery_owner_tokens")
    if isinstance(owners, dict) and expected in owners:
        return True
    stage1 = payload.get("stage1_audit") if isinstance(payload.get("stage1_audit"), dict) else {}
    callbacks = stage1.get("callbacks") if isinstance(stage1.get("callbacks"), list) else []
    return len(callbacks) >= 1
