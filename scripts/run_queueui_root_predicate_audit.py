"""Headed QUEUEUI root predicate audit against Cloud (diagnostic ledger)."""

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
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "queueui_root_predicate_audit.json"
REQUIRED = "007c39a"


def main() -> int:
    os.environ.setdefault("REQUIRED_CLOUD_SHA", os.environ.get("REQUIRED_CLOUD_SHA") or REQUIRED)
    from run_queueui_active_page_transition_diagnostic import (  # noqa: E402
        _harness_sha,
        _harness_short,
        _save_text,
        _screenshot,
        _server_latch_from_ledger,
    )
    from queueui_root_classify import classify_queueui_root
    from queueui_transition_diagnostic import (
        STATIC_TRANSITION_PATH_REVIEW,
        merge_capture_snapshots,
        summarize_ledger_events,
    )
    from run_production_stage1_authenticated import (
        production_url,
        redact_url,
        resolve_required_cloud_sha,
        scrape_active_live_page_observation,
    )
    from p8_canonical_production_start import capture_harness_page_identity
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from p8_production_start_harness import (
        capture_start_click_transport,
        dispatch_start_single_authoritative_click,
        scrape_stage1_ledger_rows,
    )
    from solo_draft_start_harness import (
        SCAN_SETUP_JS,
        SOLO_RADIO_JS,
        ensure_solo_setup_picks_meet_roster,
        maybe_clear_stale_draft,
        set_number_via_playwright,
    )
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup

    required = resolve_required_cloud_sha() or REQUIRED
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight

    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        return 1

    report: dict[str, Any] = {
        "audit": "queueui_root_predicate",
        "required_cloud_sha_at_start": required,
        "harness_sha": _harness_sha(),
        "harness_sha_short": _harness_short(),
        "static_predicate_sources": STATIC_TRANSITION_PATH_REVIEW,
        "predicate_source_map": {
            "active_lifecycle_branch": "streamlit_app.py ~24878 (_live_draft_lifecycle in active_draft|waiting_shared_lobby)",
            "room_body": "streamlit_app.py ~25127 ldr_section room_body",
            "draft_in_progress": "live_draft_safe_mode.live_draft_is_in_progress ~25454",
            "timer_ok": "streamlit_app.py ~25809 (_draft_in_progress and slot and reconcile.timer_should_run)",
            "pause_control": "live_draft_control_center_ui.render_live_draft_control_center ~26011 timer_render_controls",
            "recommendations_queue": "streamlit_app.py ~26284 _paint_heavy_recommendations_body; live_draft_heavy_paint_ui defer",
            "countdown_mount": "streamlit_app.py ~25746 solo expire owner / placement ladder; solo_countdown_wake_micro_core",
            "start_in_flight_clear": "live_draft_start_progress.finish_live_draft_start ~24147 streamlit_app",
            "auth_restore_gate": "live_draft_state.live_draft_restore_allowed ~141",
        },
        "started_at": time.time(),
        "script_pass_timeline": [],
    }

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_deploy_build

    url = production_url()
    out_dir = ROOT / "data" / "queueui_root_audit"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        page.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(20000)
        report["cloud_sha"] = scrape_deploy_build(page) or pre.get("cloud_sha")
        ensure_p8_ldr_setup_surface(page, setup_url=url)
        if not run_stage1_preflight_cleanup(page, max_wait_s=180).get("ok"):
            browser.close()
            return 1
        setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
        if not setup_scan.get("soloSelected"):
            page.evaluate(SOLO_RADIO_JS)
            page.wait_for_timeout(2000)
        cps: list[dict[str, Any]] = []
        maybe_clear_stale_draft(page, cps)
        set_number_via_playwright(page, "Number of Teams", "2")
        ensure_solo_setup_picks_meet_roster(page, cps)
        page.wait_for_timeout(1500)
        _screenshot(page, "01_before_start")
        snap_before = merge_capture_snapshots(page, label="before_start", ledger_rows=scrape_stage1_ledger_rows(page))
        report["streamlit_session_id"] = capture_harness_page_identity(
            page, context, label="before", ledger_rows=scrape_stage1_ledger_rows(page)
        ).get("streamlit_session_id")
        click = dispatch_start_single_authoritative_click(page, cps)
        capture_start_click_transport(page, click_ts=float(click.get("click_timestamp") or time.time()))
        page.wait_for_timeout(1000)

        server_latch = {"ok": False}
        seen_seq: set[int] = set()
        t0 = time.time()
        last_ledger: list[dict[str, Any]] = []
        while time.time() - t0 < 90:
            ledger = scrape_stage1_ledger_rows(page)
            last_ledger = ledger
            server_latch = _server_latch_from_ledger(ledger)
            audit = [r for r in ledger if r.get("event") == "production_stage1_queueui_predicate_audit"]
            for r in audit:
                seq = int(r.get("script_run_seq") or 0)
                if seq:
                    seen_seq.add(seq)
            if server_latch.get("ok") and len(seen_seq) >= 3:
                page.wait_for_timeout(2500)
                last_ledger = scrape_stage1_ledger_rows(page)
                break
            page.wait_for_timeout(2500)

        dom = scrape_active_live_page_observation(
            page,
            start_val={
                "latched_room_id": server_latch.get("server_room_id"),
                "in_progress": bool(server_latch.get("ok")),
                "room_latch_pass": bool(server_latch.get("ok")),
            },
        )
        root = classify_queueui_root(ledger_rows=last_ledger, dom_observation=dom)
        by_seq: dict[int, list[dict[str, Any]]] = {}
        for r in last_ledger:
            if r.get("event") != "production_stage1_queueui_predicate_audit":
                continue
            seq = int(r.get("script_run_seq") or 0)
            by_seq.setdefault(seq, []).append(r)
        for seq in sorted(by_seq):
            rows = by_seq[seq]
            report["script_pass_timeline"].append(
                {
                    "script_run_seq": seq,
                    "checkpoints": [str(r.get("checkpoint") or "") for r in rows],
                    "rows": rows,
                }
            )

        report["finished_at"] = time.time()
        report["server_latch"] = server_latch
        report["room_id"] = server_latch.get("server_room_id")
        report["ledger_summary"] = summarize_ledger_events(last_ledger)
        report["dom_after_latch"] = dom
        report["root_classification"] = root
        report["audit_events_present"] = any(r.get("event") == "production_stage1_queueui_predicate_audit" for r in last_ledger)
        report["setup_url_redacted"] = redact_url(url)
        report["stage1a_queue"] = "NOT_RUN"
        _screenshot(page, "02_final")
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "root": root.get("classification"), "audit_events": report.get("audit_events_present")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
