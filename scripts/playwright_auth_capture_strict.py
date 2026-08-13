"""Strict headed-capture evaluation (Cloud ledger; no secrets)."""

from __future__ import annotations

from typing import Any

from playwright_auth_preflight_strict import (
    PREFLIGHT_FAIL_NO_TOKEN_ROW,
    PREFLIGHT_FAIL_START_DISABLED,
    PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE,
    _last_hydration,
    evaluate_strict_preflight,
)

CAPTURE_FAIL_SID_DRIFT = "suite_sid_changed"
CAPTURE_FAIL_BRIDGE_PERSIST = "bridge_persistence_not_proven"
CAPTURE_FAIL_BRIDGE_PERSIST_SID = "bridge_persistence_sid_mismatch"
CAPTURE_FAIL_RESTORE_AUTH_REQUIRED = "restore_blocked_auth_required"
CAPTURE_FAIL_SIGNED_IN_ONLY = "signed_in_display_without_streamlit_auth"
CAPTURE_FAIL_SESSION_FLAG = "suite_auth_session_missing"
CAPTURE_FAIL_SESSION_FINALIZE = "auth_session_finalization_incomplete"


def _restore_blocked_from_ledger(ledger_rows: list[dict[str, Any]]) -> str:
    for row in reversed(ledger_rows):
        if str(row.get("event") or "") == "production_stage1_queueui_predicate_audit":
            return str(row.get("restore_blocked_reason") or "").strip()
        rb = str(row.get("restore_blocked_reason") or "").strip()
        if rb:
            return rb
    return ""


def _before_start_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [r for r in rows if str(r.get("event") or "") == "production_stage1_auth_state_before_start_control"]
    return matches[-1] if matches else None


def _flag_from_row(row: dict[str, Any] | None, key: str) -> bool:
    if not row:
        return False
    if key in row:
        return bool(row.get(key))
    prot = row.get("protected_keys")
    if isinstance(prot, dict) and key in prot:
        return bool(prot.get(key))
    return False


