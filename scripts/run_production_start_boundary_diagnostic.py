"""Start-pipeline boundary diagnostic (Case A dispatch authority → one start click → classify)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_start_boundary_diagnostic.json"
LOG = ROOT / "data" / "production_start_boundary_diagnostic.out"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT
    from p8_canary_build_gate import git_head_short, local_deploy_pin, poll_live_cloud_sha
    from p8_production_start_harness import INVALID_PRODUCTION_EXPIRATION_TRACE, run_gate_b_production_start
    from p8_start_boundary_classify import START_PIPELINE_PASS
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from p8_callback_metadata_classify import evaluate_case_a_gate_a
    from p8_callback_metadata_classify import (
        CONTROL_ENTERED,
        HOOKS_INSTALLED,
        REG_HOOK_ENTERED,
    )
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from p8_ledger_observability import capture_all_ledger_sources, P8LedgerHarnessCollector
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
    from live_draft_streamlit_registration_hooks import run_local_case_a_hook_self_test

    if not harness_ready() or not run_preflight().get("authenticated_restored"):
        return 1

    pin = local_deploy_pin()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "mode": "production_start_boundary_v1",
        "deploy_pin": pin,
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
        report["case_a_gate_a"] = case_gate_a
        report["case_a_dispatch_authority"] = bool(case_gate_a.get("case_a_dispatch_authority"))
        if not case_gate_a.get("case_a_dispatch_authority"):
            report["first_boundary"] = "CASE_A_DISPATCH_AUTHORITY_FAILED"
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 1

        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        ensure_p8_ldr_setup_surface(page, setup_url=url)
        cleanup = ensure_fresh_setup_lobby(page, max_wait_s=180)
        report["production_cleanup"] = cleanup
        start_val = run_gate_b_production_start(
            page,
            url,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            auth_preflight=run_preflight(),
        )
        report["production_start"] = start_val
        report["diagnostic_run_id"] = (
            (start_val.get("ledger_rows_after_start") or [{}])[0].get("run_id")
            if start_val.get("ledger_rows_after_start")
            else ""
        )
        report["start_classification"] = start_val.get("start_classification")
        report["start_boundary"] = start_val.get("start_boundary")
        report["start_click_transport"] = start_val.get("start_click_transport")
        report["start_click"] = start_val.get("start_click")
        report["first_boundary"] = (
            start_val.get("start_boundary")
            or (start_val.get("start_classification") or {}).get("classification")
            or (
                f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP"
                if not start_val.get("valid")
                else START_PIPELINE_PASS
            )
        )
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"start_boundary": report.get("start_boundary"), "artifact": str(OUT)}, indent=2))
    return 0 if start_val.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
