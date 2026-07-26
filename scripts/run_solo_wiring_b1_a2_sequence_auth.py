"""Run synthetic matrix cells B1→A2→(B2) with A1-equivalent harness (Cloud, headless auth)."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
REQUIRED_SHA = "66f85f6"
EXPECTED_BUILD = f"baseball-dev-{REQUIRED_SHA}"
DEPLOY_PROBE_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room&solo_delivery_diag=1&solo_bridge_transition=A0"
)
SUMMARY_OUT = ROOT / "data" / "solo_wiring_matrix_b1_a2_sequence.json"


def cell_out_path(cell: str) -> Path:
    return ROOT / "data" / f"solo_wiring_{cell.lower()}_baseline.json"


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from solo_wiring_matrix_harness_core import (  # noqa: E402
    build_cell_record,
    build_distinct_counts,
    collect_parent_messages,
    install_parent_capture,
    merge_peak_distinct,
    score_matrix_cell,
    scrape_repro_events,
)
from verify_cloud_deploy_playwright import scrape_deploy  # noqa: E402


def matrix_url(cell: str, widget_key: str, ls_key: str) -> str:
    q = urlencode(
        {
            "active_page": "Live Draft Room",
            "solo_wiring_synthetic": "1",
            "solo_wiring_matrix": cell,
            "solo_wiring_key": widget_key,
            "solo_wiring_ls_key": ls_key,
            "solo_transport_probe": "1",
        }
    )
    return append_suite_sid_to_url(f"{BASE}/?{q}")


def scrape_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-wiring-matrix-diag');
            if (!el) continue;
            let decoded = null;
            const b64 = el.getAttribute('data-b64')||'';
            try { decoded = b64 ? JSON.parse(atob(b64)) : null; } catch(e) { decoded = {err:String(e)}; }
            return {
              expected: el.getAttribute('data-expected-token')||'',
              key: el.getAttribute('data-key')||'',
              decoded,
            };
          }
          return {missing:true};
        }"""
    )


def verify_cloud_deploy(page, *, timeout_s: float = 600.0) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    t0 = time.time()
    last: dict[str, Any] = {}
    while time.time() - t0 < timeout_s:
        goto_and_wake(page, DEPLOY_PROBE_URL, timeout_s=240)
        page.wait_for_timeout(8000)
        probe = scrape_deploy(page)
        sha = str(probe.get("sha") or "").lower()[:7]
        build = str(probe.get("build") or "")
        last = {"cloud_sha": sha, "cloud_build": build, "probe": probe}
        if sha == REQUIRED_SHA and build == EXPECTED_BUILD:
            last["deploy_ok"] = True
            return last
        page.wait_for_timeout(15000)
    last["deploy_ok"] = False
    last["required_sha"] = REQUIRED_SHA
    last["required_build"] = EXPECTED_BUILD
    return last


