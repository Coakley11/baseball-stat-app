"""Stage-1 auth / Start-arm snapshot diagnostics (ledger only; no behavior changes)."""

from __future__ import annotations

import inspect
from typing import Any

from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_START_RERUN_SNAPSHOT_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    AUTH_PROTECTED_SESSION_KEYS,
    auth_session_complete,
    is_auth_enabled,
    is_authenticated,
    snapshot_auth_session,
)

EVENT_AUTH_BEFORE_START = "production_stage1_auth_state_before_start_control"
EVENT_SNAPSHOT_CAPTURE = "production_stage1_auth_snapshot_capture"
EVENT_SNAPSHOT_BEFORE_RERUN = "production_stage1_auth_snapshot_before_rerun"
EVENT_SNAPSHOT_RESTORE_ATTEMPT = "production_stage1_auth_snapshot_restore_attempt"
EVENT_SNAPSHOT_POST_RESTORE = "production_stage1_auth_snapshot_post_restore"
EVENT_AUTH_MUTATION = "production_stage1_auth_state_mutation"

TRACE_MUTATIONS_KEY = "_solo_auth_diag_trace_mutations"
SNAPSHOT_SOURCE_SID_KEY = "_solo_auth_snapshot_source_streamlit_session_id"
SNAPSHOT_SOURCE_OBJ_ID_KEY = "_solo_auth_snapshot_source_session_object_id"

_AUTH_MUTATION_KEYS = frozenset(
    {
        AUTH_SESSION_KEY,
        AUTH_USER_EMAIL_KEY,
        AUTH_USER_ID_KEY,
        AUTH_TOKENS_KEY,
        AUTH_START_RERUN_SNAPSHOT_KEY,
        "_live_draft_restore_blocked_reason",
    }
)


def _streamlit_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _suite_sid_present(st: Any | None) -> bool:
    if st is None:
        return False
    try:
        from suite_auth_browser import SESSION_STATE_SID_KEY, SESSION_QUERY_PARAM

        sid = str(st.session_state.get(SESSION_STATE_SID_KEY) or "").strip()
        if sid:
            return True
        raw = st.query_params.get(SESSION_QUERY_PARAM)
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        return bool(str(raw or "").strip())
    except Exception:
        return False


def auth_session_complete_breakdown(session: dict[str, Any]) -> dict[str, Any]:
    tokens = dict(session.get(AUTH_TOKENS_KEY) or {})
    enabled = bool(is_auth_enabled())
    session_flag = bool(session.get(AUTH_SESSION_KEY)) if enabled else True
    user_id_present = bool(str(session.get(AUTH_USER_ID_KEY) or "").strip())
    email_present = bool(str(session.get(AUTH_USER_EMAIL_KEY) or "").strip())
    access_present = bool(str(tokens.get("access_token") or "").strip())
    refresh_present = bool(str(tokens.get("refresh_token") or "").strip())
    complete = bool(auth_session_complete(session)) if enabled else True
    return {
        "auth_enabled": enabled,
        "session_flag_present": session_flag,
        "auth_user_id_present": user_id_present,
        "auth_email_present": email_present,
        "access_token_present": access_present,
        "refresh_token_present": refresh_present,
        "auth_session_complete": complete,
        "is_authenticated": bool(is_authenticated(session)) if enabled else True,
    }


