"""Focused P8 binding setup boundary (harness only — not application defects)."""

from __future__ import annotations

from typing import Any

SETUP1 = "SETUP1 — START CONTROL NOT FOUND OR NOT ENABLED"
SETUP2 = "SETUP2 — START CLICK NOT DISPATCHED"
SETUP3 = "SETUP3 — START CLICK DISPATCHED BUT HANDLER NOT ENTERED"
SETUP4 = "SETUP4 — START HANDLER ENTERED BUT ROOM CREATION NOT ENTERED"
SETUP5 = "SETUP5 — ROOM CREATION ENTERED BUT FAILED OR RETURNED EMPTY"
SETUP6 = "SETUP6 — ROOM CREATED BUT FOCUSED HARNESS DID NOT DETECT IT"
SETUP7 = "SETUP7 — PAGE, FRAME, SESSION, OR CONTEXT CHANGED AFTER CLICK"
SETUP8 = "SETUP8 — LEDGER CAPTURE OR FILTER DROPPED START/ROOM EVENTS"
SETUP9 = "SETUP9 — AUTH/RESTORE/CLEANUP REMOVED THE NEW ROOM"
SETUP10 = "SETUP10 — SETUP SURFACE DISAPPEARED BEFORE AUTHORITATIVE PROOF"
SETUP11 = "SETUP11 — OTHER"

FOCUSED_SETUP_TRACE = "INVALID_FOCUSED_P8_SETUP_TRACE — START TRANSITION NOT AUTHORITATIVELY OBSERVED"

try:
    from p8_room_latch_reconcile import ACCEPTED_ROOM_CREATED
except ImportError:
    ACCEPTED_ROOM_CREATED = "ROOM_CREATED — ROOM_LATCH_RECONCILIATION_REQUIRED"


def _audit_counts(audit: dict[str, Any]) -> dict[str, int]:
    by = audit.get("by_event") or {}
    return {
        "handler_entered": int(audit.get("handler_entered_count") or len(by.get("production_stage1_start_handler_entered") or [])),
        "handler_exited": int(audit.get("handler_exited_count") or len(by.get("production_stage1_start_handler_exited") or [])),
        "room_creation_entered": len(by.get("production_stage1_room_creation_entered") or []),
        "room_creation_exited": len(by.get("production_stage1_room_creation_exited") or []),
    }


