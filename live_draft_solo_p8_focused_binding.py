"""Authorized P8 focused binding diagnostic — stop before ownership claim."""

from __future__ import annotations

import re
import time
from typing import Any

FOCUSED_BINDING_GATE_VERSION = 1
SOLO_P8_FOCUSED_EFFECTIVE_KEY = "_solo_p8_focused_binding_effective"
SOLO_P8_HARNESS_TXN_KEY = "_solo_p8_harness_transaction_id"
SOLO_P8_AUTH_STATE_KEY = "_solo_p8_focused_auth_state"
SOLO_P8_FOCUSED_TXN_KEY = "_solo_p8_focused_binding_transaction"
FOCUSED_TXN_TTL_S = 900.0
HARNESS_RUN_ID_RE = re.compile(r"^[a-f0-9]{16}$", re.I)

EVENT_REQUESTED = "production_stage1_p8_focused_mode_requested"
EVENT_AUTHORIZED = "production_stage1_p8_focused_mode_authorized"
EVENT_EFFECTIVE = "production_stage1_p8_focused_mode_effective"
EVENT_STOP_BEFORE_CLAIM = "production_stage1_p8_focused_binding_stop_before_claim"
EVENT_FLUSH_BLOCKED = "production_stage1_p8_focused_flush_blocked"
EVENT_PRECLAIM_BLOCKED = "production_stage1_p8_focused_preclaim_blocked"
EVENT_HANDOFF_TERMINAL = "production_stage1_p8_focused_handoff_terminal"


def _qp_get(st: Any, name: str) -> str:
    try:
        from live_draft_cloud_diagnostics import _qp_get as get

        return get(st, name)
    except ImportError:
        return ""


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as flag

        return flag(st, name)
    except ImportError:
        return False


def _diagnostic_developer_authorized(st: Any | None, session: dict[str, Any]) -> tuple[bool, str]:
    try:
        from live_draft_solo_component_diagnostics import (
            SOLO_DIAG_ENABLED_KEY,
            solo_component_diag_enabled,
        )

        if solo_component_diag_enabled(st, session) or session.get(SOLO_DIAG_ENABLED_KEY):
            return True, ""
    except ImportError:
        pass
    txn = focused_transaction_record(session)
    if isinstance(txn, dict) and txn.get("component_diag_armed"):
        return True, ""
    try:
        from live_draft_cloud_diagnostics import _admin_ok

        if _admin_ok(st, session):
            return True, ""
    except ImportError:
        pass
    try:
        from streamlit_app import developer_mode_enabled

        if developer_mode_enabled():
            return True, ""
    except ImportError:
        pass
    try:
        from suite_workspace import is_admin_session

        if is_admin_session(st=st):
            return True, ""
    except ImportError:
        pass
    return False, "developer_diagnostic_not_authorized"


def focused_transaction_record(session: dict[str, Any]) -> dict[str, Any]:
    rec = session.get(SOLO_P8_FOCUSED_TXN_KEY)
    return dict(rec) if isinstance(rec, dict) else {}


def _runtime_build_sha(session: dict[str, Any]) -> str:
    return str(session.get("_solo_stage1_deployment_sha") or session.get("_solo_deployment_sha") or "")[:7]


def _runtime_streamlit_session_id(session: dict[str, Any]) -> str:
    return str(session.get("_solo_stage1_streamlit_session_id") or "")[:64]


def _persist_focused_transaction(
    session: dict[str, Any],
    *,
    harness_run_id: str,
    authorized: bool,
    component_diag_armed: bool,
) -> None:
    if not authorized or not harness_run_id:
        return
    session[SOLO_P8_FOCUSED_TXN_KEY] = {
        "harness_run_id": harness_run_id,
        "application_diagnostic_run_id": str(session.get("_solo_stage1_run_id") or "")[:40],
        "streamlit_session_id": _runtime_streamlit_session_id(session),
        "build_sha": _runtime_build_sha(session),
        "created_ts": time.time(),
        "expires_ts": time.time() + FOCUSED_TXN_TTL_S,
        "terminal": False,
        "component_diag_armed": bool(component_diag_armed),
        "focused_param_seen": True,
    }


