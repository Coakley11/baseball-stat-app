"""Production: Pause → R0 → O0 → O1 → O2 (dedicated dispatch counters)."""

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

OUT = ROOT / "data" / "production_bridge_button_dispatch_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"

CONTROLS = (
    ("R0", "Stage1 Return-Value Probe"),
    ("O0", "Stage1 OnClick Direct Probe"),
    ("O1", "Stage1 OnClick Args Probe"),
    ("O2", "Stage1 OnClick Closure Probe"),
)

LABEL_BY_MODE = {m: lbl for m, lbl in CONTROLS}
REMAINING_AFTER = {
    "R0": ("O0", "O1", "O2"),
    "O0": ("O1", "O2"),
    "O1": ("O2",),
    "O2": (),
}


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _remaining_visibility(page, frame, modes: tuple[str, ...]) -> dict[str, Any]:
    from stage1_button_dispatch_scrape import scrape_dispatch_control_marker, scrape_dispatch_surface_continuity

    out: dict[str, Any] = {"modes": {}}
    for m in modes:
        label = LABEL_BY_MODE[m]
        marker = scrape_dispatch_control_marker(frame, m)
        try:
            loc = frame.get_by_role("button", name=label, exact=True)
            attached = loc.count() > 0 and loc.first.is_visible()
        except Exception:
            attached = False
        out["modes"][m] = {
            "button_visible": attached,
            "marker_found": bool(marker.get("marker_found")),
            "marker": marker,
        }
    out["surface"] = scrape_dispatch_surface_continuity(page, frame, control_labels=LABEL_BY_MODE)
    return out


