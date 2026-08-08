"""Production: Pause → C3 → C0 → context expander → C2 → C1."""

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

OUT = ROOT / "data" / "production_bridge_fragment_context_isolation_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"

CONTROLS = (
    ("C3", "Stage1 Top-Level Normal Button Probe", "fragment_context_c3"),
    ("C0", "Stage1 Top-Level Fragment Probe", "fragment_context_c0"),
    ("C2", "Stage1 Expander Normal Button Probe", "fragment_context_c2"),
    ("C1", "Stage1 Expander Fragment Probe", "fragment_context_c1"),
)

CONTEXT_EXPANDER = "Stage1 fragment context isolation (diag)"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _ledger_payload(page) -> dict[str, Any]:
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger

    scrape = scrape_fragment_callback_ledger(page)
    if isinstance(scrape.get("payload"), dict):
        return dict(scrape["payload"])
    return {"ledger_len": scrape.get("ledger_len"), "rows": []}


def _ledger_delta(before: dict[str, Any], after: dict[str, Any], source: str) -> dict[str, Any]:
    before_rows = list(before.get("rows") or [])
    after_rows = list(after.get("rows") or [])
    before_len = int(before.get("ledger_len") if before.get("ledger_len") is not None else len(before_rows))
    after_len = int(after.get("ledger_len") if after.get("ledger_len") is not None else len(after_rows))
    last: dict[str, Any] = {}
    for row in reversed(after_rows):
        if isinstance(row, dict) and str(row.get("source") or "") == source:
            last = dict(row)
            break
    new_event = after_len > before_len or bool(last.get("event_id"))
    return {
        "ledger_len_before": before_len,
        "ledger_len_after": after_len,
        "new_event": new_event,
        "callback_entered": bool(last.get("callback_entered")),
        "callback_ledger_last": last,
    }


def _app_frame(page):
    for fr in page.frames:
        if "/~/" in str(fr.url or ""):
            return fr
    return page.main_frame


def click_context_control(page, *, control: str, label: str, source: str) -> dict[str, Any]:
    from stage1_dom_click_capture import (
        fragment_context_capture_target,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )

    cap = fragment_context_capture_target(control)
    out: dict[str, Any] = {"control": control, "label": label, "source": source, "started_ts": time.time()}
    fr = _app_frame(page)
    before = _ledger_payload(page)
    out["ledger_len_before"] = int(before.get("ledger_len") or len(before.get("rows") or []))
    loc = fr.get_by_role("button", name=label, exact=True)
    if loc.count() == 0:
        loc = page.get_by_role("button", name=label, exact=True)
    try:
        loc.first.wait_for(state="attached", timeout=8000)
        out["target_attached"] = True
        loc.first.wait_for(state="visible", timeout=8000)
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        if not out["target_enabled"]:
            out["setup_abort"] = "UI_NOT_EXPOSED"
            out["click_dispatched"] = False
            out["trusted_dom_click"] = False
            out["callback_entered"] = False
            out["callback_ledger_delta"] = _ledger_delta(before, before, source)
            out["finished_ts"] = time.time()
            return out
        loc.first.scroll_into_view_if_needed(timeout=8000)
    except Exception as exc:
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = str(exc)[:240]
        out["click_dispatched"] = False
        out["trusted_dom_click"] = False
        out["callback_entered"] = False
        out["callback_ledger_delta"] = _ledger_delta(before, before, source)
        out["finished_ts"] = time.time()
        return out
    prep = prepare_isolated_dom_click_capture(fr, capture_target=cap, frame_url_hint=str(fr.url or ""))
    out["dom_click_capture_prep"] = prep
    clicked = False
    err = ""
    try:
        loc.first.click(timeout=8000)
        clicked = True
    except Exception as exc:
        err = str(exc)[:240]
    page.wait_for_timeout(4000)
    dom = read_and_summarize_dom_click_capture(fr, capture_target=cap)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    out["click_dispatched"] = clicked
    out["click_error"] = err
    after = _ledger_payload(page)
    delta = _ledger_delta(before, after, source)
    out["callback_ledger_delta"] = delta
    out["callback_entered"] = bool(delta.get("callback_entered")) and bool(delta.get("new_event"))
    out["finished_ts"] = time.time()
    return out


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from live_draft_stage1_fragment_context_isolation import CONTEXT_EXPANDER_TITLE
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import queue_setup_pause_for_seeding, resolve_required_cloud_sha
    from stage1_fragment_context_gate_classify import classify_context_steps, recommended_context_fix
    from stage1_fragment_matrix_expander import open_streamlit_expander_by_label
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup

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
        "mode": "production_bridge_fragment_context_isolation_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "started_at": time.time(),
        "chronology": [],
    }
    room_id = ""

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
        if not pause_ok:
            report["classification"] = pause.get("pause_classification") or "QUEUEUI_PAUSE1"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 2

        steps: list[dict[str, Any]] = []
        for ctrl, label, source in CONTROLS[:2]:
            step = click_context_control(page, control=ctrl, label=label, source=source)
            steps.append(step)
            report["chronology"].append({"step": ctrl, "callback_entered": step.get("callback_entered"), "ts": time.time()})
            if step.get("setup_abort"):
                break
            page.wait_for_timeout(600)

        expander = None
        if len(steps) == 2 and not steps[-1].get("setup_abort"):
            expander = open_streamlit_expander_by_label(
                page,
                expander_label=CONTEXT_EXPANDER_TITLE,
                visible_button_label="Stage1 Expander Normal Button Probe",
            )
            report["context_expander"] = expander
            report["chronology"].append({"step": "context_expander", "open_after": expander.get("matrix_expander_open_after"), "ts": time.time()})
            if expander.get("matrix_expander_open_after"):
                for ctrl, label, source in CONTROLS[2:]:
                    step = click_context_control(page, control=ctrl, label=label, source=source)
                    steps.append(step)
                    report["chronology"].append({"step": ctrl, "callback_entered": step.get("callback_entered"), "ts": time.time()})
                    if step.get("setup_abort"):
                        break
                    page.wait_for_timeout(600)

        report["context_controls"] = steps
        case, note = classify_context_steps(steps, expander=expander)
        report["classification"] = case
        report["classification_note"] = note
        report["recommended_next_fix"] = recommended_context_fix(case)
        report["room_id"] = room_id
        report["ok"] = case == "FRAGMENT_CONTEXT_CASE_B_ALL_PASS"
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
