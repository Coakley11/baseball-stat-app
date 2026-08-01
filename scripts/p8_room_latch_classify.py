"""Classify Live Draft room latch boundaries (harness)."""

from __future__ import annotations

from typing import Any

LATCH1 = "LATCH1 — ROOM_RESULT_NEVER_WRITTEN_TO_SESSION_STATE"
LATCH2 = "LATCH2 — ROOM_WRITTEN_UNDER_WRONG_KEY"
LATCH3 = "LATCH3 — ROOM_WRITTEN_TO_WRONG_SESSION"
LATCH4 = "LATCH4 — ROOM_STATE_CLEARED_AFTER_HANDLER"
LATCH5 = "LATCH5 — WORKSPACE_RESTORE_OVERWRITES_NEW_ROOM"
LATCH6 = "LATCH6 — NEXT_RUN_ROOM_LOOKUP_FAILS"
LATCH7 = "LATCH7 — STATUS_NORMALIZATION_RESETS_TO_SETUP"
LATCH8 = "LATCH8 — RERUN_OR_NAVIGATION_USES_STALE_PRE_START_STATE"
LATCH9 = "LATCH9 — UI/SCRAPER_READS_WRONG_SURFACE_OR_SESSION"
LATCH10 = "LATCH10 — OTHER"

EV_WRITE = "production_stage1_room_state_write"
EV_CLEAR = "production_stage1_room_state_clear"
EV_RESTORE = "production_stage1_room_state_restore"
EV_READ = "production_stage1_room_state_read"
EV_SURFACE = "production_stage1_surface_decision"
EV_PROOF = "production_stage1_handler_exit_session_state_proof"
EV_HANDLER_OUT = "production_stage1_start_handler_exited"
EV_ROOM_OUT = "production_stage1_room_creation_exited"
EV_RERUN = "production_stage1_rerun_transition"


