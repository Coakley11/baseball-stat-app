"""
Browser auth persistence for Streamlit Cloud (C2b).

CookieManager/iframed cookies do not survive on Streamlit Cloud (component iframe
isolation). This module stores tokens in Supabase and keeps an opaque session id in
``st.query_params['suite_sid']``, which survives browser refresh on the same URL.

Synced to sibling repos.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

SESSION_QUERY_PARAM = "suite_sid"
SESSION_STATE_SID_KEY = "_suite_browser_session_id"
BROWSER_LOAD_REASON_KEY = "_suite_browser_auth_load_reason"
AUTH_USER_ID_SESSION_KEY = "_suite_auth_user_id"

InitState = Literal["ready"]


def init_browser_auth_storage(st: Any) -> InitState:
    """Query-param storage is synchronous — always ready."""
    return "ready"


def _session_id_from_st(st: Any) -> str:
    raw = st.query_params.get(SESSION_QUERY_PARAM)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    sid = str(raw or st.session_state.get(SESSION_STATE_SID_KEY) or "").strip()
    return sid


def sync_suite_sid_from_query(st: Any) -> str:
    """Bind opaque ``suite_sid`` from URL into session state before token lookup."""
    sid = _session_id_from_st(st)
    if sid:
        st.session_state[SESSION_STATE_SID_KEY] = sid
        try:
            if SESSION_QUERY_PARAM not in st.query_params:
                st.query_params[SESSION_QUERY_PARAM] = sid
        except Exception:
            pass
    return sid


def _set_session_id(st: Any, session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    st.session_state[SESSION_STATE_SID_KEY] = sid
    st.query_params[SESSION_QUERY_PARAM] = sid


def _clear_session_id(st: Any) -> None:
    st.session_state.pop(SESSION_STATE_SID_KEY, None)
    try:
        if SESSION_QUERY_PARAM in st.query_params:
            del st.query_params[SESSION_QUERY_PARAM]
    except Exception:
        pass


def _note_browser_load_reason(st: Any | None, reason: str) -> None:
    if st is None:
        return
    try:
        st.session_state[BROWSER_LOAD_REASON_KEY] = str(reason or "")[:120]
    except Exception:
        pass


def load_browser_auth_tokens(st: Any) -> dict[str, Any] | None:
    sid = sync_suite_sid_from_query(st)
    if not sid:
        _note_browser_load_reason(st, "suite_sid_missing")
        return None
    try:
        from suite_storage_supabase import load_browser_auth_session

        tokens = load_browser_auth_session(sid)
    except Exception as exc:
        _note_browser_load_reason(st, f"load_error:{type(exc).__name__}")
        return None
    if not tokens:
        _note_browser_load_reason(st, "token_record_missing")
        return None
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not access or not refresh:
        _note_browser_load_reason(st, "token_record_incomplete")
        return None
    st.session_state[SESSION_STATE_SID_KEY] = sid
    _note_browser_load_reason(st, "ok")
    return tokens


def _emit_save_browser_auth_checkpoint(st: Any, *, extra: dict[str, Any]) -> None:
    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(
            st.session_state,
            "save_browser_auth_tokens",
            st=st,
            skip_or_failure_reason=str(extra.get("failure_reason") or "")[:120],
            extra=extra,
        )
    except Exception:
        pass


def save_browser_auth_tokens(
    st: Any,
    tokens: dict[str, Any],
    *,
    auth_user_id: str = "",
) -> None:
    """Write tokens to Supabase and mirror opaque id in URL query params."""
    access = str((tokens or {}).get("access_token") or "").strip()
    refresh = str((tokens or {}).get("refresh_token") or "").strip()
    sid = sync_suite_sid_from_query(st) or str(uuid.uuid4())
    base_extra: dict[str, Any] = {
        "persistence_attempted": True,
        "persistence_succeeded": False,
        "failure_reason": "",
        "suite_sid_prefix": sid[:8] if sid else "",
        "access_token_present": bool(access),
        "refresh_token_present": bool(refresh),
        "auth_user_id_present": False,
        "bridge_record_complete": False,
    }
    if not access or not refresh:
        base_extra["failure_reason"] = "tokens_incomplete"
        base_extra["persistence_attempted"] = False
        _emit_save_browser_auth_checkpoint(st, extra=base_extra)
        return
    uid = str(auth_user_id or "").strip()
    if not uid:
        try:
            uid = str(st.session_state.get(AUTH_USER_ID_SESSION_KEY) or "").strip()
        except Exception:
            uid = ""
    base_extra["auth_user_id_present"] = bool(uid)
    if not uid:
        base_extra["failure_reason"] = "auth_user_id_missing"
        _emit_save_browser_auth_checkpoint(st, extra=base_extra)
        return
    if not sid:
        sid = str(uuid.uuid4())
    try:
        from suite_storage_supabase import load_browser_auth_session, save_browser_auth_session

        save_browser_auth_session(sid, user_id=uid, tokens=tokens)
    except Exception as exc:
        base_extra["failure_reason"] = f"save_error:{type(exc).__name__}"
        _emit_save_browser_auth_checkpoint(st, extra=base_extra)
        return
    _set_session_id(st, sid)
    try:
        from suite_storage_supabase import load_browser_auth_session

        row = load_browser_auth_session(sid)
        complete = bool(
            row
            and str(row.get("access_token") or "").strip()
            and str(row.get("refresh_token") or "").strip()
        )
        base_extra["bridge_record_complete"] = complete
        base_extra["persistence_succeeded"] = complete
        base_extra["failure_reason"] = "ok" if complete else "post_save_record_incomplete"
    except Exception as exc:
        base_extra["failure_reason"] = f"verify_error:{type(exc).__name__}"
        base_extra["persistence_succeeded"] = True
        base_extra["bridge_record_complete"] = False
    _emit_save_browser_auth_checkpoint(st, extra=base_extra)


def clear_browser_auth_tokens(st: Any) -> None:
    sid = _session_id_from_st(st)
    if sid:
        try:
            from suite_storage_supabase import invalidate_browser_auth_session

            invalidate_browser_auth_session(sid)
        except Exception:
            pass
    _clear_session_id(st)
    _note_browser_load_reason(st, "cleared")


def browser_auth_storage_status(st: Any) -> dict[str, Any]:
    """Dev diagnostics — no secret token values."""
    sid = _session_id_from_st(st)
    qp_raw = st.query_params.get(SESSION_QUERY_PARAM)
    out: dict[str, Any] = {
        "storage": "supabase_query_param",
        "session_id_present": bool(sid),
        "session_id_prefix": sid[:8] if sid else "",
        "query_param_present": bool(qp_raw),
        "cloud_payload_present": False,
        "cloud_payload_bytes": 0,
        "last_load_reason": str(st.session_state.get(BROWSER_LOAD_REASON_KEY) or ""),
    }
    if sid:
        try:
            from suite_storage_supabase import load_browser_auth_session

            payload = load_browser_auth_session(sid)
            if payload:
                out["cloud_payload_present"] = True
                out["cloud_payload_bytes"] = len(str(payload.get("access_token") or "")) + len(
                    str(payload.get("refresh_token") or "")
                )
        except Exception as exc:
            out["cloud_error"] = str(exc)[:120]
    return out


def ensure_browser_cookies_loaded(st: Any) -> bool:
    return True
