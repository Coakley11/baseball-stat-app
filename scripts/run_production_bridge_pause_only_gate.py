"""Focused production Pause-only gate: hydrate → Start/latch → proven Pause → cleanup."""

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

OUT = ROOT / "data" / "production_bridge_pause_only_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _queue_url(bridge_sid: str) -> str:
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    from playwright_daniel_auth_session import append_suite_sid_to_url

    base = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1"
    )
    return append_suite_sid_to_url(base, bridge_sid)


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED, proven_pause_single_click
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid, wait_bridge_auth_hydrated
    from run_production_stage1_authenticated import redact_url, resolve_required_cloud_sha
    from stage1_application_phase import harness_end_live_draft_room
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup

    bridge_sid = resolve_bridge_suite_sid() or os.environ.get("STAGE1_BRIDGE_SUITE_SID") or ""
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1
    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "71bb1ac").strip().lower()[:7]
    url = _queue_url(bridge_sid)
    report: dict[str, Any] = {
        "mode": "production_bridge_pause_only_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "setup_url_redacted": redact_url(url),
        "started_at": time.time(),
        "artifact_path": str(OUT),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        report["proven_context_scripts"] = install_proven_start_context_scripts(context)
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake

        if resolve_real_accounts_wake(bridge_restore_mode=True):
            try:
                page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
                page.wait_for_timeout(3000)
            except Exception:
                pass
        hydrate_timeout = float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240"))
        bridge_pre = wait_bridge_auth_hydrated(
            page,
            bridge_sid,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            expected_application_phase="setup_lobby",
        )
        report["bridge_hydration"] = {
            k: bridge_pre.get(k)
            for k in ("authenticated_restored", "failure", "failure_classification", "deployment_sha")
        }
        if not bridge_pre.get("authenticated_restored"):
            report["classification"] = bridge_pre.get("failure_classification") or "ABORTED_BRIDGE_HYDRATION"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"]}))
            return 1
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180)
        report["preflight_cleanup"] = {k: cleanup.get(k) for k in ("ok", "detected_room_id")}
        if not cleanup.get("ok"):
            report["classification"] = "ABORTED_SETUP_CLEANUP"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1
        latch_ts = time.time()
        canonical = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            fresh_lobby_cleanup=False,
            max_wait_s=90.0,
        )
        room_id = str(canonical.get("room_id") or canonical.get("latched_room_id") or "")
        report["start_latch"] = {
            "room_id": room_id,
            "room_latch_pass": canonical.get("room_latch_pass"),
            "handler_entered": canonical.get("handler_entered"),
        }
        if not room_id or not canonical.get("room_latch_pass"):
            report["classification"] = "ABORTED_START_LATCH"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1
        pause = proven_pause_single_click(page, room_id=room_id, latch_completed_ts=latch_ts)
        report["pause_delivery"] = pause
        classification = str(pause.get("pause_classification") or "")
        report["ok"] = classification == PAUSE_DELIVERY_RESOLVED
        report["classification"] = classification
        if report["ok"]:
            report["post_pause_cleanup"] = harness_end_live_draft_room(page, room_id=room_id)
            report["setup_state_consumed"] = True
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report.get("ok"), "classification": report["classification"], "room_id": room_id}))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