def _rows(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [r for r in events if isinstance(r, dict) and str(r.get("event") or "") == name]


def _after_ts(rows: list[dict[str, Any]], click_ts: float) -> list[dict[str, Any]]:
    if not click_ts:
        return rows
    return [r for r in rows if float(r.get("ts") or 0) >= click_ts - 0.05]


def _first_transition_to_empty(
    rows: list[dict[str, Any]], *, created_room_id: str
) -> dict[str, Any] | None:
    rid = str(created_room_id or "").strip().upper()
    for r in sorted(rows, key=lambda x: float(x.get("ts") or 0)):
        ev = str(r.get("event") or "")
        if ev == EV_CLEAR and str(r.get("prev_room_id") or "").upper() == rid:
            return r
        if ev == EV_WRITE and str(r.get("prev_room_id") or "").upper() == rid:
            if not str(r.get("new_room_id") or "").upper():
                return r
            if str(r.get("new_status") or "") == "setup" and str(r.get("prev_status") or "") == "in_progress":
                return r
        if ev == EV_RESTORE:
            post = r.get("post_restore_snapshot") if isinstance(r.get("post_restore_snapshot"), dict) else {}
            if rid and str(post.get("session_room_id") or "").upper() not in ("", rid):
                return r
    return None


def classify_room_latch(
    *,
    ledger_rows: list[dict[str, Any]],
    authoritative_state: dict[str, Any],
    click_ts: float = 0.0,
    created_room_id: str = "",
    ws_supplemental: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _after_ts(ledger_rows, click_ts)
    ws_supplemental = ws_supplemental or {}
    room_out = _rows(rows, EV_ROOM_OUT)
    handler_out = _rows(rows, EV_HANDLER_OUT)
    proof = _rows(rows, EV_PROOF)
    writes = _rows(rows, EV_WRITE)
    clears = _rows(rows, EV_CLEAR)
    restores = _rows(rows, EV_RESTORE)
    reads = _rows(rows, EV_READ)
    surfaces = _rows(rows, EV_SURFACE)
    reruns = _rows(rows, EV_RERUN)

    created = str(created_room_id or "").strip().upper()
    if not created and room_out:
        created = str(room_out[-1].get("created_room_id") or "").upper()
    if not created and handler_out:
        created = str(handler_out[-1].get("created_room_id") or "").upper()

    audit: dict[str, Any] = {
        "created_room_id": created,
        "room_creation_success": any(r.get("room_creation_success") for r in room_out),
        "handler_exit_success": any(r.get("handler_success") for r in handler_out),
        "handler_session_proof_rows": len(proof),
        "session_matches_local_at_handler_exit": any(r.get("session_matches_local") for r in proof),
        "room_state_writes": len(writes),
        "room_state_clears": len(clears),
        "room_state_restores": len(restores),
        "ultra_early_reads": len([r for r in reads if "ultra_early" in str(r.get("read_label") or "")]),
        "rerun_transitions": len(reruns),
        "surface_decisions": len(surfaces),
        "ws_supplemental": ws_supplemental,
        "scraped_room_id": str(authoritative_state.get("room_id") or "").upper(),
        "scraped_in_progress": bool(authoritative_state.get("in_progress")),
    }

    if not created and not audit["room_creation_success"]:
        return _out(LATCH1, audit, "no_room_creation_result", "room never created")

    if proof and proof[-1].get("local_created_room_id"):
        auth = proof[-1].get("authoritative_session_state") or {}
        blob_rid = str(auth.get("canonical_blob_room_id") or "").upper()
        sess_rid = str(auth.get("session_room_id") or "").upper()
        local_rid = str(proof[-1].get("local_created_room_id") or "").upper()
        if blob_rid == local_rid and sess_rid != local_rid:
            return _out(LATCH2, audit, "blob_has_room_live_draft_room_empty", LATCH2)

    if proof and not any(r.get("session_matches_local") for r in proof):
        if proof[-1].get("local_created_room_id") and not proof[-1].get("authoritative_session_state", {}).get(
            "session_room_id"
        ):
            return _out(LATCH1, audit, "handler_local_room_not_in_session_state", LATCH1)

    handler_sid = str((proof[-1].get("authoritative_session_state") or {}).get("streamlit_session_id") or "") if proof else ""
    ultra = [r for r in reads if "ultra_early" in str(r.get("read_label") or "")]
    if handler_sid and ultra:
        next_sid = str(ultra[-1].get("streamlit_session_id") or "")
        if next_sid and handler_sid != next_sid:
            return _out(LATCH3, audit, "streamlit_session_id_changed_after_start", LATCH3)

    transition = _first_transition_to_empty(rows, created_room_id=created)
    if transition:
        ev = str(transition.get("event") or "")
        if ev == EV_CLEAR:
            return _out(LATCH4, audit, f"clear:{transition.get('reason')}", LATCH4)
        if ev == EV_RESTORE:
            return _out(LATCH5, audit, f"restore:{transition.get('reason')}", LATCH5)
        if ev == EV_WRITE:
            return _out(LATCH7, audit, f"write_status_reset:{transition.get('reason')}", LATCH7)

    if created and writes and not any(str(w.get("new_room_id") or "").upper() == created for w in writes):
        if any(str(w.get("new_room_id") or "").upper() for w in writes):
            return _out(LATCH5, audit, "writes_without_target_room_id", LATCH5)
        return _out(LATCH1, audit, "no_write_with_created_room_id", LATCH1)

    if created and not str(authoritative_state.get("room_id") or ""):
        if ultra and str(ultra[-1].get("session_room_id") or "").upper() == created:
            return _out(LATCH9, audit, "session_had_room_scrape_empty", LATCH9)
        if ultra and not str(ultra[-1].get("session_room_id") or ""):
            return _out(LATCH6, audit, "next_run_ultra_early_missing_room", LATCH6)
        if reruns and not ultra:
            return _out(LATCH8, audit, "rerun_without_ultra_early_capture", LATCH8)
        return _out(LATCH6, audit, "room_id_lost_before_scrape", LATCH6)

    if str(authoritative_state.get("room_id") or "").upper() == created and not authoritative_state.get(
        "in_progress"
    ):
        return _out(LATCH7, audit, "scraped_setup_with_room_id", LATCH7)

    return _out(
        LATCH10,
        audit,
        "unmapped_latch_sequence",
        LATCH10,
    )


def _out(code: str, audit: dict[str, Any], missing: str, functional_boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_missing_latch_event": missing,
        "smallest_functional_correction_boundary": functional_boundary,
        "audit": audit,
    }