def _bridge_persist_row(ledger_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    readback = _last_hydration(ledger_rows, "save_browser_auth_tokens_readback")
    if readback:
        return readback
    return _last_hydration(ledger_rows, "save_browser_auth_tokens")


def bridge_persistence_proof(
    ledger_rows: list[dict[str, Any]],
    *,
    target_sid: str,
) -> dict[str, Any]:
    """Non-secret summary of save_browser_auth_tokens ledger checkpoint."""
    row = _bridge_persist_row(ledger_rows) or {}
    save_row = _last_hydration(ledger_rows, "save_browser_auth_tokens") or {}
    prefix = str(row.get("suite_sid_prefix") or save_row.get("suite_sid_prefix") or "").strip()
    target_prefix = str(target_sid or "")[:8]
    readback_ok = bool(row.get("readback_record_complete"))
    save_ok = bool(save_row.get("persistence_succeeded") or save_row.get("bridge_record_complete"))
    out: dict[str, Any] = {
        "persistence_attempted": bool(
            row.get("persistence_attempted")
            or row.get("save_reported_success")
            or save_row.get("persistence_attempted")
        ),
        "persistence_succeeded": bool(readback_ok or row.get("persistence_succeeded") or save_ok),
        "readback_succeeded": readback_ok,
        "failure_reason": str(row.get("failure_reason") or row.get("skip_or_failure_reason") or "")[:120],
        "suite_sid_prefix_match": bool(prefix and target_prefix and prefix == target_prefix),
        "access_token_present": bool(row.get("access_token_present") or save_row.get("access_token_present")),
        "refresh_token_present": bool(row.get("refresh_token_present") or save_row.get("refresh_token_present")),
        "auth_user_id_present": bool(row.get("auth_user_id_present") or save_row.get("auth_user_id_present")),
        "bridge_record_complete": bool(
            save_row.get("bridge_record_complete") or row.get("bridge_record_complete") or readback_ok
        ),
    }
    return out


def evaluate_strict_capture(
    *,
    target_sid: str,
    url_sid: str,
    ledger_rows: list[dict[str, Any]],
    start_enabled: bool,
    start_visible: bool,
    paired_authenticated: bool | None,
    signed_in_display: bool = False,
    restore_blocked_reason: str = "",
    current_auth_dom: dict[str, Any] | None = None,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any]:
    """All conditions required before writing harness auth files."""
    from playwright_auth_current_state_eval import (
        bound_state_passes_observability_resolved,
        evaluate_bound_current_auth_state,
        resolve_auth_finalize_failure,
    )

    bound = evaluate_bound_current_auth_state(
        current_auth_dom=current_auth_dom,
        ledger_rows=ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
        start_enabled=start_enabled,
        start_visible=start_visible,
    )
    out: dict[str, Any] = {
        "target_sid_prefix": target_sid[:8] if target_sid else "",
        "url_sid_prefix": url_sid[:8] if url_sid else "",
        "sid_stable": bool(target_sid and url_sid and target_sid == url_sid),
        "bridge_persisted": False,
        "strict_auth_passed": False,
        "start_enabled": bool(start_enabled),
        "start_visible": bool(start_visible),
        "auth_session_complete": bound.get("auth_session_complete"),
        "is_authenticated": bound.get("is_authenticated"),
        "session_flag_present": bound.get("session_flag_present"),
        "restore_blocked_reason": str(bound.get("current_restore_blocked_reason") or "")[:80],
        "current_restore_blocked_reason": str(bound.get("current_restore_blocked_reason") or "")[:80],
        "failure": "",
        "bridge_persistence": {},
        "bound_field_sources": bound.get("field_sources"),
        "auth_finalize_diag": "",
        "auth_finalize_diag_detail": "",
    }
    if not target_sid:
        out["failure"] = "target_suite_sid_missing"
        return out
    if url_sid and url_sid != target_sid:
        out["failure"] = CAPTURE_FAIL_SID_DRIFT
        return out

    load_row = _last_hydration(ledger_rows, "load_browser_auth_tokens")
    load_reason = ""
    if load_row and not load_row.get("browser_tokens_loaded"):
        load_reason = "token_record_missing"

    base = evaluate_strict_preflight(
        harness_sid=target_sid,
        url_sid=url_sid or target_sid,
        ledger_rows=ledger_rows,
        start_enabled=start_enabled,
        start_visible=start_visible,
        paired_authenticated=paired_authenticated,
        load_reason=load_reason,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
        current_auth_dom=current_auth_dom,
    )
    out.update(
        {
            "hydration_source": base.get("hydration_source") or bound.get("auth_hydration_source") or "",
            "apply_authenticated_user_ok": bound.get("apply_authenticated_user_ok")
            if bound.get("apply_authenticated_user_ok") is not None
            else base.get("apply_authenticated_user_ok"),
            "bridge_lookup": base.get("bridge_lookup"),
        }
    )

    resolved_failure, diag_class, diag_detail = resolve_auth_finalize_failure(
        bound,
        legacy_strict=base,
        prior_failure=str(base.get("failure") or ""),
    )
    out["auth_finalize_diag"] = diag_class
    out["auth_finalize_diag_detail"] = diag_detail

    persist = bridge_persistence_proof(ledger_rows, target_sid=target_sid)
    out["bridge_persistence"] = persist
    if persist.get("persistence_succeeded") and persist.get("bridge_record_complete"):
        out["bridge_persisted"] = True

    apply_row = _last_hydration(ledger_rows, "apply_authenticated_user_exit")
    before_start = _before_start_row(ledger_rows)
    session_flag = bound.get("session_flag_present")
    if session_flag is None:
        session_flag = _flag_from_row(apply_row, "session_flag_present") or _flag_from_row(
            before_start, "session_flag_present"
        )
    auth_complete = bound.get("auth_session_complete")
    if auth_complete is None:
        auth_complete = _flag_from_row(before_start, "auth_session_complete") or bool(
            base.get("streamlit_auth_complete")
        )
    is_auth = bound.get("is_authenticated")
    if is_auth is None:
        is_auth = _flag_from_row(before_start, "is_authenticated") or session_flag
    out["session_flag_present"] = session_flag
    out["is_authenticated"] = is_auth
    out["auth_session_complete"] = auth_complete
    if (bound.get("field_sources") or {}).get("is_authenticated") == "not_observed":
        out["is_authenticated"] = None
        out["auth_session_complete"] = None
        out["session_flag_present"] = None
        out["auth_state_observability"] = "not_observed"

    if signed_in_display and not base.get("streamlit_auth_complete") and not load_row:
        out["failure"] = CAPTURE_FAIL_SIGNED_IN_ONLY
        return out

    if base.get("failure") and not resolved_failure:
        out["failure"] = str(base["failure"])
        if out["failure"] == PREFLIGHT_FAIL_START_DISABLED and persist.get("persistence_succeeded"):
            out["failure"] = CAPTURE_FAIL_SESSION_FINALIZE
        elif out["failure"] == PREFLIGHT_FAIL_STREAMLIT_INCOMPLETE and persist.get("persistence_succeeded"):
            if bound_state_passes_observability_resolved(bound):
                out["failure"] = ""
        elif out["failure"] == PREFLIGHT_FAIL_NO_TOKEN_ROW and persist.get("persistence_succeeded"):
            if bound_state_passes_observability_resolved(bound) and persist.get("bridge_record_complete"):
                out["failure"] = ""
        if out["failure"]:
            return out
    elif base.get("failure") and resolved_failure:
        out["failure"] = resolved_failure
        if out["failure"]:
            return out

    if not session_flag:
        out["failure"] = CAPTURE_FAIL_SESSION_FLAG
        return out

    if not persist.get("persistence_succeeded") or not persist.get("suite_sid_prefix_match"):
        if persist.get("persistence_attempted") and not persist.get("suite_sid_prefix_match"):
            out["failure"] = CAPTURE_FAIL_BRIDGE_PERSIST_SID
        else:
            out["failure"] = CAPTURE_FAIL_BRIDGE_PERSIST
        return out
    if not persist.get("bridge_record_complete"):
        out["failure"] = CAPTURE_FAIL_BRIDGE_PERSIST
        return out

    rb = str(out.get("current_restore_blocked_reason") or out.get("restore_blocked_reason") or "").strip().lower()
    if rb == "auth_required" and not bound_state_passes_observability_resolved(bound):
        out["failure"] = CAPTURE_FAIL_RESTORE_AUTH_REQUIRED
        return out

    if bound_state_passes_observability_resolved(bound) and persist.get("persistence_succeeded"):
        out["bridge_persisted"] = True
        out["strict_auth_passed"] = True
        out["failure"] = ""
        return out

    out["failure"] = CAPTURE_FAIL_SESSION_FINALIZE
    return out


def metadata_has_no_secrets(metadata: dict[str, Any]) -> bool:
    """Reject metadata that embeds raw token-shaped strings."""
    import json
    import re

    text = json.dumps(metadata, default=str)
    if re.search(r'"access_token"\s*:\s*"[^"]{8,}', text):
        return False
    if re.search(r'"refresh_token"\s*:\s*"[^"]{8,}', text):
        return False
    if "eyj" in text.lower():
        return False
    return True
