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
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_callback_metadata_classify import CONTROL_ENTERED, REG_HOOK_ENTERED, evaluate_case_a_gate_a
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_room_latch_verify_classify import ACCEPTED_FAIL, VERIFY1
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import production_url
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
        start_result = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id="",
            fresh_lobby_cleanup=True,
        )
        report["production_start"] = start_result
        report["start_click"] = start_result.get("start_click")
        report["start_click_count"] = start_result.get("click_count")
        report["diagnostic_run_id"] = start_result.get("diagnostic_run_id")
        report["streamlit_session_id"] = start_result.get("streamlit_session_id")
        report["created_room_id"] = start_result.get("room_id")
        report["handler_room_id"] = start_result.get("room_id")
        report["latch_ledger_export"] = start_result.get("latch_ledger_export")
        report["room_state_timeline"] = start_result.get("room_state_timeline")
        report["final_ui_scrape"] = start_result.get("authoritative_state")
        report["final_server_surface_decision"] = next(
            (t for t in reversed(start_result.get("room_state_timeline") or []) if t.get("operation") == "surface"),
            None,
        )
        verify = start_result.get("verify_classification") or {}
        report["verify_classification"] = verify
        report["verify_boundary"] = verify.get("classification")
        report["smallest_supported_correction_boundary"] = verify.get("smallest_supported_correction_boundary")
        report["identity_timeline"] = start_result.get("identity_timeline")

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
