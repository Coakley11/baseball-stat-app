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

OUT = ROOT / "data" / "production_callback_metadata_diagnostic.json"
OUT_TXT = ROOT / "data" / "production_callback_metadata_diagnostic.txt"
LEGACY_OUT = ROOT / "data" / "production_callback_binding_diagnostic.json"
LOG = ROOT / "data" / "production_callback_binding_diagnostic_run.out"
PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
INVALID_OBS = "INVALID_OBSERVABILITY_NOT_DEPLOYED"


def _persist_report(report: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    LEGACY_OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    try:
        from p8_callback_metadata_diagnostic_report import format_metadata_diagnostic_txt

        OUT_TXT.write_text(format_metadata_diagnostic_txt(report), encoding="utf-8")
    except ImportError:
        pass


def _write_abort(report: dict[str, Any], *, reason: str, boundary: str = INVALID_OBS) -> None:
    report["aborted"] = True
    report["abort_reason"] = reason
    report["first_boundary"] = boundary
    report["smallest_correction_boundary"] = boundary
    report["artifact_path"] = str(OUT)
    report["artifact_txt_path"] = str(OUT_TXT)
    report["finished_at"] = time.time()
    _persist_report(report)


def main() -> int:
    os.environ.pop("REQUIRED_CLOUD_SHA", None)
    from p8_callback_boundary_classify import (
        CONTROL_ENTERED,
        PROD_ENTERED,
        PROD_EXITED,
        REGISTRATION,
        classify_callback_boundary,
    )
    from p8_callback_metadata_classify import (
        BACKEND_STATE,
        CALLBACK_DISPATCH_EVALUATED,
        CONTROL_PROBE_INVALID,
        HOOKS_INSTALLED,
        INTERNAL_META,
        INVALID_CLOUD_DIAGNOSTIC_LEDGER_VISIBILITY,
        INVALID_CLOUD_REGISTRATION_HOOK_INSTALLATION,
        INVALID_INTERNAL_METADATA_OBSERVABILITY,
        INVALID_REGISTRATION_BOUNDARY_OBSERVABILITY,
        METADATA_AT_DISPATCH,
        METADATA_AT_REGISTRATION,
        REG_HOOK_ENTERED,
        REG_HOOK_EXITED,
        classify_callback_metadata_boundary,
        evaluate_case_a_gate_a,
    )
    from p8_canary_build_gate import (
        CALLBACK_METADATA_OBS_ANCHOR_SHA,
        CALLBACK_METADATA_OBS_GATE_SHA,
        REGISTRATION_HOOK_OBS_SHA,
        REGISTRATION_BOUNDARY_OBS_SHA,
        CALLBACK_OBS_ANCHOR_SHA,
        git_head_short,
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
    from p8_production_start_harness import (
        INVALID_PRODUCTION_EXPIRATION_TRACE,
        run_gate_b_production_start,
    )
    from run_production_p8_binding_diagnostic import (
        _infer_run_id,
        _ledger_rows,
        resolve_required_sha,
    )
    from stage1_ledger_run_filter import filter_ledger_rows_for_diagnostic_run
    from p8_ledger_observability import capture_all_ledger_sources, P8LedgerHarnessCollector

    if not harness_ready():
        _write_abort({"reason": "auth_harness_incomplete"}, reason="auth_harness_incomplete")
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        _write_abort({"reason": "auth_preflight_failed", "preflight": pre}, reason="auth_preflight_failed")
        return 1

    from live_draft_streamlit_registration_hooks import run_local_case_a_hook_self_test

    hook_self_test = run_local_case_a_hook_self_test()
    if not hook_self_test.get("ok"):
        _write_abort(
            {
                "reason": "registration_hook_case_a_self_test_failed",
                "hook_self_test": hook_self_test,
            },
            reason="registration_hook_case_a_self_test_failed",
            boundary=INVALID_REGISTRATION_BOUNDARY_OBSERVABILITY,
        )
        return 1

    pin = local_deploy_pin()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "accepted_prior_cloud_run": "INVALID_CLOUD_DIAGNOSTIC_LEDGER_VISIBILITY @ 3125f9e",
        "accepted_cb1": "CB1 — PRODUCTION_ON_CHANGE_NEVER_INVOKED",
        "cm1_cm10_from_prior_run": "not_accepted",
        "deploy_pin": pin,
        "observability_implementation_sha": CALLBACK_OBS_ANCHOR_SHA,
        "prior_invalid_registration_boundary_sha": "f7ce65c",
        "registration_hook_observability_sha": REGISTRATION_HOOK_OBS_SHA,
        "metadata_fix_implementation_sha": REGISTRATION_BOUNDARY_OBS_SHA,
        "deploy_trigger_sha": CALLBACK_METADATA_OBS_GATE_SHA,
        "git_head": git_head_short(),
        "mode": "callback_metadata_diagnostic_v6_dispatch_authority_gate_b",
        "local_registration_hook_self_test": hook_self_test,
        "artifact_path": str(OUT),
        "artifact_txt_path": str(OUT_TXT),
        "legacy_artifact_path": str(LEGACY_OUT),
        "log_path": str(LOG),
    }

    poll = poll_live_cloud_sha(
        max_attempts=48,
        sleep_s=20.0,
        require_canary_impl=False,
        wait_for_callback_metadata_observability=True,
    )
    obs = poll.get("callback_metadata_observability_readiness") or poll.get("callback_observability_readiness") or {}
    report["observability_deploy_poll"] = poll
    report["cloud_callback_observability_readiness"] = obs
    report["metadata_read_fix_readiness"] = obs.get("metadata_read_fix_at_runtime_git")
    report["live_sha"] = obs.get("runtime_git_head_short") or poll.get("live_sha")
    report["live_build"] = obs.get("marker_build") or poll.get("live_build")

    if not poll.get("ok") or not obs.get("ok"):
        _write_abort(
            report,
            reason="callback_observability_bytecode_not_proven_on_cloud",
            boundary=INVALID_OBS,
        )
        print(json.dumps({"first_boundary": INVALID_OBS, "artifact": str(OUT)}, indent=2))
        return 1

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

        goto_and_wake(page, case_a_url(), timeout_s=240)
        case_a_deadline = time.time() + 130.0
        snap: dict[str, Any] = {}
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
        peak = collector.peak_rows()
        from live_draft_stage1_ledger_pipeline import (
            PIPELINE_CANARY_EVENT,
            classify_first_ledger_pipeline_failure,
        )

        pipeline_dom = cap_a.get("pipeline_canary_dom") or {}
        browser_extract = cap_a.get("browser_ledger_extract") or {}
        pipeline_eval = classify_first_ledger_pipeline_failure(
            pipeline_dom=pipeline_dom,
            ledger_rows=peak,
            artifact_has_canary=any(
                isinstance(r, dict) and r.get("event") == PIPELINE_CANARY_EVENT for r in peak
            ),
            raw_p6_capture_pass=cap_a.get("raw_p6_capture_pass"),
            filtered_p6_capture_pass=cap_a.get("filtered_p6_capture_pass"),
        )
        report["browser_ledger_extract"] = browser_extract
        report["raw_p6_capture_pass"] = cap_a.get("raw_p6_capture_pass")
        report["filtered_p6_capture_pass"] = cap_a.get("filtered_p6_capture_pass")
        report["first_scrape_boundary"] = browser_extract.get("first_scrape_boundary")
        report["ledger_scrape_candidates"] = browser_extract.get("candidates")
        report["ledger_pipeline_dom"] = pipeline_dom
        report["ledger_pipeline_stages"] = pipeline_eval
        if str(pipeline_eval.get("classification") or "") not in ("", "LEDGER_PIPELINE_OK"):
            report["first_boundary"] = str(pipeline_eval.get("classification") or "LEDGER10 — OTHER")
            report["smallest_correction_boundary"] = report["first_boundary"]
            report["production_skipped"] = True
            report["gate"] = "ledger_pipeline_failed"
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            _persist_report(report)
            print(
                json.dumps(
                    {
                        "first_boundary": report["first_boundary"],
                        "artifact": str(OUT),
                        "gate": "ledger_pipeline",
                    },
                    indent=2,
                )
            )
            return 1

        control_entered = [r for r in peak if r.get("event") == CONTROL_ENTERED]
        control_exited = [r for r in peak if r.get("event") == "production_stage1_control_on_change_exited"]
        case_dispatch = [r for r in peak if r.get("event") == CALLBACK_DISPATCH_EVALUATED]
        case_backend = [r for r in peak if r.get("event") == BACKEND_STATE]
        case_meta = [r for r in peak if r.get("event") == INTERNAL_META]
        hooks_installed = [r for r in peak if r.get("event") == HOOKS_INSTALLED]
        reg_hook_entered = [r for r in peak if r.get("event") == REG_HOOK_ENTERED]
        reg_hook_exited = [r for r in peak if r.get("event") == REG_HOOK_EXITED]
        delivery_proven = case_a_ok and (
            bool(control_entered) or bool(reg_hook_entered) or bool(hooks_installed)
        )
        case_gate_a = evaluate_case_a_gate_a(
            peak_rows=peak,
            case_a_delivery_proven=delivery_proven,
            control_entered=control_entered or reg_hook_entered,
            control_exited=control_exited,
            local_hook_self_test_ok=bool(hook_self_test.get("ok")),
        )
        from p8_callback_metadata_diagnostic_report import summarize_internal_lane

        report["case_a"] = {
            "ok": case_a_ok,
            "scrape": snap,
            "registration_hooks_installed_timeline": hooks_installed,
            "registration_hook_entered_timeline": reg_hook_entered,
            "registration_hook_exited_timeline": reg_hook_exited,
            "callback_registration_timeline": [r for r in peak if r.get("event") == REGISTRATION],
            "legacy_metadata_at_registration_timeline": [
                r for r in peak if r.get("event") == METADATA_AT_REGISTRATION
            ],
            "internal_metadata_timeline": case_meta,
            "dispatch_timeline": case_dispatch,
            "backend_state_timeline": case_backend,
            "control_callback_entered_timeline": control_entered,
            "control_callback_exited_timeline": control_exited,
            "control_delivery_proven": delivery_proven,
        }
        report["case_a_gate_a"] = case_gate_a
        report["runtime_registration_map_paths"] = {
            "json": "data/p8_streamlit_registration_runtime_map.json",
            "txt": "data/p8_streamlit_registration_runtime_map.txt",
        }
        report["case_a_internal_timeline_summary"] = {
            "metadata": summarize_internal_lane(
                [r for r in case_meta if str(r.get("diagnostic_surface") or "") == "case_a"]
                or [r for r in case_meta if str(r.get("widget_key", "")).startswith("minimal_wake")],
                label="case_a",
            ),
            "dispatch": summarize_internal_lane(case_dispatch, label="case_a_dispatch"),
            "backend": summarize_internal_lane(case_backend, label="case_a_backend"),
        }

        if not case_gate_a.get("case_a_dispatch_authority"):
            boundary = (
                case_gate_a.get("failure_boundary")
                or INVALID_INTERNAL_METADATA_OBSERVABILITY
            )
            report["first_boundary"] = boundary
            report["smallest_correction_boundary"] = boundary
            report["production_skipped"] = True
            report["gate"] = "A_dispatch_failed"
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            _persist_report(report)
            print(
                json.dumps(
                    {
                        "first_boundary": boundary,
                        "artifact": str(OUT),
                        "gate": "A_dispatch",
                    },
                    indent=2,
                )
            )
            return 1

        report["case_a_dispatch_authority"] = bool(case_gate_a.get("case_a_dispatch_authority"))
        report["case_a_registration_trace_available"] = bool(
            case_gate_a.get("case_a_registration_trace_available")
        )
        report["registration_trace_boundary"] = case_gate_a.get("registration_trace_boundary") or ""
        report["gate_a_outcome"] = case_gate_a.get("gate_a_outcome") or ""
        report["gate_a_passed"] = bool(case_gate_a.get("authoritative"))
        ledger_ok = str(pipeline_eval.get("classification") or "") in ("", "LEDGER_PIPELINE_OK")

        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(5000)
        report["production_ldr_surface"] = ensure_p8_ldr_setup_surface(page, setup_url=url)
        cleanup = ensure_fresh_setup_lobby(page, max_wait_s=180)
        report["production_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["first_boundary"] = "INVALID_PRODUCTION_SETUP"
            report["production_skipped"] = True
            report["gate"] = "B_setup_failed"
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            _persist_report(report)
            return 1

        start_val = run_gate_b_production_start(
            page,
            url,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            auth_preflight=pre,
        )
        report["production_start_timeline"] = start_val.get("timeline")
        report["production_start_boundary"] = start_val.get("start_boundary")
        report["production_setup"] = start_val
        if not start_val.get("valid"):
            report["first_boundary"] = (
                start_val.get("failure_boundary")
                or f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP"
            )
            report["smallest_correction_boundary"] = start_val.get("start_boundary") or report["first_boundary"]
            report["production_skipped"] = True
            report["gate"] = "B_start_proof_failed"
            report["production_expiration_trace"] = INVALID_PRODUCTION_EXPIRATION_TRACE
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            _persist_report(report)
            print(
                json.dumps(
                    {
                        "first_boundary": report["first_boundary"],
                        "start_boundary": start_val.get("start_boundary"),
                        "artifact": str(OUT),
                        "gate": "B_start",
                    },
                    indent=2,
                )
            )
            return 1

        from p8_ledger_observability import enrich_expiration_ledger
        from run_production_stage1_authenticated import build_return_value_chain_report

        page.wait_for_timeout(8000)
        exp = wait_one_expiration(page, timeout_s=95.0)
        enrich_expiration_ledger(page, exp, collector, label="post_expiration")
        sha = str(report.get("live_sha") or "")
        exp["cloud_sha"] = sha
        room_latched = str(start_val.get("latched_room_id") or "")
        exp["room_id"] = room_latched
        rv = build_return_value_chain_report(
            page,
            exp,
            start_val=start_val,
            queue_meta={"queue_independence": "NOT EXERCISED — EMPTY QUEUE"},
            cloud_sha=sha,
            cloud_build=str(report.get("live_build") or ""),
        )
        unfiltered = _ledger_rows(exp)
        if not unfiltered:
            meta = exp.get("ledger_meta") or {}
            unfiltered = list(meta.get("merged_server_ledger") or [])
        token_for_filter = str(
            exp.get("token_sent")
            or rv.get("browser", {}).get("exact_expiration_token")
            or (start_val.get("authoritative_state") or {}).get("production_token")
            or ""
        ).strip()
        run_id = _infer_run_id(unfiltered, room_latched)
        filtered_meta = filter_ledger_rows_for_diagnostic_run(
            unfiltered,
            run_id=run_id,
            room_id=room_latched,
            deployment_sha=sha,
            exact_token=token_for_filter,
        )
        filtered_rows = filtered_meta.get("filtered_rows") or []
        exp["filtered_ledger_rows"] = filtered_rows
        exp["ledger_filter"] = filtered_meta
        report["production_diagnostic_run_id"] = run_id
        report["production_room_id"] = room_latched
        report["production_exact_token"] = token_for_filter
        report["production_expiration"] = exp
        report["production_return_value_chain"] = rv

        cb_report = classify_callback_boundary(
            filtered_rows=filtered_rows,
            exact_token=token_for_filter,
            outbound_widget_id=str(exp.get("outbound_widget_id") or ""),
        )
        cm_report = classify_callback_metadata_boundary(
            filtered_rows=filtered_rows,
            exact_token=token_for_filter,
            production_widget_key=PRODUCTION_WIDGET_KEY,
        )
        report["callback_boundary"] = cb_report
        report["callback_metadata_boundary"] = cm_report
        report["accepted_cb1"] = cb_report.get("classification") or report.get("accepted_cb1")
        report["production_skipped"] = False
        report["gate"] = "B_complete"
        report["first_boundary"] = cm_report.get("classification") or cb_report.get("classification") or ""
        report["smallest_correction_boundary"] = (
            cm_report.get("smallest_correction_boundary")
            or cb_report.get("classification")
            or report["first_boundary"]
        )
        report["finished_at"] = time.time()
        context.close()
        browser.close()
        _persist_report(report)
        print(
            json.dumps(
                {
                    "gate_a_outcome": report.get("gate_a_outcome"),
                    "case_a_dispatch_authority": report.get("case_a_dispatch_authority"),
                    "callback_boundary": cb_report.get("classification"),
                    "callback_metadata_boundary": cm_report.get("classification"),
                    "artifact": str(OUT),
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
