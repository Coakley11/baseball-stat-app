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

EV_HANDLER_PROOF = "production_stage1_handler_exit_session_state_proof"


def _norm_room(value: Any) -> str:
    return str(value or "").strip().upper()


def _deadline_or_token_present(row: dict[str, Any]) -> bool:
    token = str(row.get("deadline_token") or row.get("expected_token") or row.get("session_deadline_token") or "")
    if token.strip():
        return True
    deadline = row.get("deadline")
    if deadline is not None and str(deadline).strip() not in ("", "0", "None"):
        try:
            return float(deadline) > 0
        except (TypeError, ValueError):
            return bool(str(deadline).strip())
    return False


def _handler_session_proof_row(filtered_ledger: list[dict[str, Any]], created: str) -> dict[str, Any] | None:
    proofs = [r for r in filtered_ledger if r.get("event") == EV_HANDLER_PROOF]
    for r in reversed(proofs):
        if not r.get("session_matches_local"):
            continue
        auth = r.get("authoritative_session_state") or {}
        rid = _norm_room(auth.get("session_room_id") or r.get("room_id") or r.get("local_created_room_id"))
        if rid != created:
            continue
        status = str(auth.get("session_draft_status") or r.get("room_status") or "").lower()
        pick = auth.get("session_pick_index", r.get("pick_index"))
        if status != "in_progress":
            continue
        if pick is not None and int(pick) != 0:
            continue
        if not _deadline_or_token_present({**auth, **r}):
            continue
        return r
    return None


def _post_handler_server_read(
    timeline: list[dict[str, Any]], *, created: str, after_ts: float
) -> dict[str, Any] | None:
    reads = [
        t
        for t in timeline
        if t.get("operation") == "read"
        and "ultra_early" in str(t.get("reason") or "")
        and float(t.get("ts") or 0) >= after_ts
    ]
    for r in reversed(reads):
        rid = _norm_room(r.get("room_id_after"))
        if rid != created:
            continue
        status = str(r.get("draft_status") or "").lower()
        if status != "in_progress":
            continue
        pick = r.get("pick_index")
        if pick is not None and int(pick) != 0:
            continue
        if not _deadline_or_token_present(r):
            continue
        return r
    return None


def _later_clear_or_empty_overwrite(timeline: list[dict[str, Any]], *, created: str, after_ts: float) -> dict[str, Any] | None:
    for t in timeline:
        if float(t.get("ts") or 0) <= after_ts:
            continue
        op = t.get("operation")
        before = _norm_room(t.get("room_id_before"))
        after = _norm_room(t.get("room_id_after"))
        if op == "clear" and before == created:
            return t
        if op == "write" and before == created and after not in ("", created):
            return t
        if op in ("clear", "restore", "write") and before == created and not after:
            return t
    return None


def _server_room_lost_after_proof(
    timeline: list[dict[str, Any]], *, created: str, after_ts: float
) -> bool:
    for t in timeline:
        if float(t.get("ts") or 0) <= after_ts:
            continue
        rid = _norm_room(t.get("room_id_after"))
        if t.get("operation") in ("read", "surface", "handler_session_proof") and rid and rid != created:
            return True
        if t.get("operation") == "clear" and _norm_room(t.get("room_id_before")) == created:
            return True
    return False


def _countdown_mounted_scrape(final_scrape: dict[str, Any]) -> bool:
    if final_scrape.get("countdown_mounted"):
        return True
    mount = final_scrape.get("mount") or {}
    if str(mount.get("mounted") or "") in ("1", "true"):
        return True
    if final_scrape.get("timer_seconds") not in (None, ""):
        return True
    ui = final_scrape.get("ui") or {}
    if ui.get("ccTimer") is not None:
        return True
    text = str(final_scrape.get("text_excerpt") or "")
    return bool(final_scrape.get("in_progress")) and "Time remaining:" in text


def _ui_corroborates_active_room(final_scrape: dict[str, Any], *, created: str) -> bool:
    scrape_rid = _norm_room(final_scrape.get("room_id"))
    if scrape_rid != created:
        return False
    if not final_scrape.get("in_progress"):
        return False
    if final_scrape.get("setup_start_visible"):
        return False
    if final_scrape.get("live_draft_ui_visible") is False:
        return False
    if not _countdown_mounted_scrape(final_scrape):
        return False
    return True


