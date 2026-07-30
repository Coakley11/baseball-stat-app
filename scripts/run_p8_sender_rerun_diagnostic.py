"""Run one live P8 sender-and-rerun trace on frozen Cloud build (not general focused P8)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "p8_sender_rerun_live_trace.json"
OUT_TXT = ROOT / "data" / "p8_sender_rerun_live_trace.txt"


def resolve_required_sha() -> str:
    env = str(os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    if env:
        return env
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


def run() -> dict:
    required = resolve_required_sha()
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from p8_diagnostic_setup import (
        collect_setup_stage_diagnostics,
        ensure_p8_ldr_setup_surface,
        retry_draft_start_if_stalled,
        validate_p8_diagnostic_setup,
    )
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
        from p8_boundary_instrumentation import WebSocketBoundaryCapture
        from p8_sender_rerun_trace import P8_SENDER_RERUN_INIT_SCRIPT, wait_for_send_then_trace

        ws_capture = WebSocketBoundaryCapture()

    if not harness_ready():
        return {"aborted": True, "reason": "auth_harness_incomplete"}

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        return {"aborted": True, "reason": "auth_replay_preflight_failed", "preflight": pre}

    report: dict = {
        "started_at": time.time(),
        "mode": "p8_sender_rerun_live_trace",
        "required_cloud_sha": required,
        "harness_commit_note": "9df749d + sender_rerun_trace harness",
        "prior_lifecycle_classification": "LIFECYCLE_ANALYSIS_INCONCLUSIVE_POST_SEND_SERVER_TRACE_MISSING",
    }
    parent_sink = ParentEventSinkStore()
    collector = P8LedgerHarnessCollector()
    url = production_url()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        try:
            from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
            from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT

            context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
            context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
            context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
        except ImportError:
            context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)

        page = context.new_page()
        ws_capture.attach(page)
        report["parent_event_sink_install"] = install_parent_event_sink(page, parent_sink)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(20000)
        sha = (scrape_live_sha(page) or scrape_deploy_build(page) or "")[:7].lower()
        report["cloud_sha"] = sha
        if sha != required[:7]:
            report["aborted"] = True
            report["abort_reason"] = "cloud_sha_mismatch"
            context.close()
            browser.close()
            return report

        cleanup = ensure_fresh_setup_lobby(page)
        report["cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "setup_lobby_blocked"
            context.close()
            browser.close()
            return report

        report["p8_ldr_surface"] = ensure_p8_ldr_setup_surface(page, setup_url=url)
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        draft = retry_draft_start_if_stalled(page, draft, setup_url=url)
        start_val = validate_p8_diagnostic_setup(
            page,
            draft,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            auth_preflight=pre,
            max_wait_s=75.0,
        )
        report["setup"] = start_val
        if not start_val.get("valid"):
            report["aborted"] = True
            report["abort_reason"] = start_val.get("verdict") or "setup_failed"
            context.close()
            browser.close()
            return report

        room_id = str(start_val.get("latched_room_id") or draft.get("room_id") or "")
        exact_token = str((start_val.get("authoritative_state") or {}).get("production_token") or "")
        collector.absorb_capture(capture_all_ledger_sources(page), label="pre_send")

        trace = wait_for_send_then_trace(
            page,
            parent_sink=parent_sink,
            collector=collector,
            room_id=room_id,
            deployment_sha=sha,
            exact_token=exact_token,
            ws_capture=ws_capture,
            diagnostic_run_id=room_id,
            pick_index=int((start_val.get("authoritative_state") or {}).get("pick_index") or 0),
        )
        report["trace"] = trace
        report["classification"] = trace.get("boundary_classification") or trace.get("classification") or {}
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    return report


def format_txt(report: dict) -> str:
    lines = [
        "P8 live sender-and-rerun trace",
        f"cloud_sha={report.get('cloud_sha')} required={report.get('required_cloud_sha')}",
        f"prior_offline_note={report.get('prior_lifecycle_classification')}",
        "",
    ]
    if report.get("aborted"):
        lines.append(f"ABORTED: {report.get('abort_reason')}")
        return "\n".join(lines) + "\n"

    tr = report.get("trace") or {}
    send = tr.get("send_boundary") or {}
    poll = tr.get("post_send_poll") or {}
    cls = report.get("classification") or {}
    ev = cls.get("evidence") or {}
    lines.append(f"exact_send_epoch: {send.get('ts_epoch')}  ({send.get('ts_source')})")
    lines.append(f"send_token: {send.get('token')}")
    lines.append(f"sending_iframe_instance_id: {send.get('iframe_instance_id')}")
    lines.append(f"production_countdown_send: widget_key={send.get('widget_key')}")
    lines.append("")
    lines.append(f"CLASSIFICATION: {cls.get('label')}")
    lines.append(str(cls.get("rationale") or ""))
    lines.append(f"first_difference: {cls.get('first_causally_meaningful_difference')}")
    lines.append("")
    lines.append(f"post_send_script_begins (server_ts>=send): {ev.get('post_send_script_begin_count')}")
    lines.append(f"max_peak_ledger_server_ts: {ev.get('max_peak_ledger_server_ts')} vs send {send.get('ts_epoch')}")
    lines.append(f"post_send_declaration_returned_rows: {len(poll.get('post_send_declaration_returned') or [])}")
    lines.append(f"prod_scv_receipts (harness top listener): {ev.get('prod_scv_receipts')} minimal: {ev.get('minimal_scv_receipts')}")
    lines.append(f"post_send_tick_cancel_streamlit_render: {ev.get('post_send_tick_cancel_streamlit_render')}")
    lines.append("")
    lines.append(
        "smallest_likely_correction_boundary: production countdown post-SCV Streamlit rerun "
        "(script_begin + declaration_returned) before iframe streamlit_render cancels timer; "
        "not P8C7 snapshot path until bind surface exists."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    report = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    print(f"artifact={OUT}")
    return 1 if report.get("aborted") or not (report.get("trace") or {}).get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
