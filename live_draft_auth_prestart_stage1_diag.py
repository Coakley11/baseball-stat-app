"""Pre-Start auth hydration diagnostics (ledger only; no behavior changes)."""

from __future__ import annotations

import inspect
from typing import Any

from live_draft_auth_snapshot_stage1_diag import auth_session_complete_breakdown
from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    is_auth_enabled,
    is_authenticated,
)

EVENT_AUTH_BEFORE_START = "production_stage1_auth_state_before_start_control"
EVENT_PRESTART_HYDRATION = "production_stage1_auth_prestart_hydration"
EVENT_PRESTART_MUTATION = "production_stage1_auth_prestart_mutation"

PRESTART_TRACE_ARMED_KEY = "_solo_auth_prestart_trace_armed"
_PRESTART_MUTATION_KEYS = frozenset(
    {
        AUTH_SESSION_KEY,
        AUTH_USER_EMAIL_KEY,
        AUTH_USER_ID_KEY,
        AUTH_TOKENS_KEY,
        "_suite_auth_browser_restored",
        "_suite_auth_last_hydration_source",
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


def _protected_key_presence(session: dict[str, Any]) -> dict[str, bool]:
    tokens = dict(session.get(AUTH_TOKENS_KEY) or {})
    return {
        "session_flag_present": bool(session.get(AUTH_SESSION_KEY)),
        "auth_user_id_present": bool(str(session.get(AUTH_USER_ID_KEY) or "").strip()),
        "auth_email_present": bool(str(session.get(AUTH_USER_EMAIL_KEY) or "").strip()),
        "access_token_present": bool(str(tokens.get("access_token") or "").strip()),
        "refresh_token_present": bool(str(tokens.get("refresh_token") or "").strip()),
    }


def _note(session: dict[str, Any], event: str, *, st: Any | None = None, extra: dict[str, Any] | None = None) -> None:
    try:
        from live_draft_stage1_production_ledger import ensure_stage1_run_id, note_stage1_event

        payload: dict[str, Any] = {
            "streamlit_session_id": _streamlit_session_id(),
            "session_object_id": id(session),
            "diagnostic_run_id": ensure_stage1_run_id(session),
            **auth_session_complete_breakdown(session),
        }
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


def arm_prestart_mutation_trace(session: dict[str, Any], *, reason: str = "") -> None:
    session[PRESTART_TRACE_ARMED_KEY] = True
    if reason:
        session["_solo_auth_prestart_trace_arm_reason"] = str(reason)[:120]


def _restore_block_ledger_fields(session: dict[str, Any]) -> dict[str, Any]:
    try:
        from live_draft_stage1_current_auth_state import restore_block_observability_fields

        auth_on = bool(is_auth_enabled())
        return restore_block_observability_fields(session, auth_on=auth_on)
    except ImportError:
        current = str(session.get("_live_draft_restore_blocked_reason") or "").strip()[:80]
        return {
            "current_restore_blocked_reason": current,
            "last_restore_failure_reason": str(session.get("_live_draft_last_restore_failure_reason") or "")[:80],
            "last_restore_failure_seq": int(session.get("_live_draft_last_restore_failure_seq") or 0),
            "restore_blocked_reason": current,
        }


def emit_prestart_hydration_checkpoint(
    session: dict[str, Any],
    checkpoint: str,
    *,
    st: Any | None = None,
    authenticated_before: bool | None = None,
    authenticated_after: bool | None = None,
    hydration_attempted: bool | None = None,
    hydration_skipped: bool | None = None,
    skip_or_failure_reason: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    keys_before = _protected_key_presence(session)
    _note(
        session,
        EVENT_PRESTART_HYDRATION,
        st=st,
        extra={
            "checkpoint": str(checkpoint or "")[:80],
            "suite_sid_present": _suite_sid_present(st),
            "auth_hydration_source": str(session.get("_suite_auth_last_hydration_source") or ""),
            "warm_workspace_skip": bool(session.get("_baseball_warm_startup_skipped")),
            **_restore_block_ledger_fields(session),
            "hydration_attempted": hydration_attempted,
            "hydration_skipped": hydration_skipped,
            "skip_or_failure_reason": str(skip_or_failure_reason or "")[:120],
            "authenticated_before": authenticated_before
            if authenticated_before is not None
            else bool(is_authenticated(session)) if is_auth_enabled() else True,
            "authenticated_after": authenticated_after
            if authenticated_after is not None
            else bool(is_authenticated(session)) if is_auth_enabled() else True,
            "protected_keys": keys_before,
            **(extra or {}),
        },
    )


def note_prestart_mutation(
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
    if not session.get(PRESTART_TRACE_ARMED_KEY):
        return
    if key not in _PRESTART_MUTATION_KEYS:
        return
    _note(
        session,
        EVENT_PRESTART_MUTATION,
        st=st,
        extra={
            "operation": str(operation or "")[:40],
            "key": str(key or "")[:80],
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


def trace_prestart_key_pop(session: dict[str, Any], key: str, *, st: Any | None = None) -> None:
    before = key in session and session.get(key) not in (None, "", {})
    session.pop(key, None)
    after = key in session and session.get(key) not in (None, "", {})
    fn, ln = _caller_location()
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


def trace_prestart_key_set(session: dict[str, Any], key: str, *, st: Any | None = None) -> None:
    before = key in session and session.get(key) not in (None, "", {})
    fn, ln = _caller_location()
    note_prestart_mutation(
        session,
        operation="set",
        key=key,
        before_present=before,
        after_present=True,
        st=st,
        source_function=fn,
        source_line=ln,
    )


def emit_auth_state_before_start_control(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    start_button_enabled: bool | None = None,
) -> None:
    """Unconditional setup-lobby checkpoint immediately before Start control render."""
    keys = _protected_key_presence(session)
    restore_attempted = bool(session.get("_suite_auth_last_restore_attempted"))
    restore_ok = bool(session.get("_suite_auth_last_restore_ok"))
    try:
        emit_prestart_hydration_checkpoint(
            session,
            "auth_session_complete_before_start_control",
            st=st,
            extra={
                "start_button_enabled": start_button_enabled,
                **keys,
            },
        )
    except Exception:
        pass
    _note(
        session,
        EVENT_AUTH_BEFORE_START,
        st=st,
        extra={
            "suite_sid_present": _suite_sid_present(st),
            "auth_hydration_source": str(session.get("_suite_auth_last_hydration_source") or ""),
            "auth_session_validation_ok": bool(auth_session_complete(session)) if is_auth_enabled() else True,
            "warm_workspace_skip": bool(session.get("_baseball_warm_startup_skipped")),
            **_restore_block_ledger_fields(session),
            "restore_attempted_last": restore_attempted,
            "restore_accepted_last": restore_ok,
            "start_button_enabled": start_button_enabled,
            **keys,
        },
    )


def emit_start_callback_before_snapshot(session: dict[str, Any], *, st: Any | None = None) -> None:
    emit_prestart_hydration_checkpoint(
        session,
        "start_callback_before_snapshot",
        st=st,
        extra={"start_button_enabled": None},
    )
