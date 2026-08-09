"""Production: Pause → Pause-Sibling → optional R0 (Case E localization)."""

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

OUT = ROOT / "data" / "production_bridge_pause_sibling_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
SIBLING_LABEL = "Stage1 Pause-Sibling Return Probe"
R0_LABEL = "Stage1 Return-Value Probe"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _click_sibling(page, frame, *, session_hint: str) -> dict[str, Any]:
    from stage1_dom_click_capture import (
        CAPTURE_TARGET_PAUSE_SIBLING,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )
    from stage1_pause_sibling_scrape import (
        PAUSE_SIBLING_IMPL_REV,
        scrape_pause_sibling_probe,
        sibling_delta,
        wait_for_pause_sibling_probe,
    )
    from streamlit_app_frame import describe_page_frames

    out: dict[str, Any] = {"step": "pause_sibling", "started_ts": time.time()}
    out["frame_binding"] = describe_page_frames(page)
    before = scrape_pause_sibling_probe(page, frame=frame)
    out["scrape_before"] = before
    if not before.get("probe_found") or str(before.get("impl_rev") or "") != PAUSE_SIBLING_IMPL_REV:
        out["setup_abort"] = "SIBLING_LEDGER_NOT_EXPOSED"
        out["finished_ts"] = time.time()
        return out
    loc = frame.get_by_role("button", name=SIBLING_LABEL, exact=True)
    try:
        loc.first.wait_for(state="attached", timeout=12000)
        loc.first.wait_for(state="visible", timeout=12000)
        out["target_attached"] = True
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        loc.first.scroll_into_view_if_needed(timeout=12000)
    except Exception as exc:
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out
    prep = prepare_isolated_dom_click_capture(frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING, frame_url_hint=str(frame.url or ""))
    out["dom_click_capture_prep"] = prep
    try:
        loc.first.click(timeout=12000)
        out["click_dispatched"] = True
    except Exception as exc:
        out["click_dispatched"] = False
        out["click_error"] = str(exc)[:240]
        out["finished_ts"] = time.time()
        return out
    min_count = int(before.get("count") or 0) + 1
    wait = wait_for_pause_sibling_probe(
        page, frame, timeout_s=22.0, min_count=min_count, session_id_hint=session_hint
    )
    out["probe_wait"] = wait
    after = dict(wait.get("scrape") or {})
    out["scrape_after"] = after
    dom = read_and_summarize_dom_click_capture(frame, capture_target=CAPTURE_TARGET_PAUSE_SIBLING)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    delta = sibling_delta(before, after)
    out["delta"] = delta
    if delta.get("observability_abort"):
        out["sibling_pass"] = False
        out["observability_abort"] = delta["observability_abort"]
    else:
        last = dict(delta.get("last_event") or {})
        out["sibling_pass"] = (
            int(delta.get("count_delta") or 0) == 1
            and bool(delta.get("new_event"))
            and bool(last.get("returned_true"))
            and bool(last.get("branch_entered"))
        )
        out["last_event_id"] = last.get("event_id")
    out["finished_ts"] = time.time()
    return out


def _click_r0_optional(page, frame) -> dict[str, Any]:
    from stage1_button_dispatch_scrape import dispatch_delta, evaluate_dispatch_pass, scrape_button_dispatch_probe, wait_for_dispatch_probe
    from stage1_dom_click_capture import button_dispatch_capture_target, prepare_isolated_dom_click_capture, read_and_summarize_dom_click_capture

    out: dict[str, Any] = {"step": "r0_optional", "started_ts": time.time()}
    before = scrape_button_dispatch_probe(page, frame=frame)
    out["dispatch_scrape_before"] = before
    if not before.get("probe_found"):
        out["r0_pass"] = None
        out["skipped_reason"] = "dispatch_ledger_missing"
        out["finished_ts"] = time.time()
        return out
    loc = frame.get_by_role("button", name=R0_LABEL, exact=True)
    try:
        loc.first.click(timeout=12000)
        out["click_dispatched"] = True
    except Exception as exc:
        out["click_dispatched"] = False
        out["click_error"] = str(exc)[:240]
        out["r0_pass"] = False
        out["finished_ts"] = time.time()
        return out
    cap = button_dispatch_capture_target("R0")
    dom = read_and_summarize_dom_click_capture(frame, capture_target=cap)
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    wait = wait_for_dispatch_probe(page, frame, timeout_s=22.0)
    after = dict(wait.get("scrape") or {})
    out["dispatch_scrape_after"] = after
    delta = dispatch_delta(before, after, "R0")
    out["dispatch_delta"] = delta
    if delta.get("observability_abort"):
        out["r0_pass"] = False
    else:
        passed, ev = evaluate_dispatch_pass(delta, after, "R0")
        out["r0_pass"] = passed
        out["r0_evidence"] = ev
    out["finished_ts"] = time.time()
    return out


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import queue_setup_pause_for_seeding, resolve_required_cloud_sha
    from stage1_pause_sibling_gate_classify import classify_pause_sibling_run, recommended_pause_sibling_fix
    from stage1_pause_sibling_scrape import PAUSE_SIBLING_IMPL_REV, scrape_pause_sibling_probe
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame

    if str(os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "").strip().lower() in ("0", "false"):
        print(json.dumps({"ok": False, "classification": "ABORTED_CAPTURE_BRIDGE_DISABLED"}))
        return 1

    bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1

    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    include_r0 = str(os.environ.get("PAUSE_SIBLING_SKIP_R0") or "").strip().lower() not in ("1", "true", "yes")
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    url = append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    report: dict[str, Any] = {
        "mode": "production_bridge_pause_sibling_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "accepted_boundary": "BUTTON_DISPATCH_CASE_E_R0_FAIL_PAUSE_PASS",
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "include_r0_ab": include_r0,
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

        pause = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=time.time())
        report["pause_delivery"] = pause
        pause_ok = bool(pause.get("paused")) and pause.get("pause_classification") == PAUSE_DELIVERY_RESOLVED

        frame = resolve_streamlit_app_frame(page)
        report["app_frame_inventory"] = describe_page_frames(page)
        pre_sibling = scrape_pause_sibling_probe(page, frame=frame)
        report["pause_sibling_ledger_before_click"] = pre_sibling

        sibling_step = _click_sibling(page, frame, session_hint=str(pre_sibling.get("streamlit_session_id") or ""))
        report["pause_sibling_step"] = sibling_step

        r0_step = None
        r0_pass_opt: bool | None = None
        if include_r0 and sibling_step.get("setup_abort") != "SIBLING_LEDGER_NOT_EXPOSED":
            frame = resolve_streamlit_app_frame(page)
            r0_step = _click_r0_optional(page, frame)
            report["r0_optional_step"] = r0_step
            r0_pass_opt = r0_step.get("r0_pass") if isinstance(r0_step.get("r0_pass"), bool) else None

        case, note = classify_pause_sibling_run(
            pause_resolved=pause_ok,
            sibling_pass=bool(sibling_step.get("sibling_pass")),
            sibling_trusted_click=bool(sibling_step.get("trusted_dom_click")),
            r0_optional_pass=r0_pass_opt,
            observability_abort=str(sibling_step.get("observability_abort") or ""),
        )
        if not pre_sibling.get("probe_found") and pause_ok:
            case = "ABORTED_PAUSE_SIBLING_LEDGER_NOT_EXPOSED"
            note = "sibling_probe_missing_before_click"

        report["classification"] = case
        report["classification_note"] = note
        report["recommended_next_fix"] = recommended_pause_sibling_fix(case)
        report["room_id"] = room_id
        report["ok"] = case == "BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL"
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
