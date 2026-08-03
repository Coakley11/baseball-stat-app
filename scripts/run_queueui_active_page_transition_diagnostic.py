"""One-shot QUEUEUI active-page transition diagnostic (headed, early stop)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from queueui_transition_diagnostic import (  # noqa: E402
    STATIC_TRANSITION_PATH_REVIEW,
    classify_queueui_boundary,
    merge_capture_snapshots,
    summarize_ledger_events,
)
from run_production_stage1_authenticated import (  # noqa: E402
    production_url,
    redact_url,
    resolve_required_cloud_sha,
    scrape_active_live_page_observation,
)
from stage1_harness_observability import evaluate_active_live_page_gate  # noqa: E402

REQUIRED_CLOUD_SHA = "007c39a"
OUT_JSON = ROOT / "data" / "queueui_transition_diagnostic_007c39a.json"
OUT_DIR = ROOT / "data" / "queueui_transition_007c39a"
MAX_POST_LATCH_SAMPLES = 8
STABLE_SAMPLES_TO_STOP = 3
POLL_MS = 2500


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _harness_short() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def _screenshot(page, name: str) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception as exc:
        return f"screenshot_failed:{exc}"


def _server_latch_from_ledger(
    ledger_rows: list[dict[str, Any]],
    *,
    created_hint: str = "",
) -> dict[str, Any]:
    summary = summarize_ledger_events(ledger_rows)
    created = (created_hint or summary.get("created_room_id_from_ledger") or "").upper()
    pick_index = None
    deadline = ""
    token = ""
    status = ""
    for r in reversed(ledger_rows):
        rid = str(r.get("room_id") or r.get("created_room_id") or r.get("draft_room_id") or "").upper()
        if created and rid and rid != created:
            continue
        if r.get("event") in (
            "production_stage1_room_state_read",
            "production_stage1_handler_exit_session_state_proof",
        ):
            if r.get("draft_status"):
                status = str(r.get("draft_status"))
            if r.get("pick_index") is not None:
                pick_index = r.get("pick_index")
            if r.get("deadline"):
                deadline = str(r.get("deadline"))
            if r.get("token"):
                token = str(r.get("token"))
        if r.get("operation") == "read" and str(r.get("draft_status") or "").lower() == "in_progress":
            created = created or rid
            status = status or "in_progress"
    try:
        from p8_room_latch_reconcile import server_latch_bundle_proven
        from p8_room_latch_timeline import build_room_state_timeline
        from p8_room_latch_ledger_export import filter_latch_ledger_rows

        filtered = filter_latch_ledger_rows(ledger_rows, created_room_id=created)
        timeline = build_room_state_timeline(filtered, created_room_id=created)
        bundle = server_latch_bundle_proven(
            filtered_ledger=filtered, timeline=timeline, created_room_id=created
        )
        return {
            "ok": bool(bundle.get("ok")),
            "server_room_id": created,
            "server_pick_index": pick_index,
            "server_deadline": deadline,
            "server_token": token,
            "server_status": status,
            "bundle": bundle,
            "ledger_summary": summary,
        }
    except Exception as exc:
        return {
            "ok": bool(created) and summary.get("handler_exited"),
            "server_room_id": created,
            "server_pick_index": pick_index,
            "server_deadline": deadline,
            "server_token": token,
            "server_status": status,
            "bundle_error": str(exc)[:200],
            "ledger_summary": summary,
        }


def main() -> int:
    required = resolve_required_cloud_sha() or REQUIRED_CLOUD_SHA
    os.environ.setdefault("REQUIRED_CLOUD_SHA", required)

    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight

    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed", "pre": pre}))
        return 1

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_deploy_build
    from p8_canonical_production_start import capture_harness_page_identity
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from solo_draft_start_harness import (
        SCAN_SETUP_JS,
        SOLO_RADIO_JS,
        ensure_solo_setup_picks_meet_roster,
        maybe_clear_stale_draft,
        set_number_via_playwright,
    )
    from p8_production_start_harness import (
        capture_start_click_transport,
        dispatch_start_single_authoritative_click,
        scrape_stage1_ledger_rows,
    )
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT

    report: dict[str, Any] = {
        "diagnostic": "queueui_active_page_transition",
        "required_cloud_sha": required,
        "harness_sha_full": _harness_sha(),
        "harness_sha_short": _harness_short(),
        "static_transition_path_review": STATIC_TRANSITION_PATH_REVIEW,
        "started_at": time.time(),
        "timeline": [],
        "artifacts": {},
    }

    console_errors: list[str] = []
    page_errors: list[str] = []

    url = production_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        page.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)

        def _on_console(msg):
            if msg.type in ("error", "warning"):
                console_errors.append(f"{msg.type}:{msg.text}"[:500])

        def _on_pageerror(exc):
            page_errors.append(str(exc)[:500])

        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)

        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(20000)

        cloud_sha = scrape_deploy_build(page) or str(pre.get("cloud_sha") or "")
        report["cloud_sha"] = cloud_sha
        if str(cloud_sha).lower()[:7] != required.lower()[:7]:
            report["cloud_sha_mismatch"] = True
            browser.close()
            OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"aborted": True, "reason": "cloud_sha_mismatch", "live": cloud_sha}))
            return 1

        ensure_p8_ldr_setup_surface(page, setup_url=url)
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["aborted"] = "setup_cleanup_failed"
            browser.close()
            OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return 1


        setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
        if not setup_scan.get("soloSelected"):
            page.evaluate(SOLO_RADIO_JS)
            page.wait_for_timeout(2000)
        checkpoints: list[dict[str, Any]] = []
        maybe_clear_stale_draft(page, checkpoints)
        set_number_via_playwright(page, "Number of Teams", "2")
        ensure_solo_setup_picks_meet_roster(page, checkpoints)
        page.wait_for_timeout(1500)

        ledger_pre = scrape_stage1_ledger_rows(page)
        identity_pre = capture_harness_page_identity(page, context, label="before_start", ledger_rows=ledger_pre)
        snap_before = merge_capture_snapshots(
            page, label="before_start", ledger_rows=ledger_pre, console_errors=console_errors, page_errors=page_errors
        )
        report["streamlit_session_id"] = (
            identity_pre.get("streamlit_session_id") or snap_before.get("streamlit_session_id_from_ko") or ""
        )
        report["application_diagnostic_run_id"] = identity_pre.get("diagnostic_run_id") or ""
        report["timeline"].append({"milestone": "before_start", "snap": snap_before, "identity": identity_pre})
        report["artifacts"]["screenshot_before_start"] = _screenshot(page, "01_before_start")
        _save_text(OUT_DIR / "01_before_start_dom.txt", str(snap_before.get("text_head") or ""))

        click = dispatch_start_single_authoritative_click(page, checkpoints)
        click_ts = float(click.get("click_timestamp") or time.time())
        transport = capture_start_click_transport(page, click_ts=click_ts)
        page.wait_for_timeout(800)
        ledger_after_cb = scrape_stage1_ledger_rows(page)
        snap_after_cb = merge_capture_snapshots(
            page,
            label="after_callback",
            ledger_rows=ledger_after_cb,
            console_errors=console_errors,
            page_errors=page_errors,
        )
        report["timeline"].append(
            {
                "milestone": "after_callback",
                "click": click,
                "transport": transport,
                "snap": snap_after_cb,
                "ledger_summary": summarize_ledger_events(ledger_after_cb),
            }
        )
        report["artifacts"]["screenshot_after_callback"] = _screenshot(page, "02_after_callback")
        _save_text(OUT_DIR / "02_after_callback_dom.txt", str(snap_after_cb.get("text_head") or ""))

        server_latch: dict[str, Any] = {"ok": False}
        latch_milestone_recorded = False
        post_latch_snaps: list[dict[str, Any]] = []
        stable_streak = 0
        last_fp = ""
        classification = ""
        defect_side = ""
        reason = ""
        room_id = ""

        t0 = time.time()
        while time.time() - t0 < 120:
            ledger = scrape_stage1_ledger_rows(page)
            summary = summarize_ledger_events(ledger)
            created_hint = summary.get("created_room_id_from_ledger") or ""
            server_latch = _server_latch_from_ledger(ledger, created_hint=str(created_hint))
            snap = merge_capture_snapshots(
                page,
                label=f"poll_{len(post_latch_snaps)}",
                ledger_rows=ledger,
                console_errors=console_errors,
                page_errors=page_errors,
            )
            post_latch_snaps.append(snap)

            if server_latch.get("ok") and not latch_milestone_recorded:
                latch_milestone_recorded = True
                report["timeline"].append({"milestone": "server_room_latch", "server_latch": server_latch, "snap": snap})
                report["artifacts"]["screenshot_server_latch"] = _screenshot(page, "03_server_latch")
                _save_text(OUT_DIR / "03_server_latch_dom.txt", str(snap.get("text_head") or ""))

            if latch_milestone_recorded and len(post_latch_snaps) == 1:
                report["artifacts"]["screenshot_first_client_rerun"] = _screenshot(page, "04_first_client_poll")
                report["timeline"].append({"milestone": "first_client_poll_after_latch", "snap": snap})

            room_id = str(server_latch.get("server_room_id") or snap.get("python_room_id") or "").upper()
            start_val = {
                "latched_room_id": room_id,
                "visible_room_id": snap.get("visible_room_id"),
                "in_progress": bool(server_latch.get("ok")),
                "room_latch_pass": bool(server_latch.get("ok")),
            }
            obs = scrape_active_live_page_observation(page, start_val=start_val)
            gate_eval = evaluate_active_live_page_gate(obs, start_val=start_val)
            cls, side, rsn = classify_queueui_boundary(
                server_latch=server_latch,
                snap=snap,
                ledger_summary=summary,
                gate_eval=gate_eval,
                console_errors=console_errors,
                page_errors=page_errors,
            )

            fp = snap.get("fingerprint") or ""
            if latch_milestone_recorded and fp and fp == last_fp:
                stable_streak += 1
            else:
                stable_streak = 0
            last_fp = fp

            if gate_eval.get("passed"):
                classification = cls
                defect_side = side
                reason = rsn
                break

            if latch_milestone_recorded and stable_streak >= STABLE_SAMPLES_TO_STOP:
                classification = cls
                defect_side = side
                reason = rsn
                break

            if cls.startswith("QUEUEUI2") or cls.startswith("QUEUEUI3") or cls.startswith("QUEUEUI8"):
                classification = cls
                defect_side = side
                reason = rsn
                if server_latch.get("ok") and stable_streak >= 2:
                    break

            if len(post_latch_snaps) >= MAX_POST_LATCH_SAMPLES:
                classification = cls or classification
                defect_side = side or defect_side
                reason = rsn or reason
                break

            page.wait_for_timeout(POLL_MS)

        if not classification:
            last_snap = post_latch_snaps[-1] if post_latch_snaps else snap_before
            ledger = scrape_stage1_ledger_rows(page)
            summary = summarize_ledger_events(ledger)
            start_val = {
                "latched_room_id": room_id,
                "in_progress": bool(server_latch.get("ok")),
                "room_latch_pass": bool(server_latch.get("ok")),
            }
            gate_eval = evaluate_active_live_page_gate(
                scrape_active_live_page_observation(page, start_val=start_val),
                start_val=start_val,
            )
            classification, defect_side, reason = classify_queueui_boundary(
                server_latch=server_latch,
                snap=last_snap,
                ledger_summary=summary,
                gate_eval=gate_eval,
                console_errors=console_errors,
                page_errors=page_errors,
            )

        from queueui_transition_diagnostic import build_room_identity_table, evaluate_active_page_predicate_terms

        final_snap = post_latch_snaps[-1] if post_latch_snaps else snap_before
        final_ledger = scrape_stage1_ledger_rows(page)
        final_ledger_summary = summarize_ledger_events(final_ledger)
        identity_table = build_room_identity_table(
            server_room_id=str(server_latch.get("server_room_id") or room_id),
            snap=final_snap,
            ledger_summary=final_ledger_summary,
        )
        start_val_final = {
            "latched_room_id": room_id,
            "in_progress": bool(server_latch.get("ok")),
            "room_latch_pass": bool(server_latch.get("ok")),
        }
        gate_final = evaluate_active_live_page_gate(
            scrape_active_live_page_observation(page, start_val=start_val_final),
            start_val=start_val_final,
        )
        classification, defect_side, reason = classify_queueui_boundary(
            server_latch=server_latch,
            snap=final_snap,
            ledger_summary=final_ledger_summary,
            gate_eval=gate_final,
            console_errors=console_errors,
            page_errors=page_errors,
        )
        predicate_terms = evaluate_active_page_predicate_terms(final_snap, ledger_summary=final_ledger_summary)
        report["first_exact_queueui_classification"] = classification
        report["defect_side"] = defect_side
        report["classification_reason"] = reason

        report["artifacts"]["screenshot_final_classification"] = _screenshot(page, "05_final_classification")
        _save_text(OUT_DIR / "05_final_dom.txt", str(final_snap.get("text_head") or ""))
        report["finished_at"] = time.time()
        report["room_id"] = room_id
        report["server_latch"] = server_latch
        report["first_exact_queueui_classification"] = classification
        report["defect_side"] = defect_side
        report["classification_reason"] = reason
        report["room_identity_table"] = identity_table
        report["active_page_render_predicate_terms"] = predicate_terms
        report["console_errors"] = console_errors[-40:]
        report["page_errors"] = page_errors[-40:]
        report["post_latch_sample_count"] = len(post_latch_snaps)
        report["setup_url_redacted"] = redact_url(url)
        report["stage1a_core_unchanged"] = "PASS"
        report["stage1a_queue"] = {
            "functional_outcome": "NOT_RUN",
            "execution_status": "BLOCKED_BEFORE_EXPIRATION",
            "note": "QUEUEUI transition diagnostic only; no queue campaign",
        }

        browser.close()

    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "classification": report.get("first_exact_queueui_classification"), "out": str(OUT_JSON)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