def _focused_transaction_valid(st: Any | None, session: dict[str, Any], *, harness_run_id: str = "") -> tuple[bool, str]:
    txn = focused_transaction_record(session)
    if not txn or txn.get("terminal"):
        return False, "txn_missing_or_terminal"
    if float(txn.get("expires_ts") or 0) < time.time():
        return False, "txn_expired"
    expected_h = str(harness_run_id or session.get(SOLO_P8_HARNESS_TXN_KEY) or txn.get("harness_run_id") or "").lower()
    if expected_h and str(txn.get("harness_run_id") or "").lower() != expected_h:
        return False, "harness_run_id_mismatch"
    sid = _runtime_streamlit_session_id(session)
    if sid and txn.get("streamlit_session_id") and sid != txn.get("streamlit_session_id"):
        return False, "streamlit_session_mismatch"
    build = _runtime_build_sha(session)
    if build and txn.get("build_sha") and build != txn.get("build_sha"):
        return False, "build_sha_mismatch"
    return True, ""


def mark_focused_transaction_terminal(session: dict[str, Any], *, reason: str = "") -> None:
    txn = focused_transaction_record(session)
    if not txn:
        return
    txn["terminal"] = True
    txn["terminal_reason"] = str(reason or "")[:120]
    txn["terminal_ts"] = time.time()
    session[SOLO_P8_FOCUSED_TXN_KEY] = txn
    session[SOLO_P8_FOCUSED_EFFECTIVE_KEY] = False
    auth = focused_auth_state(session)
    auth["focused_effective"] = False
    auth["authorization_result"] = "terminal"
    session[SOLO_P8_AUTH_STATE_KEY] = auth


def get_effective_focused_binding_context(st: Any | None, session: dict[str, Any]) -> dict[str, Any]:
    """Single authoritative focused context for all guards."""
    auth = focused_auth_state(session)
    txn = focused_transaction_record(session)
    harness_qp, _, harness_id = _harness_marker_ok(st, session) if st is not None else (False, "", str(session.get(SOLO_P8_HARNESS_TXN_KEY) or ""))
    param_requested = bool(st is not None and _qp_flag(st, "solo_p8_focused_binding")) or bool(
        auth.get("focused_param_requested") or txn.get("focused_param_seen")
    )
    txn_ok, txn_reason = _focused_transaction_valid(st, session, harness_run_id=harness_id)
    if txn_ok and txn:
        session[SOLO_P8_FOCUSED_EFFECTIVE_KEY] = True
        session[SOLO_P8_HARNESS_TXN_KEY] = str(txn.get("harness_run_id") or "")
        _store_auth_state(
            session,
            focused_param_requested=True,
            focused_authorized=True,
            focused_effective=True,
            authorization_result="authorized",
            denial_reason="",
            harness_transaction_id=str(txn.get("harness_run_id") or ""),
        )
        auth = focused_auth_state(session)
    effective = bool(session.get(SOLO_P8_FOCUSED_EFFECTIVE_KEY)) and not txn.get("terminal")
    if session.get(SOLO_P8_FOCUSED_EFFECTIVE_KEY) is True and bool(auth.get("focused_authorized")) and not txn.get("terminal"):
        effective = True
    return {
        "requested": param_requested,
        "authorized": bool(auth.get("focused_authorized")) or txn_ok,
        "effective": effective and (bool(auth.get("focused_authorized")) or txn_ok),
        "harness_run_id": str(session.get(SOLO_P8_HARNESS_TXN_KEY) or harness_id or txn.get("harness_run_id") or ""),
        "application_diagnostic_run_id": str(
            session.get("_solo_stage1_run_id") or txn.get("application_diagnostic_run_id") or ""
        )[:40],
        "streamlit_session_id": _runtime_streamlit_session_id(session),
        "build_sha": _runtime_build_sha(session),
        "denial_reason": str(auth.get("denial_reason") or txn_reason or ""),
        "authorization_result": str(auth.get("authorization_result") or ""),
        "transaction": txn,
    }


def _build_supports_focused_gate(session: dict[str, Any]) -> tuple[bool, str]:
    if FOCUSED_BINDING_GATE_VERSION < 1:
        return False, "focused_gate_version_unsupported"
    try:
        from live_draft_stage1_post_bind_flush import complete_delivery_only_observation_and_actionable_flush

        _ = complete_delivery_only_observation_and_actionable_flush
        from live_draft_solo_p8_focused_binding import bootstrap_solo_p8_focused_binding

        _ = bootstrap_solo_p8_focused_binding
    except ImportError:
        return False, "focused_gate_handlers_missing"
    return True, ""


