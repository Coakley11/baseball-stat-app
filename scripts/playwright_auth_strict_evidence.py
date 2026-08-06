"""Strict auth evidence extraction for audit comparison (harness)."""

from __future__ import annotations

from typing import Any

from playwright_auth_ledger_export import (
    filter_ledger_rows,
    ledger_max_script_run_seq,
    max_ledger_event_index,
)
from playwright_auth_preflight_strict import (
    evaluate_strict_preflight,
    inspect_start_control,
    paired_transition_authenticated,
    suite_sid_from_url,
    _last_hydration,
)


def _prot(row: dict[str, Any], key: str) -> Any:
    prot = row.get("protected_keys")
    if isinstance(prot, dict) and key in prot:
        return prot.get(key)
    return row.get(key)


def _tri(val: Any) -> str:
    if val is True:
        return "true"
    if val is False:
        return "false"
    return "absent"


def _last_event(rows: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    matches = [r for r in rows if str(r.get("event") or "") == event]
    return matches[-1] if matches else None


def build_strict_auth_evidence(
    *,
    harness_sid: str,
    url: str,
    ledger_rows: list[dict[str, Any]],
    start_inspect: dict[str, Any],
    paired_authenticated: bool | None,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scoped, scope_meta = filter_ledger_rows(
        ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    url_sid = suite_sid_from_url(url)
    load_h = _last_hydration(scoped, "load_browser_auth_tokens")
    apply_h = _last_hydration(scoped, "apply_authenticated_user_exit")
    restore_h = _last_hydration(scoped, "restore_auth_session_exit")
    before_start = _last_event(scoped, "production_stage1_auth_state_before_start_control")
    ev = evaluation or evaluate_strict_preflight(
        harness_sid=harness_sid,
        url_sid=url_sid,
        ledger_rows=scoped,
        start_enabled=bool(start_inspect.get("enabled")),
        start_visible=bool(start_inspect.get("visible")),
        paired_authenticated=paired_authenticated,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    return {
        "ledger_max_index": max_ledger_event_index(scoped),
        "script_run_seq_max": ledger_max_script_run_seq(scoped),
        "script_run_seq_selected": scope_meta.get("max_script_run_seq_in_scope"),
        "ledger_scope": scope_meta,
        "suite_sid_url_prefix": url_sid[:8] if url_sid else "",
        "bridge_lookup": ev.get("bridge_lookup"),
        "hydration_source": ev.get("hydration_source")
        or (before_start or {}).get("auth_hydration_source")
        or (restore_h or {}).get("auth_hydration_source")
        or "",
        "session_flag_present": _tri(_prot(before_start or {}, "session_flag_present") if before_start else None),
        "auth_user_id_present": _tri(_prot(before_start or {}, "auth_user_id_present") if before_start else None),
        "auth_email_present": _tri(_prot(before_start or {}, "auth_email_present") if before_start else None),
        "access_token_present": _tri(_prot(before_start or {}, "access_token_present") if before_start else None),
        "refresh_token_present": _tri(_prot(before_start or {}, "refresh_token_present") if before_start else None),
        "is_authenticated": _tri((before_start or {}).get("is_authenticated") if before_start else None),
        "auth_session_complete": _tri((before_start or {}).get("auth_session_complete") if before_start else None),
        "apply_authenticated_user_ok": _tri(ev.get("apply_authenticated_user_ok")),
        "apply_transition_row_present": _tri(
            bool(apply_h and apply_h.get("authenticated_after") is True)
        ),
        "restore_blocked_reason": str((before_start or {}).get("restore_blocked_reason") or ev.get("restore_blocked_reason") or ""),
        "start_visible": _tri(start_inspect.get("visible")),
        "start_enabled": _tri(start_inspect.get("enabled")),
        "paired_transition_authenticated": _tri(paired_authenticated),
        "streamlit_auth_complete_eval": _tri(ev.get("streamlit_auth_complete")),
        "authenticated_restored_eval": _tri(ev.get("authenticated_restored")),
        "strict_failure": str(ev.get("failure") or ""),
        "current_state_authoritative": _tri(ev.get("current_state_authoritative")),
        "paired_transition_ignored": _tri(ev.get("paired_transition_ignored")),
        "incomplete_reason": ev.get("incomplete_reason") or "",
    }


def strict_preflight_from_page_scoped(
    page,
    *,
    harness_sid: str,
    ledger_rows: list[dict[str, Any]],
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any]:
    start = inspect_start_control(page)
    paired = paired_transition_authenticated(page)
    scoped, _ = filter_ledger_rows(
        ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    result = evaluate_strict_preflight(
        harness_sid=harness_sid,
        url_sid=suite_sid_from_url(page.url or ""),
        ledger_rows=scoped,
        start_enabled=bool(start.get("enabled")),
        start_visible=bool(start.get("visible")),
        paired_authenticated=paired,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    result["evidence"] = build_strict_auth_evidence(
        harness_sid=harness_sid,
        url=page.url or "",
        ledger_rows=ledger_rows,
        start_inspect=start,
        paired_authenticated=paired,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
        evaluation=result,
    )
    return result
