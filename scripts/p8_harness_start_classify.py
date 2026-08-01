"""Harness-only start path divergence (not application START boundaries)."""

from __future__ import annotations

from typing import Any

HARNESS_START1 = "HARNESS_START1 — DIFFERENT_SETUP_HELPER"
HARNESS_START2 = "HARNESS_START2 — DIFFERENT_NAVIGATION_OR_SURFACE"
HARNESS_START3 = "HARNESS_START3 — DIAGNOSTIC_RUN_ID_CHANGED"
HARNESS_START4 = "HARNESS_START4 — STREAMLIT_SESSION_CHANGED"
HARNESS_START5 = "HARNESS_START5 — POST_CLICK_PAGE_OR_CONTEXT_REPLACED"
HARNESS_START6 = "HARNESS_START6 — LEDGER_FILTER_DROPPED_HANDLER_ROWS"
HARNESS_START7 = "HARNESS_START7 — ROOM_CREATED_BY_ANOTHER_START_PATH"
HARNESS_START8 = "HARNESS_START8 — START_PROOF_POLLED_FROM_STALE_PAGE"
HARNESS_START9 = "HARNESS_START9 — CLEANUP_REMOVED_ACTIVE_ROOM"
HARNESS_START10 = "HARNESS_START10 — OTHER"

GATE_B_START_PATH_DIVERGENCE = (
    "INVALID_PRODUCTION_EXPIRATION_TRACE — GATE_B_START_PATH_OR_AUDIT_DIVERGENCE"
)

CANONICAL_HELPER_NAME = "establish_single_solo_live_draft"


def compare_harness_chains(
    *,
    reference: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    """Compare verified room-latch reference chain vs Gate B actual chain."""
    diffs: list[dict[str, Any]] = []
    keys = (
        "helper_name",
        "fresh_lobby_cleanup",
        "navigation_helper",
        "setup_surface_helper",
        "start_click_helper",
        "post_click_ledger_poll",
        "ledger_filter",
        "room_latch_verify",
    )
    for k in keys:
        ref_v = reference.get(k)
        act_v = actual.get(k)
        if ref_v != act_v:
            diffs.append({"field": k, "reference": ref_v, "actual": act_v})
    return {"diffs": diffs, "first_difference": diffs[0] if diffs else None}


ROOM_LATCH_REFERENCE_CHAIN: dict[str, Any] = {
    "helper_name": CANONICAL_HELPER_NAME,
    "fresh_lobby_cleanup": "ensure_fresh_setup_lobby",
    "navigation_helper": "goto_and_wake(production_url)",
    "setup_surface_helper": "ensure_p8_ldr_setup_surface",
    "start_click_helper": "dispatch_start_single_authoritative_click",
    "post_click_ledger_poll": "handler_exited_or_room_creation_exited",
    "ledger_filter": "filter_latch_ledger_rows",
    "room_latch_verify": "classify_room_latch_verify",
}


def classify_harness_start_divergence(
    *,
    result: dict[str, Any],
    identity_timeline: list[dict[str, Any]] | None = None,
    prior_identity: dict[str, Any] | None = None,
    audit_reconcile: dict[str, Any] | None = None,
    functional_start_label: str = "",
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "functional_start_label_suppressed": functional_start_label,
        "room_latch_pass": bool(result.get("room_latch_pass")),
        "pre_expiration_ready": bool(result.get("pre_expiration_ready")),
    }
    if audit_reconcile and audit_reconcile.get("audit_filter_mismatch"):
        audit["audit_reconcile"] = {
            "handler_entered_count": audit_reconcile.get("handler_entered_count"),
            "handler_exited_count": audit_reconcile.get("handler_exited_count"),
        }
        return _out(
            HARNESS_START6,
            audit,
            "ledger_filter_dropped_handler_rows",
            GATE_B_START_PATH_DIVERGENCE,
        )

    if functional_start_label.startswith("START8") and result.get("inferred_created_room_id"):
        return _out(
            HARNESS_START6,
            audit,
            "start8_with_authoritative_room_in_ledger",
            GATE_B_START_PATH_DIVERGENCE,
        )

    timeline = identity_timeline or result.get("identity_timeline") or []
    if len(timeline) >= 2:
        first = timeline[0]
        last = timeline[-1]
        if str(first.get("streamlit_session_id") or "") and str(last.get("streamlit_session_id") or ""):
            if first.get("streamlit_session_id") != last.get("streamlit_session_id"):
                return _out(HARNESS_START4, audit, "streamlit_session_changed", GATE_B_START_PATH_DIVERGENCE)
        if str(first.get("diagnostic_run_id") or "") and str(last.get("diagnostic_run_id") or ""):
            if first.get("diagnostic_run_id") != last.get("diagnostic_run_id"):
                return _out(HARNESS_START3, audit, "diagnostic_run_id_changed", GATE_B_START_PATH_DIVERGENCE)
        if first.get("page_url") and last.get("page_url") and first.get("page_url") != last.get("page_url"):
            if "active_page=Live" not in str(last.get("page_url") or ""):
                return _out(HARNESS_START5, audit, "post_click_url_changed", GATE_B_START_PATH_DIVERGENCE)

    if prior_identity and result.get("identity_before_click"):
        before = result["identity_before_click"]
        if prior_identity.get("browser_context_id") != before.get("browser_context_id"):
            return _out(HARNESS_START5, audit, "browser_context_replaced", GATE_B_START_PATH_DIVERGENCE)

    if result.get("stale_page_proof"):
        return _out(HARNESS_START8, audit, "stale_page_start_proof", GATE_B_START_PATH_DIVERGENCE)

    if int(result.get("click_count") or 0) != 1:
        return _out(HARNESS_START10, audit, "click_count_not_one", GATE_B_START_PATH_DIVERGENCE)

    if not result.get("room_latch_pass") and result.get("room_id"):
        return _out(HARNESS_START7, audit, "room_without_latch_pass", GATE_B_START_PATH_DIVERGENCE)

    missing = result.get("first_missing_pre_expiration") or "pre_expiration_not_ready"
    return _out(HARNESS_START10, audit, missing, GATE_B_START_PATH_DIVERGENCE)


def _out(code: str, audit: dict[str, Any], missing: str, boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_divergence": missing,
        "accepted_fail_label": boundary,
        "smallest_correction_boundary": code,
        "audit": audit,
    }
