"""Bound current-auth evaluation with source precedence (harness only)."""

from __future__ import annotations

from typing import Any

from playwright_auth_ledger_export import filter_ledger_rows
from playwright_auth_preflight_strict import _session_flag_present

AUTH_FINALIZE_DIAG1 = "AUTH_FINALIZE_DIAG1"
AUTH_FINALIZE_DIAG2 = "AUTH_FINALIZE_DIAG2"
AUTH_FINALIZE_DIAG3 = "AUTH_FINALIZE_DIAG3"
AUTH_FINALIZE_DIAG4 = "AUTH_FINALIZE_DIAG4"
AUTH_FINALIZE_DIAG8 = "AUTH_FINALIZE_DIAG8"

EVENT_BEFORE_START = "production_stage1_auth_state_before_start_control"


def _event_index(row: dict[str, Any]) -> int:
    eid = str(row.get("event_id") or "")
    if ":" in eid:
        try:
            return int(eid.split(":")[1])
        except ValueError:
            pass
    return int(row.get("event_index") or 0)


def _script_run_seq(row: dict[str, Any]) -> int:
    try:
        return int(row.get("script_run_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _row_matches_identity(
    row: dict[str, Any],
    *,
    diagnostic_run_id: str,
    streamlit_session_id: str,
) -> bool:
    if streamlit_session_id:
        rid = str(row.get("streamlit_session_id") or "")[:36]
        if rid and rid != streamlit_session_id[:36]:
            return False
    if diagnostic_run_id:
        run = str(row.get("diagnostic_run_id") or row.get("run_id") or "")[:64]
        if run and run != diagnostic_run_id[:64]:
            return False
    return True


def _latest_before_start_row(
    rows: list[dict[str, Any]],
    *,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any] | None:
    matches = [
        r
        for r in rows
        if str(r.get("event") or "") == EVENT_BEFORE_START
        and _row_matches_identity(r, diagnostic_run_id=diagnostic_run_id, streamlit_session_id=streamlit_session_id)
    ]
    if not matches:
        return None
    return max(matches, key=lambda r: (_script_run_seq(r), _event_index(r)))


def _dom_bound(current_auth_dom: dict[str, Any] | None) -> bool:
    if not isinstance(current_auth_dom, dict) or not current_auth_dom:
        return False
    return bool(str(current_auth_dom.get("streamlit_session_id") or "").strip())


def _current_restore_from_dom(dom: dict[str, Any]) -> str:
    cur = str(dom.get("current_restore_blocked_reason") or "").strip()
    if cur:
        return cur[:80]
    return str(dom.get("restore_blocked_reason") or "").strip()[:80]


def _latest_hydration_checkpoint(
    rows: list[dict[str, Any]],
    checkpoint: str,
    *,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any] | None:
    matches = [
        r
        for r in rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == checkpoint
        and _row_matches_identity(r, diagnostic_run_id=diagnostic_run_id, streamlit_session_id=streamlit_session_id)
    ]
    if not matches:
        return None
    return max(matches, key=lambda r: (_script_run_seq(r), _event_index(r)))


def _apply_ok_from_row(apply_row: dict[str, Any] | None) -> bool | None:
    if not apply_row:
        return None
    if apply_row.get("auth_session_complete") is True:
        return True
    if apply_row.get("auth_session_complete") is False:
        return False
    if apply_row.get("apply_return_ok") is True:
        return True
    if apply_row.get("authenticated_after") is True:
        flag = _session_flag_present(apply_row)
        if flag is True:
            return True
        if flag is not False:
            return True
    return False


def evaluate_bound_current_auth_state(
    *,
    current_auth_dom: dict[str, Any] | None = None,
    ledger_rows: list[dict[str, Any]],
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    start_enabled: bool = False,
    start_visible: bool = True,
) -> dict[str, Any]:
    """Merge bound signals with explicit field source attribution."""
    scoped, scope_meta = filter_ledger_rows(
        ledger_rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    dom = dict(current_auth_dom) if isinstance(current_auth_dom, dict) else {}
    before_start = _latest_before_start_row(
        scoped,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    apply_row = _latest_hydration_checkpoint(
        scoped,
        "apply_authenticated_user_exit",
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )

    out: dict[str, Any] = {
        "field_sources": {},
        "current_auth_dom_bound": _dom_bound(dom),
        "before_start_event_index": _event_index(before_start) if before_start else None,
        "before_start_script_run_seq": _script_run_seq(before_start) if before_start else None,
        "current_auth_script_run_seq": int(dom.get("script_run_seq") or 0) if dom else 0,
        "ledger_scope": scope_meta,
    }

    def pick_bool(field: str, dom_key: str, row_key: str | None = None) -> bool | None:
        row_key = row_key or dom_key
        if _dom_bound(dom) and isinstance(dom.get(dom_key), bool):
            out["field_sources"][field] = "current_auth_dom"
            return bool(dom.get(dom_key))
        if apply_row and field.startswith("apply_") is False and apply_row.get(row_key) is not None:
            if field == "is_authenticated" and apply_row.get("authenticated_after") is True:
                out["field_sources"][field] = "apply_exit_transition"
                return True
        if before_start and before_start.get(row_key) is not None:
            out["field_sources"][field] = "ledger_before_start_latest"
            return bool(before_start.get(row_key))
        if apply_row and apply_row.get(row_key) is not None:
            out["field_sources"][field] = "apply_exit_transition"
            return bool(apply_row.get(row_key))
        out["field_sources"][field] = "not_observed"
        return None

    out["session_flag_present"] = pick_bool("session_flag_present", "session_flag_present")
    out["is_authenticated"] = pick_bool("is_authenticated", "is_authenticated")
    out["auth_session_complete"] = pick_bool("auth_session_complete", "auth_session_complete")
    out["start_enabled"] = bool(start_enabled)
    out["start_visible"] = bool(start_visible)

    if _dom_bound(dom):
        out["field_sources"]["current_restore_blocked_reason"] = "current_auth_dom"
        out["current_restore_blocked_reason"] = _current_restore_from_dom(dom)
        out["restore_blocked_reason"] = out["current_restore_blocked_reason"]
    elif before_start:
        out["field_sources"]["current_restore_blocked_reason"] = "ledger_before_start_latest"
        out["current_restore_blocked_reason"] = str(before_start.get("restore_blocked_reason") or "").strip()[:80]
        out["restore_blocked_reason"] = out["current_restore_blocked_reason"]
    else:
        out["field_sources"]["current_restore_blocked_reason"] = "not_observed"
        out["current_restore_blocked_reason"] = ""
        out["restore_blocked_reason"] = ""

    apply_ok = _apply_ok_from_row(apply_row)
    out["apply_authenticated_user_ok"] = apply_ok
    out["field_sources"]["apply_authenticated_user_ok"] = (
        "apply_exit_transition" if apply_row else "not_observed"
    )

    if _dom_bound(dom):
        out["auth_hydration_source"] = str(dom.get("auth_hydration_source") or "")[:64]
        out["field_sources"]["auth_hydration_source"] = "current_auth_dom"
    elif before_start:
        out["auth_hydration_source"] = str(before_start.get("auth_hydration_source") or "")[:64]
        out["field_sources"]["auth_hydration_source"] = "ledger_before_start_latest"
    else:
        out["auth_hydration_source"] = ""
        out["field_sources"]["auth_hydration_source"] = "not_observed"

    return out


def classify_auth_finalize_diag(
    bound: dict[str, Any],
    *,
    legacy_strict: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Diagnostic-only inconsistency between bound current state and stale harness signals."""
    legacy = legacy_strict or {}
    evidence: dict[str, Any] = {
        "field_sources": bound.get("field_sources"),
        "before_start_event_index": bound.get("before_start_event_index"),
        "before_start_script_run_seq": bound.get("before_start_script_run_seq"),
        "current_auth_script_run_seq": bound.get("current_auth_script_run_seq"),
    }
    live_complete = (
        bound.get("is_authenticated") is True
        and bound.get("auth_session_complete") is True
        and bound.get("session_flag_present") is True
        and bool(bound.get("start_enabled"))
    )
    current_block = str(bound.get("current_restore_blocked_reason") or "").strip()
    stale_block = str(legacy.get("restore_blocked_reason") or "").strip()
    dom_seq = int(bound.get("current_auth_script_run_seq") or 0)
    bs_seq = int(bound.get("before_start_script_run_seq") or 0)

    if live_complete and current_block:
        return AUTH_FINALIZE_DIAG1, "live_auth_complete_current_restore_block_stale", evidence

    if live_complete and bs_seq and dom_seq > bs_seq:
        if legacy.get("is_authenticated") is False or legacy.get("auth_session_complete") is False:
            return AUTH_FINALIZE_DIAG2, "strict_evaluator_used_older_before_start_row", evidence

    apply_dom_ok = bound.get("apply_authenticated_user_ok") is True
    legacy_apply = legacy.get("apply_authenticated_user_ok")
    if apply_dom_ok and legacy_apply is False:
        return AUTH_FINALIZE_DIAG3, "apply_exit_success_misparsed_as_failure", evidence

    if live_complete and not current_block and apply_dom_ok:
        return "", "bound_current_state_consistent", evidence

    if live_complete and current_block and stale_block == current_block:
        return AUTH_FINALIZE_DIAG1, "restore_block_not_cleared_in_checkpoint", evidence

    if bound.get("current_auth_dom_bound") and live_complete is False:
        dom_complete = bound.get("auth_session_complete")
        if dom_complete is True and bound.get("is_authenticated") is False:
            return AUTH_FINALIZE_DIAG4, "current_checkpoint_internally_contradictory", evidence

    if legacy.get("failure") and live_complete and not current_block:
        return "", "legacy_failure_superseded_by_bound_state", evidence

    return AUTH_FINALIZE_DIAG8, "unclassified_diagnostic_inconsistency", evidence


def bound_state_passes_observability_resolved(bound: dict[str, Any]) -> bool:
    return (
        bool(bound.get("start_enabled"))
        and bound.get("session_flag_present") is True
        and bound.get("is_authenticated") is True
        and bound.get("auth_session_complete") is True
        and not str(bound.get("current_restore_blocked_reason") or "").strip()
        and bound.get("apply_authenticated_user_ok") is not False
    )


def resolve_auth_finalize_failure(
    bound: dict[str, Any],
    *,
    legacy_strict: dict[str, Any],
    prior_failure: str = "",
) -> tuple[str, str, str]:
    """
    Compare bound current state to legacy strict evaluation.
    Returns (failure_code, diag_classification, detail).
    """
    if bound_state_passes_observability_resolved(bound):
        return "", "", "bound_current_state_consistent"

    diag, detail, _ = classify_auth_finalize_diag(bound, legacy_strict=legacy_strict)
    if diag in (AUTH_FINALIZE_DIAG1, AUTH_FINALIZE_DIAG2, AUTH_FINALIZE_DIAG3):
        return "", diag, detail

    live_complete = (
        bound.get("is_authenticated") is True
        and bound.get("auth_session_complete") is True
        and bound.get("session_flag_present") is True
        and bool(bound.get("start_enabled"))
    )
    if live_complete and diag == AUTH_FINALIZE_DIAG4:
        return prior_failure or "auth_session_finalization_incomplete", diag, detail

    if prior_failure in ("auth_session_finalization_incomplete", "streamlit_auth_incomplete") and live_complete:
        return "", diag or AUTH_FINALIZE_DIAG8, detail or "legacy_failure_superseded_by_bound_state"

    return prior_failure, diag, detail
