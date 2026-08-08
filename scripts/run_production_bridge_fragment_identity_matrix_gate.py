"""Production: fresh Context A path → Start → Pause → fragment matrix S0–D1."""

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

OUT = ROOT / "data" / "production_bridge_fragment_identity_matrix_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"

CONTROLS = (
    ("S0", "Stage1 Static Fragment Probe", "stage1_fragment_matrix_s0", None),
    ("S1", "Stage1 Static Timed Fragment Probe", "stage1_fragment_matrix_s1", 1),
    ("D0", "Stage1 Dynamic Fragment Probe", "stage1_fragment_matrix_d0", None),
    ("D1", "Stage1 Dynamic Timed Fragment Probe", "stage1_fragment_matrix_d1", 1),
)


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
    if not last:
        tail = after.get("last") if isinstance(after.get("last"), dict) else {}
        if str(tail.get("source") or "") == source:
            last = dict(tail)
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


def click_matrix_control(
    page,
    *,
    control: str,
    label: str,
    source: str,
    run_every: int | None,
    room_id: str,
) -> dict[str, Any]:
    from stage1_dom_click_capture import (
        fragment_matrix_capture_target,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )
    from stage1_fragment_matrix_scrape import latest_probe_for_control, scrape_matrix_probes

    cap_target = fragment_matrix_capture_target(control)

    out: dict[str, Any] = {
        "control": control,
        "label": label,
        "source": source,
        "run_every": run_every,
        "widget_key_expected": f"stage1_fragment_matrix_{control.lower()}_{str(room_id or 'noroom').strip().upper()[:16]}_diag",
        "started_ts": time.time(),
    }
    fr = _app_frame(page)
    stability: list[dict[str, Any]] = []
    if control in ("D0", "D1"):
        for i in range(3):
            page.wait_for_timeout(900 if run_every else 400)
            probes = scrape_matrix_probes(page, control=control)
            row = latest_probe_for_control(probes, control)
            stability.append({"poll": i + 1, "probe": row, "ts": time.time()})
        out["fragment_id_stability_polls"] = stability

    probes_pre = scrape_matrix_probes(page, control=control)
    pre_probe = latest_probe_for_control(probes_pre, control)
    out["pre_click_dom_probe"] = pre_probe
    out["pre_click_ownership"] = {
        "render_fragment": pre_probe.get("thread_fragment_id") or "",
        "metadata_fragment": pre_probe.get("metadata_fragment_id") or "",
        "widget_owner_fragment_current": pre_probe.get("widget_owner_fragment_current"),
        "ownership_subcode": pre_probe.get("ownership_subcode") or "",
        "fragment_registered_pre_click": pre_probe.get("metadata_fragment_in_storage"),
    }
    before = _ledger_payload(page)
    out["ledger_len_before"] = int(before.get("ledger_len") or len(before.get("rows") or []))

    clicked = False
    err = ""
    loc = fr.get_by_role("button", name=label, exact=True)
    if loc.count() == 0:
        loc = page.get_by_role("button", name=label, exact=True)
    out["target_visible"] = False
    out["target_enabled"] = False
    out["target_attached"] = False
    try:
        loc.first.wait_for(state="attached", timeout=8000)
        out["target_attached"] = True
        loc.first.wait_for(state="visible", timeout=8000)
        out["target_visible"] = True
        out["target_enabled"] = bool(loc.first.is_enabled())
        if not out["target_enabled"]:
            out["setup_abort"] = "UI_NOT_EXPOSED"
            out["click_error"] = "target_not_enabled"
            out["finished_ts"] = time.time()
            return out
        loc.first.scroll_into_view_if_needed(timeout=8000)
    except Exception as exc:
        err = f"{type(exc).__name__}:{exc}"
        out["setup_abort"] = "UI_NOT_EXPOSED"
        out["click_error"] = err[:240]
        out["click_dispatched"] = False
        out["trusted_dom_click"] = False
        out["callback_ledger_delta"] = {
            "ledger_len_before": int(before.get("ledger_len") or len(before.get("rows") or [])),
            "ledger_len_after": int(before.get("ledger_len") or len(before.get("rows") or [])),
            "new_event": False,
            "callback_entered": False,
            "callback_ledger_last": {},
        }
        out["callback_entered"] = False
        out["finished_ts"] = time.time()
        return out

    prep = prepare_isolated_dom_click_capture(
        fr,
        capture_target=cap_target,
        frame_url_hint=str(fr.url or ""),
    )
    out["dom_click_capture_prep"] = prep
    try:
        loc.first.click(timeout=8000)
        clicked = True
    except Exception as exc:
        err = f"{type(exc).__name__}:{exc}"
    page.wait_for_timeout(4000)
    dom = read_and_summarize_dom_click_capture(fr, capture_target=cap_target)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    out["click_dispatched"] = clicked
    out["click_error"] = err[:240]
    after = _ledger_payload(page)
    delta = _ledger_delta(before, after, source)
    out["callback_ledger_delta"] = delta
    out["callback_entered"] = bool(delta.get("callback_entered")) and bool(delta.get("new_event"))
    last = delta.get("callback_ledger_last") if isinstance(delta.get("callback_ledger_last"), dict) else {}
    out["callback_at_click"] = {
        "fragment_id": (last.get("fragment_identity") or {}).get("thread_state_fragment_id")
        if isinstance(last.get("fragment_identity"), dict)
        else "",
        "full_app_run_seq": last.get("full_app_run_seq"),
        "ts": last.get("ts"),
        "event_id": last.get("event_id"),
    }
    out["finished_ts"] = time.time()
    return out


