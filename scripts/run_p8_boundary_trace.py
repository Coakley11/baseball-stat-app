"""Run one live P8 boundary trace (immediate parent + WebSocket + server audit)."""

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

OUT = ROOT / "data" / "p8_boundary_trace.json"
OUT_TXT = ROOT / "data" / "p8_boundary_trace.txt"
OUT_LEGACY = ROOT / "data" / "p8_sender_rerun_live_trace.json"


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
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface, retry_draft_start_if_stalled, validate_p8_diagnostic_setup
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_sender_rerun_trace import P8_SENDER_RERUN_INIT_SCRIPT, wait_for_send_then_trace
    from p8_boundary_instrumentation import WebSocketBoundaryCapture, P8_WS_BOUNDARY_INIT_SCRIPT

    if not harness_ready():
        return {"aborted": True, "reason": "auth_harness_incomplete"}

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        return {"aborted": True, "reason": "auth_replay_preflight_failed", "preflight": pre}

    report: dict = {
        "started_at": time.time(),
        "mode": "p8_boundary_trace",
        "required_cloud_sha": required,
        "provisional_boundary": "PRODUCTION_POSTMESSAGE_EMITTED_BUT_NO_BACKEND_RERUN_OBSERVED",
    }
    parent_sink = ParentEventSinkStore()
    collector = P8LedgerHarnessCollector()
    ws_capture = WebSocketBoundaryCapture()
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
            context.add_init_script(P8_WS_BOUNDARY_INIT_SCRIPT)
        except ImportError:
            context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
            try:
                from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT

                context.add_init_script(P8_WS_BOUNDARY_INIT_SCRIPT)
            except ImportError:
                pass

        page = context.new_page()
        ws_capture.attach_context(context)
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
        pick_index = (start_val.get("authoritative_state") or {}).get("pick_index")
        if pick_index is not None:
            pick_index = int(pick_index)
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
            pick_index=pick_index,
        )
        report["trace"] = trace
        report["classification"] = trace.get("boundary_classification") or trace.get("classification") or {}
        report["websocket_socket_count"] = len(ws_capture.sockets)
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    return report


def format_txt(report: dict) -> str:
    lines = [
        "P8 boundary trace (immediate parent + WebSocket + server audit)",
        f"cloud_sha={report.get('cloud_sha')} required={report.get('required_cloud_sha')}",
        f"provisional={report.get('provisional_boundary')}",
        "",
    ]
    if report.get("aborted"):
        lines.append(f"ABORTED: {report.get('abort_reason')}")
        return "\n".join(lines) + "\n"

    tr = report.get("trace") or {}
    send = tr.get("send_boundary") or {}
    poll = tr.get("post_send_poll") or {}
    cls = report.get("classification") or {}
    facts = cls.get("facts") or {}
    imm = poll.get("immediate_parent_final") or {}
    ws_corr = poll.get("websocket_correlation") or cls.get("ws_correlation") or {}
    answers = cls.get("ws_explicit_answers") or ws_corr.get("explicit_answers") or {}
    lines.append(f"exact_send_epoch: {send.get('ts_epoch')} ({send.get('ts_source')})")
    lines.append(f"send_token: {send.get('token')}")
    lines.append(f"production_iframe_instance_id: {send.get('iframe_instance_id')}")
    lines.append(f"immediate_parent_url: {imm.get('parent_url')}")
    lines.append(f"immediate_parent_frame_index: {imm.get('parent_frame_index')}")
    lines.append("")
    lines.append("WebSocket explicit answers:")
    lines.append(f"  first_outbound_after_parent_contains_expiration_token: {answers.get('first_outbound_after_parent_contains_expiration_token')}")
    lines.append(f"  first_outbound_after_parent_contains_widget_key: {answers.get('first_outbound_after_parent_contains_widget_key')}")
    lines.append(f"  first_outbound_after_parent_is_widget_update: {answers.get('first_outbound_after_parent_is_widget_update')}")
    co = ws_corr.get("correlated_outbound") or {}
    if co:
        lines.append(f"  correlated_outbound_sha256: {co.get('sha256') or co.get('sha256_prefix')}")
        lines.append(f"  correlated_outbound_frame_type: {co.get('frame_type_hint')}")
    lines.append(f"  inbound_232ms_frame_category: {cls.get('inbound_232ms_frame_category')}")
    lines.append("")
    lines.append(f"post_send_global_canary_count: {facts.get('post_send_global_canary_count')}")
    lines.append(f"post_send_branch_canary_count: {facts.get('post_send_branch_canary_count')}")
    lines.append(f"post_send_declaration_pre_count: {facts.get('post_send_declaration_pre_count')}")
    lines.append("")
    lines.append(f"BOUNDARY CLASSIFICATION: {cls.get('label')}")
    lines.append(str(cls.get("rationale") or ""))
    lines.append(f"smallest_correction_boundary: {cls.get('smallest_correction_boundary')}")
    lines.append("")
    lines.append(f"parent_scv_exact_count: {facts.get('parent_scv_exact_count')}")
    lines.append(f"parent_receipt_ts: {facts.get('parent_receipt_ts')}")
    lines.append(f"first_ws_outbound_ts: {facts.get('first_ws_outbound_ts')}")
    lines.append(f"first_ws_inbound_ts: {facts.get('first_ws_inbound_ts')}")
    lines.append(f"post_send_script_begin_count: {facts.get('post_send_script_begin_count')}")
    lines.append(f"iframe_render/disconnect_ts: {facts.get('iframe_disconnect_or_render_ts')}")
    if cls.get("absence_note"):
        lines.append(f"absence: {cls.get('absence_note')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    report = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    OUT_LEGACY.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(format_txt(report))
    print(f"artifact={OUT}")
    return 1 if report.get("aborted") or not (report.get("trace") or {}).get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
