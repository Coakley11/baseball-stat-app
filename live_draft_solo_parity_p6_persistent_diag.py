"""Process-wide P6 parity ledger — keyed by diagnostic run ID, shared via st.cache_resource."""

from __future__ import annotations

import json
import time
from typing import Any

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
)

PARITY_QP = "solo_persistent_parity"
P6_RUN_ID_QP = "solo_p6_run_id"
P6_PERSISTENT_PROBE_ID = "solo-persistent-parity-diag"
_MAX_ROWS = 600

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
            for key, rows in _P6_LEDGERS.items():
                if key not in store:
                    store[key] = list(rows)
                else:
                    store[key].extend(rows)
                    store[key] = store[key][-_MAX_ROWS:]
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


def resolve_p6_run_id(st: Any | None, session: dict[str, Any]) -> str:
    rid = str(session.get("_solo_p6_run_id") or "").strip()
    if not rid and st is not None:
        rid = _qp_get(st, P6_RUN_ID_QP).strip()
    if rid:
        session["_solo_p6_run_id"] = rid
    return rid


def _ledger_key(st: Any | None, session: dict[str, Any]) -> str:
    rid = resolve_p6_run_id(st, session)
    if rid:
        return f"run:{rid}"
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    if not sid:
        sid = "unknown"
    return f"sid:{sid}"


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
    rid = _qp_get(st, P6_RUN_ID_QP).strip()
    if rid:
        session["_solo_p6_run_id"] = rid
    if _qp_get(st, PARITY_QP).strip().upper() == "P6":
        session["_solo_parity_p6_persistent_diag"] = True
        session["_solo_delivery_diag_enabled"] = True
        if _qp_flag(st, "solo_transport_probe"):
            try:
                from live_draft_solo_transport_boundary_diag import bootstrap_transport_diagnostics

                bootstrap_transport_diagnostics(st, session)
            except ImportError:
                pass


def _expected_token(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_parity_expected_token") or session.get(SOLO_PERSISTENT_WAKE_TOKEN_KEY) or ""
    )[:400]


def append_p6_ledger_row(
    session: dict[str, Any],
    stage: str,
    *,
    st: Any | None = None,
    actual_token: str = "",
    expected_token: str = "",
    **fields: Any,
) -> dict[str, Any]:
    if not p6_persistent_diag_active(st, session) and not parity_p6_active(session):
        return {}
    key = _ledger_key(st, session)
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    if sid:
        session["_solo_parity_p6_streamlit_session_id"] = sid
    run_id = resolve_p6_run_id(st, session)
    run_n = int(_P6_SCRIPT_RUN.get(key) or 0)
    exp = (expected_token or _expected_token(session))[:400]
    act = (actual_token or fields.pop("actual_token", "") or "")[:400]
    row: dict[str, Any] = {
        "ts": time.time(),
        "stage": str(stage),
        "diagnostic_run_id": run_id,
        "streamlit_session_id": sid,
        "script_run": run_n,
        "expected_token": exp,
        "actual_token": act,
        **fields,
    }
    store = _ledger_store()
    ledger = list(store.get(key) or [])
    row["seq"] = len(ledger) + 1
    ledger.append(row)
    store[key] = ledger[-_MAX_ROWS:]
    return row


def bump_p6_script_run(st: Any | None, session: dict[str, Any]) -> int:
    key = _ledger_key(st, session)
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "unknown")
    session["_solo_parity_p6_streamlit_session_id"] = sid
    n = int(_P6_SCRIPT_RUN.get(key) or 0) + 1
    _P6_SCRIPT_RUN[key] = n
    if _P6_DELIVERY_SEEN.get(key):
        append_p6_ledger_row(
            session,
            "post_delivery_script_run",
            st=st,
            prior_delivery_seen=True,
            script_run=n,
        )
    return n