def classify_focused_setup_boundary(
    *,
    start_result: dict[str, Any],
    observability_empty: bool = False,
    legacy_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify first setup boundary for focused binding diagnostic.
    Does not treat setup_page_disappeared alone as room-not-created.
    """
    click = start_result.get("start_click") or {}
    transport = start_result.get("start_click_transport") or {}
    audit = start_result.get("start_audit_reconcile") or {}
    counts = _audit_counts(audit)
    created = str(
        start_result.get("room_id")
        or start_result.get("inferred_created_room_id")
        or audit.get("inferred_created_room_id")
        or ""
    ).upper()
    handler_entered = bool(start_result.get("handler_entered") or counts["handler_entered"])
    room_creation = bool(
        start_result.get("room_creation_success") or counts["room_creation_exited"] or counts["room_creation_entered"]
    )
    latch_pass = bool(start_result.get("room_latch_pass"))
    valid = bool(start_result.get("valid") or start_result.get("pre_expiration_ready"))

    legacy = legacy_draft or {}
    legacy_rid = ""
    for cp in legacy.get("checkpoints") or []:
        if cp.get("step") == "room_id_detected":
            legacy_rid = str(cp.get("room_id") or "").upper()

    if valid and latch_pass:
        return {"classification": "", "focused_p8_outcome": "", "reason": "setup_pass"}

    status_auth = start_result.get("room_status_authority") or {}
    if latch_pass and status_auth.get("status_in_progress_server"):
        pre = start_result.get("pre_expiration_resolution") or {}
        if pre.get("pre_expiration_ready") or (
            pre.get("status") == "in_progress" and str(start_result.get("expected_token") or "").strip()
        ):
            return {"classification": "", "focused_p8_outcome": "", "reason": "setup_pass_server_status"}

    latch_recon = start_result.get("latch_reconciliation") or {}
    token_resolved = bool(str(start_result.get("expected_token") or "").strip())
    if created and (token_resolved or start_result.get("deadline")) and handler_entered:
        if latch_pass or latch_recon.get("room_latch_pass"):
            if not valid:
                return {
                    "classification": str(latch_recon.get("classification") or "LATCHREC1"),
                    "focused_p8_outcome": FOCUSED_SETUP_TRACE,
                    "reason": "room_latch_pass_preexp_incomplete",
                    "room_hint": created,
                }
        return {
            "classification": str(latch_recon.get("classification") or "ROOM_LATCH_RECONCILIATION_REQUIRED"),
            "focused_p8_outcome": ACCEPTED_ROOM_CREATED,
            "reason": "room_created_latch_reconciliation_required",
            "room_hint": created,
        }

    if observability_empty and (handler_entered or created or legacy_rid):
        return {
            "classification": SETUP8,
            "focused_p8_outcome": FOCUSED_SETUP_TRACE,
            "reason": "ledger_capture_empty_with_start_or_room_signals",
            "legacy_room_id_hint": legacy_rid,
        }

    matches = click.get("start_matches") or transport.get("start_matches") or []
    enabled = [m for m in matches if isinstance(m, dict) and m.get("visible") and not m.get("disabled")]
    if matches and not enabled:
        return {"classification": SETUP1, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "start_not_enabled"}
    if not click.get("dom_click_dispatched") and not click.get("playwright_clicked") and not transport.get("dom_click_dispatched"):
        if not legacy.get("start_click", {}).get("playwright_clicked"):
            return {"classification": SETUP2, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "click_not_dispatched"}

    timeline = start_result.get("identity_timeline") or []
    if len(timeline) >= 2:
        first, last = timeline[0], timeline[-1]
        if first.get("streamlit_session_id") and last.get("streamlit_session_id"):
            if first.get("streamlit_session_id") != last.get("streamlit_session_id"):
                return {"classification": SETUP7, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "session_changed"}
        if first.get("page_object_id") and last.get("page_object_id"):
            if first.get("page_object_id") != last.get("page_object_id"):
                return {"classification": SETUP7, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "page_replaced"}

    if handler_entered and not room_creation and not created:
        return {"classification": SETUP4, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "handler_without_room_creation"}
    if room_creation and not created:
        return {"classification": SETUP5, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "room_creation_empty"}
    if not handler_entered and not created and not legacy_rid:
        if click.get("dom_click_dispatched") or legacy.get("start_click", {}).get("playwright_clicked"):
            return {"classification": SETUP3, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "click_without_handler_evidence"}

    if (created or legacy_rid) and not latch_pass and not valid:
        return {
            "classification": str((start_result.get("latch_reconciliation") or {}).get("classification") or SETUP10),
            "focused_p8_outcome": ACCEPTED_ROOM_CREATED if created else FOCUSED_SETUP_TRACE,
            "reason": "room_detected_latch_incomplete",
            "room_hint": created or legacy_rid,
        }

    if legacy.get("first_missing_criterion") == "setup_page_disappeared" or legacy_rid:
        return {
            "classification": SETUP10,
            "focused_p8_outcome": FOCUSED_SETUP_TRACE,
            "reason": "setup_surface_transition_without_authoritative_proof",
            "legacy_room_id_hint": legacy_rid,
        }

    cleanup = start_result.get("production_cleanup") or {}
    if cleanup.get("ok") is False:
        return {"classification": SETUP9, "focused_p8_outcome": FOCUSED_SETUP_TRACE, "reason": "cleanup_failed"}

    return {
        "classification": SETUP11,
        "focused_p8_outcome": FOCUSED_SETUP_TRACE,
        "reason": str(start_result.get("first_missing_pre_expiration") or "unknown"),
    }


def setup_disappearance_is_not_room_not_created(*, legacy_first_missing: str, room_hint: str) -> bool:
    """Regression helper: legacy flag alone must not imply room-not-created."""
    if legacy_first_missing != "setup_page_disappeared":
        return False
    return bool(str(room_hint or "").strip())
