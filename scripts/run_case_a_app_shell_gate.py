"""App-shell Case A — four minimal-repro tokens, no Solo draft start."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

BASE = os.environ.get(
    "SOLO_ISOLATION_BASE_URL",
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app",
)
OUT = ROOT / "data" / "solo_case_a_app_shell_gate.json"
REQUIRED_CYCLES = 4
TIMEOUT_S = 120


def case_a_url() -> str:
    return f"{BASE.rstrip('/')}/?solo_delivery_diag=1&solo_delivery_case=A"


def scrape_case_a(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          const out = {
            page_url: location.href,
            title: document.title,
            case_a: null,
            repro_client: null,
            delivery: null,
          };
          for (const root of roots()) {
            const caseA = root.querySelector('#solo-case-a-diag');
            if (caseA) {
              out.case_a = {
                passed: caseA.getAttribute('data-passed') || '',
                callbacks: parseInt(caseA.getAttribute('data-callbacks') || '0', 10),
                cycles_done: parseInt(caseA.getAttribute('data-cycles-done') || '0', 10),
                component_name: caseA.getAttribute('data-component-name') || '',
                key: caseA.getAttribute('data-key') || '',
                token: caseA.getAttribute('data-token') || '',
                stages: caseA.getAttribute('data-stages') || '',
                rerun: caseA.getAttribute('data-rerun') || '',
                json: caseA.getAttribute('data-json') || '',
              };
            }
            const repro = root.querySelector('#repro-client');
            if (repro) {
              out.repro_client = {
                last: repro.getAttribute('data-last') || '',
                chain: repro.getAttribute('data-chain') || '',
              };
            }
            const delivery = root.querySelector('#solo-delivery-diag');
            if (delivery) {
              out.delivery = {
                stages: delivery.getAttribute('data-stages') || '',
                on_change: delivery.getAttribute('data-on-change') || '',
              };
            }
          }
          return out;
        }"""
    )


def python_stages(stages_chain: str) -> set[str]:
    return {p for p in str(stages_chain or "").split("|") if p}


def finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    final = dict(report.get("final_scrape") or {})
    case_a = final.get("case_a") or {}
    repro = final.get("repro_client") or {}
    delivery = final.get("delivery") or {}
    stages = python_stages(case_a.get("stages") or "") | python_stages(delivery.get("stages") or "")
    client = python_stages(repro.get("chain") or "")
    json_blob = str(case_a.get("json") or "")
    payload: dict[str, Any] = {}
    if json_blob:
        try:
            payload = json.loads(json_blob.replace("'", '"'))
        except json.JSONDecodeError:
            payload = {"raw": json_blob[:500]}
    callback_rows = payload.get("callbacks") if isinstance(payload.get("callbacks"), list) else []
    callbacks = int(case_a.get("callbacks") or len(callback_rows) or 0)
    passed = (case_a.get("passed") or "") in ("1", "true") or callbacks >= REQUIRED_CYCLES
    report["callbacks_received"] = callbacks
    stages_list = [p for p in str(case_a.get("stages") or delivery.get("stages") or "").split("|") if p]
    on_change_count = stages_list.count("on_change_callback_entry")
    raw_received_count = stages_list.count("session_state_raw_received")
    return_count = stages_list.count("component_return_value_received")
    tokens = [str(c.get("token") or "") for c in callback_rows if isinstance(c, dict)]
    dup_tokens = len(tokens) - len(set(t for t in tokens if t))
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    report["delivery_counts"] = {
        "on_change_callback_entry": on_change_count,
        "session_state_raw_received": raw_received_count,
        "component_return_value_received": return_count,
        "unique_tokens": len(set(t for t in tokens if t)),
        "duplicate_token_count": max(0, dup_tokens),
        "client_value_sent_count": str(repro.get("chain") or "").count("component_value_sent"),
        "browser_deadline_crossed_count": str(repro.get("chain") or "").count("browser_deadline_crossed"),
        "websocket_widget_value_frame_count": len(report.get("ws_frames") or []),
        "rerun_count": int(case_a.get("rerun") or meta.get("rerun_count") or 0),
    }
    report["deploy_sha"] = str(final.get("deploy_sha") or report.get("deploy_sha") or "")
    report["passed_4_of_4"] = passed and callbacks >= REQUIRED_CYCLES
    report["chain_hits"] = {
        "component_declaration_loaded": "component_declaration_loaded" in stages,
        "session_state_raw_received": "session_state_raw_received" in stages,
        "on_change_callback_entry": "on_change_callback_entry" in stages,
        "component_return_value_received": "component_return_value_received" in stages,
        "browser_deadline_crossed": "browser_deadline_crossed" in client,
        "component_value_sent": "component_value_sent" in client,
        "websocket_widget_value_frame": bool(report.get("ws_frames")),
    }
    report["valid_case"] = bool((case_a or {}).get("component_name")) or bool(
        (repro or {}).get("chain")
    )
    if not report["valid_case"]:
        report["invalid_reason"] = "case_a_probe_not_mounted_deploy_pending"
    report["verdict"] = (
        "pass"
        if report["passed_4_of_4"]
        and report["chain_hits"]["session_state_raw_received"]
        and report["chain_hits"]["on_change_callback_entry"]
        else ("fail" if report["valid_case"] else "invalid")
    )
    return report


def run_case_a_gate() -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from solo_widget_update_compare import scrape_client_chain

    url = case_a_url()
    report: dict[str, Any] = {
        "case": "A",
        "mode": "app_shell_minimal_repro",
        "setup_url": url,
        "started_at": time.time(),
        "samples": [],
        "ws_frames": [],
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        ws_frames: list[dict[str, Any]] = []
        install_ws_and_postmessage_hooks(page, ws_frames)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(5000)
        deadline = time.time() + TIMEOUT_S
        best_callbacks = 0
        while time.time() < deadline:
            snap = scrape_case_a(page)
            snap["client"] = scrape_client_chain(page)
            snap["elapsed_s"] = round(time.time() - float(report["started_at"]), 2)
            snap["ws_frame_count"] = len(ws_frames)
            cb = int((snap.get("case_a") or {}).get("callbacks") or 0)
            best_callbacks = max(best_callbacks, cb)
            prev_cb = int((report["samples"][-1].get("case_a") or {}).get("callbacks") or 0) if report["samples"] else -1
            if not report["samples"] or prev_cb != cb:
                report["samples"].append(snap)
            if cb >= REQUIRED_CYCLES and (snap.get("case_a") or {}).get("passed") in ("1", 1, "true"):
                break
            page.wait_for_timeout(1000)
        report["final_scrape"] = scrape_case_a(page)
        report["final_scrape"]["client"] = scrape_client_chain(page)
        from run_solo_clean_verification import scrape_live_sha

        report["deploy_sha"] = scrape_live_sha(page)
        report["final_scrape"]["deploy_sha"] = report["deploy_sha"]
        report["ws_frames"] = ws_frames[-40:]
        browser.close()
    report["best_callbacks"] = best_callbacks
    report = finalize_report(report)
    report["finished_at"] = time.time()
    return report


def main() -> int:
    report = run_case_a_gate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "verdict": report.get("verdict"), "passed_4_of_4": report.get("passed_4_of_4")}, indent=2))
    ok = report.get("verdict") == "pass"
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
