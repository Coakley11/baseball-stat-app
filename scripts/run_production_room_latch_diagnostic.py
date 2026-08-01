"""Room latch diagnostic: Case A → one start → Session State trace → LATCH classify."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_room_latch_diagnostic.json"
LOG = ROOT / "data" / "production_room_latch_diagnostic.out"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT
    from p8_canary_build_gate import git_head_short, local_deploy_pin, poll_live_cloud_sha
    from p8_production_start_harness import run_gate_b_production_start
    from p8_room_latch_classify import classify_room_latch
    from p8_callback_metadata_classify import (
        CONTROL_ENTERED,
        HOOKS_INSTALLED,
        REG_HOOK_ENTERED,
        evaluate_case_a_gate_a,
    )
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
    from live_draft_streamlit_registration_hooks import run_local_case_a_hook_self_test

    if not harness_ready():
        return 1
    preflight = run_preflight()
    if not preflight.get("authenticated_restored"):
        return 1

    pin = local_deploy_pin()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "mode": "production_room_latch_v1",
        "deploy_pin": pin,
        "git_head": git_head_short(),
        "accepted_start9c_run": "8f431e2",
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
    start_val: dict[str, Any] = {}
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
        if not case_gate_a.get("case_a_dispatch_authority"):
            report["latch_classification"] = {"classification": "CASE_A_DISPATCH_AUTHORITY_FAILED"}
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
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
            auth_preflight=preflight,
        )
        report["production_start"] = {
            k: start_val.get(k)
            for k in (
                "start_click",
                "start_click_transport",
                "start_classification",
                "start_boundary",
                "authoritative_state",
                "start_proof",
                "screenshot",
                "ledger_rows_after_start",
            )
        }
        ledger_rows = start_val.get("ledger_rows_after_start") or []
        click = start_val.get("start_click") or {}
        click_ts = float(click.get("click_timestamp") or 0)
        created = ""
        for ev in ("production_stage1_room_creation_exited", "production_stage1_start_handler_exited"):
            for r in ledger_rows:
                if r.get("event") == ev and r.get("created_room_id"):
                    created = str(r.get("created_room_id") or "").upper()
                    break
        report["diagnostic_run_id"] = str(
            (ledger_rows[0].get("run_id") if ledger_rows else "") or ""
        )
        report["created_room_id"] = created
        latch = classify_room_latch(
            ledger_rows=ledger_rows,
            authoritative_state=start_val.get("authoritative_state") or {},
            click_ts=click_ts,
            created_room_id=created,
            ws_supplemental=start_val.get("start_click_transport") or {},
        )
        report["latch_classification"] = latch
        report["latch_boundary"] = latch.get("classification")
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"latch_boundary": report.get("latch_boundary"), "artifact": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
