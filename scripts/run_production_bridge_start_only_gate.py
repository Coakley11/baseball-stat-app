"""Focused production Start-only gate (bridge hydrate → one Start → callback/handler/room)."""

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
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_bridge_start_only_gate.json"
OUT_QUEUE120 = ROOT / "data" / "production_bridge_start_only_gate_queue120.json"
DEFAULT_BRIDGE = "d60b8d93-3a6c-4163-bc0e-f48660ee1fdd"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def resolve_start_only_setup_url(bridge_sid: str) -> tuple[str, str, Path]:
    """Return (url, policy_label, artifact_path). Queue policy matches Stage 1A-QUEUE."""
    use_queue = str(os.environ.get("START_ONLY_QUEUE_URL") or "").strip().lower() in ("1", "true", "yes")
    if use_queue:
        timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
        base = (
            f"{BASE}/?active_page=Live%20Draft%20Room"
            f"&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1"
        )
        from playwright_daniel_auth_session import append_suite_sid_to_url

        return append_suite_sid_to_url(base, bridge_sid), f"stage1a_queue_timer_{timer}", OUT_QUEUE120
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from queueui_audit_protocol import queueui_root_predicate_audit_url_base

    return append_suite_sid_to_url(queueui_root_predicate_audit_url_base(), bridge_sid), "root_audit_ldr", OUT


def _harness_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
        )
    except Exception:
        return ""


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_start_delivery import (
        START_DELIVERY_RESOLVED,
        classify_start_delivery_outcome,
        install_proven_start_context_scripts,
        inspect_start_click_authority,
        wait_for_start_callback_handler_proof,
    )
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid, wait_bridge_auth_hydrated
    from run_production_stage1_authenticated import redact_url, resolve_required_cloud_sha
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup

    bridge_sid = resolve_bridge_suite_sid() or os.environ.get("STAGE1_BRIDGE_SUITE_SID") or DEFAULT_BRIDGE
    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "71bb1ac").strip().lower()[:7]
    url, url_policy, artifact = resolve_start_only_setup_url(bridge_sid)

    report: dict[str, Any] = {
        "mode": "production_bridge_start_only_gate",
        "url_policy": url_policy,
        "started_at": time.time(),
        "required_cloud_sha": required,
        "harness_sha": _harness_sha(),
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "setup_url_redacted": redact_url(url),
        "artifact_path": str(artifact),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        report["proven_start_context_scripts"] = install_proven_start_context_scripts(context)
        from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink

        parent_sink_store = ParentEventSinkStore()
        page = context.new_page()
        report["parent_event_sink_install"] = install_parent_event_sink(page, parent_sink_store)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake

        if resolve_real_accounts_wake(bridge_restore_mode=True):
            try:
                page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
                page.wait_for_timeout(3000)
                report["real_accounts_wake_clicked"] = True
            except Exception:
                report["real_accounts_wake_clicked"] = False
        hydrate_timeout = float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240"))
        bridge_pre = wait_bridge_auth_hydrated(
            page,
            bridge_sid,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            poll_interval_s=float(os.environ.get("BRIDGE_HYDRATION_POLL_S", "2")),
            initial_settle_ms=0,
            preamble_mode="stage1",
        )
        report["bridge_hydration"] = {
            k: bridge_pre.get(k)
            for k in (
                "authenticated_restored",
                "streamlit_session_id",
                "diagnostic_run_id",
                "deployment_sha",
                "failure",
            )
        }
        if not bridge_pre.get("authenticated_restored"):
            report["classification"] = "ABORTED_BRIDGE_HYDRATION"
            report["finished_at"] = time.time()
            artifact.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "failure": bridge_pre.get("failure")}))
            return 1
        live_sha = str(bridge_pre.get("deployment_sha") or "")[:7].lower()
        report["live_cloud_sha"] = live_sha
        if required and live_sha and live_sha != required:
            report["classification"] = "ABORTED_SHA_MISMATCH"
            report["finished_at"] = time.time()
            artifact.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "live": live_sha}))
            return 1
        page.wait_for_timeout(5000)
        report["pre_start_authority"] = inspect_start_click_authority(page)
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180)
        report["preflight_cleanup"] = {k: cleanup.get(k) for k in ("ok", "skipped", "detected_room_id")}
        if not cleanup.get("ok"):
            report["classification"] = "ABORTED_SETUP_CLEANUP"
            report["finished_at"] = time.time()
            artifact.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"]}))
            return 1

        canonical = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            fresh_lobby_cleanup=False,
            max_wait_s=90.0,
        )
        click = canonical.get("start_click") or {}
        transport = canonical.get("start_click_transport") or {}
        click_ts = float(click.get("click_timestamp") or time.time())
        proof = wait_for_start_callback_handler_proof(page, click_ts=click_ts, max_wait_s=30.0)
        report["canonical_start"] = {
            "start_click_helper": canonical.get("start_click_helper"),
            "dom_click_dispatched": click.get("dom_click_dispatched"),
            "click_frame_url": click.get("click_frame_url"),
            "room_latch_pass": canonical.get("room_latch_pass"),
            "room_id": canonical.get("room_id"),
            "handler_entered": canonical.get("handler_entered"),
        }
        report["start_proof"] = proof
        report["start_click_transport"] = {
            k: transport.get(k)
            for k in (
                "outbound_frames_after_click",
                "streamlit_backmsg_sent",
                "python_rerun_started",
                "aggregate_ws_entries",
                "timing_ms",
            )
        }
        classification = classify_start_delivery_outcome(
            authority=report.get("pre_start_authority") or {},
            click=click,
            transport=transport,
            proof=proof,
        )
        if classification == START_DELIVERY_RESOLVED:
            report["ok"] = True
            if url_policy.startswith("stage1a_queue"):
                classification = "START_DELIVERY_RESOLVED_QUEUE120"
        else:
            report["ok"] = False
        report["classification"] = classification
        if report.get("ok") and proof.get("room_id"):
            from stage1_application_phase import harness_end_live_draft_room

            cleanup = harness_end_live_draft_room(page, room_id=str(proof.get("room_id") or ""))
            report["post_start_harness_cleanup"] = cleanup
            report["setup_state_consumed"] = True
            report["standalone_start_only_warning"] = (
                "Do not launch a setup-lobby-dependent runner in a new browser context without cleanup or continuous session."
            )
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    artifact.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report.get("ok"), "classification": report["classification"], "room_id": proof.get("room_id")}))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
