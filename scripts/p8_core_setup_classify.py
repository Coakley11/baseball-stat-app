"""Stage 1A-CORE setup boundaries (harness only — before expiration)."""

from __future__ import annotations

from typing import Any

CORESETUP1 = "CORESETUP1 — SERVER ROOM SIGNAL OBSERVED BUT LEGACY VALIDATOR ABORTED"
CORESETUP2 = "CORESETUP2 — START CLICK DISPATCHED BUT HANDLER NOT ENTERED"
CORESETUP3 = "CORESETUP3 — HANDLER ENTERED BUT ROOM NOT CREATED"
CORESETUP4 = "CORESETUP4 — ROOM CREATED BUT SERVER STATUS NOT IN_PROGRESS"
CORESETUP5 = "CORESETUP5 — ROOM CREATED THEN CLEARED OR OVERWRITTEN"
CORESETUP6 = "CORESETUP6 — ROOM LATCH PASSED BUT PRE-EXPIRATION STATE INCOMPLETE"
CORESETUP7 = "CORESETUP7 — MULTIPLE START CLICKS OR MULTIPLE ROOMS"
CORESETUP8 = "CORESETUP8 — HARNESS/APPLICATION RUN OR SESSION MISMATCH"
CORESETUP9 = "CORESETUP9 — LEDGER FILTER OMITTED AUTHORITATIVE ROOM EVIDENCE"
CORESETUP10 = "CORESETUP10 — OTHER"

INVALID_STAGE1A_CORE_TRACE = (
    "INVALID_STAGE1A_CORE_TRACE — LEGACY START VALIDATION ABORTED BEFORE CORE EXECUTION"
)


def _checkpoint_room_signals(draft: dict[str, Any]) -> dict[str, Any]:
    cps = list(draft.get("checkpoints") or [])
    if isinstance(draft.get("draft_start"), dict):
        cps = cps or list((draft["draft_start"].get("checkpoints") or []))
    toast_room = ""
    dom_room = ""
    setup_disappeared_room = ""
    for cp in cps:
        if not isinstance(cp, dict):
            continue
        step = str(cp.get("step") or "")
        if step == "room_id_detected":
            dom_room = str(cp.get("room_id") or "").upper()
        if step == "toast_detected":
            alerts = cp.get("alerts") or []
            for a in alerts:
                m = str(a)
                if "Room ID" in m:
                    parts = m.split("Room ID")
                    if len(parts) > 1:
                        toast_room = parts[-1].strip().rstrip(".").upper()[:16]
        if step == "setup_page_disappeared_after_start":
            setup_disappeared_room = str(cp.get("room_id") or "").upper()
    return {
        "dom_or_micro_probe": dom_room,
        "toast": toast_room,
        "setup_page_disappeared": setup_disappeared_room,
    }


def replay_legacy_core_artifact(summary: dict[str, Any]) -> dict[str, Any]:
    """Retrospective classification for legacy CORE runs (e.g. FFD33258)."""
    draft = summary.get("draft_start_validation") or {}
    inner = draft.get("draft_start") or {}
    signals = _checkpoint_room_signals({**inner, "checkpoints": inner.get("checkpoints") or draft.get("checkpoints")})
    room_hint = signals["dom_or_micro_probe"] or signals["toast"] or signals["setup_page_disappeared"]
    legacy_valid = bool(draft.get("valid"))
    legacy_reason = str(draft.get("reason") or inner.get("first_missing_criterion") or "")
    auth = draft.get("authoritative_grade") or {}
    server_in_progress = bool((auth.get("checks") or {}).get("room_in_progress"))
    server_room = str((auth.get("checks") or {}).get("nonempty_room_id"))

    retrospective = CORESETUP1
    room_signal_class = "C"
    if room_hint and not server_in_progress and not legacy_valid:
        if legacy_reason in ("draft_start_success_false", "setup_page_disappeared"):
            retrospective = CORESETUP1
            room_signal_class = "C"
    if room_hint and signals["setup_page_disappeared"] and not legacy_valid:
        room_signal_class = "A_partial_dom_toast_without_legacy_latch"

    latch_in_artifact = False
    for row in inner.get("timeline") or []:
        st = row.get("state") or {}
        if str(st.get("room_id") or "").upper() == room_hint:
            if row.get("flags", {}).get("success_toast_or_room_id"):
                latch_in_artifact = False
    for row in inner.get("timeline") or []:
        if str((row.get("state") or {}).get("room_id") or "").upper() == room_hint:
            if (row.get("flags") or {}).get("room_in_progress"):
                latch_in_artifact = True
                room_signal_class = "A"
                break

    return {
        "room_signal": room_hint,
        "room_signal_sources": signals,
        "room_signal_classification": room_signal_class,
        "legacy_valid": legacy_valid,
        "legacy_reason": legacy_reason,
        "authoritative_grade_pass": auth.get("pass"),
        "retrospective_coresetup": retrospective,
        "authoritative_room_latch_proof_in_artifact": latch_in_artifact,
        "invalid_stage1a_core_trace": INVALID_STAGE1A_CORE_TRACE,
    }


