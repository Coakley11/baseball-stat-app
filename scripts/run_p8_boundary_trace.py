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
OUT_GATE = ROOT / "data" / "p8_canary_deploy_gate.json"


def resolve_required_sha() -> str:
    env = str(os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    if env:
        return env
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


def run(*, skip_deploy_poll: bool = False) -> dict:
    from p8_canary_build_gate import (
        commit_has_canary_implementation,
        git_head_short,
        local_deploy_pin,
        poll_live_cloud_sha,
        verify_pre_trace_canaries,
        verify_declaration_canaries_after_mount,
    )
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface, retry_draft_start_if_stalled, validate_p8_diagnostic_setup
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy
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
        "mode": "p8_boundary_trace_canary_gated",
        "proven_frontend_boundary": "FRONTEND_WIDGET_UPDATE_PROVEN",
        "git_head": git_head_short(),
        "local_deploy_pin": local_deploy_pin(),
    }

    if not skip_deploy_poll and not os.environ.get("SKIP_CANARY_DEPLOY_POLL"):
        deploy_poll = poll_live_cloud_sha(max_attempts=24, sleep_s=25.0)
        OUT_GATE.parent.mkdir(parents=True, exist_ok=True)
        OUT_GATE.write_text(json.dumps(deploy_poll, indent=2, default=str), encoding="utf-8")
        report["deploy_poll"] = deploy_poll
        report["implementation_at_live_sha"] = deploy_poll.get("implementation_at_live_sha") or {}
        if not deploy_poll.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "canary_build_not_live_on_cloud"
            report["classification"] = {
                "code": "WAIT_FOR_CANARY_DEPLOY",
                "label": "WAIT_FOR_CANARY_DEPLOY",
            }
            return report
        required = str(deploy_poll.get("live_sha") or resolve_required_sha())[:7]
    else:
        required = resolve_required_sha()

    report["required_cloud_sha"] = required

    parent_sink = ParentEventSinkStore()
    collector = P8LedgerHarnessCollector()
    ws_capture = WebSocketBoundaryCapture()
    url = production_url()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        try:
            from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
            from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT

            context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
            context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
            context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
            context.add_init_script(P8_WS_BOUNDARY_INIT_SCRIPT)
        except ImportError:
            context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
            try:
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
        probe = scrape_deploy(page)
        sha = (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")[:7].lower()
        build = str(probe.get("build") or "")
        report["cloud_sha"] = sha
        report["cloud_build"] = build
        impl = commit_has_canary_implementation(sha)
        report["implementation_at_live_sha"] = impl
        if not impl.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "live_sha_lacks_canary_implementation"
            context.close()
            browser.close()
            return report

        canary_pre = verify_pre_trace_canaries(page)
        report["pre_trace_canary_validation"] = canary_pre
        if canary_pre.get("classification") != "CANARY_PRE_TRACE_OK":
            report["aborted"] = True
            report["abort_reason"] = canary_pre.get("classification") or "INVALID_CANARY_DEPLOY_OR_CAPTURE"
            report["classification"] = {
                "code": "INVALID_CANARY_DEPLOY_OR_CAPTURE",
                "label": "INVALID_CANARY_DEPLOY_OR_CAPTURE",
                "reason": canary_pre.get("reason"),
            }
            context.close()
            browser.close()
            return report

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

        decl_canary = verify_declaration_canaries_after_mount(page)
        report["pre_trace_declaration_canary_validation"] = decl_canary
        if decl_canary.get("classification") != "CANARY_DECLARATION_OK":
            report["aborted"] = True
            report["abort_reason"] = decl_canary.get("classification") or "INVALID_CANARY_DEPLOY_OR_CAPTURE"
            report["classification"] = {
                "code": "INVALID_CANARY_DEPLOY_OR_CAPTURE",
                "label": "INVALID_CANARY_DEPLOY_OR_CAPTURE",
                "reason": decl_canary.get("reason"),
            }
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
            canary_pre_trace_validated=True,
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
        "P8 boundary trace (canary-gated)",
        f"git_head={report.get('git_head')} local_pin={report.get('local_deploy_pin')}",
        f"cloud_sha={report.get('cloud_sha')} build={report.get('cloud_build')} required={report.get('required_cloud_sha')}",
        f"proven_frontend={report.get('proven_frontend_boundary')}",
        "",
    ]
    impl = report.get("implementation_at_live_sha") or {}
    if impl:
        lines.append(f"implementation_ok={impl.get('ok')} canary_file={impl.get('file_live_draft_stage1_boundary_canaries_py')}")
        lines.append(
            f"hooks global={impl.get('streamlit_global_canary_hook')} "
            f"ldr={impl.get('streamlit_ldr_branch_canary_hook')} "
            f"decl={impl.get('micro_core_declaration_canaries')}"
        )
        lines.append("")
    pre = report.get("pre_trace_canary_validation") or {}
    lines.append(f"pre_trace_canary: {pre.get('classification')} global={pre.get('global_canary_seen')} branch={pre.get('branch_canary_seen')}")
    lines.append("")
    if report.get("aborted"):
        lines.append(f"ABORTED: {report.get('abort_reason')}")
        cls = report.get("classification") or {}
        if cls.get("code"):
            lines.append(f"classification={cls.get('code')}")
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
    lines.append(f"parent_receipt_ts: {facts.get('parent_receipt_ts')}")
    lines.append("")
    lines.append("WebSocket:")
    lines.append(f"  outbound_token: {answers.get('first_outbound_after_parent_contains_expiration_token')}")
    lines.append(f"  outbound_widget_key: {answers.get('first_outbound_after_parent_contains_widget_key')}")
    ci = ws_corr.get("correlated_inbound_first") or {}
    lines.append(f"  first_inbound_category: {ci.get('frame_type_hint')}")
    lines.append("")
    lines.append(f"post_send_global_canary_count: {facts.get('post_send_global_canary_count')}")
    lines.append(f"post_send_branch_canary_count: {facts.get('post_send_branch_canary_count')}")
    lines.append(f"post_send_declaration_pre_count: {facts.get('post_send_declaration_pre_count')}")
    lines.append(f"declaration_nonempty: {facts.get('declaration_nonempty')}")
    lines.append("")
    lines.append(f"FINAL: {cls.get('label')}")
    lines.append(str(cls.get("rationale") or ""))
    lines.append(f"smallest_correction_boundary: {cls.get('smallest_correction_boundary')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    report = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    OUT_LEGACY.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(format_txt(report))
    print(f"artifact={OUT} gate={OUT_GATE}")
    ok_trace = (report.get("trace") or {}).get("ok")
    return 1 if report.get("aborted") or not ok_trace else 0


if __name__ == "__main__":
    raise SystemExit(main())
