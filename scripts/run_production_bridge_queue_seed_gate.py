"""Focused gate: hydrate → Start/latch → Pause → active surface → seed 3 distinct players (no Resume/expire)."""

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

OUT = ROOT / "data" / "production_bridge_queue_seed_gate.json"
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
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import (
        BridgeSuiteSidConflictError,
        resolve_bridge_suite_sid_with_source,
        wait_bridge_auth_hydrated,
    )
    from run_production_stage1_authenticated import (
        queue_populate_deliberate,
        redact_url,
        resolve_required_cloud_sha,
    )
    from stage1_active_queue_surface import (
        ACTIVE_QUEUE_SURFACE_RESOLVED,
        wait_for_active_queue_surface,
    )
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from stage1_application_phase import EXPECTED_PHASE_AUTH_ONLY, classify_ldr_phase_from_page
    from stage1_queue_seed_harness import QUEUE_SEED_RESOLVED

    try:
        bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    except BridgeSuiteSidConflictError as exc:
        print(json.dumps({"ok": False, "classification": "ABORTED_BRIDGE_SID_CONFLICT", "detail": str(exc)}))
        return 1
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1
    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "71bb1ac").strip().lower()[:7]
    url = _queue_url(bridge_sid)
    report: dict[str, Any] = {
        "mode": "production_bridge_queue_seed_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "setup_url_redacted": redact_url(url),
        "started_at": time.time(),
        "artifact_path": str(OUT),
    }
    print(json.dumps({"bridge_suite_sid_source": bridge_source, "bridge_suite_sid_prefix": bridge_sid[:8]}), flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        report["proven_context_scripts"] = install_proven_start_context_scripts(context)
        parent_sink_store = ParentEventSinkStore()
        page = context.new_page()
        report["parent_event_sink_install"] = install_parent_event_sink(page, parent_sink_store)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake
        from stage1_application_phase import EXPECTED_PHASE_SETUP_LOBBY
        from stage1_preflight_cleanup import run_stage1_preflight_cleanup

        settle_s = float(os.environ.get("BRIDGE_POST_CAPTURE_SETTLE_S", "8"))
        if settle_s > 0:
            page.wait_for_timeout(int(settle_s * 1000))
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
            poll_interval_s=float(os.environ.get("BRIDGE_HYDRATION_POLL_S", "2")),
            initial_settle_ms=0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_AUTH_ONLY,
        )
        report["bridge_hydration_auth_only"] = bridge_pre
        if not bridge_pre.get("authenticated_restored"):
            report["ok"] = False
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"]}))
            return 1
        report["application_phase_before_cleanup"] = classify_ldr_phase_from_page(page)
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["ok"] = False
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        bridge_pre = wait_bridge_auth_hydrated(
            page,
            bridge_sid,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            poll_interval_s=float(os.environ.get("BRIDGE_HYDRATION_POLL_S", "2")),
            initial_settle_ms=0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_SETUP_LOBBY,
        )
        report["bridge_hydration"] = bridge_pre
        if not bridge_pre.get("authenticated_restored"):
            report["ok"] = False
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        cleanup2 = run_stage1_preflight_cleanup(page, max_wait_s=120.0)
        report["preflight_cleanup_final"] = cleanup2
        if not cleanup2.get("ok"):
            report["ok"] = False
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        canonical = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id="",
            fresh_lobby_cleanup=False,
            max_wait_s=90.0,
        )
        report["start_latch"] = {
            "room_id": canonical.get("room_id") or canonical.get("created_room_id"),
            "handler_entered": canonical.get("handler_entered"),
            "start_click_transport": canonical.get("start_click_transport"),
            "start_click": {
                "click_timestamp": (canonical.get("start_click") or {}).get("click_timestamp"),
                "pre_click_script_run_seq": (canonical.get("start_click") or {}).get("pre_click_script_run_seq"),
            },
        }
        room_id = str(report["start_latch"].get("room_id") or "").upper()
        start_val = {
            "latched_room_id": room_id,
            "in_progress": True,
            "room_latch_pass": True,
            "expected_token": canonical.get("expected_token") or "",
            "pick_index": canonical.get("pick_index"),
            "deadline": canonical.get("deadline"),
        }
        from run_production_stage1_authenticated import queue_setup_pause_for_seeding

        latch_ts = time.time()
        pause = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=latch_ts)
        report["pause_delivery"] = pause
        if not pause.get("paused") or pause.get("pause_classification") != PAUSE_DELIVERY_RESOLVED:
            report["ok"] = False
            report["classification"] = pause.get("pause_classification") or "QUEUEUI_PAUSE1"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        gate_start = dict(start_val)
        gate_start["pause_ack_ts"] = float((pause.get("pause_timing") or {}).get("pause_click_dispatch_ts") or time.time())
        active = wait_for_active_queue_surface(
            page,
            start_val=gate_start,
            while_paused=True,
            auth_complete=True,
            run_id=str(canonical.get("application_diagnostic_run_id") or canonical.get("diagnostic_run_id") or ""),
        )
        report["active_queue_surface_gate"] = active
        if not active.get("passed"):
            report["ok"] = False
            report["classification"] = active.get("classification") or "QUEUE_ACTIVE_PAGE8"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "room_id": room_id}))
            return 2
        surf_mut = bool((active.get("timing") or {}).get("surface_activation_queue_mutation"))
        from stage1_queue_seed_harness import wait_for_min_add_to_queue_controls

        seed_min = max(1, int(str(os.environ.get("STAGE1_QUEUE_SEED_MIN_PLAYERS") or "3").strip() or "3"))
        add_wait = wait_for_min_add_to_queue_controls(
            page,
            min_controls=max(1, seed_min),
            timeout_s=90.0,
            start_val=gate_start,
        )
        report["add_control_wait"] = add_wait
        report["stage1_queue_seed_min_players"] = seed_min
        report["stage1_seed_player_name"] = str(os.environ.get("STAGE1_SEED_PLAYER_NAME") or "").strip()
        queue_meta = queue_populate_deliberate(
            page,
            min_players=seed_min,
            surface_activation_queue_mutation=surf_mut,
        )
        focus_name = str(os.environ.get("STAGE1_SEED_PLAYER_NAME") or "").strip()
        if seed_min == 1 and focus_name and queue_meta.get("ok"):
            steps = list(queue_meta.get("seed_steps") or [])
            if steps and steps[0].get("mutation_proven") and str(steps[0].get("player_name") or "").lower() == focus_name.lower():
                queue_meta["classification"] = "PLAYER_A_QUEUE_MUTATION_RESOLVED"
                queue_meta["ok"] = True
        report["queue_seed"] = queue_meta
        report["classification"] = str(queue_meta.get("classification") or "")
        steps = list(queue_meta.get("seed_steps") or [])
        if steps:
            first = steps[0] if isinstance(steps[0], dict) else {}
            report["francisco_widget_liveness_proof"] = {
                "player_name": first.get("player_name"),
                "app_render_trace": first.get("app_render_trace"),
                "render_trace_fields": {
                    k.replace("render_trace_", ""): first.get(k)
                    for k in first
                    if k.startswith("render_trace_")
                },
                "browser_dom_click_events": (first.get("delivery_detail") or {}).get("browser_dom_click_events"),
                "post_click_transport": (first.get("delivery_detail") or {}).get("post_click_transport"),
                "classification": first.get("classification"),
            }
        report["ok"] = report["classification"] == QUEUE_SEED_RESOLVED
        if active.get("classification") == ACTIVE_QUEUE_SURFACE_RESOLVED:
            report["active_queue_surface"] = ACTIVE_QUEUE_SURFACE_RESOLVED
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        context.close()
        browser.close()
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "classification": report["classification"],
                "room_id": room_id,
                "harness_sha": report.get("harness_sha"),
            }
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