def classify_core_setup_outcome(
    canonical: dict[str, Any],
    *,
    setup_auth: dict[str, Any],
    latch_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latch = latch_replay or {}
    if setup_auth.get("canonical_setup_pass"):
        return {
            "coresetup_classification": "",
            "setup_pass": True,
            "room_id": setup_auth.get("room_id"),
        }
    failures = list(setup_auth.get("failures") or [])
    click_count = int(canonical.get("click_count") or 0)
    handler = bool(canonical.get("handler_entered"))
    room_id = str(canonical.get("room_id") or latch.get("room_id") or "").upper()
    status_auth = canonical.get("room_status_authority") or {}
    later_clear = bool((latch.get("server_latch_bundle") or {}).get("checks", {}).get("later_clear"))

    if click_count > 1:
        return {"coresetup_classification": CORESETUP7, "setup_pass": False, "reason": "multiple_clicks"}
    if not handler and click_count == 1:
        return {"coresetup_classification": CORESETUP2, "setup_pass": False}
    if handler and not room_id:
        return {"coresetup_classification": CORESETUP3, "setup_pass": False}
    if room_id and not status_auth.get("status_in_progress_server") and "server_status_not_in_progress" in failures:
        return {"coresetup_classification": CORESETUP4, "setup_pass": False}
    if later_clear or "room_later_cleared" in failures:
        return {"coresetup_classification": CORESETUP5, "setup_pass": False}
    if "harness_run_id_mismatch" in failures or "streamlit_session_mismatch" in str(failures):
        return {"coresetup_classification": CORESETUP8, "setup_pass": False}
    if latch.get("room_latch_pass_reconciled") and not setup_auth.get("expected_token"):
        return {"coresetup_classification": CORESETUP6, "setup_pass": False}
    if "room_latch_not_proven" in failures:
        return {"coresetup_classification": CORESETUP9, "setup_pass": False}
    return {
        "coresetup_classification": CORESETUP10,
        "setup_pass": False,
        "reason": ",".join(failures) or "unknown",
    }


def focused_mode_absent_proof(page: Any, url: str, canonical: dict[str, Any]) -> dict[str, Any]:
    qp_focused = "solo_p8_focused_binding" in str(url or "")
    rows = []
    export = canonical.get("latch_ledger_export") or {}
    if isinstance(export, dict):
        rows = list(export.get("rows") or [])
    focused_events = [
        str(r.get("event") or "")
        for r in rows
        if isinstance(r, dict) and "p8_focused" in str(r.get("event") or "")
    ]
    return {
        "focused_query_param_present": qp_focused,
        "focused_ledger_events_at_setup": focused_events,
        "focused_requested": False if not qp_focused else True,
        "focused_effective_at_setup": bool(focused_events),
        "absent_ok": not qp_focused and not focused_events,
    }


def normalize_core_start_validation(
    canonical: dict[str, Any],
    setup_auth: dict[str, Any],
    latch_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rid = str(setup_auth.get("room_id") or canonical.get("room_id") or "").upper()
    return {
        "valid": True,
        "canonical_setup_pass": True,
        "latched_room_id": rid,
        "visible_room_id": rid,
        "draft_start_success": True,
        "in_progress": True,
        "authoritative_start": True,
        "expected_token": setup_auth.get("expected_token") or canonical.get("expected_token"),
        "pick_index": setup_auth.get("pick_index") if setup_auth.get("pick_index") is not None else canonical.get("pick_index"),
        "deadline": setup_auth.get("deadline") or canonical.get("deadline"),
        "room_latch_pass": bool(canonical.get("room_latch_pass") or (latch_replay or {}).get("room_latch_pass_reconciled")),
        "room_latch_pass_reconciled": bool((latch_replay or {}).get("room_latch_pass_reconciled")),
        "production_setup": canonical,
        "setup_authority": setup_auth,
        "reason": "canonical_setup_pass",
    }