def snapshot_field_presence(snap: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(snap, dict) or not snap:
        return {f"snap_{k}_present": False for k in AUTH_PROTECTED_SESSION_KEYS}
    out: dict[str, bool] = {}
    for key in AUTH_PROTECTED_SESSION_KEYS:
        out[f"snap_{key}_present"] = key in snap and snap.get(key) not in (None, "", {})
    return out


def _note(session: dict[str, Any], event: str, *, st: Any | None = None, extra: dict[str, Any] | None = None) -> None:
    try:
        from live_draft_stage1_production_ledger import note_stage1_event

        payload = {
            "streamlit_session_id": _streamlit_session_id(),
            "session_object_id": id(session),
            "diagnostic_run_id": "",
            "restore_blocked_reason": str(session.get("_live_draft_restore_blocked_reason") or ""),
            **auth_session_complete_breakdown(session),
        }
        try:
            from live_draft_stage1_production_ledger import ensure_stage1_run_id

            payload["diagnostic_run_id"] = ensure_stage1_run_id(session)
        except ImportError:
            pass
        try:
            from live_draft_stage1_production_ledger import STAGE1_SCRIPT_SEQ_KEY

            payload["script_run_seq"] = int(session.get(STAGE1_SCRIPT_SEQ_KEY) or 0)
        except ImportError:
            pass
        if extra:
            payload.update(extra)
        note_stage1_event(session, event, st=st, extra=payload)
    except ImportError:
        pass


def emit_auth_state_before_start_control(session: dict[str, Any], *, st: Any | None = None) -> None:
    """Deprecated wrapper — use live_draft_auth_prestart_stage1_diag.emit_auth_state_before_start_control."""
    try:
        from live_draft_auth_prestart_stage1_diag import emit_auth_state_before_start_control as _emit

        _emit(session, st=st, start_button_enabled=None)
    except ImportError:
        pass


def record_auth_snapshot_capture(session_state: dict[str, Any], *, st: Any | None = None) -> None:
    """Same capture rules as production; emits capture diagnostics."""
    attempted = True
    accepted = False
    rejection_reason = ""
    if not is_auth_enabled():
        rejection_reason = "auth_disabled"
    elif not auth_session_complete(session_state):
        breakdown = auth_session_complete_breakdown(session_state)
        if not breakdown.get("session_flag_present"):
            rejection_reason = "session_flag_missing"
        elif not breakdown.get("auth_user_id_present"):
            rejection_reason = "auth_user_id_missing"
        elif not breakdown.get("access_token_present"):
            rejection_reason = "access_token_missing"
        elif not breakdown.get("refresh_token_present"):
            rejection_reason = "refresh_token_missing"
        else:
            rejection_reason = "auth_session_incomplete"
    else:
        session_state[AUTH_START_RERUN_SNAPSHOT_KEY] = snapshot_auth_session(session_state)
        session_state[TRACE_MUTATIONS_KEY] = True
        sid = _streamlit_session_id()
        session_state[SNAPSHOT_SOURCE_SID_KEY] = sid
        session_state[SNAPSHOT_SOURCE_OBJ_ID_KEY] = id(session_state)
        try:
            from live_draft_auth_snapshot_stage1_diag import trace_auth_key_set

            trace_auth_key_set(session_state, AUTH_START_RERUN_SNAPSHOT_KEY, st=st)
        except ImportError:
            pass
        accepted = True
        rejection_reason = ""
    snap = session_state.get(AUTH_START_RERUN_SNAPSHOT_KEY)
    _note(
        session_state,
        EVENT_SNAPSHOT_CAPTURE,
        st=st,
        extra={
            "capture_attempted": attempted,
            "capture_accepted": accepted,
            "rejection_reason": rejection_reason,
            "source_auth_session_complete_breakdown": auth_session_complete_breakdown(session_state),
            "snapshot_key_created": AUTH_START_RERUN_SNAPSHOT_KEY in session_state,
            "source_streamlit_session_id": str(session_state.get(SNAPSHOT_SOURCE_SID_KEY) or _streamlit_session_id()),
            "source_session_object_id": session_state.get(SNAPSHOT_SOURCE_OBJ_ID_KEY) or id(session_state),
            **snapshot_field_presence(snap if isinstance(snap, dict) else None),
        },
    )


def emit_auth_snapshot_before_rerun(session: dict[str, Any], *, st: Any | None = None) -> None:
    snap = session.get(AUTH_START_RERUN_SNAPSHOT_KEY)
    snap_complete = isinstance(snap, dict) and bool(snap) and auth_session_complete(
        {**session, **snap} if isinstance(snap, dict) else session
    )
    _note(
        session,
        EVENT_SNAPSHOT_BEFORE_RERUN,
        st=st,
        extra={
            "snapshot_key_present": AUTH_START_RERUN_SNAPSHOT_KEY in session,
            "snapshot_complete": bool(snap_complete),
            "current_session_flag_present": bool(session.get(AUTH_SESSION_KEY)),
            "current_is_authenticated": bool(is_authenticated(session)) if is_auth_enabled() else True,
            **snapshot_field_presence(snap if isinstance(snap, dict) else None),
        },
    )


def emit_auth_snapshot_restore_attempt(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    snap = session.get(AUTH_START_RERUN_SNAPSHOT_KEY)
    source_sid = str(session.get(SNAPSHOT_SOURCE_SID_KEY) or "")
    current_sid = _streamlit_session_id()
    before = auth_session_complete_breakdown(session)
    restore_attempted = isinstance(snap, dict) and bool(snap)
    restore_accepted = False
    rejection_reason = ""
    if not is_auth_enabled():
        rejection_reason = "auth_disabled"
    elif not isinstance(snap, dict) or not snap:
        rejection_reason = "snapshot_absent"
    else:
        from suite_auth import restore_auth_session_snapshot

        sid_mismatch = bool(source_sid and current_sid and source_sid != current_sid)
        restore_auth_session_snapshot(session, snap)
        restore_accepted = bool(auth_session_complete(session))
        if not restore_accepted:
            rejection_reason = "restored_snapshot_still_incomplete"
        elif sid_mismatch:
            rejection_reason = ""
    after = auth_session_complete_breakdown(session)
    keys_restored = {
        f"restored_{k}_present": bool(session.get(k)) for k in (AUTH_SESSION_KEY, AUTH_USER_ID_KEY, AUTH_TOKENS_KEY)
    }
    extra = {
        "snapshot_key_present": isinstance(snap, dict) and bool(snap),
        "snapshot_source_session_id": source_sid,
        "current_streamlit_session_id": current_sid,
        "same_streamlit_session_id": bool(not source_sid or not current_sid or source_sid == current_sid),
        "restore_attempted": restore_attempted,
        "restore_accepted": restore_accepted,
        "rejection_reason": rejection_reason,
        "authenticated_before_restore": before.get("is_authenticated"),
        "authenticated_after_restore": after.get("is_authenticated"),
        **keys_restored,
        **snapshot_field_presence(snap if isinstance(snap, dict) else None),
    }
    _note(session, EVENT_SNAPSHOT_RESTORE_ATTEMPT, st=st, extra=extra)
    return extra


def emit_auth_snapshot_post_restore(session: dict[str, Any], *, st: Any | None = None, context: str = "") -> None:
    _note(
        session,
        EVENT_SNAPSHOT_POST_RESTORE,
        st=st,
        extra={
            "context": str(context or "")[:120],
            "snapshot_key_present": AUTH_START_RERUN_SNAPSHOT_KEY in session,
            "suite_sid_present": _suite_sid_present(st),
        },
    )


def note_auth_state_mutation(
    session: dict[str, Any],
    *,
    operation: str,
    key: str,
    before_present: bool,
    after_present: bool,
    st: Any | None = None,
    source_function: str = "",
    source_line: int = 0,
) -> None:
    if not session.get(TRACE_MUTATIONS_KEY):
        return
    if key not in _AUTH_MUTATION_KEYS and key not in AUTH_PROTECTED_SESSION_KEYS:
        return
    category = "auth_session_flag" if key == AUTH_SESSION_KEY else "auth_token" if key == AUTH_TOKENS_KEY else key
    _note(
        session,
        EVENT_AUTH_MUTATION,
        st=st,
        extra={
            "operation": str(operation or "")[:40],
            "key": str(key or "")[:80],
            "key_category": str(category)[:80],
            "value_present_before": bool(before_present),
            "value_present_after": bool(after_present),
            "source_function": str(source_function or "")[:120],
            "source_line": int(source_line or 0),
        },
    )


def _caller_location() -> tuple[str, int]:
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None or frame.f_back.f_back is None:
        return "", 0
    caller = frame.f_back.f_back
    return str(caller.f_code.co_name or ""), int(caller.f_lineno or 0)


def trace_auth_key_pop(session: dict[str, Any], key: str, *, st: Any | None = None) -> None:
    before = key in session and session.get(key) not in (None, "", {})
    session.pop(key, None)
    after = key in session and session.get(key) not in (None, "", {})
    fn, ln = _caller_location()
    note_auth_state_mutation(
        session,
        operation="pop",
        key=key,
        before_present=before,
        after_present=after,
        st=st,
        source_function=fn,
        source_line=ln,
    )
    try:
        from live_draft_auth_prestart_stage1_diag import note_prestart_mutation

        note_prestart_mutation(
            session,
            operation="pop",
            key=key,
            before_present=before,
            after_present=after,
            st=st,
            source_function=fn,
            source_line=ln,
        )
    except ImportError:
        pass


def trace_auth_key_set(session: dict[str, Any], key: str, *, st: Any | None = None) -> None:
    before = key in session and session.get(key) not in (None, "", {})
    fn, ln = _caller_location()
    note_auth_state_mutation(
        session,
        operation="set",
        key=key,
        before_present=before,
        after_present=True,
        st=st,
        source_function=fn,
        source_line=ln,
    )


def trace_restore_blocked_reason(session: dict[str, Any], reason: str, *, st: Any | None = None) -> None:
    key = "_live_draft_restore_blocked_reason"
    before = bool(str(session.get(key) or "").strip())
    session[key] = str(reason or "")
    fn, ln = _caller_location()
    note_auth_state_mutation(
        session,
        operation="set",
        key=key,
        before_present=before,
        after_present=bool(str(reason or "").strip()),
        st=st,
        source_function=fn,
        source_line=ln,
    )
