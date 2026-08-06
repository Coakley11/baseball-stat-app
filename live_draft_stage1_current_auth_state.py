"""Overwrite-in-place current auth observability probe (diagnostics only; no secrets)."""

from __future__ import annotations

import time
from typing import Any

from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    is_auth_enabled,
    is_authenticated,
)

CURRENT_AUTH_PROBE_ID = "solo-stage1-current-auth-state"
AUTH_TRANSITION_PROBE_ID = "solo-stage1-auth-transition-snapshot"


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _suite_sid_prefix(st: Any | None) -> str:
    if st is None:
        return ""
    try:
        from suite_auth_browser import SESSION_QUERY_PARAM, SESSION_STATE_SID_KEY

        sid = str(st.session_state.get(SESSION_STATE_SID_KEY) or "").strip()
        if not sid:
            raw = st.query_params.get(SESSION_QUERY_PARAM)
            if isinstance(raw, list):
                raw = raw[0] if raw else ""
            sid = str(raw or "").strip()
        return sid[:8] if sid else ""
    except Exception:
        return ""


def _token_presence(session: dict[str, Any]) -> tuple[bool, bool]:
    tokens = dict(session.get(AUTH_TOKENS_KEY) or {})
    access = bool(str(tokens.get("access_token") or "").strip())
    refresh = bool(str(tokens.get("refresh_token") or "").strip())
    return access, refresh


def _bridge_lookup_status(session: dict[str, Any]) -> str:
    reason = str(session.get("_suite_auth_last_bridge_lookup") or "").strip()
    if reason:
        return reason[:40]
    loaded = bool(session.get("_suite_auth_browser_restored"))
    if loaded:
        return "record_found"
    if session.get("_suite_auth_last_hydration_source") == "already_complete":
        return "already_complete"
    return "unknown"


def build_current_auth_state_payload(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    start_visible: bool = True,
    start_enabled: bool = False,
) -> dict[str, Any]:
    """Non-secret current auth snapshot for DOM export."""
    access, refresh = _token_presence(session)
    auth_on = bool(is_auth_enabled())
    return {
        "deployment_sha": str(session.get("_solo_stage1_deployment_sha") or "")[:7],
        "streamlit_session_id": _streamlit_session_id(),
        "diagnostic_run_id": str(session.get("_solo_stage1_run_id") or "")[:64],
        "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        "suite_sid_prefix": _suite_sid_prefix(st),
        "session_flag_present": bool(session.get(AUTH_SESSION_KEY)) if auth_on else True,
        "auth_user_id_present": bool(str(session.get(AUTH_USER_ID_KEY) or "").strip()) if auth_on else True,
        "auth_email_present": bool(str(session.get(AUTH_USER_EMAIL_KEY) or "").strip()) if auth_on else True,
        "access_token_present": access if auth_on else True,
        "refresh_token_present": refresh if auth_on else True,
        "is_authenticated": bool(is_authenticated(session)) if auth_on else True,
        "auth_session_complete": bool(auth_session_complete(session)) if auth_on else True,
        "auth_hydration_source": str(session.get("_suite_auth_last_hydration_source") or "")[:64],
        "bridge_lookup_status": _bridge_lookup_status(session)[:40],
        "restore_blocked_reason": str(session.get("_live_draft_restore_blocked_reason") or "")[:80],
        "start_visible": bool(start_visible),
        "start_enabled": bool(start_enabled),
        "probe_ts": time.time(),
    }


def render_stage1_current_auth_state_probe(
    st: Any,
    session: dict[str, Any],
    *,
    start_visible: bool = True,
    start_enabled: bool = False,
) -> None:
    try:
        from live_draft_stage1_production_ledger import stage1_production_ledger_enabled
    except ImportError:
        return
    if not stage1_production_ledger_enabled(st, session):
        return
    payload = build_current_auth_state_payload(
        session,
        st=st,
        start_visible=start_visible,
        start_enabled=start_enabled,
    )
    session["_solo_stage1_current_auth_state"] = dict(payload)
    attrs = " ".join(
        f'data-{k.replace("_", "-")}="{str(v).lower() if isinstance(v, bool) else str(v)}"'
        for k, v in payload.items()
        if k != "probe_ts"
    )
    st.markdown(
        f'<div id="{CURRENT_AUTH_PROBE_ID}" {attrs} data-probe-ts="{payload["probe_ts"]}"></div>',
        unsafe_allow_html=True,
    )
    try:
        from live_draft_stage1_production_ledger import render_stage1_auth_transition_probe

        render_stage1_auth_transition_probe(st, session)
    except ImportError:
        pass