def _ui_only_would_pass(final_scrape: dict[str, Any], *, created: str) -> bool:
    return _ui_corroborates_active_room(final_scrape, created=created)


def _auth_blocked_preserve_context(
    timeline: list[dict[str, Any]],
    filtered_ledger: list[dict[str, Any]],
    *,
    created: str,
) -> bool:
    blocked_reasons = ("auth_required", "auth_required_for_owned_blob")
    for t in timeline:
        if t.get("operation") != "restore":
            continue
        inf = t.get("preserve_inference") or {}
        if str(inf.get("restore_blocked_reason") or "") in blocked_reasons:
            return True
    handler = _handler_session_proof_row(filtered_ledger, created)
    if handler:
        auth = handler.get("authoritative_session_state") or {}
        if str(auth.get("restore_blocked_reason") or "") in blocked_reasons:
            return True
    return False


def _try_verify1_authoritative_bundle(
    *,
    timeline: list[dict[str, Any]],
    filtered_ledger: list[dict[str, Any]],
    created: str,
    final_scrape: dict[str, Any],
    audit: dict[str, Any],
    require_auth_blocked: bool = True,
) -> dict[str, Any] | None:
    if not created:
        return None
    if require_auth_blocked and not _auth_blocked_preserve_context(timeline, filtered_ledger, created=created):
        return None

    handler = _handler_session_proof_row(filtered_ledger, created)
    if not handler:
        return None
    handler_ts = float(handler.get("ts") or 0)
    audit["verify1_handler_proof"] = True
    audit["verify1_handler_ts"] = handler_ts

    post_read = _post_handler_server_read(timeline, created=created, after_ts=handler_ts)
    if not post_read:
        return None
    audit["verify1_post_rerun_read"] = post_read.get("reason")
    audit["verify1_post_rerun_seq"] = post_read.get("script_run_seq")

    if _later_clear_or_empty_overwrite(timeline, created=created, after_ts=handler_ts):
        return None

    if _server_room_lost_after_proof(timeline, created=created, after_ts=float(post_read.get("ts") or handler_ts)):
        audit["verify1_server_loss_before_ui"] = True
        return None

    if not _ui_corroborates_active_room(final_scrape, created=created):
        return None
    audit["verify1_ui_corroborated"] = True
    audit["verify1_without_surface_decision"] = True
    return _out(VERIFY1, audit, "", VERIFY1)