def note_p6_delivery_completed(session: dict[str, Any], *, token: str = "", st: Any | None = None) -> None:
    key = _ledger_key(st, session)
    _P6_DELIVERY_SEEN[key] = True
    append_p6_ledger_row(
        session,
        "delivery_completed_marker",
        st=st,
        actual_token=str(token or "")[:400],
    )


def record_p6_token_latched(session: dict[str, Any], *, token: str, st: Any | None = None) -> None:
    append_p6_ledger_row(
        session,
        "production_token_latched",
        st=st,
        expected_token=str(token or "")[:400],
        actual_token=str(token or "")[:400],
    )


def on_ultra_early_script_run(st: Any, session: dict[str, Any]) -> None:
    if not p6_persistent_diag_active(st, session):
        return
    run_n = bump_p6_script_run(st, session)
    expected = _expected_token(session)
    widget_key = SOLO_PERSISTENT_WAKE_WIDGET_KEY
    raw = ""
    try:
        raw = repr(st.session_state.get(widget_key))[:400] if widget_key in st.session_state else ""
    except Exception:
        raw = ""
    append_p6_ledger_row(
        session,
        "script_begin",
        st=st,
        expected_token=expected,
        actual_token=raw.strip("'\"")[:400],
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
    st: Any | None = None,
) -> None:
    append_p6_ledger_row(
        session,
        "component_declared",
        st=st,
        widget_key=widget_key,
        expected_token=str(expire_token or "")[:400],
        actual_token=str(expire_token or "")[:400],
        component_return=repr(component_return)[:400],
        mount_location=mount_location,
    )


def record_p6_callback_entry(
    session: dict[str, Any],
    *,
    raw: Any,
    widget_key: str,
    expected_token: str = "",
    st: Any | None = None,
) -> None:
    actual = str(raw).strip("'\"")[:400] if raw is not None else ""
    append_p6_ledger_row(
        session,
        "on_change_callback_entry",
        st=st,
        raw_widget_value=repr(raw)[:400],
        widget_key=widget_key,
        expected_token=(expected_token or _expected_token(session))[:400],
        actual_token=actual,
    )


def record_p6_ownership_claim(
    session: dict[str, Any],
    *,
    attempted: bool,
    accepted: bool | None,
    reject_code: str = "",
    token: str = "",
    delivery_via: str = "",
    st: Any | None = None,
) -> None:
    stage = "ownership_claim_accepted" if accepted else "ownership_claim_rejected"
    append_p6_ledger_row(
        session,
        stage,
        st=st,
        ownership_claim_attempted=attempted,
        ownership_claim_accepted=accepted,
        reject_code=str(reject_code or "")[:120],
        expected_token=str(token or _expected_token(session))[:400],
        actual_token=str(token or "")[:400],
        delivery_via=delivery_via,
    )


def record_p6_callback_return(
    session: dict[str, Any],
    *,
    reason: str,
    pick_processing_skipped: bool = False,
    raw: Any = None,
    st: Any | None = None,
) -> None:
    append_p6_ledger_row(
        session,
        "callback_return",
        st=st,
        callback_return_reason=str(reason or "")[:200],
        pick_processing_intentionally_skipped=bool(pick_processing_skipped),
        raw_widget_value=repr(raw)[:400] if raw is not None else "",
        actual_token=str(raw).strip("'\"")[:400] if raw is not None else "",
    )


def record_p6_diagnostic_pick_skipped(
    session: dict[str, Any],
    *,
    reason: str,
    token: str = "",
    st: Any | None = None,
) -> None:
    append_p6_ledger_row(
        session,
        "pick_processing_skipped",
        st=st,
        skip_reason=str(reason or "")[:200],
        expected_token=str(token or _expected_token(session))[:400],
        actual_token=str(token or "")[:400],
    )


def get_p6_ledger_for_run(run_id: str) -> list[dict[str, Any]]:
    if not run_id:
        return []
    return list(_ledger_store().get(f"run:{run_id}") or [])