def click_dispatch_control(
    page,
    frame,
    *,
    mode: str,
    label: str,
    session_id_hint: str = "",
) -> dict[str, Any]:
    from stage1_button_dispatch_scrape import (
        dispatch_delta,
        evaluate_dispatch_pass,
        scrape_button_dispatch_probe,
        wait_for_dispatch_probe,
    )
    from stage1_button_dispatch_gate_classify import DISPATCH_PROBE_LOST_AFTER_RERUN
    from stage1_dom_click_capture import (
        button_dispatch_capture_target,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )
    from streamlit_app_frame import describe_page_frames

    cap = button_dispatch_capture_target(mode)
    out: dict[str, Any] = {
        "mode": mode,
        "label": label,
        "started_ts": time.time(),
        "frame_binding": describe_page_frames(page),
    }
    before = scrape_button_dispatch_probe(page, frame=frame)
    out["dispatch_scrape_before"] = before
    if not before.get("probe_found"):
        out["observability_abort"] = "before_probe_missing"
        out["setup_abort"] = "OBSERVABILITY"
        out["click_dispatched"] = False
        out["trusted_dom_click"] = False
        out["dispatch_pass"] = False
        out["dispatch_delta"] = dispatch_delta(before, before, mode)
        out["finished_ts"] = time.time()
        return out

    loc = frame.get_by_role("button", name=label, exact=True)
    try:
        loc.first.wait_for(state="attached", timeout=12000)
        out["target_attached"] = True
        loc.first.wait_for(state="visible", timeout=12000)
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        if not out["target_enabled"]:
            out["setup_abort"] = "UI_NOT_EXPOSED"
            out["click_dispatched"] = False
            out["trusted_dom_click"] = False
            out["dispatch_pass"] = False
            out["dispatch_delta"] = dispatch_delta(before, before, mode)
            out["finished_ts"] = time.time()
            return out
        loc.first.scroll_into_view_if_needed(timeout=12000)
    except Exception as exc:
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = str(exc)[:240]
        out["click_dispatched"] = False
        out["trusted_dom_click"] = False
        out["dispatch_pass"] = False
        out["dispatch_delta"] = dispatch_delta(before, before, mode)
        out["finished_ts"] = time.time()
        return out

    prep = prepare_isolated_dom_click_capture(frame, capture_target=cap, frame_url_hint=str(frame.url or ""))
    out["dom_click_capture_prep"] = prep
    clicked = False
    err = ""
    try:
        loc.first.click(timeout=12000)
        clicked = True
    except Exception as exc:
        err = str(exc)[:240]
    out["click_dispatched"] = clicked
    out["click_error"] = err

    wait = wait_for_dispatch_probe(page, frame, timeout_s=22.0, session_id_hint=session_id_hint)
    out["dispatch_probe_wait"] = wait
    after = dict(wait.get("scrape") or {})
    if not wait.get("ready") or not after.get("probe_found"):
        out["observability_abort"] = DISPATCH_PROBE_LOST_AFTER_RERUN
        out["dispatch_scrape_after"] = after
        out["dispatch_delta"] = dispatch_delta(before, after, mode)
        out["trusted_dom_click"] = bool(
            read_and_summarize_dom_click_capture(frame, capture_target=cap).get("trusted_dom_click")
        ) if clicked else False
        out["dom_click_capture"] = read_and_summarize_dom_click_capture(frame, capture_target=cap) if clicked else {}
        out["dispatch_pass"] = False
        out["finished_ts"] = time.time()
        return out

    dom = read_and_summarize_dom_click_capture(frame, capture_target=cap)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    out["dispatch_scrape_after"] = after
    delta = dispatch_delta(before, after, mode)
    out["dispatch_delta"] = delta
    if delta.get("observability_abort"):
        out["observability_abort"] = delta["observability_abort"]
        out["dispatch_pass"] = False
    else:
        passed, evidence = evaluate_dispatch_pass(delta, after, mode)
        out["dispatch_pass"] = passed
        out["dispatch_pass_evidence"] = evidence
    out["remaining_after"] = _remaining_visibility(page, frame, REMAINING_AFTER.get(mode, ()))
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
    from stage1_button_dispatch_gate_classify import (
        ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED,
        classify_dispatch_gate_report,
        recommended_dispatch_fix,
    )
    from stage1_button_dispatch_scrape import scrape_button_dispatch_probe, validate_pre_r0_ledger
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
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    url = append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    report: dict[str, Any] = {
        "mode": "production_bridge_button_dispatch_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "started_at": time.time(),
        "chronology": [],
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

        bridge_pre = wait_bridge_auth_hydrated(
            page, bridge_sid, scrape_stage1_ledger_rows, timeout_s=240.0, preamble_mode="stage1"
        )
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
        report["chronology"].append(
            {"step": "pause", "pause_classification": pause.get("pause_classification"), "ts": time.time()}
        )
        if not pause_ok:
            report["classification"] = pause.get("pause_classification") or "QUEUEUI_PAUSE1"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 2

        app_frame = resolve_streamlit_app_frame(page)
        report["app_frame_inventory"] = describe_page_frames(page)
        ledger_pre = scrape_button_dispatch_probe(page, frame=app_frame)
        report["dispatch_ledger_before_r0"] = ledger_pre
        pre_ok, pre_reasons = validate_pre_r0_ledger(ledger_pre)
        report["dispatch_ledger_before_r0_validation"] = {"ok": pre_ok, "reasons": pre_reasons}
        if not pre_ok:
            report["classification"] = ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED
            report["classification_note"] = ",".join(pre_reasons)
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 2

        session_hint = str(ledger_pre.get("streamlit_session_id") or "")
        steps: list[dict[str, Any]] = []
        for mode, label in CONTROLS:
            app_frame = resolve_streamlit_app_frame(page)
            step = click_dispatch_control(
                page,
                app_frame,
                mode=mode,
                label=label,
                session_id_hint=session_hint,
            )
            steps.append(step)
            report["chronology"].append(
                {
                    "step": mode,
                    "dispatch_pass": step.get("dispatch_pass"),
                    "observability_abort": step.get("observability_abort"),
                    "ts": time.time(),
                }
            )
            if step.get("setup_abort") or step.get("observability_abort"):
                break
            page.wait_for_timeout(400)

        report["dispatch_controls"] = steps
        case, note = classify_dispatch_gate_report(
            report,
            steps,
            pause_resolved=pause_ok,
            ledger_before_r0=ledger_pre,
        )
        report["classification"] = case
        report["classification_note"] = note
        report["recommended_next_fix"] = recommended_dispatch_fix(case)
        report["room_id"] = room_id
        report["ok"] = case == "BUTTON_DISPATCH_CASE_D_ALL_PASS"
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
