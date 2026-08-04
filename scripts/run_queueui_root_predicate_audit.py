"""Headed QUEUEUI root predicate audit against Cloud (diagnostic ledger)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "queueui_root_predicate_audit.json"


def _deploy_pin() -> str:
    pin = ROOT / "deploy_commit.txt"
    if not pin.is_file():
        return ""
    return pin.read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()


def _write_report(report: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _summarize(last_ledger: list[dict[str, Any]]) -> dict[str, Any]:
    from queueui_transition_diagnostic import summarize_ledger_events

    return summarize_ledger_events(last_ledger)


def _wait_setup_stable(page, scrape_ledger, *, timeout_s: float = 90) -> dict[str, Any]:
    from queueui_audit_protocol import distinct_global_script_run_seqs

    t0 = time.time()
    last_seen: list[int] = []
    while time.time() - t0 < timeout_s:
        rows = scrape_ledger(page)
        seen = distinct_global_script_run_seqs(rows)
        last_seen = seen
        if len(seen) >= 2:
            return {"ok": True, "script_run_seqs": seen, "wait_s": time.time() - t0}
        page.wait_for_timeout(2500)
    return {"ok": False, "script_run_seqs": last_seen, "wait_s": time.time() - t0}


def _finish_invalid_protocol(
    report: dict[str, Any],
    *,
    violation: dict[str, Any],
    baseline: dict[str, Any],
    pre_rows: list[dict[str, Any]],
    post_rows: list[dict[str, Any]],
    last_ledger: list[dict[str, Any]],
    browser,
) -> int:
    from queueui_audit_protocol import first_forbidden_in_rows, invalid_protocol_report_fields

    stale = first_forbidden_in_rows(pre_rows)
    report.update(invalid_protocol_report_fields(violation))
    report["audit_baseline"] = baseline
    report["post_baseline_forbidden_checks"] = {
        "violation": violation,
        "stale_historical_forbidden": stale,
        "post_start_row_count": len(post_rows),
        "pre_start_row_count": len(pre_rows),
    }
    report["ledger_summary_at_stop"] = _summarize(last_ledger)
    report["post_start_ledger_summary"] = _summarize(post_rows)
    report["finished_at"] = time.time()
    browser.close()
    _write_report(report)
    print(
        json.dumps(
            {
                "ok": False,
                "audit_execution_status": report["audit_execution_status"],
                "first_boundary": report["first_boundary"],
                "forbidden": violation.get("event"),
            }
        )
    )
    return 4


def main() -> int:
    from queueui_audit_deploy_preflight import (
        APPLICATION_DIAGNOSTIC_SHA,
        DEFAULT_REQUIRED_DIAGNOSTIC_SHA,
        build_deploy_block_report,
    )
    from queueui_audit_protocol import (
        INVALID_PROTOCOL_RUN,
        capture_audit_baseline,
        evaluate_audit_completion,
        evaluate_prestart_isolation,
        first_forbidden_after_baseline,
        partition_ledger_by_baseline,
        prestart_not_clean_report_fields,
        queueui_root_predicate_audit_url_base,
        resolve_deployment_verification,
    )
    from run_queueui_active_page_transition_diagnostic import (
        _harness_sha,
        _harness_short,
        _screenshot,
        _server_latch_from_ledger,
    )
    from queueui_predicate_timeline import predicate_timeline_from_ledger
    from queueui_root_classify import classify_queueui_root
    from queueui_transition_diagnostic import STATIC_TRANSITION_PATH_REVIEW
    from run_production_stage1_authenticated import (
        redact_url,
        resolve_required_cloud_sha,
        scrape_active_live_page_observation,
    )
    from p8_canonical_production_start import capture_harness_page_identity
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
    from stage1_preflight_cleanup import _infer_status, _scrape_lobby, run_stage1_preflight_cleanup

    required = resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or DEFAULT_REQUIRED_DIAGNOSTIC_SHA
    required = required.strip().lower()[:7]

    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready
    from replay_playwright_daniel_auth_preflight import run_preflight

    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        return 1

    deploy_pin = _deploy_pin()
    report: dict[str, Any] = {
        "audit": "queueui_root_predicate",
        "required_cloud_sha": required,
        "application_diagnostic_sha": APPLICATION_DIAGNOSTIC_SHA,
        "deploy_commit_txt_pin": deploy_pin[:7] if deploy_pin else "",
        "harness_sha": _harness_sha(),
        "harness_sha_short": _harness_short(),
        "static_predicate_sources": STATIC_TRANSITION_PATH_REVIEW,
        "started_at": time.time(),
        "stage1a_core": "PASS",
        "stage1a_queue": "NOT_RUN — BLOCKED_BEFORE_EXPIRATION",
        "queue_campaign_ran": False,
        "expiration_wait": False,
    }

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    url = append_suite_sid_to_url(queueui_root_predicate_audit_url_base())
    report["setup_url_redacted"] = redact_url(url)

    root: dict[str, Any] = {"classification": None, "proven": False}
    predicate_timeline: list[dict[str, Any]] = []

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

        deploy = resolve_deployment_verification(
            page,
            pre,
            required=required,
            deploy_pin=deploy_pin,
        )
        preflight = deploy.get("preflight") or {}
        report["deployment_verification"] = deploy
        report["live_cloud_sha"] = deploy.get("live_cloud_sha")
        report["live_cloud_sha_source"] = deploy.get("verification_method")
        report["cloud_build_preflight"] = preflight

        if not preflight.get("passed"):
            browser.close()
            block = build_deploy_block_report(
                preflight=preflight,
                harness_sha=report["harness_sha"],
                harness_sha_short=report["harness_sha_short"],
                deploy_commit_pin=deploy_pin,
            )
            report.update(block)
            report["finished_at"] = time.time()
            _write_report(report)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "audit_execution_status": report.get("audit_execution_status"),
                        "first_boundary": report.get("first_boundary"),
                        "live": deploy.get("live_cloud_sha"),
                        "required": required,
                    }
                )
            )
            return 2

        from p8_diagnostic_setup import ensure_p8_ldr_setup_surface

        ensure_p8_ldr_setup_surface(page, setup_url=url)
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            browser.close()
            report["audit_execution_status"] = "NOT_RUN"
            report["first_boundary"] = "QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN"
            report["finished_at"] = time.time()
            _write_report(report)
            return 1

        setup_stable = _wait_setup_stable(page, scrape_stage1_ledger_rows)
        report["setup_stability"] = setup_stable

        setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
        if not setup_scan.get("soloSelected"):
            page.evaluate(SOLO_RADIO_JS)
            page.wait_for_timeout(2000)
        cps: list[dict[str, Any]] = []
        maybe_clear_stale_draft(page, cps)
        set_number_via_playwright(page, "Number of Teams", "2")
        ensure_solo_setup_picks_meet_roster(page, cps)
        page.wait_for_timeout(1500)

        lobby = _scrape_lobby(page)
        lobby["inferred_status"] = _infer_status(lobby)
        ledger_pre = scrape_stage1_ledger_rows(page)
        prestart = evaluate_prestart_isolation(
            lobby,
            ledger_pre,
            setup_stable=setup_stable,
        )
        report["prestart_isolation"] = prestart
        if not prestart.get("passed"):
            browser.close()
            report.update(prestart_not_clean_report_fields(prestart))
            report["finished_at"] = time.time()
            _write_report(report)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "audit_execution_status": "NOT_RUN",
                        "first_boundary": report.get("first_boundary"),
                        "reasons": prestart.get("reasons"),
                    }
                )
            )
            return 5

        _screenshot(page, "01_before_start")
        identity = capture_harness_page_identity(page, context, label="before", ledger_rows=ledger_pre)
        report["streamlit_session_id"] = identity.get("streamlit_session_id")
        report["application_diagnostic_run_id"] = identity.get("diagnostic_run_id")

        click_ts = time.time()
        baseline = capture_audit_baseline(ledger_pre, identity, lobby, click_ts=click_ts)
        report["audit_baseline"] = baseline

        click = dispatch_start_single_authoritative_click(page, cps)
        start_observed = bool(
            click.get("clicked")
            or click.get("dispatch_ok")
            or click.get("dom_click_dispatched")
            or int(click.get("start_click_count") or 0) >= 1
        )
        report["start_draft_click"] = click
        capture_start_click_transport(page, click_ts=float(click.get("click_timestamp") or click_ts))
        page.wait_for_timeout(1000)

        server_latch: dict[str, Any] = {"ok": False}
        seen_seq: set[int] = set()
        t0 = time.time()
        last_ledger: list[dict[str, Any]] = []
        post_rows: list[dict[str, Any]] = []
        pre_rows: list[dict[str, Any]] = []
        protocol_violation: dict[str, Any] | None = None

        while time.time() - t0 < 90:
            ledger = scrape_stage1_ledger_rows(page)
            last_ledger = ledger
            violation, pre_rows, post_rows = first_forbidden_after_baseline(ledger, baseline)
            if violation:
                return _finish_invalid_protocol(
                    report,
                    violation=violation,
                    baseline=baseline,
                    pre_rows=pre_rows,
                    post_rows=post_rows,
                    last_ledger=ledger,
                    browser=browser,
                )
            server_latch = _server_latch_from_ledger(last_ledger)
            post_summary_loop = _summarize(post_rows)
            if post_summary_loop.get("created_room_id_from_ledger"):
                server_latch = _server_latch_from_ledger(
                    last_ledger,
                    created_hint=str(post_summary_loop.get("created_room_id_from_ledger") or ""),
                )
            for r in post_rows:
                if r.get("event") != "production_stage1_queueui_predicate_audit":
                    continue
                seq = int(r.get("script_run_seq") or 0)
                if seq:
                    seen_seq.add(seq)
            if server_latch.get("ok") and len(seen_seq) >= 3:
                page.wait_for_timeout(2500)
                last_ledger = scrape_stage1_ledger_rows(page)
                violation, pre_rows, post_rows = first_forbidden_after_baseline(last_ledger, baseline)
                if violation:
                    return _finish_invalid_protocol(
                        report,
                        violation=violation,
                        baseline=baseline,
                        pre_rows=pre_rows,
                        post_rows=post_rows,
                        last_ledger=last_ledger,
                        browser=browser,
                    )
                break
            page.wait_for_timeout(2500)

        pre_rows, post_rows = partition_ledger_by_baseline(last_ledger, baseline)
        post_summary = _summarize(post_rows)
        room_id = str(
            server_latch.get("server_room_id")
            or post_summary.get("created_room_id_from_ledger")
            or ""
        ).strip()
        server_latch = _server_latch_from_ledger(
            last_ledger,
            created_hint=room_id,
        )
        room_id = str(server_latch.get("server_room_id") or room_id).strip()

        completion = evaluate_audit_completion(
            ledger_rows=post_rows,
            server_latch=server_latch,
            room_id=room_id,
            protocol_violation=protocol_violation,
            start_click_observed=start_observed,
            ledger_summary=post_summary,
        )
        report["audit_completion"] = completion
        report["audit_execution_status"] = completion.get("audit_execution_status")
        report["first_boundary"] = completion.get("first_boundary") or ""
        report["distinct_script_run_seq_with_audit"] = completion.get(
            "distinct_predicate_script_run_seq", []
        )
        report["post_baseline_forbidden_checks"] = {
            "violation": None,
            "stale_historical_forbidden": None,
            "post_start_row_count": len(post_rows),
            "pre_start_row_count": len(pre_rows),
        }

        predicate_timeline = predicate_timeline_from_ledger(post_rows)
        report["predicate_timeline"] = predicate_timeline
        by_seq: dict[int, list[dict[str, Any]]] = {}
        for row in predicate_timeline:
            seq = int(row.get("script_run_seq") or 0)
            by_seq.setdefault(seq, []).append(row)
        report["script_pass_timeline"] = [
            {"script_run_seq": seq, "entries": by_seq[seq]} for seq in sorted(by_seq)
        ]

        dom = scrape_active_live_page_observation(
            page,
            start_val={
                "latched_room_id": room_id,
                "in_progress": bool(server_latch.get("ok")),
                "room_latch_pass": bool(server_latch.get("ok")),
            },
        )
        report["server_latch"] = server_latch
        report["room_id"] = room_id
        report["ledger_summary"] = _summarize(last_ledger)
        report["post_start_ledger_summary"] = post_summary
        report["dom_after_latch"] = dom
        report["audit_events_present"] = bool(predicate_timeline)

        if completion.get("completed"):
            root = classify_queueui_root(ledger_rows=post_rows, dom_observation=dom)
            report["root_classification"] = root
            report["queueuiroot_classification"] = root.get("classification")
        else:
            report["root_classification"] = None
            report["queueuiroot_classification"] = None
            report["root_audit_status"] = (
                "INCOMPLETE — INSUFFICIENT EVIDENCE (NO QUEUEUIROOT)"
                if completion.get("audit_execution_status") != INVALID_PROTOCOL_RUN
                else report.get("root_audit_status")
            )

        report["finished_at"] = time.time()
        _screenshot(page, "02_final")
        browser.close()

    _write_report(report)
    ok_completed = report.get("audit_execution_status") == "COMPLETED"
    print(
        json.dumps(
            {
                "ok": ok_completed,
                "audit_execution_status": report.get("audit_execution_status"),
                "root": report.get("queueuiroot_classification"),
                "distinct_seq": report.get("distinct_script_run_seq_with_audit"),
            }
        )
    )
    if report.get("audit_execution_status") == INVALID_PROTOCOL_RUN:
        return 4
    if report.get("audit_execution_status") == "NOT_RUN":
        return 5
    if not ok_completed:
        return 3
    return 0 if root.get("proven") or predicate_timeline else 3


if __name__ == "__main__":
    raise SystemExit(main())
