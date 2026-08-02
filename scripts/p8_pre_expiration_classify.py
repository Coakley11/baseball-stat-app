"""Pre-expiration gate classifications (harness only)."""

from __future__ import annotations

from typing import Any

PREEXP1 = "PREEXP1 — SERVER STATE COMPLETE, DOM DIAGNOSTIC FIELDS MISSING"
PREEXP2 = "PREEXP2 — PICK INDEX MISSING FROM ALL AUTHORITATIVE SOURCES"
PREEXP3 = "PREEXP3 — DEADLINE MISSING FROM ALL AUTHORITATIVE SOURCES"
PREEXP4 = "PREEXP4 — EXPECTED TOKEN MISSING OR CANNOT BE VALIDATED"
PREEXP5 = "PREEXP5 — SERVER TOKEN AND COUNTDOWN MOUNT TOKEN DIFFER"
PREEXP6 = "PREEXP6 — COUNTDOWN MOUNT EXISTS BUT DECLARATION CONTEXT IS STALE"
PREEXP7 = "PREEXP7 — COUNTDOWN ALREADY EXPIRED BEFORE HARNESS ARMED"
PREEXP8 = "PREEXP8 — ROOM/SESSION/RUN CONTEXT DIVERGED"
PREEXP9 = "PREEXP9 — AUTHORITATIVE SERVER STATE PARTIALLY LOST AFTER LATCH"
PREEXP10 = "PREEXP10 — OTHER"

ROOM_START_LATCH_PASS_INCOMPLETE = (
    "ROOM_START_AND_LATCH_PASS — PRE_EXPIRATION_EVIDENCE_RESOLUTION_INCOMPLETE"
)


def classify_pre_expiration_boundary(
    *,
    resolved: dict[str, Any],
    room_latch_pass: bool,
    identity_timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    audit = {
        "room_latch_pass": room_latch_pass,
        "pre_expiration_ready": bool(resolved.get("pre_expiration_ready")),
        "dom_diagnostics_missing": resolved.get("dom_diagnostics_missing"),
        "consistency": resolved.get("consistency"),
    }
    if resolved.get("pre_expiration_ready"):
        return _out("", audit, "", "")

    if not room_latch_pass:
        return _out(PREEXP10, audit, "room_latch_not_pass", ROOM_START_LATCH_PASS_INCOMPLETE)

    timeline = identity_timeline or []
    if len(timeline) >= 2:
        sids = {str(t.get("streamlit_session_id") or "") for t in timeline if t.get("streamlit_session_id")}
        runs = {str(t.get("diagnostic_run_id") or "") for t in timeline if t.get("diagnostic_run_id")}
        if len(sids) > 1 or len(runs) > 1:
            return _out(PREEXP8, audit, "session_or_run_diverged", ROOM_START_LATCH_PASS_INCOMPLETE)

    cons = resolved.get("consistency") or {}

    pick = resolved.get("pick_index")
    if pick is None:
        return _out(PREEXP2, audit, "pick_index_missing", ROOM_START_LATCH_PASS_INCOMPLETE)

    deadline = resolved.get("deadline")
    if deadline is None:
        return _out(PREEXP3, audit, "deadline_missing", ROOM_START_LATCH_PASS_INCOMPLETE)

    if cons.get("countdown_mounted") and not cons.get("deadline_not_expired"):
        return _out(PREEXP7, audit, "deadline_already_expired", ROOM_START_LATCH_PASS_INCOMPLETE)

    token = str(resolved.get("expected_token") or "")
    dom = resolved.get("dom_diagnostics_missing") or {}
    server_has_pick = bool(resolved.get("pick_index_source") and "ui" not in str(resolved.get("pick_index_source")))
    server_has_deadline = bool(resolved.get("deadline_source") and "ui" not in str(resolved.get("deadline_source")))

    if not token or not cons.get("token_parses"):
        if server_has_pick and server_has_deadline and pick == 0 and not token:
            return _out(PREEXP4, audit, "token_missing_despite_server_fields", ROOM_START_LATCH_PASS_INCOMPLETE)
        return _out(PREEXP4, audit, "expected_token_missing_or_invalid", ROOM_START_LATCH_PASS_INCOMPLETE)

    if not cons.get("token_matches_room") or not cons.get("token_pick_matches") or not cons.get("token_deadline_matches"):
        return _out(PREEXP5, audit, "token_parse_mismatch", ROOM_START_LATCH_PASS_INCOMPLETE)

    if not cons.get("countdown_mounted"):
        return _out(PREEXP6, audit, "countdown_not_mounted", ROOM_START_LATCH_PASS_INCOMPLETE)

    if not cons.get("room_id_matches_ui"):
        return _out(PREEXP8, audit, "room_ui_mismatch", ROOM_START_LATCH_PASS_INCOMPLETE)

    if dom.get("pick_index") and dom.get("deadline") and dom.get("token") and server_has_pick and server_has_deadline:
        if pick == 0 and deadline and not cons.get("token_parses"):
            return _out(PREEXP4, audit, "token_not_validated", ROOM_START_LATCH_PASS_INCOMPLETE)
        if token and cons.get("countdown_mounted") and not resolved.get("pre_expiration_ready"):
            return _out(PREEXP1, audit, "dom_fields_missing_server_complete", ROOM_START_LATCH_PASS_INCOMPLETE)

    return _out(PREEXP10, audit, "unmapped_pre_expiration_state", ROOM_START_LATCH_PASS_INCOMPLETE)


def _out(code: str, audit: dict[str, Any], missing: str, boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_missing": missing,
        "accepted_label": boundary,
        "smallest_correction_boundary": code or "PRE_EXPIRATION_PASS",
        "audit": audit,
    }