def main() -> int:
    from stage1_fragment_matrix_gate_classify import classify_matrix_steps, recommended_next_fix
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import queue_setup_pause_for_seeding, resolve_required_cloud_sha
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from stage1_run_binding import control_only_pause_binding_passes

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
    chronology: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "mode": "production_bridge_fragment_identity_matrix_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "started_at": time.time(),
        "chronology": chronology,
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
        chronology.append({"step": "start", "room_id": room_id, "ts": time.time()})
        if not room_id or not canonical.get("room_latch_pass"):
            report["classification"] = "ABORTED_START_LATCH"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        pause = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=time.time())
        report["pause_delivery"] = pause
        pause_ok = bool(pause.get("paused")) and pause.get("pause_classification") == PAUSE_DELIVERY_RESOLVED
        pause_click = pause.get("pause_click") if isinstance(pause.get("pause_click"), dict) else {}
        pause_dom = pause_click.get("dom_click_capture") if isinstance(pause_click.get("dom_click_capture"), dict) else {}
        chronology.append({"step": "pause", "classification": pause.get("pause_classification"), "ts": time.time()})
        if not pause_ok:
            report["classification"] = pause.get("pause_classification") or "QUEUEUI_PAUSE1"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 2

        report["pause_control"] = {
            "pause_classification": PAUSE_DELIVERY_RESOLVED,
            "trusted_dom_click": bool(pause_dom.get("trusted_dom_click") or pause_click.get("trusted_dom_click")),
        }

        from stage1_fragment_matrix_expander import open_fragment_identity_matrix_expander

        expander = open_fragment_identity_matrix_expander(page)
        report["matrix_expander"] = expander
        chronology.append(
            {
                "step": "matrix_expander",
                "open_after": expander.get("matrix_expander_open_after"),
                "s0_visible": expander.get("s0_visible_after_open"),
                "ts": time.time(),
            }
        )

        steps: list[dict[str, Any]] = []
        matrix_aborted = False
        for ctrl, label, source, run_every in CONTROLS:
            if matrix_aborted:
                break
            step = click_matrix_control(
                page,
                control=ctrl,
                label=label,
                source=source,
                run_every=run_every,
                room_id=room_id,
            )
            steps.append(step)
            chronology.append(
                {
                    "step": f"matrix_{ctrl}",
                    "callback_entered": step.get("callback_entered"),
                    "trusted_dom_click": step.get("trusted_dom_click"),
                    "target_visible": step.get("target_visible"),
                    "ts": time.time(),
                }
            )
            if step.get("setup_abort") == "UI_NOT_EXPOSED":
                matrix_aborted = True
            page.wait_for_timeout(800)

        report["matrix_controls"] = steps
        by_ctrl = {str(s.get("control") or ""): s for s in steps}
        report["matrix_summary"] = {
            c: {
                "trusted_dom_click": bool(by_ctrl.get(c, {}).get("trusted_dom_click")),
                "callback_entered": bool(by_ctrl.get(c, {}).get("callback_entered")),
                "pre_click_ownership": by_ctrl.get(c, {}).get("pre_click_ownership"),
            }
            for c in ("S0", "S1", "D0", "D1")
        }
        case, ownership_note = classify_matrix_steps(steps, expander=expander)
        report["classification"] = case
        report["ownership_subcodes"] = ownership_note
        report["recommended_next_fix"] = recommended_next_fix(case)
        report["room_id"] = room_id
        report["ok"] = case == "FRAGMENT_MATRIX_CASE_IV_ALL_PASS"
        report["matrix_architecture_decidable"] = case.startswith("FRAGMENT_MATRIX_CASE_")
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "classification": report.get("classification"),
                "room_id": room_id,
                "harness_sha": report.get("harness_sha"),
                "application_runtime_sha": report.get("application_runtime_sha"),
                "artifact": str(OUT),
            }
        )
    )
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