def classify_room_latch_verify(
    *,
    timeline: list[dict[str, Any]],
    filtered_ledger: list[dict[str, Any]],
    created_room_id: str,
    final_surface: dict[str, Any] | None,
    final_scrape: dict[str, Any],
) -> dict[str, Any]:
    created = _norm_room(created_room_id)
    scrape_rid = _norm_room(final_scrape.get("room_id"))
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

    # Later clear/replace (before success paths)
    for t in timeline:
        if t.get("operation") == "clear" and _norm_room(t.get("room_id_before")) == created:
            return _out(VERIFY4, audit, f"clear:{t.get('reason')}", VERIFY4)
        if (
            t.get("operation") == "write"
            and _norm_room(t.get("room_id_before")) == created
            and _norm_room(t.get("room_id_after")) not in ("", created)
        ):
            return _out(VERIFY4, audit, f"write_replace:{t.get('reason')}", VERIFY4)

    room_ids_seen = {_norm_room(t.get("room_id_after")) for t in timeline if t.get("room_id_after")}
    room_ids_seen.discard("")
    if len(room_ids_seen) > 1 and created in room_ids_seen:
        return _out(VERIFY9, audit, "multiple_room_ids", VERIFY9)

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
                    and _norm_room(t.get("room_id_after")) not in ("", created)
                    and t.get("operation") in ("clear", "restore", "write")
                    and _norm_room(t.get("room_id_after")) != created
                ),
                None,
            )
            if not later_lost:
                for t in reversed(timeline):
                    if t.get("operation") == "surface":
                        sr = _norm_room(t.get("room_id_after"))
                        audit["final_server_surface_room_id"] = sr
                        if sr == created and t.get("draft_status") == "in_progress":
                            audit["downstream_ui_scrape_empty"] = not bool(scrape_rid)
                            return _out(VERIFY1, audit, "", VERIFY1)
                        break
                authoritative = _try_verify1_authoritative_bundle(
                    timeline=timeline,
                    filtered_ledger=filtered_ledger,
                    created=created,
                    final_scrape=final_scrape,
                    audit=audit,
                    require_auth_blocked=True,
                )
                if authoritative:
                    return authoritative
            if inf.get("inferred_clear_foreign_likely"):
                return _out(VERIFY3, audit, "auth_restore_post_empty", VERIFY3)

    proofs = [r for r in filtered_ledger if r.get("event") == EV_HANDLER_PROOF]
    if proofs and proofs[-1].get("session_matches_local"):
        for t in auth_restores:
            inf = t.get("preserve_inference") or {}
            if inf.get("inferred_clear_foreign_likely"):
                return _out(VERIFY3, audit, "handler_proof_then_auth_restore_wipe", VERIFY3)

    surfaces = [t for t in timeline if t.get("operation") == "surface"]
    if surfaces:
        last_s = surfaces[-1]
        audit["final_server_surface"] = last_s
        srid = _norm_room(last_s.get("room_id_after"))
        if srid == created and last_s.get("draft_status") == "in_progress" and not scrape_rid:
            return _out(VERIFY7, audit, "surface_in_progress_scrape_setup", VERIFY7)

    if created and any(_norm_room(t.get("room_id_after")) == created for t in timeline):
        handler = _handler_session_proof_row(filtered_ledger, created)
        if handler and _server_room_lost_after_proof(
            timeline, created=created, after_ts=float(handler.get("ts") or 0)
        ):
            if _ui_only_would_pass(final_scrape, created=created):
                return _out(VERIFY4, audit, "server_loss_ui_scrape_overridden", VERIFY4)
        if not scrape_rid:
            ultra = [t for t in timeline if t.get("operation") == "read" and "ultra_early" in str(t.get("reason") or "")]
            if ultra and _norm_room(ultra[-1].get("room_id_after")) != created:
                return _out(VERIFY5, audit, "room_lost_after_ultra_early", VERIFY5)
            if handler and _post_handler_server_read(
                timeline, created=created, after_ts=float(handler.get("ts") or 0)
            ):
                return _out(VERIFY7, audit, "server_had_room_scrape_empty_or_setup", VERIFY7)
            return _out(VERIFY7, audit, "server_had_room_scrape_empty", VERIFY7)

    if scrape_rid and scrape_rid != created:
        return _out(VERIFY8, audit, "scrape_room_mismatch", VERIFY8)

    if scrape_rid == created and final_scrape.get("setup_start_visible") and not surfaces:
        handler = _handler_session_proof_row(filtered_ledger, created)
        if not handler:
            return _out(VERIFY7, audit, "setup_visible_without_server_surface", VERIFY7)

    # UI-only cannot establish VERIFY1
    if _ui_only_would_pass(final_scrape, created=created) and not _handler_session_proof_row(filtered_ledger, created):
        return _out(VERIFY10, audit, "ui_only_insufficient_for_verify1", ACCEPTED_FAIL)

    authoritative = _try_verify1_authoritative_bundle(
        timeline=timeline,
        filtered_ledger=filtered_ledger,
        created=created,
        final_scrape=final_scrape,
        audit=audit,
        require_auth_blocked=True,
    )
    if authoritative:
        return authoritative

    bundle = None
    try:
        from p8_room_latch_reconcile import server_latch_bundle_proven

        bundle = server_latch_bundle_proven(
            filtered_ledger=filtered_ledger, timeline=timeline, created_room_id=created
        )
    except ImportError:
        bundle = {"ok": False}
    if bundle and bundle.get("ok"):
        audit["server_latch_bundle_pass"] = True
        audit["server_latch_without_ui_scrape"] = not _norm_room(final_scrape.get("room_id"))
        return _out(VERIFY1, audit, "server_authoritative_bundle", VERIFY1)

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
