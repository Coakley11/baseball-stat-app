"""Production: strict BackMsg protobuf decode — sibling PRE vs Pause (E2B S0–S4)."""

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

OUT = ROOT / "data" / "production_bridge_e2b_strict_backmsg_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _capture_pause_strict(page, *, room_id: str) -> dict[str, Any]:
    from p8_proven_pause_delivery import (
        PAUSE_DELIVERY_RESOLVED,
        dispatch_proven_pause_click,
        wait_for_authoritative_pause_control,
        wait_for_pause_server_proof,
    )
    from stage1_streamlit_click_transport import capture_streamlit_click_transport, clear_ws_boundary_log

    out: dict[str, Any] = {"step": "pause_strict_backmsg", "started_ts": time.time()}
    hydration = wait_for_authoritative_pause_control(page, max_wait_s=30.0, room_id=room_id)
    out["pause_hydration"] = hydration
    if not hydration.get("ready"):
        out["setup_abort"] = "PAUSE_UI_NOT_READY"
        out["finished_ts"] = time.time()
        return out
    out["ws_clear"] = clear_ws_boundary_log(page)
    click = dispatch_proven_pause_click(page)
    out["pause_click"] = click
    click_ts = float(click.get("click_timestamp") or time.time())
    page.wait_for_timeout(450)
    transport = capture_streamlit_click_transport(page, click_ts=click_ts, frame_url_hint=str(click.get("click_frame_url") or ""))
    out["streamlit_transport"] = transport
    server = wait_for_pause_server_proof(page, click_ts=click_ts, max_wait_s=20.0)
    out["pause_server_proof"] = server
    out["trusted_dom_click"] = bool(click.get("trusted_dom_click"))
    out["pause_resolved"] = bool(server.get("paused_recognized"))
    out["pause_classification"] = PAUSE_DELIVERY_RESOLVED if out["pause_resolved"] else "PAUSE_NOT_RESOLVED"
    out["finished_ts"] = time.time()
    return out


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import wait_for_authoritative_pause_control
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import resolve_required_cloud_sha
    from stage1_e2b_strict_backmsg_classify import classify_strict_backmsg_ab, recommended_strict_backmsg_fix
    from stage1_pause_sibling_transport_capture import capture_sibling_pre_pause_transport
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from stage1_strict_backmsg_decode import build_strict_evidence_table_row
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
        "mode": "production_bridge_e2b_strict_backmsg_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "application_runtime_sha_expected": "99ced8c",
        "accepted_boundary": "BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC",
        "supersedes_relaxed_classification": {
            "prior_run_harness": "fb0deff",
            "prior_relaxed_classification": "BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED",
            "reclassified_as": "BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED",
            "reason": "relaxed_grader_cannot_prove_sibling_widget_state",
        },
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "sequence": ["start", "sibling_pre_strict_decode", "pause_strict_decode", "classify"],
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

        wait_for_authoritative_pause_control(page, max_wait_s=45.0, room_id=room_id)
        frame = resolve_streamlit_app_frame(page)
        report["app_frame_inventory"] = describe_page_frames(page)
        report["app_frame_url"] = str(frame.url or "")[:240]

        sibling_step = capture_sibling_pre_pause_transport(page)
        report["sibling_pre_pause_transport"] = sibling_step
        if sibling_step.get("setup_abort"):
            report["classification"] = "ABORTED_SIBLING_PRE_TRANSPORT_SETUP"
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 1

        pause_step = _capture_pause_strict(page, room_id=room_id)
        report["pause_transport"] = pause_step

        sib_tr = dict(sibling_step.get("streamlit_transport") or {})
        pause_tr = dict(pause_step.get("streamlit_transport") or {})
        sib_strict = dict(sib_tr.get("strict_backmsg") or {})
        pause_strict = dict(pause_tr.get("strict_backmsg") or {})

        sibling_py = "counter_increment" if sibling_step.get("sibling_python_effect") else "no_counter_change"
        report["strict_evidence_table"] = {
            "sibling": build_strict_evidence_table_row(
                trusted_dom_click=bool(sibling_step.get("trusted_dom_click")),
                strict=sib_strict,
                python_effect=sibling_py,
            ),
            "pause": build_strict_evidence_table_row(
                trusted_dom_click=bool(pause_step.get("trusted_dom_click")),
                strict=pause_strict,
                python_effect=str(pause_step.get("pause_classification") or ""),
            ),
        }

        case, note = classify_strict_backmsg_ab(
            sibling_strict=sib_strict,
            pause_strict=pause_strict,
            sibling_python_effect=bool(sibling_step.get("sibling_python_effect")),
            pause_resolved=bool(pause_step.get("pause_resolved")),
        )
        report["classification"] = case
        report["classification_note"] = note
        report["recommended_next_fix"] = recommended_strict_backmsg_fix(case)
        report["streamlit_session_id"] = sibling_step.get("streamlit_session_id")
        report["room_id"] = room_id
        report["ok"] = case in (
            "BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT",
            "BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED",
            "BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED",
            "BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY",
        )
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else (1 if str(report.get("classification", "")).startswith("ABORTED") or "S0" in str(report.get("classification", "")) else 2)


if __name__ == "__main__":
    raise SystemExit(main())