def observe_cell(page, *, cell: str, expected_token: str, deadline: float) -> dict[str, Any]:
    install_parent_capture(page, expected_token=expected_token)
    t0 = time.time()
    browser_send_ts: float | None = None
    samples: list[dict[str, Any]] = []
    parent_all: list[dict[str, Any]] = []
    peak: dict[str, Any] = {}

    while time.time() - t0 < 32.0:
        install_parent_capture(page, expected_token=expected_token)
        repro = scrape_repro_events(page)
        sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
        parent_rows = collect_parent_messages(page)
        parent_all = parent_rows
        if browser_send_ts is None and (
            int(sc.get("transport_postmessage_invoked") or 0) >= 1
            or int(sc.get("component_value_sent") or 0) >= 1
        ):
            browser_send_ts = time.time()

        probe = scrape_probe(page)
        decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
        meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
        callbacks = meta.get("callback_log") if isinstance(meta.get("callback_log"), list) else []
        session_raw = str(meta.get("session_state_value") or "").strip("'\"")

        distinct = build_distinct_counts(
            repro=repro,
            parent_rows=parent_rows,
            expected_token=expected_token,
            session_raw=session_raw,
            callback_log=callbacks,
            browser_send_ts=browser_send_ts,
        )
        peak = merge_peak_distinct(peak, distinct)
        samples.append({"elapsed_s": round(time.time() - t0, 1), "distinct": distinct})

        scored = score_matrix_cell(peak, cell=cell, expected_token=expected_token)
        if scored.get("outcome") == "PASS":
            scored["distinct"] = peak
            scored["samples"] = samples
            scored["observation_s"] = round(time.time() - t0, 1)
            return scored

        if time.time() >= deadline + 8 and int(peak.get("browser_deadline_crossed") or 0) >= 1:
            break
        page.wait_for_timeout(800)

    probe = scrape_probe(page)
    decoded = probe.get("decoded") if isinstance(probe.get("decoded"), dict) else {}
    meta = decoded.get("meta") if isinstance(decoded.get("meta"), dict) else {}
    callbacks = meta.get("callback_log") if isinstance(meta.get("callback_log"), list) else []
    session_raw = str(meta.get("session_state_value") or "").strip("'\"")
    repro = scrape_repro_events(page)
    distinct = build_distinct_counts(
        repro=repro,
        parent_rows=parent_all,
        expected_token=expected_token,
        session_raw=session_raw,
        callback_log=callbacks,
        browser_send_ts=browser_send_ts,
    )
    peak = merge_peak_distinct(peak, distinct)
    scored = score_matrix_cell(peak, cell=cell, expected_token=expected_token)
    if (
        int(peak.get("on_change_callback") or 0) >= 1
        and int(peak.get("logical_send_postmessage") or 0) == 0
        and int(peak.get("parent_message") or 0) == 0
    ):
        scored["outcome"] = "INVALID"
        scored.setdefault("invalid_reasons", []).append("python_callback_without_browser_evidence")
    scored["distinct"] = peak
    scored["samples"] = samples[-15:]
    scored["observation_s"] = round(time.time() - t0, 1)
    return scored


