"""Room-latch verification v2: full ledger export + VERIFY classification."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_room_latch_verification.json"
LOG = ROOT / "data" / "production_room_latch_verification.out"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT
    from p8_canary_build_gate import git_head_short, local_deploy_pin, poll_live_cloud_sha
    from p8_production_start_harness import dispatch_start_single_authoritative_click, scrape_stage1_ledger_rows
    from p8_callback_metadata_classify import CONTROL_ENTERED, REG_HOOK_ENTERED, evaluate_case_a_gate_a
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_room_latch_ledger_export import filter_latch_ledger_rows, resolve_run_and_session
    from p8_room_latch_timeline import build_room_state_timeline
    from p8_room_latch_verify_classify import ACCEPTED_FAIL, VERIFY1, classify_room_latch_verify
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from production_draft_start_authoritative import scrape_authoritative_start_state
    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from solo_draft_start_harness import ensure_solo_setup_picks_meet_roster, maybe_clear_stale_draft, set_number_via_playwright, SOLO_RADIO_JS, SCAN_SETUP_JS
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
    from live_draft_streamlit_registration_hooks import run_local_case_a_hook_self_test

    if not harness_ready():
        return 1
    preflight = run_preflight()
    if not preflight.get("authenticated_restored"):
        return 1

    report: dict[str, Any] = {
        "started_at": time.time(),
        "mode": "production_room_latch_verification_v2",
        "accepted_prior_fail": ACCEPTED_FAIL,
        "deploy_pin": local_deploy_pin(),
        "git_head": git_head_short(),
        "artifact_path": str(OUT),
        "log_path": str(LOG),
    }
    poll = poll_live_cloud_sha(
        max_attempts=12,
        sleep_s=15.0,
        require_canary_impl=False,
        wait_for_callback_metadata_observability=True,
        wait_for_start_stage1_observability=True,
        wait_for_room_latch_observability=True,
    )
    report["cloud_poll"] = poll
    report["live_sha"] = poll.get("live_sha")
    report["live_build"] = poll.get("live_build")

    hook_self_test = run_local_case_a_hook_self_test()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        for script in (HARNESS_TOP_OBSERVER_INIT_SCRIPT, LEDGER_DURABLE_INIT_SCRIPT, P8_WS_BOUNDARY_INIT_SCRIPT):
            try:
                context.add_init_script(script)
            except Exception:
                pass
        page = context.new_page()
        goto_and_wake(page, case_a_url(), timeout_s=240)
        case_a_ok = False
        deadline = time.time() + 130.0
        while time.time() < deadline:
            snap = scrape_case_a(page)
            ca = snap.get("case_a") or {}
            if int(ca.get("callbacks") or 0) >= 1 or ca.get("passed") in ("1", "true"):
                case_a_ok = True
                break
            page.wait_for_timeout(3000)
        collector = P8LedgerHarnessCollector()
        cap_a = capture_all_ledger_sources(page)
        collector.absorb_capture(cap_a, label="case_a")
        peak = collector.peak_rows()
        control_entered = [r for r in peak if r.get("event") == CONTROL_ENTERED]
        control_exited = [r for r in peak if r.get("event") == "production_stage1_control_on_change_exited"]
        reg_hook_entered = [r for r in peak if r.get("event") == REG_HOOK_ENTERED]
        case_gate_a = evaluate_case_a_gate_a(
            peak_rows=peak,
            case_a_delivery_proven=case_a_ok and bool(control_entered or reg_hook_entered),
            control_entered=control_entered or reg_hook_entered,
            control_exited=control_exited,
            local_hook_self_test_ok=bool(hook_self_test.get("ok")),
        )
        report["case_a_dispatch_authority"] = bool(case_gate_a.get("case_a_dispatch_authority"))
        if not report["case_a_dispatch_authority"]:
            report["verify_classification"] = {"classification": "CASE_A_FAILED"}
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1

        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        ensure_p8_ldr_setup_surface(page, setup_url=url)
        cleanup = ensure_fresh_setup_lobby(page, max_wait_s=180)
        report["production_cleanup"] = cleanup
        setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
        if not setup_scan.get("soloSelected"):
            page.evaluate(SOLO_RADIO_JS)
            page.wait_for_timeout(2000)
        checkpoints: list[dict] = []
        maybe_clear_stale_draft(page, checkpoints)
        set_number_via_playwright(page, "Number of Teams", "2")
        ensure_solo_setup_picks_meet_roster(page, checkpoints)
        page.wait_for_timeout(1500)
        click = dispatch_start_single_authoritative_click(page, checkpoints)
        click_ts = float(click.get("click_timestamp") or time.time())
        report["start_click"] = click
        report["start_click_count"] = 1

        created_rid = ""
        handler_rid = ""
        t0 = time.time()
        last_scrape: dict[str, Any] = {}
        while time.time() - t0 < 90.0:
            last_scrape = scrape_authoritative_start_state(page)
            ledger_peek = scrape_stage1_ledger_rows(page)
            for r in ledger_peek:
                if r.get("event") == "production_stage1_start_handler_exited" and r.get("created_room_id"):
                    handler_rid = str(r.get("created_room_id") or "").upper()
                if r.get("event") == "production_stage1_room_creation_exited" and r.get("created_room_id"):
                    created_rid = str(r.get("created_room_id") or "").upper()
            if handler_rid or created_rid:
                page.wait_for_timeout(4000)
                break
            page.wait_for_timeout(2000)

        ledger_full = scrape_stage1_ledger_rows(page)
        created = (created_rid or handler_rid).upper()
        run_id, session_id = resolve_run_and_session(ledger_full, created_room_id=created)
        report["diagnostic_run_id"] = run_id
        report["streamlit_session_id"] = session_id
        report["created_room_id"] = created
        report["handler_room_id"] = handler_rid

        filtered = filter_latch_ledger_rows(
            ledger_full,
            diagnostic_run_id=run_id,
            streamlit_session_id=session_id,
            created_room_id=created,
            click_ts=click_ts,
        )
        timeline = build_room_state_timeline(filtered, created_room_id=created)
        report["latch_ledger_export"] = {
            "row_count_full_scrape": len(ledger_full),
            "row_count_filtered": len(filtered),
            "filter": {
                "diagnostic_run_id": run_id,
                "streamlit_session_id": session_id,
                "created_room_id": created,
                "click_ts": click_ts,
            },
            "rows": filtered,
        }
        report["room_state_timeline"] = timeline

        final_surface_row = next(
            (t for t in reversed(timeline) if t.get("operation") == "surface"),
            None,
        )
        last_scrape = scrape_authoritative_start_state(page)
        report["final_ui_scrape"] = last_scrape
        report["final_server_surface_decision"] = final_surface_row

        verify = classify_room_latch_verify(
            timeline=timeline,
            filtered_ledger=filtered,
            created_room_id=created,
            final_surface=final_surface_row,
            final_scrape=last_scrape,
        )
        report["verify_classification"] = verify
        report["verify_boundary"] = verify.get("classification")
        report["smallest_supported_correction_boundary"] = verify.get("smallest_supported_correction_boundary")

        if verify.get("classification") == VERIFY1:
            report["result"] = "ROOM_LATCH_PASS"
        else:
            report["result"] = ACCEPTED_FAIL

        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "verify_boundary": report.get("verify_boundary"),
                "result": report.get("result"),
                "created_room_id": report.get("created_room_id"),
                "artifact": str(OUT),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
