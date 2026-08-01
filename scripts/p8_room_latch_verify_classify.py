"""VERIFY boundaries for room-latch verification (harness; server ledger authority)."""

from __future__ import annotations

from typing import Any

VERIFY1 = "VERIFY1 — AUTH_BLOCKED_RESTORE_PRESERVATION_PASS"
VERIFY2 = "VERIFY2 — PRESERVATION_PREDICATE_FALSE"
VERIFY3 = "VERIFY3 — PRESERVE_PATH_SELECTED_BUT_STATE_STILL_CLEARED"
VERIFY4 = "VERIFY4 — LATER_EXPLICIT_CLEAR_OR_RESTORE"
VERIFY5 = "VERIFY5 — NEXT_RUN_ROOM_LOOKUP_FAILURE"
VERIFY6 = "VERIFY6 — STATUS_OR_BUNDLE_PARTIALLY_LOST"
VERIFY7 = "VERIFY7 — SERVER_STATE_VALID_BUT_RENDER_USES_STALE_STATE"
VERIFY8 = "VERIFY8 — UI_OR_SCRAPER_WRONG_SESSION_OR_SURFACE"
VERIFY9 = "VERIFY9 — ROOM_RECREATED_OR_DUPLICATED"
VERIFY10 = "VERIFY10 — OTHER"

ACCEPTED_FAIL = "ROOM_LATCH_FAIL_AFTER_AUTH_RESTORE_FIX — POST_HANDLER_SERVER_STATE_OUTCOME_UNRESOLVED"


def classify_room_latch_verify(
    *,
    timeline: list[dict[str, Any]],
    filtered_ledger: list[dict[str, Any]],
    created_room_id: str,
    final_surface: dict[str, Any] | None,
    final_scrape: dict[str, Any],
) -> dict[str, Any]:
    created = str(created_room_id or "").strip().upper()
    scrape_rid = str(final_scrape.get("room_id") or "").upper()
    audit: dict[str, Any] = {
        "created_room_id": created,
        "final_scrape_room_id": scrape_rid,
        "final_scrape_in_progress": bool(final_scrape.get("in_progress")),
        "timeline_steps": len(timeline),
    }

    auth_restores = [
        t
        for t in timeline
        if t.get("operation") == "restore"
        and t.get("preserve_inference")
        and (t["preserve_inference"].get("restore_blocked_reason") or "") in (
            "auth_required",
            "auth_required_for_owned_blob",
        )
    ]
    audit["auth_blocked_restore_count"] = len(auth_restores)

    if auth_restores:
        first = auth_restores[0]
        inf = first.get("preserve_inference") or {}
        audit["first_auth_restore"] = inf
        if inf.get("inferred_preserve_success"):
            later = [t for t in timeline if float(t.get("ts") or 0) > float(first.get("ts") or 0)]
            later_lost = next(
                (
                    t
                    for t in later
                    if created
                    and str(t.get("room_id_after") or "").upper() not in ("", created)
                    and t.get("operation") in ("clear", "restore", "write")
                    and str(t.get("room_id_after") or "").upper() != created
                ),
                None,
            )
            if not later_lost:
                for t in reversed(timeline):
                    if t.get("operation") == "surface":
                        sr = str(t.get("room_id_after") or "").upper()
                        audit["final_server_surface_room_id"] = sr
                        if sr == created and t.get("draft_status") == "in_progress":
                            audit["downstream_ui_scrape_empty"] = not bool(scrape_rid)
                            return _out(VERIFY1, audit, "", VERIFY1)
                        break
            if inf.get("inferred_clear_foreign_likely"):
                return _out(VERIFY3, audit, "auth_restore_post_empty", VERIFY3)

    surfaces = [t for t in timeline if t.get("operation") == "surface"]
    if surfaces:
        last_s = surfaces[-1]
        audit["final_server_surface"] = last_s
        srid = str(last_s.get("room_id_after") or "").upper()
        if srid == created and last_s.get("draft_status") == "in_progress" and not scrape_rid:
            return _out(VERIFY7, audit, "surface_in_progress_scrape_setup", VERIFY7)

    # Room survived through handler proof then lost on empty auth restore
    proofs = [r for r in filtered_ledger if r.get("event") == "production_stage1_handler_exit_session_state_proof"]
    if proofs and proofs[-1].get("session_matches_local"):
        for t in auth_restores:
            inf = t.get("preserve_inference") or {}
            if inf.get("inferred_clear_foreign_likely"):
                return _out(VERIFY3, audit, "handler_proof_then_auth_restore_wipe", VERIFY3)

    # Later clear/replace
    for t in timeline:
        if t.get("operation") == "clear" and str(t.get("room_id_before") or "").upper() == created:
            return _out(VERIFY4, audit, f"clear:{t.get('reason')}", VERIFY4)
        if (
            t.get("operation") == "write"
            and str(t.get("room_id_before") or "").upper() == created
            and str(t.get("room_id_after") or "").upper() not in ("", created)
        ):
            return _out(VERIFY4, audit, f"write_replace:{t.get('reason')}", VERIFY4)

    room_ids_seen = {str(t.get("room_id_after") or "").upper() for t in timeline if t.get("room_id_after")}
    room_ids_seen.discard("")
    if len(room_ids_seen) > 1 and created in room_ids_seen:
        return _out(VERIFY9, audit, "multiple_room_ids", VERIFY9)

    if created and any(str(t.get("room_id_after") or "").upper() == created for t in timeline):
        if not scrape_rid:
            ultra = [t for t in timeline if t.get("operation") == "read" and "ultra_early" in str(t.get("reason") or "")]
            if ultra and str(ultra[-1].get("room_id_after") or "").upper() != created:
                return _out(VERIFY5, audit, "room_lost_after_ultra_early", VERIFY5)
            return _out(VERIFY7, audit, "server_had_room_scrape_empty", VERIFY7)

    if scrape_rid and scrape_rid != created:
        return _out(VERIFY8, audit, "scrape_room_mismatch", VERIFY8)

    return _out(
        VERIFY10,
        audit,
        "post_handler_server_state_unresolved",
        ACCEPTED_FAIL,
    )


def _out(code: str, audit: dict[str, Any], missing: str, boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_missing_event": missing,
        "smallest_supported_correction_boundary": boundary,
        "accepted_fail_label": ACCEPTED_FAIL if code != VERIFY1 else "",
        "audit": audit,
    }
