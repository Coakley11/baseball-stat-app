"""Production: Start → Sibling PRE-PAUSE → Pause → Sibling POST-PAUSE (E2 order)."""

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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_bridge_pause_sibling_order_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _room_phase_snapshot(page) -> dict[str, Any]:
    from stage1_application_phase import classify_ldr_phase_from_page

    return classify_ldr_phase_from_page(page)


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED, wait_for_authoritative_pause_control
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import queue_setup_pause_for_seeding, resolve_required_cloud_sha
    from stage1_pause_sibling_click_step import execute_pause_sibling_click
    from stage1_pause_sibling_order_gate_classify import (
        ABORTED_PAUSE_SIBLING_LEDGER,
        classify_pause_sibling_order,
        recommended_pause_sibling_order_fix,
    )
    from stage1_pause_sibling_scrape import (
        PAUSE_SIBLING_IMPL_REV,
        generation_comparison,
        scrape_pause_sibling_generation,
        scrape_pause_sibling_probe,
    )
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame

    if str(os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "").strip().lower() in ("0", "false"):
        print(json.dumps({"ok": False, "classification": "ABORTED_CAPTURE_BRIDGE_DISABLED"}))
        return 1

    bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1

    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "99ced8c").strip().lower()[:7]
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    url = append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    report: dict[str, Any] = {
        "mode": "production_bridge_pause_sibling_order_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "application_runtime_sha_expected": "99ced8c",
        "accepted_boundary": "BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE",
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "sequence": ["start", "sibling_pre_pause", "pause", "sibling_post_pause", "classify"],
        "started_at": time.time(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        install_proven_start_context_scripts(context)
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)

        from p8_production_start_harness import scrape_stage1_ledger_rows
        from queueui_audit_protocol import scrape_deploy_marker_from_page

        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        report["application_runtime_sha"] = str(deploy_sha or "")[:7]
        if required and str(report["application_runtime_sha"]).lower()[:7] != required:
            report["classification"] = "ABORTED_RUNTIME_SHA_MISMATCH"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        bridge_pre = wait_bridge_auth_hydrated(page, bridge_sid, scrape_stage1_ledger_rows, timeout_s=240.0, preamble_mode="stage1")
        report["bridge_hydration"] = bridge_pre
        if not bridge_pre.get("authenticated_restored"):
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1
        restore_block = str(
            (bridge_pre.get("bound_current_auth") or {}).get("current_restore_blocked_reason")
            or bridge_pre.get("restore_block")
            or ""
        ).strip()
        if restore_block:
            report["classification"] = "ABORTED_RESTORE_BLOCK"
            report["restore_blocked_reason"] = restore_block
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        canonical = establish_single_solo_live_draft(page, context, setup_url=url, prior_room_id="", max_wait_s=90.0)
        room_id = str(canonical.get("room_id") or "").upper()
        report["start_latch"] = {"room_id": room_id, "room_latch_pass": canonical.get("room_latch_pass")}
        if not room_id or not canonical.get("room_latch_pass"):
            report["classification"] = "ABORTED_START_LATCH"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        pause_hydration = wait_for_authoritative_pause_control(page, max_wait_s=45.0, room_id=room_id)
        report["pre_pause_hydration"] = pause_hydration
        report["room_phase_pre_sibling"] = _room_phase_snapshot(page)
        if not pause_hydration.get("ready"):
            report["classification"] = "ABORTED_PAUSE_UI_NOT_READY_FOR_PRE_SIBLING"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        frame = resolve_streamlit_app_frame(page)
        report["app_frame_inventory_pre_sibling"] = describe_page_frames(page)
        pre_ledger = scrape_pause_sibling_probe(page, frame=frame)
        report["sibling_ledger_pre_click"] = pre_ledger
        if not pre_ledger.get("probe_found") or str(pre_ledger.get("impl_rev") or "") != PAUSE_SIBLING_IMPL_REV:
            report["classification"] = ABORTED_PAUSE_SIBLING_LEDGER
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1
        if int(pre_ledger.get("count") or 0) != 0:
            report["classification"] = ABORTED_PAUSE_SIBLING_LEDGER
            report["classification_note"] = "pre_count_not_zero"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        session_hint = str(pre_ledger.get("streamlit_session_id") or "")
        pre_step = execute_pause_sibling_click(
            page,
            phase="sibling_pre_pause",
            session_hint=session_hint,
            require_count_baseline=0,
        )
        report["sibling_pre_pause_step"] = pre_step
        pre_pass: bool | None
        pre_evaluated = not pre_step.get("setup_abort")
        if pre_step.get("setup_abort"):
            pre_pass = None
            report["classification"] = ABORTED_PAUSE_SIBLING_LEDGER if pre_step.get("setup_abort") == "SIBLING_LEDGER_NOT_EXPOSED" else "ABORTED_PAUSE_SIBLING_PRE_SETUP"
            report["classification_note"] = str(pre_step.get("setup_abort"))
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 1
        else:
            pre_pass = bool(pre_step.get("sibling_pass")) and bool(pre_step.get("trusted_dom_click"))

        post_step: dict[str, Any] | None = None
        post_pass: bool | None = None
        post_evaluated = False

        latch_ts = time.time()
        pause_block = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=latch_ts)
        report["pause_delivery"] = pause_block
        pause_ok = bool(pause_block.get("paused")) and pause_block.get("pause_classification") == PAUSE_DELIVERY_RESOLVED
        report["room_phase_post_pause"] = _room_phase_snapshot(page)

        if not pause_ok:
            case, note = classify_pause_sibling_order(
                pre_pass=pre_pass,
                pause_resolved=False,
                post_pass=None,
                pre_evaluated=True,
                post_evaluated=False,
            )
            report["classification"] = case
            report["classification_note"] = note
            report["recommended_next_fix"] = recommended_pause_sibling_order_fix(case)
            report["pre_pass"] = pre_pass
            report["pause_resolved"] = False
            report["post_pass"] = None
            report["post_skipped_reason"] = "pause_not_resolved_order_d_or_e"
            report["room_id"] = room_id
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": case, "artifact": str(OUT)}))
            return 1

        frame_post_pause = resolve_streamlit_app_frame(page)
        report["app_frame_inventory_post_pause"] = describe_page_frames(page)
        post_gen_before = scrape_pause_sibling_generation(page, frame=frame_post_pause)
        report["sibling_generation_post_pause_before_click"] = post_gen_before
        post_ledger_before = scrape_pause_sibling_probe(page, frame=frame_post_pause)
        report["sibling_ledger_post_pause_before_click"] = post_ledger_before

        expected_post_baseline: int | None = 1 if pre_pass else 0
        if pre_pass and int(post_ledger_before.get("count") or 0) < 1:
            report["post_pause_baseline_warning"] = "expected_count_1_after_pre_pass"
        post_step = execute_pause_sibling_click(
            page,
            phase="sibling_post_pause",
            session_hint=session_hint,
            require_count_baseline=expected_post_baseline if pre_pass else None,
        )
        report["sibling_post_pause_step"] = post_step
        post_evaluated = not post_step.get("setup_abort")
        if post_step.get("setup_abort") == "SIBLING_COUNT_BASELINE_MISMATCH" and pre_pass:
            post_step_retry = execute_pause_sibling_click(
                page,
                phase="sibling_post_pause_retry",
                session_hint=session_hint,
                require_count_baseline=None,
            )
            report["sibling_post_pause_step_retry"] = post_step_retry
            post_step = post_step_retry
            post_evaluated = not post_step.get("setup_abort")
        if post_evaluated and not post_step.get("setup_abort"):
            post_pass = bool(post_step.get("sibling_pass")) and bool(post_step.get("trusted_dom_click"))
        else:
            post_pass = None

        pre_gen = dict(pre_step.get("generation_before_click") or {})
        post_gen = dict(post_step.get("generation_before_click") or {}) if post_step else {}
        report["generation_comparison_pre_vs_post"] = generation_comparison(pre_gen, post_gen)

        setup_abort = ""
        if post_step and post_step.get("setup_abort") == "SIBLING_LEDGER_NOT_EXPOSED":
            setup_abort = "post_sibling_ledger"

        case, note = classify_pause_sibling_order(
            pre_pass=pre_pass,
            pause_resolved=pause_ok,
            post_pass=post_pass if post_evaluated else None,
            pre_evaluated=True,
            post_evaluated=post_evaluated,
            setup_abort=setup_abort,
        )

        report["classification"] = case
        report["classification_note"] = note
        report["recommended_next_fix"] = recommended_pause_sibling_order_fix(case)
        report["pre_pass"] = pre_pass
        report["pause_resolved"] = pause_ok
        report["post_pass"] = post_pass
        report["room_id"] = room_id
        report["ok"] = case in (
            "BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL",
            "BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC",
            "BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN",
        )
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else (1 if str(report.get("classification", "")).startswith("ABORTED") else 2)


if __name__ == "__main__":
    raise SystemExit(main())
