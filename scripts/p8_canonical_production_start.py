"""Canonical shared production Solo Live Draft start (room-latch + Gate B)."""

from __future__ import annotations

import time
from typing import Any

try:
    from p8_harness_start_classify import CANONICAL_HELPER_NAME, ROOM_LATCH_REFERENCE_CHAIN
except ImportError:
    from scripts.p8_harness_start_classify import CANONICAL_HELPER_NAME, ROOM_LATCH_REFERENCE_CHAIN  # type: ignore[no-redef]

HELPER_NAME = CANONICAL_HELPER_NAME


def capture_harness_page_identity(
    page,
    context,
    *,
    label: str,
    ledger_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = ledger_rows or []
    run_id = ""
    session_id = ""
    for r in reversed(rows):
        if not run_id:
            run_id = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
        if not session_id:
            session_id = str(r.get("streamlit_session_id") or "")
        if run_id and session_id:
            break
    ctx_id = ""
    try:
        ctx_id = str(getattr(context, "_impl_obj", None) or id(context))
    except Exception:
        ctx_id = str(id(context))
    frame_url = ""
    try:
        frame_url = str(getattr(page, "url", "") or "")
        if page.frames:
            frame_url = page.frames[0].url or frame_url
    except Exception:
        pass
    return {
        "label": label,
        "ts": time.time(),
        "browser_context_id": ctx_id,
        "page_object_id": str(id(page)),
        "page_url": getattr(page, "url", ""),
        "frame_url": frame_url,
        "streamlit_session_id": session_id,
        "diagnostic_run_id": run_id,
    }


def _countdown_mounted(state: dict[str, Any]) -> bool:
    if state.get("countdown_mounted"):
        return True
    try:
        from p8_diagnostic_setup import _countdown_mounted as _cm
    except ImportError:
        from scripts.p8_diagnostic_setup import _countdown_mounted as _cm  # type: ignore[no-redef]

    if _cm(state):
        return True
    mount = state.get("mount") or {}
    if str(mount.get("mounted") or "") in ("1", "true"):
        return True
    if state.get("timer_seconds") not in (None, ""):
        return True
    ui = state.get("ui") or {}
    if ui.get("ccTimer") is not None:
        return True
    text = str(state.get("text_excerpt") or "")
    return bool(state.get("in_progress")) and "Time remaining:" in text


def establish_single_solo_live_draft(
    page,
    context,
    *,
    setup_url: str,
    prior_room_id: str = "",
    fresh_lobby_cleanup: bool = True,
    max_wait_s: float = 90.0,
) -> dict[str, Any]:
    """
    One navigation context, one setup, one start click, unified latch proof.
    Used by room-latch verification and Gate B diagnostics.
    """
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from p8_production_start_harness import (
        capture_start_click_transport,
        dispatch_start_single_authoritative_click,
        scrape_stage1_ledger_rows,
        start_proof_from_state,
    )
    from p8_room_latch_ledger_export import filter_latch_ledger_rows, resolve_run_and_session
    from p8_room_latch_timeline import build_room_state_timeline
    from p8_room_latch_verify_classify import VERIFY1, classify_room_latch_verify
    from p8_start_audit_reconcile import collect_start_audit_rows, infer_created_room_after_click
    from p8_start_boundary_classify import START_PIPELINE_PASS, classify_start_boundary
    from production_draft_start_authoritative import (
        grade_authoritative_draft_start,
        scrape_authoritative_start_state,
    )
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby
    from solo_draft_start_harness import (
        SCAN_SETUP_JS,
        SOLO_RADIO_JS,
        checkpoint,
        ensure_solo_setup_picks_meet_roster,
        maybe_clear_stale_draft,
        set_number_via_playwright,
    )

    identity_timeline: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    out: dict[str, Any] = {
        "helper_name": HELPER_NAME,
        "canonical_chain": dict(ROOM_LATCH_REFERENCE_CHAIN),
        "click_count": 0,
        "room_latch_pass": False,
        "pre_expiration_ready": False,
        "valid": False,
        "identity_timeline": identity_timeline,
        "checkpoints": checkpoints,
    }

    ldr = ensure_p8_ldr_setup_surface(page, setup_url=setup_url)
    out["ldr_surface"] = ldr
    identity_timeline.append(
        capture_harness_page_identity(page, context, label="setup", ledger_rows=scrape_stage1_ledger_rows(page))
    )

    cleanup: dict[str, Any] = {"ok": True, "skipped": True}
    if fresh_lobby_cleanup:
        cleanup = ensure_fresh_setup_lobby(page, max_wait_s=180)
        cleanup["skipped"] = False
    out["production_cleanup"] = cleanup
    if not cleanup.get("ok"):
        out["first_missing_pre_expiration"] = "setup_cleanup_failed"
        return out

    setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
    if not setup_scan.get("soloSelected"):
        page.evaluate(SOLO_RADIO_JS)
        page.wait_for_timeout(2000)
    maybe_clear_stale_draft(page, checkpoints)
    set_number_via_playwright(page, "Number of Teams", "2")
    ensure_solo_setup_picks_meet_roster(page, checkpoints)
    page.wait_for_timeout(1500)

    pre_rows = scrape_stage1_ledger_rows(page)
    identity_timeline.append(
        capture_harness_page_identity(page, context, label="before_click", ledger_rows=pre_rows)
    )
    out["identity_before_click"] = identity_timeline[-1]
    baseline_run = str(identity_timeline[-1].get("diagnostic_run_id") or "")
    baseline_session = str(identity_timeline[-1].get("streamlit_session_id") or "")

    pre_state = scrape_authoritative_start_state(page)
    if pre_state.get("in_progress") and _countdown_mounted(pre_state):
        rid = str(pre_state.get("room_id") or "").upper()
        if rid and (not prior_room_id or rid != prior_room_id.strip().upper()):
            token = str(pre_state.get("production_token") or pre_state.get("expire_token") or "")
            out.update(
                _structured_result(
                    room_id=rid,
                    state=pre_state,
                    run_id=baseline_run,
                    session_id=baseline_session,
                    click_count=0,
                    handler_entered=True,
                    handler_success=True,
                    room_creation_success=True,
                    reused_existing=True,
                )
            )
            out["room_latch_pass"] = True
            out["pre_expiration_ready"] = _pre_expiration_ready(out)
            out["valid"] = out["pre_expiration_ready"]
            return out

    click = dispatch_start_single_authoritative_click(page, checkpoints)
    out["start_click"] = click
    out["click_count"] = 1
    click_ts = float(click.get("click_timestamp") or time.time())
    transport = capture_start_click_transport(page, click_ts=click_ts)
    out["start_click_transport"] = transport

    identity_timeline.append(
        capture_harness_page_identity(page, context, label="after_click", ledger_rows=scrape_stage1_ledger_rows(page))
    )

    created_rid = ""
    handler_rid = ""
    handler_entered_seen = False
    handler_success = False
    room_creation_success = False
    t0 = time.time()
    last_state: dict[str, Any] = {}
    last_scrape_ts = 0.0
    ledger_full: list[dict[str, Any]] = []

    while time.time() - t0 < max_wait_s:
        last_state = scrape_authoritative_start_state(page)
        last_scrape_ts = time.time()
        ledger_peek = scrape_stage1_ledger_rows(page)
        for r in ledger_peek:
            ev = str(r.get("event") or "")
            if ev == "production_stage1_start_handler_entered":
                handler_entered_seen = True
            if ev == "production_stage1_start_handler_exited":
                if r.get("created_room_id"):
                    handler_rid = str(r.get("created_room_id") or "").upper()
                handler_success = bool(r.get("handler_success", True))
            if ev == "production_stage1_room_creation_exited":
                if r.get("created_room_id"):
                    created_rid = str(r.get("created_room_id") or "").upper()
                room_creation_success = bool(r.get("room_creation_success", True))
        if handler_rid or created_rid:
            page.wait_for_timeout(4000)
            ledger_full = scrape_stage1_ledger_rows(page)
            break
        if last_state.get("in_progress") and _countdown_mounted(last_state) and str(last_state.get("room_id") or ""):
            ledger_full = ledger_peek
            created_rid = str(last_state.get("room_id") or "").upper()
            page.wait_for_timeout(2000)
            ledger_full = scrape_stage1_ledger_rows(page)
            break
        page.wait_for_timeout(2000)

    if not ledger_full:
        ledger_full = scrape_stage1_ledger_rows(page)

    created = (handler_rid or created_rid or infer_created_room_after_click(ledger_full, click_ts=click_ts)).upper()
    run_id, session_id = resolve_run_and_session(ledger_full, created_room_id=created)
    if not run_id and baseline_run:
        run_id = baseline_run
    if not session_id and baseline_session:
        session_id = baseline_session

    audit_reconcile = collect_start_audit_rows(
        ledger_full,
        click_ts=click_ts,
        diagnostic_run_id=run_id,
        streamlit_session_id=session_id,
        created_room_id=created,
    )
    if not handler_entered_seen:
        handler_entered_seen = bool(audit_reconcile.get("handler_entered_count"))
    if not handler_rid and audit_reconcile.get("handler_exited_count"):
        for r in audit_reconcile.get("by_event", {}).get("production_stage1_start_handler_exited") or []:
            handler_rid = str(r.get("created_room_id") or r.get("room_id") or "").upper()
            if handler_rid:
                break
    if not created:
        created = str(audit_reconcile.get("inferred_created_room_id") or "").upper()

    filtered = filter_latch_ledger_rows(
        ledger_full,
        diagnostic_run_id=run_id,
        streamlit_session_id=session_id,
        created_room_id=created,
        click_ts=click_ts,
    )
    timeline = build_room_state_timeline(filtered, created_room_id=created)
    final_scrape = scrape_authoritative_start_state(page)
    final_surface_row = next((t for t in reversed(timeline) if t.get("operation") == "surface"), None)

    verify = classify_room_latch_verify(
        timeline=timeline,
        filtered_ledger=filtered,
        created_room_id=created,
        final_surface=final_surface_row,
        final_scrape=final_scrape,
    )

    grade = grade_authoritative_draft_start(
        final_scrape,
        prior_room_id=prior_room_id,
        start_click_dispatched=bool(click.get("dom_click_dispatched")),
    )
    proof = start_proof_from_state(final_scrape, grade)
    proof["countdown_mounted"] = _countdown_mounted(final_scrape)

    narrow_classification = classify_start_boundary(
        ldr_surface=ldr,
        click_transport={**click, **transport},
        ledger_rows=ledger_full,
        authoritative_state=final_scrape,
        start_proof=proof,
        click_ts=click_ts,
        reconciled_audit=audit_reconcile,
    )

    identity_timeline.append(
        capture_harness_page_identity(
            page,
            context,
            label="room_latch_proof",
            ledger_rows=ledger_full,
        )
    )
    identity_timeline.append(
        capture_harness_page_identity(
            page,
            context,
            label="countdown_mount",
            ledger_rows=ledger_full,
        )
    )

    structured = _structured_result(
        room_id=created or str(final_scrape.get("room_id") or "").upper(),
        state=final_scrape,
        run_id=run_id,
        session_id=session_id,
        click_count=1,
        handler_entered=handler_entered_seen,
        handler_success=handler_success or bool(handler_rid),
        room_creation_success=room_creation_success or bool(created_rid or handler_rid),
        expected_token=str(final_scrape.get("production_token") or final_scrape.get("expire_token") or ""),
    )
    out.update(structured)
    out["latch_ledger_export"] = {
        "row_count_full_scrape": len(ledger_full),
        "row_count_filtered": len(filtered),
        "rows": filtered,
    }
    out["room_state_timeline"] = timeline
    out["verify_classification"] = verify
    out["start_audit_reconcile"] = audit_reconcile
    out["start_classification"] = narrow_classification
    out["authoritative_state"] = final_scrape
    out["authoritative_grade"] = grade
    out["start_proof"] = proof
    out["latched_room_id"] = out.get("room_id")
    out["diagnostic_run_id"] = run_id
    out["streamlit_session_id"] = session_id
    out["room_latch_pass"] = verify.get("classification") == VERIFY1

    ledger_for_pre = ledger_full
    export_rows = (out.get("latch_ledger_export") or {}).get("rows")
    if isinstance(export_rows, list) and export_rows:
        ledger_for_pre = export_rows + [r for r in ledger_full if r not in export_rows]

    from p8_pre_expiration_resolve import resolve_authoritative_pre_expiration_state

    pre = resolve_authoritative_pre_expiration_state(
        ledger_rows=ledger_for_pre,
        ui_scrape=final_scrape,
        room_id=created or str(final_scrape.get("room_id") or ""),
        diagnostic_run_id=run_id,
        click_count=int(out.get("click_count") or 1),
        room_latch_pass=out["room_latch_pass"],
    )
    out["pre_expiration_resolution"] = pre
    out["pre_expiration_ready"] = bool(pre.get("pre_expiration_ready"))
    out["expected_token"] = pre.get("expected_token")
    out["pick_index"] = pre.get("pick_index")
    out["deadline"] = pre.get("deadline")
    out["valid"] = out["pre_expiration_ready"]
    out["stale_page_proof"] = False

    if out["valid"]:
        out["start_boundary"] = START_PIPELINE_PASS
        out["setup_gate"] = "PASS_POSITIVE_START_PROOF"
    else:
        out["first_missing_pre_expiration"] = _first_missing_pre_expiration(out)
        func_label = str(narrow_classification.get("classification") or "")
        if func_label.startswith("START8") and created and audit_reconcile.get("audit_filter_mismatch"):
            out["start_boundary"] = "HARNESS_AUDIT_RECONCILE_NOT_START8"
        else:
            out["start_boundary"] = func_label
    return out


def _structured_result(
    *,
    room_id: str,
    state: dict[str, Any],
    run_id: str,
    session_id: str,
    click_count: int,
    handler_entered: bool,
    handler_success: bool,
    room_creation_success: bool,
    expected_token: str = "",
    reused_existing: bool = False,
) -> dict[str, Any]:
    pick = state.get("pick_index")
    deadline = state.get("deadline")
    token = expected_token or str(state.get("production_token") or state.get("expire_token") or "")
    return {
        "room_id": str(room_id or "").upper(),
        "status": "in_progress" if state.get("in_progress") else "setup",
        "pick_index": pick,
        "deadline": deadline,
        "expected_token": token,
        "countdown_mounted": _countdown_mounted(state),
        "handler_entered": handler_entered,
        "handler_success": handler_success,
        "room_creation_success": room_creation_success,
        "reused_existing_room": reused_existing,
        "inferred_created_room_id": str(room_id or "").upper(),
    }


def _pre_expiration_ready(result: dict[str, Any]) -> bool:
    if int(result.get("click_count") or 0) != 1 and not result.get("reused_existing_room"):
        if int(result.get("click_count") or 0) == 0 and result.get("reused_existing_room"):
            pass
        elif int(result.get("click_count") or 0) != 1:
            return False
    rid = str(result.get("room_id") or "")
    if not rid:
        return False
    if str(result.get("status") or "") != "in_progress":
        return False
    pick = result.get("pick_index")
    if pick is not None and int(pick) != 0:
        return False
    if not result.get("deadline") and not result.get("expected_token"):
        return False
    if not result.get("countdown_mounted"):
        return False
    if not result.get("room_latch_pass"):
        return False
    if not (result.get("handler_entered") or result.get("handler_success") or result.get("room_creation_success")):
        if not result.get("reused_existing_room"):
            return False
    return True


def _first_missing_pre_expiration(result: dict[str, Any]) -> str:
    if int(result.get("click_count") or 0) != 1 and not result.get("reused_existing_room"):
        return "click_count_not_one"
    if not result.get("room_id"):
        return "room_id_missing"
    if str(result.get("status") or "") != "in_progress":
        return "status_not_in_progress"
    pick = result.get("pick_index")
    if pick is not None and int(pick) != 0:
        return "pick_index_not_zero"
    if not result.get("deadline") and not result.get("expected_token"):
        return "deadline_or_token_missing"
    if not result.get("countdown_mounted"):
        return "countdown_not_mounted"
    if not result.get("room_latch_pass"):
        return "room_latch_not_pass"
    if not (
        result.get("handler_entered")
        or result.get("handler_success")
        or result.get("room_creation_success")
        or result.get("reused_existing_room")
    ):
        return "handler_or_creation_evidence_missing"
    return "unknown"
