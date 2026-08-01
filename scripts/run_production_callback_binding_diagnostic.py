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
        INTERNAL_META,
        INVALID_INTERNAL_METADATA_OBSERVABILITY,
        METADATA_AT_DISPATCH,
        METADATA_AT_REGISTRATION,
        classify_callback_metadata_boundary,
        evaluate_case_a_metadata_authority,
    )
    from p8_canary_build_gate import (
        CALLBACK_METADATA_OBS_ANCHOR_SHA,
        CALLBACK_METADATA_OBS_GATE_SHA,
        METADATA_READ_FIX_SHA,
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
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from p8_diagnostic_setup import (
        ensure_p8_ldr_setup_surface,
        retry_draft_start_if_stalled,
        validate_p8_diagnostic_setup,
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

    pin = local_deploy_pin()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "accepted_prior_outcome": "CB1 — PRODUCTION_ON_CHANGE_NEVER_INVOKED",
        "prior_metadata_run_verdict": CONTROL_PROBE_INVALID,
        "prior_invalid_internal_observability_sha": "39b9ef4",
        "deploy_pin": pin,
        "observability_implementation_sha": CALLBACK_OBS_ANCHOR_SHA,
        "metadata_fix_implementation_sha": REGISTRATION_BOUNDARY_OBS_SHA,
        "deploy_trigger_sha": CALLBACK_METADATA_OBS_GATE_SHA,
        "git_head": git_head_short(),
        "mode": "callback_metadata_diagnostic_v3",
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
        control_entered = [r for r in peak if r.get("event") == CONTROL_ENTERED]
        control_exited = [r for r in peak if r.get("event") == "production_stage1_control_on_change_exited"]
        case_dispatch = [r for r in peak if r.get("event") == CALLBACK_DISPATCH_EVALUATED]
        case_backend = [r for r in peak if r.get("event") == BACKEND_STATE]
        case_meta = [r for r in peak if r.get("event") == INTERNAL_META]
        delivery_proven = case_a_ok and bool(control_entered)
        case_authority = evaluate_case_a_metadata_authority(
            peak_rows=peak,
            case_a_delivery_proven=delivery_proven,
            control_entered=control_entered,
            control_exited=control_exited,
        )
        from p8_callback_metadata_diagnostic_report import summarize_internal_lane

        report["case_a"] = {
            "ok": case_a_ok,
            "scrape": snap,
            "callback_registration_timeline": [r for r in peak if r.get("event") == REGISTRATION],
            "internal_metadata_timeline": case_meta,
            "dispatch_timeline": case_dispatch,
            "backend_state_timeline": case_backend,
            "control_callback_entered_timeline": control_entered,
            "control_callback_exited_timeline": control_exited,
            "control_delivery_proven": delivery_proven,
        }
        report["case_a_metadata_authority"] = case_authority
        report["case_a_internal_timeline_summary"] = {
            "metadata": summarize_internal_lane(
                [r for r in case_meta if str(r.get("diagnostic_surface") or "") == "case_a"]
                or [r for r in case_meta if str(r.get("widget_key", "")).startswith("minimal_wake")],
                label="case_a",
            ),
            "dispatch": summarize_internal_lane(case_dispatch, label="case_a_dispatch"),
            "backend": summarize_internal_lane(case_backend, label="case_a_backend"),
        }

        if not case_authority.get("authoritative"):
            report["first_boundary"] = case_authority.get("failure_boundary") or INVALID_INTERNAL_METADATA_OBSERVABILITY
            report["smallest_correction_boundary"] = INVALID_INTERNAL_METADATA_OBSERVABILITY
            report["production_skipped"] = True
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            _persist_report(report)
            print(
                json.dumps(
                    {
                        "first_boundary": INVALID_INTERNAL_METADATA_OBSERVABILITY,
                        "artifact": str(OUT),
                    },
                    indent=2,
                )
            )
            return 1

        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        report["cloud_runtime_probe"] = scrape_cloud_runtime_deploy_probe(page)
        cleanup = ensure_fresh_setup_lobby(page)
        if not cleanup.get("ok"):
            report["first_boundary"] = "CB10 — OTHER"
            _write_abort(report, reason="setup_lobby_blocked", boundary=report["first_boundary"])
            context.close()
            browser.close()
            return 1
        ensure_p8_ldr_setup_surface(page, setup_url=url)
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        draft = retry_draft_start_if_stalled(page, draft, setup_url=url)
        start_val = validate_p8_diagnostic_setup(
            page, draft, prior_room_id="", auth_preflight=pre, max_wait_s=75.0
        )
        if not start_val.get("valid"):
            _write_abort(report, reason=start_val.get("verdict") or "setup_invalid", boundary="CB10 — OTHER")
            context.close()
            browser.close()
            return 1

        exp = wait_one_expiration(page, timeout_s=95.0)
        cap_p = capture_all_ledger_sources(page)
        collector.absorb_capture(cap_p, label="production_expiration")
        token_sent = str(exp.get("token_sent") or "")
        room = str(start_val.get("latched_room_id") or "")
        report["diagnostic_run_id"] = _infer_run_id(collector.peak_rows(), room)
        report["room_id"] = room
        report["exact_expiration_token"] = token_sent
        report["production_expiration"] = {
            "token_sent": token_sent,
            "client_stages": exp.get("client_stages"),
        }

        unfiltered = _ledger_rows(exp) or collector.peak_rows()
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
        direct_return = ""
        for r in rows:
            if r.get("event") == "production_countdown_declaration_post":
                outbound_id = str(
                    r.get("actual_registered_widget_id") or r.get("generated_internal_widget_id") or ""
                )
                direct_return = str(r.get("direct_return_value") or "")
                if outbound_id:
                    break
        prod_entered = [r for r in rows if r.get("event") == PROD_ENTERED]
        prod_exited = [r for r in rows if r.get("event") == PROD_EXITED]
        regs = [r for r in rows if r.get("event") == REGISTRATION]
        entry = prod_entered[-1] if prod_entered else {}
        exit_row = prod_exited[-1] if prod_exited else {}
        report["production_callback_registration_timeline"] = regs
        report["production_internal_metadata_timeline"] = [r for r in rows if r.get("event") == INTERNAL_META]
        report["production_backend_state_timeline"] = [r for r in rows if r.get("event") == BACKEND_STATE]
        report["production_dispatch_timeline"] = [r for r in rows if r.get("event") == CALLBACK_DISPATCH_EVALUATED]
        report["production_callback_timeline"] = {
            "registrations": regs,
            "prod_entered": prod_entered,
            "prod_exited": prod_exited,
        }
        report["outbound_widget_id"] = outbound_id
        report["callback_owning_declaration_id"] = (
            str(regs[-1].get("declaration_invocation_id") or "") if regs else ""
        )
        report["prod_on_change_entered"] = bool(prod_entered)
        report["session_state_at_callback_entry"] = {
            "key_exists": entry.get("session_state_key_exists"),
            "value_repr": entry.get("session_state_value_repr"),
        }
        report["session_state_at_callback_exit"] = {
            "key_exists": exit_row.get("session_state_key_exists_at_exit"),
            "value_repr": exit_row.get("session_state_value_at_exit_repr"),
        }
        report["direct_component_return"] = direct_return
        report["exceptions"] = str(exit_row.get("exception_status") or "") or None

        cb_classification = classify_callback_boundary(
            filtered_rows=rows,
            exact_token=token_sent,
            outbound_widget_id=outbound_id,
        )
        cm_classification = classify_callback_metadata_boundary(
            filtered_rows=rows,
            exact_token=token_sent,
            production_widget_key=PRODUCTION_WIDGET_KEY,
        )
        report["cb1_boundary"] = cb_classification.get("classification")
        report["first_boundary"] = cm_classification.get("classification")
        report["classification_detail"] = cm_classification
        report["callback_boundary_detail"] = cb_classification
        report["internal_comparison"] = cm_classification.get("comparison")
        report["architectural_options"] = cm_classification.get("architectural_options") or []
        report["smallest_correction_boundary"] = cm_classification.get("smallest_correction_boundary")
        report["production_internal_timeline_summary"] = {
            "metadata": summarize_internal_lane(
                [r for r in rows if r.get("event") == INTERNAL_META],
                label="production",
            ),
            "dispatch": summarize_internal_lane(
                [r for r in rows if r.get("event") == CALLBACK_DISPATCH_EVALUATED],
                label="production_dispatch",
            ),
            "backend": summarize_internal_lane(
                [r for r in rows if r.get("event") == BACKEND_STATE],
                label="production_backend",
            ),
            "prod_callback_entered": len(prod_entered),
            "prod_callback_exited": len(prod_exited),
            "exact_expiration_token": token_sent,
            "direct_component_return": direct_return,
        }
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    _persist_report(report)
    print(json.dumps({"first_boundary": report.get("first_boundary"), "artifact": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
