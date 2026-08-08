"""Production gate: Stage1 fragment identity matrix S0→S1→D0→D1 (solo diag, post-Pause)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_bridge_fragment_identity_matrix_gate.json"

CONTROLS = (
    ("S0", "Stage1 Static Fragment Probe", "stage1_fragment_matrix_s0"),
    ("S1", "Stage1 Static Timed Fragment Probe", "stage1_fragment_matrix_s1"),
    ("D0", "Stage1 Dynamic Fragment Probe", "stage1_fragment_matrix_d0"),
    ("D1", "Stage1 Dynamic Timed Fragment Probe", "stage1_fragment_matrix_d1"),
)


def _ledger_payload(page) -> dict[str, Any]:
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger

    scrape = scrape_fragment_callback_ledger(page)
    payload = scrape.get("payload") if isinstance(scrape.get("payload"), dict) else {}
    return payload


def _ledger_delta(before: dict[str, Any], after: dict[str, Any], source: str) -> dict[str, Any]:
    before_len = int(before.get("ledger_len") or 0)
    after_len = int(after.get("ledger_len") or 0)
    last = {}
    for row in reversed(list(after.get("rows") or [])):
        if isinstance(row, dict) and str(row.get("source") or "") == source:
            last = dict(row)
            break
    if not last:
        last_row = after.get("last") if isinstance(after.get("last"), dict) else {}
        if str(last_row.get("source") or "") == source:
            last = dict(last_row)
    return {
        "ledger_len_before": before_len,
        "ledger_len_after": after_len,
        "callback_entered": bool(last.get("callback_entered")),
        "callback_ledger_last": last,
    }


def click_matrix_control(page, *, label: str, source: str) -> dict[str, Any]:
    from stage1_dom_click_capture import (
        CAPTURE_TARGET_FRAGMENT_PROBE,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )

    out: dict[str, Any] = {"label": label, "source": source, "started_ts": time.time()}
    before = _ledger_payload(page)
    fr = page
    for frame in page.frames:
        if "/~/" in str(frame.url or ""):
            fr = frame
            break
    prep = prepare_isolated_dom_click_capture(
        fr,
        capture_target=CAPTURE_TARGET_FRAGMENT_PROBE,
        frame_url_hint=str(fr.url or ""),
    )
    out["dom_click_capture_prep"] = prep
    clicked = False
    err = ""
    try:
        loc = fr.get_by_role("button", name=label, exact=False)
        if loc.count() == 0:
            loc = page.get_by_role("button", name=label, exact=False)
        loc.first.scroll_into_view_if_needed(timeout=8000)
        loc.first.click(timeout=8000)
        clicked = True
    except Exception as exc:
        err = f"{type(exc).__name__}:{exc}"
    page.wait_for_timeout(3500)
    dom = read_and_summarize_dom_click_capture(fr, capture_target=CAPTURE_TARGET_FRAGMENT_PROBE)
    out["dom_click_capture"] = dom
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    out["click_dispatched"] = clicked
    out["click_error"] = err[:240]
    after = _ledger_payload(page)
    delta = _ledger_delta(before, after, source)
    out["callback_ledger_delta"] = delta
    out["callback_entered"] = bool(delta.get("callback_entered"))
    out["finished_ts"] = time.time()
    return out


def classify_matrix(steps: list[dict[str, Any]]) -> str:
    from stage1_fragment_matrix_gate_classify import classify_matrix_steps

    case, _note = classify_matrix_steps(steps, expander=None)
    return case


def main() -> int:
    import os
    import subprocess

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import resolve_required_cloud_sha

    bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1
    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "c6b36c1").strip()[:7]
    harness_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    url = append_suite_sid_to_url(
        "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
        "?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    report: dict[str, Any] = {
        "mode": "fragment_identity_matrix_gate",
        "harness_sha": harness_sha,
        "required_cloud_sha": required,
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_source": bridge_source,
        "steps": [],
        "started_at": time.time(),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        try:
            page.get_by_text("Stage1 fragment identity matrix", exact=False).first.click(timeout=5000)
            page.wait_for_timeout(800)
        except Exception:
            pass
        for ctrl, label, source in CONTROLS:
            step = click_matrix_control(page, label=label, source=source)
            step["control"] = ctrl
            report["steps"].append(step)
        browser.close()
    report["classification"] = classify_matrix(report["steps"])
    report["ok"] = report["classification"] == "FRAGMENT_MATRIX_ALL_CONTROLS_CALLBACK"
    report["finished_at"] = time.time()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "classification": report["classification"], "artifact": str(OUT)}))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
