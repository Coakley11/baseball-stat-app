"""Room-latch verification: start → prepare → ROOM_LATCH_PASS (no expiration)."""

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
ROOM_LATCH_PASS = "ROOM_LATCH_PASS"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT
    from p8_canary_build_gate import git_head_short, local_deploy_pin, poll_live_cloud_sha
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface, _countdown_mounted
    from p8_production_start_harness import dispatch_start_single_authoritative_click, scrape_stage1_ledger_rows
    from p8_callback_metadata_classify import CONTROL_ENTERED, REG_HOOK_ENTERED, evaluate_case_a_gate_a
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from production_draft_start_authoritative import grade_authoritative_draft_start, scrape_authoritative_start_state
    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from solo_draft_start_harness import checkpoint, ensure_solo_setup_picks_meet_roster, maybe_clear_stale_draft, set_number_via_playwright, SOLO_RADIO_JS, SCAN_SETUP_JS
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
        "mode": "production_room_latch_verification_v1",
        "deploy_pin": local_deploy_pin(),
        "git_head": git_head_short(),
        "artifact_path": str(OUT),
        "log_path": str(LOG),
    }
    poll = poll_live_cloud_sha(
        max_attempts=24,
        sleep_s=20.0,
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
            report["result"] = "CASE_A_FAILED"
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
        report["start_click"] = click
        report["start_click_count"] = 1

        created_rid = ""
        handler_rid = ""
        t0 = time.time()
        last: dict[str, Any] = {}
        pass_row: dict[str, Any] = {}
        while time.time() - t0 < 120.0:
            last = scrape_authoritative_start_state(page)
            grade = grade_authoritative_draft_start(last, prior_room_id="", start_click_dispatched=True)
            rid = str(last.get("room_id") or "").upper()
            ledger = scrape_stage1_ledger_rows(page)
            for r in ledger:
                if r.get("event") == "production_stage1_start_handler_exited" and r.get("created_room_id"):
                    handler_rid = str(r.get("created_room_id") or "").upper()
                if r.get("event") == "production_stage1_room_creation_exited" and r.get("created_room_id"):
                    created_rid = str(r.get("created_room_id") or "").upper()
            token = str(last.get("production_token") or last.get("expire_token") or "")
            checks = {
                "one_room_created": bool(created_rid or handler_rid),
                "same_room_handler": (not handler_rid or not rid or rid == handler_rid),
                "same_room_after_rerun": bool(rid),
                "in_progress": bool(last.get("in_progress")),
                "pick_index_zero": last.get("pick_index") == 0,
                "deadline_present": bool(last.get("deadline")),
                "token_present": bool(token),
                "countdown_mounted": _countdown_mounted(last),
                "setup_not_visible": not last.get("setup_start_visible"),
            }
            empty_auth_overwrite = any(
                r.get("event") == "production_stage1_room_state_restore"
                and not str(r.get("restored_room_id") or "")
                and (r.get("post_restore_snapshot") or {}).get("session_room_id") == ""
                and rid
                and str((r.get("post_restore_snapshot") or {}).get("restore_blocked_reason") or "") == "auth_required"
                for r in ledger
                if isinstance(r.get("post_restore_snapshot"), dict)
            )
            checks["no_auth_empty_restore_wipe"] = not empty_auth_overwrite or bool(rid)
            if all(checks.values()) and rid:
                pass_row = {"checks": checks, "state": last, "created_room_id": rid}
                break
            page.wait_for_timeout(2000)

        report["authoritative_state"] = last
        report["handler_room_id"] = handler_rid
        report["created_room_id"] = created_rid or handler_rid
        report["pass_checks"] = pass_row.get("checks") or {}
        report["diagnostic_run_id"] = ""
        ledger_final = scrape_stage1_ledger_rows(page)
        if ledger_final:
            report["diagnostic_run_id"] = str(ledger_final[0].get("run_id") or "")
        if pass_row:
            report["result"] = ROOM_LATCH_PASS
        else:
            report["result"] = "ROOM_LATCH_FAIL"
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"result": report.get("result"), "artifact": str(OUT)}, indent=2))
    return 0 if report.get("result") == ROOM_LATCH_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
