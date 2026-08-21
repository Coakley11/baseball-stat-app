"""AUTH_HYDRATE7: bound-current-auth bridge hydration waiter (harness-only)."""

from __future__ import annotations

import os
import time
from typing import Any

AUTH_HYDRATE_FAIL_AUTH_API = "exception:AuthApiError"


def resolve_real_accounts_wake(*, bridge_restore_mode: bool) -> bool:
    raw = str(os.environ.get("BRIDGE_RESTORE_REAL_ACCOUNTS_WAKE") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return not bridge_restore_mode


def bridge_load_succeeded(ledger: list[dict[str, Any]], *, streamlit_session_id: str, diagnostic_run_id: str) -> bool:
    row = latest_hydration_checkpoint(
        ledger,
        "load_browser_auth_tokens_lookup",
        streamlit_session_id=streamlit_session_id,
        diagnostic_run_id=diagnostic_run_id,
    )
    if not row:
        return False
    if str(row.get("rejection_reason") or "").strip() not in ("", "ok"):
        return False
    return bool(row.get("access_token_present")) and bool(row.get("refresh_token_present"))


def latest_hydration_checkpoint(
    ledger: list[dict[str, Any]],
    checkpoint: str,
    *,
    streamlit_session_id: str = "",
    diagnostic_run_id: str = "",
) -> dict[str, Any] | None:
    matches = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == checkpoint
    ]
    # Hard current-run correlation: when SID/run filters are supplied, do not
    # fall back to unscoped/Context-A rows (stale evidence must not satisfy restore boundaries).
    if streamlit_session_id:
        matches = [
            r
            for r in matches
            if str(r.get("streamlit_session_id") or "")[:36] == streamlit_session_id[:36]
        ]
    if diagnostic_run_id:
        matches = [
            r
            for r in matches
            if str(r.get("diagnostic_run_id") or r.get("run_id") or "")[:64] == diagnostic_run_id[:64]
        ]
    if not matches:
        return None

    def _key(r: dict[str, Any]) -> tuple[int, int]:
        try:
            ei = int(str(r.get("event_id") or "").split(":")[1])
        except (IndexError, ValueError):
            ei = int(r.get("event_index") or 0)
        return (int(r.get("script_run_seq") or 0), ei)

    return max(matches, key=_key)


def hydration_fail_fast_from_restore_exit(restore_exit: dict[str, Any] | None) -> str:
    if not restore_exit:
        return ""
    reason = str(restore_exit.get("skip_or_failure_reason") or "").strip()
    if not reason:
        return ""
    if "AuthApiError" in reason:
        return AUTH_HYDRATE_FAIL_AUTH_API
    if reason.startswith("exception:"):
        return reason[:120]
    return ""


def hydration_fail_fast_from_restore_exception(restore_exception: dict[str, Any] | None) -> str:
    """Terminal AuthApiError / refresh_token_already_used on exception checkpoint."""
    if not restore_exception:
        return ""
    cls = str(restore_exception.get("exception_class") or "").strip()
    code = str(restore_exception.get("auth_code") or "").strip().lower()
    msg = str(restore_exception.get("message_sanitized") or "").lower()
    if code == "refresh_token_already_used" or "already used" in msg:
        return "exception:AuthApiError:refresh_token_already_used"
    if cls == "AuthApiError" or "AuthApiError" in cls:
        return AUTH_HYDRATE_FAIL_AUTH_API
    return ""


def bound_bridge_auth_only_passes(
    bound: dict[str, Any],
    *,
    suite_sid: str,
    url_sid: str,
    bridge_load_ok: bool,
) -> bool:
    """Authentication hydration without requiring Start (post-start / auth-only phase)."""
    if not suite_sid or url_sid != suite_sid:
        return False
    if not bridge_load_ok:
        return False
    if bound.get("session_flag_present") is not True:
        return False
    if bound.get("is_authenticated") is not True:
        return False
    if bound.get("auth_session_complete") is not True:
        return False
    if str(bound.get("current_restore_blocked_reason") or "").strip():
        return False
    if bound.get("apply_authenticated_user_ok") is False:
        return False
    return True


def bound_bridge_hydration_passes(
    bound: dict[str, Any],
    *,
    suite_sid: str,
    url_sid: str,
    bridge_load_ok: bool,
    start_enabled: bool,
    start_visible: bool = True,
    require_start: bool = True,
) -> bool:
    if not bound_bridge_auth_only_passes(
        bound, suite_sid=suite_sid, url_sid=url_sid, bridge_load_ok=bridge_load_ok
    ):
        return False
    if require_start and (not start_visible or not start_enabled):
        return False
    return True


def detect_restore_rerun_anomaly(
    ledger: list[dict[str, Any]],
    *,
    streamlit_session_id: str,
) -> dict[str, Any]:
    entries = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == "restore_auth_session_exit"
        and (not streamlit_session_id or str(r.get("streamlit_session_id") or "")[:36] == streamlit_session_id[:36])
    ]
    ok_after_ok = 0
    saw_ok = False
    auth_api = 0
    ok_count = 0
    for row in sorted(entries, key=lambda r: (int(r.get("script_run_seq") or 0), int(r.get("event_index") or 0))):
        reason = str(row.get("skip_or_failure_reason") or "")
        if reason == "ok":
            ok_count += 1
            if saw_ok:
                ok_after_ok += 1
            saw_ok = True
        elif "AuthApiError" in reason:
            auth_api += 1
            saw_ok = False
    return {
        "restore_exit_count": len(entries),
        "restore_exit_ok_count": ok_count,
        "restore_exit_auth_api_error_count": auth_api,
        "restore_after_successful_ok_count": ok_after_ok,
        "rerun_anomaly": ok_after_ok > 0,
    }


def summarize_hydration_sequence(
    ledger: list[dict[str, Any]],
    *,
    streamlit_session_id: str,
    diagnostic_run_id: str,
) -> list[dict[str, Any]]:
    checkpoints = (
        "load_browser_auth_tokens_lookup",
        "load_browser_auth_tokens",
        "restore_auth_session_entry",
        "restore_auth_session_exit",
        "restore_auth_session_exception",
        "apply_authenticated_user_entry",
        "apply_authenticated_user_exit",
        "restore_auth_session_after_apply",
        "bridge_restore_single_flight_skip",
        "bridge_restore_rotation_persist",
        "bridge_restore_3b_final",
    )
    seq: list[dict[str, Any]] = []
    for cp in checkpoints:
        row = latest_hydration_checkpoint(
            ledger,
            cp,
            streamlit_session_id=streamlit_session_id,
            diagnostic_run_id=diagnostic_run_id,
        )
        if not row:
            continue
        seq.append(
            {
                "checkpoint": cp,
                "script_run_seq": row.get("script_run_seq"),
                "skip_or_failure_reason": row.get("skip_or_failure_reason"),
                "authenticated_after": row.get("authenticated_after"),
                "exception_class": row.get("exception_class"),
                "auth_status": row.get("auth_status"),
            }
        )
    return seq