def run_cell(browser, cell: str, *, deploy: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    if not deploy.get("deploy_ok"):
        return {
            "outcome": "INVALID",
            "cell": cell,
            "invalid_reasons": ["cloud_deploy_mismatch"],
            "deploy_probe": deploy,
        }

    widget_key = f"solo_wiring_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    ls_key = f"solo_wiring_ls_{cell.lower()}_{uuid.uuid4().hex[:10]}"
    url = matrix_url(cell, widget_key, ls_key)

    ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    page = ctx.new_page()
    try:
        goto_and_wake(page, url, timeout_s=240)
        install_parent_capture(page)
        t_nav = time.time()
        probe: dict[str, Any] = {"missing": True}
        while time.time() - t_nav < 90.0:
            install_parent_capture(page)
            probe = scrape_probe(page)
            if not probe.get("missing"):
                break
            page.wait_for_timeout(500)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=2000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        if probe.get("missing"):
            for _ in range(8):
                page.wait_for_timeout(2000)
                probe = scrape_probe(page)
                if not probe.get("missing"):
                    break
        if probe.get("missing"):
            return {
                "outcome": "INVALID",
                "cell": cell,
                "invalid_reasons": ["matrix_probe_missing"],
                "fresh_widget_key": widget_key,
            }

        expected = str(probe.get("expected") or "")
        deadline = float(expected.split("|")[2]) if expected.count("|") >= 2 else time.time() + 12
        scored = observe_cell(page, cell=cell, expected_token=expected, deadline=deadline)
        record = build_cell_record(
            cell=cell,
            scored=scored,
            peak=scored.get("distinct") or {},
            expected_token=expected,
            widget_key=widget_key,
            ls_key=ls_key,
            cloud_sha=str(deploy.get("cloud_sha") or ""),
            cloud_build=str(deploy.get("cloud_build") or ""),
            required_sha=REQUIRED_SHA,
        )
        record["observation_s"] = scored.get("observation_s")
        record["artifact_path"] = str(cell_out_path(cell))
        outp = cell_out_path(cell)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return record
    finally:
        ctx.close()


def interpret(b1: dict[str, Any], a2: dict[str, Any]) -> dict[str, Any]:
    o1 = b1.get("outcome")
    o2 = a2.get("outcome")
    notes: list[str] = []
    stop_before_b2 = False
    layer = ""
    if o1 == "VALID FAIL" and o2 == "PASS":
        layer = "production_frontend_message"
        notes.append("B1 VALID FAIL and A2 PASS → production frontend/message construction is first failing layer.")
        stop_before_b2 = True
    elif o1 == "PASS" and o2 == "VALID FAIL":
        layer = "production_micro_wrapper"
        notes.append("B1 PASS and A2 VALID FAIL → production micro-isolation wrapper is first failing layer.")
        stop_before_b2 = True
    elif o1 == "PASS" and o2 == "PASS":
        layer = "proceed_b2"
        notes.append("B1 PASS and A2 PASS → run B2.")
    elif o1 == "INVALID" or o2 == "INVALID":
        layer = "harness_or_isolation_invalid"
        notes.append("INVALID cell — fix harness/isolation before interpreting production layers.")
        stop_before_b2 = True
    else:
        layer = "inconclusive"
        notes.append(f"B1={o1} A2={o2} — review artifacts.")
        stop_before_b2 = True
    return {
        "B1": o1,
        "A2": o2,
        "first_differing_layer": layer,
        "stop_before_b2": stop_before_b2,
        "notes": notes,
    }


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    from playwright.sync_api import sync_playwright

    summary: dict[str, Any] = {
        "a1_baseline_accepted": True,
        "required_sha": REQUIRED_SHA,
        "required_build": EXPECTED_BUILD,
        "cells": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()

        for cell in ("B1", "A2"):
            deploy = verify_cloud_deploy(deploy_page)
            summary[f"deploy_probe_before_{cell}"] = deploy
            if not deploy.get("deploy_ok"):
                summary["cells"][cell] = {
                    "outcome": "INVALID",
                    "invalid_reasons": ["cloud_deploy_mismatch"],
                    "deploy_probe": deploy,
                }
                break
            summary["cells"][cell] = run_cell(browser, cell, deploy=deploy)

        interp = interpret(summary["cells"].get("B1", {}), summary["cells"].get("A2", {}))
        summary["interpretation"] = interp

        if (
            not interp.get("stop_before_b2")
            and summary["cells"].get("B1", {}).get("outcome") == "PASS"
            and summary["cells"].get("A2", {}).get("outcome") == "PASS"
        ):
            deploy = verify_cloud_deploy(deploy_page)
            summary["deploy_probe_before_B2"] = deploy
            if deploy.get("deploy_ok"):
                summary["cells"]["B2"] = run_cell(browser, "B2", deploy=deploy)
                b2 = summary["cells"]["B2"]
                if b2.get("outcome") == "VALID FAIL" and interp.get("first_differing_layer") == "proceed_b2":
                    summary["interpretation"]["B2"] = b2.get("outcome")
                    summary["interpretation"]["notes"].append(
                        "B2 failed while B1 and A2 passed → defect in frontend×wrapper combination only."
                    )
                elif b2.get("outcome") == "PASS":
                    summary["interpretation"]["notes"].append(
                        "B1, A2, B2 all PASS → frontend and wrapper sound; investigate persistent key/lifecycle/ownership."
                    )
            else:
                summary["cells"]["B2"] = {
                    "outcome": "INVALID",
                    "invalid_reasons": ["cloud_deploy_mismatch"],
                    "deploy_probe": deploy,
                }

        deploy_page.context.close()
        browser.close()

    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