def _harness_marker_ok(st: Any | None, session: dict[str, Any]) -> tuple[bool, str, str]:
    raw = _qp_get(st, "solo_p8_harness_run_id") if st is not None else ""
    raw = str(raw or session.get(SOLO_P8_HARNESS_TXN_KEY) or "").strip().lower()
    if not raw:
        return False, "harness_run_marker_missing", ""
    if not HARNESS_RUN_ID_RE.match(raw):
        return False, "harness_run_marker_invalid", raw
    session[SOLO_P8_HARNESS_TXN_KEY] = raw
    return True, "", raw


def focused_auth_state(session: dict[str, Any]) -> dict[str, Any]:
    state = session.get(SOLO_P8_AUTH_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _store_auth_state(session: dict[str, Any], **fields: Any) -> None:
    base = focused_auth_state(session)
    base.update(fields)
    base["updated_ts"] = time.time()
    session[SOLO_P8_AUTH_STATE_KEY] = base


def _emit_focused_event(
    session: dict[str, Any],
    event: str,
    *,
    st: Any | None = None,
    widget_key: str = "",
    token: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event, stage1_production_ledger_enabled

        if not stage1_production_ledger_enabled(st, session):
            return
    except ImportError:
        return
    auth = focused_auth_state(session)
    payload: dict[str, Any] = {
        "diagnostic_run_id": str(session.get("_solo_stage1_run_id") or "")[:40],
        "streamlit_session_id": str(session.get("_solo_stage1_streamlit_session_id") or "")[:64],
        "harness_transaction_id": str(session.get(SOLO_P8_HARNESS_TXN_KEY) or "")[:32],
        "token_fingerprint": str(token or "")[:400],
        "processing_source": str((extra or {}).get("processing_source") or "")[:80],
        "callback_invocation_id": str((extra or {}).get("callback_invocation_id") or "")[:32],
        "script_run_seq": session.get("_solo_stage1_script_run_seq"),
        "focused_param_requested": auth.get("focused_param_requested"),
        "focused_authorized": auth.get("focused_authorized"),
        "focused_effective": auth.get("focused_effective"),
        "authorization_result": auth.get("authorization_result"),
        "denial_reason": str(auth.get("denial_reason") or "")[:120],
        "stop_reason": str((extra or {}).get("stop_reason") or "")[:120],
    }
    if extra:
        payload.update({k: v for k, v in extra.items() if k not in payload})
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        note_stage1_event(session, event, st=st, widget_key=widget_key, extra=payload)
    except ImportError:
        pass


def bootstrap_solo_p8_focused_binding(st: Any | None, session: dict[str, Any]) -> None:
    """Evaluate authorization once per run; rehydrate validated transaction across reruns."""
    param_requested = bool(st is not None and _qp_flag(st, "solo_p8_focused_binding"))
    txn_ok, txn_reason = _focused_transaction_valid(st, session)
    if not param_requested and txn_ok:
        ctx = get_effective_focused_binding_context(st, session)
        if ctx.get("effective"):
            _emit_focused_event(session, EVENT_EFFECTIVE, st=st, extra={"processing_source": "txn_rehydrate"})
        return

    if not param_requested:
        _store_auth_state(
            session,
            focused_param_requested=False,
            focused_authorized=False,
            focused_effective=False,
            authorization_result="ignored",
            denial_reason="param_not_requested",
        )
        if not txn_ok:
            session[SOLO_P8_FOCUSED_EFFECTIVE_KEY] = False
        return

    _store_auth_state(
        session,
        focused_param_requested=True,
        focused_authorized=False,
        focused_effective=False,
        authorization_result="pending",
        denial_reason="",
    )
    _emit_focused_event(session, EVENT_REQUESTED, st=st, extra={"processing_source": "bootstrap"})
    dev_ok, dev_reason = _diagnostic_developer_authorized(st, session)
    harness_ok, harness_reason, harness_id = _harness_marker_ok(st, session)
    build_ok, build_reason = _build_supports_focused_gate(session)

    if not dev_ok:
        denial = dev_reason
        authorized = False
    elif not harness_ok:
        denial = harness_reason
        authorized = False
    elif not build_ok:
        denial = build_reason
        authorized = False
    else:
        denial = ""
        authorized = True

    effective = authorized
    session[SOLO_P8_FOCUSED_EFFECTIVE_KEY] = bool(effective)
    _store_auth_state(
        session,
        focused_authorized=authorized,
        focused_effective=effective,
        authorization_result="authorized" if authorized else "denied",
        denial_reason=denial,
        harness_transaction_id=harness_id if harness_ok else "",
    )
    if authorized:
        try:
            from live_draft_solo_component_diagnostics import SOLO_DIAG_ENABLED_KEY, solo_component_diag_enabled

            diag_armed = bool(solo_component_diag_enabled(st, session) or session.get(SOLO_DIAG_ENABLED_KEY))
        except ImportError:
            diag_armed = False
        _persist_focused_transaction(
            session,
            harness_run_id=harness_id,
            authorized=True,
            component_diag_armed=diag_armed,
        )
    _emit_focused_event(
        session,
        EVENT_AUTHORIZED,
        st=st,
        extra={
            "processing_source": "bootstrap",
            "authorization_result": "authorized" if authorized else "denied",
            "denial_reason": denial,
        },
    )
    if effective:
        _emit_focused_event(session, EVENT_EFFECTIVE, st=st, extra={"processing_source": "bootstrap"})


def solo_p8_focused_binding_effective(st: Any | None, session: dict[str, Any]) -> bool:
    bootstrap_solo_p8_focused_binding(st, session)
    ctx = get_effective_focused_binding_context(st, session)
    return bool(ctx.get("effective"))


def solo_p8_focused_binding_active(st: Any | None, session: dict[str, Any]) -> bool:
    return solo_p8_focused_binding_effective(st, session)


def note_focused_stop_before_claim(
    st: Any | None,
    session: dict[str, Any],
    *,
    widget_key: str,
    token: str,
    stop_reason: str,
    processing_source: str,
    callback_invocation_id: str = "",
) -> None:
    _emit_focused_event(
        session,
        EVENT_STOP_BEFORE_CLAIM,
        st=st,
        widget_key=widget_key,
        token=token,
        extra={
            "stop_reason": stop_reason,
            "processing_source": processing_source,
            "callback_invocation_id": callback_invocation_id,
        },
    )


def note_focused_flush_blocked(
    st: Any | None,
    session: dict[str, Any],
    *,
    widget_key: str,
    token: str,
    processing_source: str = "flush_persistent_wake_delivery",
) -> None:
    _emit_focused_event(
        session,
        EVENT_FLUSH_BLOCKED,
        st=st,
        widget_key=widget_key,
        token=token,
        extra={"stop_reason": "focused_mode_active", "processing_source": processing_source},
    )


def note_focused_preclaim_blocked(
    st: Any | None,
    session: dict[str, Any],
    *,
    widget_key: str,
    token: str,
    deliver_gate_ctx: dict[str, Any] | None = None,
) -> None:
    ctx = deliver_gate_ctx or {}
    _emit_focused_event(
        session,
        EVENT_PRECLAIM_BLOCKED,
        st=st,
        widget_key=widget_key,
        token=token,
        extra={
            "stop_reason": "p8_focused_binding_stop_before_claim",
            "processing_source": str(ctx.get("canonical_source") or ctx.get("source") or "")[:80],
            "callback_invocation_id": str(ctx.get("callback_invocation_id") or "")[:32],
        },
    )


def complete_focused_diagnostic_handoff(
    st: Any | None,
    session: dict[str, Any],
    *,
    widget_key: str,
    raw_token: str,
    callback_invocation_id: str = "",
) -> None:
    try:
        from live_draft_prod_callback_handoff import (
            STATUS_STALE,
            get_handoff_record,
            mark_handoff_terminal,
        )

        rec = get_handoff_record(session, widget_key)
        if not isinstance(rec, dict):
            return
        if not rec.get("diagnostic_only"):
            return
        if raw_token and str(rec.get("raw_token") or "") != str(raw_token).strip():
            return
        mark_handoff_terminal(
            session,
            widget_key,
            raw_token=str(rec.get("raw_token") or raw_token),
            reason="focused_diagnostic_complete_no_claim",
            st=st,
            status=STATUS_STALE,
        )
    except ImportError:
        return
    live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
    _emit_focused_event(
        session,
        EVENT_HANDOFF_TERMINAL,
        st=st,
        widget_key=widget_key,
        token=raw_token,
        extra={
            "stop_reason": "focused_diagnostic_complete_no_claim",
            "processing_source": "complete_delivery_only_observation",
            "callback_invocation_id": callback_invocation_id,
            "room_id": str(live.get("draft_room_id") or live.get("draft_id") or "")[:32],
            "pick_index": live.get("current_pick_index"),
        },
    )


def handoff_reject_if_diagnostic_only_for_production(
    session: dict[str, Any],
    record: dict[str, Any] | None,
    *,
    st: Any | None = None,
) -> tuple[bool, str]:
    if not isinstance(record, dict) or not record.get("diagnostic_only"):
        return True, ""
    if solo_p8_focused_binding_effective(st, session):
        return True, ""
    return False, "handoff_diagnostic_only"