def get_p6_ledger(session_or_run_id: str) -> list[dict[str, Any]]:
    """Backward-compatible: run id or legacy session id."""
    if not session_or_run_id:
        return []
    store = _ledger_store()
    if session_or_run_id.startswith("run:") or session_or_run_id.startswith("sid:"):
        return list(store.get(session_or_run_id) or [])
    rows = list(store.get(f"run:{session_or_run_id}") or [])
    if rows:
        return rows
    return list(store.get(f"sid:{session_or_run_id}") or [])


def build_ledger_snapshot_for_run(run_id: str) -> dict[str, Any]:
    rows = get_p6_ledger_for_run(run_id)
    expected = ""
    for r in reversed(rows):
        if isinstance(r, dict) and str(r.get("expected_token") or "").startswith("PARITY|"):
            expected = str(r.get("expected_token") or "")
            break
    streamlit_sid = ""
    for r in reversed(rows):
        if isinstance(r, dict) and r.get("streamlit_session_id"):
            streamlit_sid = str(r.get("streamlit_session_id") or "")
            break
    raw_widget = ""
    for r in reversed(rows):
        if isinstance(r, dict) and r.get("raw_widget_value"):
            raw_widget = str(r.get("raw_widget_value") or "")
            break
    prod_count = sum(1 for r in rows if isinstance(r, dict) and r.get("stage") == "on_change_callback_entry")
    return {
        "diagnostic_run_id": run_id,
        "streamlit_session_id": streamlit_sid,
        "expected_token": expected,
        "raw_session_state_value": raw_widget,
        "ledger_rows": rows,
        "callback_rows": rows,
        "production_callback_entries": prod_count,
        "pick_processing_disabled": True,
    }


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
    """Legacy same-page payload builder (observer page preferred for runners)."""
    run_id = resolve_p6_run_id(st, session)
    if run_id:
        snap = build_ledger_snapshot_for_run(run_id)
        prod_count, prod_reg = _production_callback_flag(session)
        snap["production_callback_flag_count"] = prod_count
        snap["production_callback_registered"] = prod_reg
        return snap
    sid = _streamlit_session_id() or str(session.get("_solo_parity_p6_streamlit_session_id") or "")
    rows = get_p6_ledger(f"sid:{sid}")
    snap = {
        "streamlit_session_id": sid,
        "expected_token": _expected_token(session),
        "ledger_rows": rows,
        "callback_rows": rows,
    }
    prod_count, prod_reg = _production_callback_flag(session)
    snap["production_callback_flag_count"] = prod_count
    snap["production_callback_registered"] = prod_reg
    return snap


def render_p6_persistent_probe(st: Any, session: dict[str, Any]) -> None:
    """Deprecated: writers append to process-wide ledger; runners use solo_p6_diag_observer."""
    return


def first_nonempty_p6_snapshot_criteria(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    has_entry = any(isinstance(r, dict) and r.get("stage") == "on_change_callback_entry" for r in rows)
    has_owner = any(
        isinstance(r, dict)
        and str(r.get("stage") or "") in ("ownership_claim_accepted", "ownership_claim_rejected", "ownership_claim_attempted")
        for r in rows
    )
    return has_entry and has_owner


def python_receipt_from_payload(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    for r in rows:
        if not isinstance(r, dict) or r.get("stage") != "on_change_callback_entry":
            continue
        act = str(r.get("actual_token") or "")
        if expected in act or act == expected or act:
            return True
    raw = str(payload.get("raw_session_state_value") or "").strip("'\"")
    if expected in raw or raw.strip("'") == expected:
        return True
    owners = payload.get("delivery_owner_tokens")
    if isinstance(owners, dict) and expected in owners:
        return True
    stage1 = payload.get("stage1_audit") if isinstance(payload.get("stage1_audit"), dict) else {}
    callbacks = stage1.get("callbacks") if isinstance(stage1.get("callbacks"), list) else []
    return len(callbacks) >= 1
