"""One Cloud callback trace: Case A control then production expiration (CB1–CB10)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_callback_binding_diagnostic.json"
PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"


def main() -> int:
    os.environ.pop("REQUIRED_CLOUD_SHA", None)
    from p8_callback_boundary_classify import (
        CONTROL_ENTERED,
        PROD_ENTERED,
        PROD_EXITED,
        REGISTRATION,
        classify_callback_boundary,
    )
    from p8_canary_build_gate import (
        evaluate_cloud_binding_readiness,
        local_deploy_pin,
        poll_live_cloud_sha,
        scrape_cloud_runtime_deploy_probe,
    )
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import (
        ensure_fresh_setup_lobby,
        production_url,
        wait_one_expiration,
    )
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface, retry_draft_start_if_stalled, validate_p8_diagnostic_setup
    from run_production_p8_binding_diagnostic import (
        _infer_run_id,
        _ledger_rows,
        resolve_required_sha,
    )
    from stage1_ledger_run_filter import filter_ledger_rows_for_diagnostic_run
    from p8_ledger_observability import capture_all_ledger_sources, P8LedgerHarnessCollector

    if not harness_ready():
        OUT.write_text(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}, indent=2), encoding="utf-8")
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        OUT.write_text(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}, indent=2), encoding="utf-8")
        return 1

    pin = local_deploy_pin()
    poll = poll_live_cloud_sha(
        max_attempts=24,
        sleep_s=20.0,
        require_canary_impl=False,
        wait_for_binding_readiness=True,
    )
    readiness = poll.get("binding_readiness") or {}
    report: dict[str, Any] = {
        "started_at": time.time(),
        "accepted_prior_outcome": "VALID_CORRECTED_BUILD_FAILURE",
        "deploy_pin": pin,
        "cloud_binding_readiness": readiness,
        "mode": "callback_binding_diagnostic",
    }
    if not poll.get("ok") or not readiness.get("ok"):
        report["aborted"] = True
        report["abort_reason"] = "INVALID_FIX_NOT_DEPLOYED"
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 1

    from p8_canary_build_gate import commit_has_callback_observability, git_sha_is_ancestor

    obs_sha = "919e196"
    runtime_git = str(readiness.get("runtime_git_head_short") or poll.get("live_sha") or "")
    impl_obs = commit_has_callback_observability(runtime_git)
    if not impl_obs.get("ok") and not git_sha_is_ancestor(obs_sha, runtime_git):
        for _ in range(36):
            time.sleep(20)
            poll = poll_live_cloud_sha(
                max_attempts=1,
                sleep_s=0,
                require_canary_impl=False,
                wait_for_binding_readiness=True,
            )
            readiness = poll.get("binding_readiness") or {}
            runtime_dom = (poll.get("attempts") or [{}])[-1].get("runtime_probe") or {}
            runtime_git = str(
                runtime_dom.get("runtime_git_head_short")
                or readiness.get("runtime_git_head_short")
                or poll.get("live_sha")
                or ""
            )
            impl_obs = commit_has_callback_observability(runtime_git)
            if impl_obs.get("ok") or git_sha_is_ancestor(obs_sha, runtime_git):
                break
        report["observability_deploy_poll"] = poll
        report["callback_observability_at_runtime"] = impl_obs
        if not impl_obs.get("ok") and not git_sha_is_ancestor(obs_sha, runtime_git):
            report["aborted"] = True
            report["abort_reason"] = "callback_observability_not_on_cloud_runtime"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 1

    report["live_sha"] = readiness.get("marker_sha") or poll.get("live_sha")
    report["live_build"] = readiness.get("marker_build") or poll.get("live_build")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        try:
            from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
            from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT

            context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
            context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
        except ImportError:
            pass
        page = context.new_page()
        collector = P8LedgerHarnessCollector()

        # Case A control
        goto_and_wake(page, case_a_url(), timeout_s=240)
        case_a_deadline = time.time() + 130.0
        case_a_ok = False
        while time.time() < case_a_deadline:
            snap = scrape_case_a(page)
            ca = snap.get("case_a") or {}
            if int(ca.get("callbacks") or 0) >= 1 or ca.get("passed") in ("1", "true"):
                case_a_ok = True
                break
            page.wait_for_timeout(3000)
        cap_a = capture_all_ledger_sources(page)
        collector.absorb_capture(cap_a, label="case_a")
        report["case_a"] = {
            "ok": case_a_ok,
            "scrape": snap,
            "control_on_change_entered": [
                r for r in collector.peak_rows() if r.get("event") == CONTROL_ENTERED
            ],
        }

        # Production expiration
        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        runtime_dom = scrape_cloud_runtime_deploy_probe(page)
        report["cloud_runtime_probe"] = runtime_dom
        cleanup = ensure_fresh_setup_lobby(page)
        if not cleanup.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "setup_lobby_blocked"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        ensure_p8_ldr_setup_surface(page, setup_url=url)
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        draft = retry_draft_start_if_stalled(page, draft, setup_url=url)
        start_val = validate_p8_diagnostic_setup(page, draft, prior_room_id="", auth_preflight=pre, max_wait_s=75.0)
        if not start_val.get("valid"):
            report["aborted"] = True
            report["abort_reason"] = start_val.get("verdict") or "setup_invalid"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        exp = wait_one_expiration(page, timeout_s=95.0)
        cap_p = capture_all_ledger_sources(page)
        collector.absorb_capture(cap_p, label="production_expiration")
        token_sent = str(exp.get("token_sent") or "")
        report["production_expiration"] = {
            "token_sent": token_sent,
            "client_stages": exp.get("client_stages"),
        }
        unfiltered = _ledger_rows(exp) or collector.peak_rows()
        room = str(start_val.get("latched_room_id") or "")
        run_id = _infer_run_id(unfiltered, room)
        sha = resolve_required_sha()
        filtered = filter_ledger_rows_for_diagnostic_run(
            unfiltered,
            run_id=run_id,
            room_id=room,
            deployment_sha=sha,
            exact_token=token_sent,
        )
        rows = list(filtered.get("filtered_rows") or [])
        outbound_id = ""
        for r in rows:
            if r.get("event") == "production_countdown_declaration_post":
                outbound_id = str(r.get("actual_registered_widget_id") or r.get("generated_internal_widget_id") or "")
                if outbound_id:
                    break
        classification = classify_callback_boundary(
            filtered_rows=rows,
            exact_token=token_sent,
            outbound_widget_id=outbound_id,
        )
        report["production_callback_timeline"] = {
            "registrations": [r for r in rows if r.get("event") == REGISTRATION],
            "prod_entered": [r for r in rows if r.get("event") == PROD_ENTERED],
            "prod_exited": [r for r in rows if r.get("event") == PROD_EXITED],
        }
        report["callback_owning_declaration_id"] = (
            (report["production_callback_timeline"]["registrations"][-1].get("declaration_invocation_id") or "")
            if report["production_callback_timeline"]["registrations"]
            else ""
        )
        report["outbound_widget_id"] = outbound_id
        report["first_boundary"] = classification.get("classification")
        report["classification_detail"] = classification
        report["smallest_correction_boundary"] = classification.get("classification")
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"first_boundary": report.get("first_boundary"), "artifact": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
