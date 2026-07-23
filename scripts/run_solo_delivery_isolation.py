"""Staged Solo component→Python delivery isolation on production Cloud."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = Path(__file__).resolve().parent.parent / "data" / "solo_delivery_isolation.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

CASES = ("A", "B", "C", "D")
OBSERVATION_SECONDS = 36

DELIVERY_STAGES = [
    "iframe_setComponentValue_called",
    "component_value_sent",
    "parent_postmessage_received",
    "streamlit_frontend_widget_update",
    "websocket_widget_update",
    "session_state_raw_received",
    "on_change_callback_entry",
    "token_coercion_complete",
    "process_solo_component_wake_entered",
    "pick_committed",
]

SERVER_PROXY_STAGES = [
    "component_value_received",
    "wake_received",
    "expire_entered",
    "deadline_confirmed_expired",
    "autopick_attempted",
    "pick_committed",
]


def case_url(case: str) -> str:
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_diag_timer=10"
        f"&solo_delivery_diag=1&solo_delivery_case={case}"
    )


def scrape_delivery_snapshot(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const out = { hits: [], postMessages: [], wsHints: [] };
          function scan(root, path) {
            if (!root) return;
            const client = root.querySelector('#solo-expire-client');
            const delivery = root.querySelector('#solo-delivery-diag');
            const parent = root.querySelector('#solo-delivery-parent');
            const chain = root.querySelector('#solo-expire-chain');
            if (client || delivery || parent || chain) {
              out.hits.push({
                path,
                client: client ? {
                  last: client.getAttribute('data-last') || '',
                  chain: client.getAttribute('data-chain') || '',
                  token: client.getAttribute('data-token') || '',
                  deadline: client.getAttribute('data-deadline') || '',
                } : null,
                delivery: delivery ? {
                  case: delivery.getAttribute('data-case') || '',
                  key: delivery.getAttribute('data-key') || '',
                  stages: delivery.getAttribute('data-stages') || '',
                  on_change: delivery.getAttribute('data-on-change') || '',
                  rerun: delivery.getAttribute('data-rerun') || '',
                  json: delivery.getAttribute('data-json') || '',
                } : null,
                parent: parent ? {
                  last: parent.getAttribute('data-last') || '',
                  chain: parent.getAttribute('data-chain') || '',
                  extra: parent.getAttribute('data-extra') || '',
                } : null,
                chain: chain ? {
                  owner: chain.getAttribute('data-owner') || '',
                  commits: chain.getAttribute('data-commits') || '',
                  last: chain.getAttribute('data-last') || '',
                  chain: chain.getAttribute('data-chain') || '',
                } : null,
              });
            }
            for (const f of root.querySelectorAll('iframe')) {
              try { if (f.contentDocument) scan(f.contentDocument, path + '>iframe'); } catch (e) {}
            }
          }
          scan(document, 'top');
          if (window.__soloDeliveryPostMessages) out.postMessages = window.__soloDeliveryPostMessages.slice(-40);
          return out;
        }"""
    )


def install_ws_and_postmessage_hooks(page, ws_frames: list[dict[str, Any]]) -> None:
    page.evaluate(
        """() => {
          window.__soloDeliveryPostMessages = window.__soloDeliveryPostMessages || [];
          if (!window.__soloDeliveryHooksInstalled) {
            window.addEventListener('message', (ev) => {
              const d = ev && ev.data;
              if (!d) return;
              if (d.type === 'streamlit:setComponentValue') {
                window.__soloDeliveryPostMessages.push({
                  ts: Date.now(),
                  type: d.type,
                  value: String((d.value && d.value.value) || d.value || '').slice(0, 200),
                });
              }
            }, true);
            window.__soloDeliveryHooksInstalled = true;
          }
        }"""
    )

    def _on_ws(ws):
        def _maybe_record(payload: Any) -> None:
            text = payload if isinstance(payload, str) else str(payload)
            lowered = text.lower()
            if (
                "solo_countdown_wake" in text
                or "setcomponentvalue" in lowered
                or "component" in lowered
            ):
                ws_frames.append({"ts": time.time(), "snippet": text[:500]})

        ws.on("framesent", _maybe_record)
        ws.on("framereceived", _maybe_record)

    page.on("websocket", _on_ws)


def stages_from_chain(chain: str) -> list[str]:
    return [p for p in str(chain or "").split("|") if p]


def first_hit(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    for hit in snapshot.get("hits") or []:
        val = hit.get(key)
        if val:
            return val
    return {}


def aggregate_client_stages(samples: list[dict[str, Any]]) -> set[str]:
    stages: set[str] = set()
    for sample in samples:
        client = first_hit(sample, "client")
        stages.update(stages_from_chain(str(client.get("chain") or "")))
    return stages


def aggregate_parent_stages(samples: list[dict[str, Any]]) -> set[str]:
    stages: set[str] = set()
    for sample in samples:
        parent = first_hit(sample, "parent")
        stages.update(stages_from_chain(str(parent.get("chain") or "")))
    return stages


def aggregate_python_stages(samples: list[dict[str, Any]]) -> set[str]:
    stages: set[str] = set()
    for sample in samples:
        delivery = first_hit(sample, "delivery")
        stages.update(stages_from_chain(str(delivery.get("stages") or "")))
        chain = first_hit(sample, "chain")
        stages.update(stages_from_chain(str(chain.get("chain") or "")))
    return stages


def evaluate_case(case_report: dict[str, Any]) -> dict[str, Any]:
    client = case_report.get("client_stages") or set()
    parent = case_report.get("parent_stages") or set()
    python = case_report.get("python_stages") or set()
    ws = case_report.get("websocket_frames_near_zero") or []

    stage_hits = {
        "iframe_setComponentValue_called": "iframe_setComponentValue_called" in client,
        "component_value_sent": "component_value_sent" in client,
        "parent_postmessage_received": "parent_postmessage_received" in parent,
        "streamlit_frontend_widget_update": "streamlit_frontend_widget_update" in parent,
        "websocket_widget_update": bool(ws) or "component_value_received" in python,
        "session_state_raw_received": "session_state_raw_received" in python,
        "on_change_callback_entry": "on_change_callback_entry" in python
        or str(case_report.get("on_change_dom") or "") == "1",
        "token_coercion_complete": "token_coercion_complete" in python,
        "process_solo_component_wake_entered": "process_solo_component_wake_entered" in python
        or "component_value_received" in python,
        "pick_committed": "pick_committed" in python,
    }

    first_fail = ""
    for stage in DELIVERY_STAGES:
        if stage == "websocket_widget_update":
            key = stage
        else:
            key = stage
        if not stage_hits.get(key):
            first_fail = stage
            break

    case_report["stage_hits"] = stage_hits
    case_report["first_failing_stage"] = first_fail
    case_report["passed_all_stages"] = not first_fail
    return case_report


def decision_tree(case_results: dict[str, Any]) -> str:
    passed = {c: case_results[c].get("passed_all_stages") for c in CASES}
    if not passed.get("A"):
        return "Case A fails — compare production component declaration/frontend bundle vs minimal repro."
    if not passed.get("B"):
        return "Case A passes but B fails — Solo route/page context is interfering."
    if not passed.get("C"):
        return "Case B passes but C fails — normal component location or surrounding reruns are interfering."
    if not passed.get("D"):
        return "Case C passes but D fails — wrapper or callback registration is the defect."
    if all(passed.values()):
        return "All cases pass — delivery chain intact in isolation; investigate non-diag production path."
    return "Mixed results — inspect first failing stage per case."


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake, scrape_deploy_sha_from_page
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import click_btn, dom_counts, scrape_deploy_build, set_number

    report: dict[str, Any] = {
        "started_at": time.time(),
        "observation_seconds": OBSERVATION_SECONDS,
        "cases": {},
        "decision": "",
        "proposed_minimal_fix": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        ws_frames: list[dict[str, Any]] = []
        install_ws_and_postmessage_hooks(page, ws_frames)

        setup_url = (
            f"{BASE}/?active_page=Live%20Draft%20Room"
            "&solo_component_diag=1&solo_diag_timer=10"
        )
        goto_and_wake(page, setup_url, timeout_s=240)
        report["deploy_sha"] = scrape_deploy_sha_from_page(page) or scrape_deploy_build(page)
        report["expected_deploy_sha"] = "c676334"
        if str(report.get("deploy_sha") or "").lower()[:7] != "c676334":
            report["decision"] = (
                f"Deploy not ready — live build {report.get('deploy_sha')} != expected c676334."
            )
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 3
        if "End/Delete Draft" in page.inner_text("body"):
            click_btn(page, "End/Delete Draft", wait_ms=5000)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(1500)
        click_btn(page, "Start New Live Draft", wait_ms=2000)
        active = False
        t0 = time.time()
        while time.time() - t0 < 120:
            if int(dom_counts(page).get("Pause Draft") or 0) >= 1:
                active = True
                break
            page.wait_for_timeout(1000)
        report["draft_active"] = active
        if not active:
            report["decision"] = "Draft never became active — cannot run delivery isolation."
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 2

        for case in CASES:
            case_report: dict[str, Any] = {
                "case": case,
                "url": case_url(case),
                "samples": [],
            }
            goto_and_wake(page, case_url(case), timeout_s=180)
            page.wait_for_timeout(2000)
            poll_t0 = time.time()
            while time.time() - poll_t0 < OBSERVATION_SECONDS:
                elapsed = round(time.time() - poll_t0, 2)
                snap = scrape_delivery_snapshot(page)
                snap["elapsed_s"] = elapsed
                case_report["samples"].append(snap)
                page.wait_for_timeout(1000)

            case_report["client_stages"] = aggregate_client_stages(case_report["samples"])
            case_report["parent_stages"] = aggregate_parent_stages(case_report["samples"])
            case_report["python_stages"] = aggregate_python_stages(case_report["samples"])
            last = case_report["samples"][-1] if case_report["samples"] else {}
            delivery = first_hit(last, "delivery")
            case_report["on_change_dom"] = delivery.get("on_change")
            case_report["widget_key"] = delivery.get("key")
            case_report["delivery_json"] = delivery.get("json")
            case_report["websocket_frames_near_zero"] = list(ws_frames[-20:])
            ws_frames.clear()
            case_report["postmessage_events"] = []
            for sample in case_report["samples"]:
                case_report["postmessage_events"].extend(sample.get("postMessages") or [])

            evaluate_case(case_report)
            case_report["client_stages"] = sorted(case_report["client_stages"])
            case_report["parent_stages"] = sorted(case_report["parent_stages"])
            case_report["python_stages"] = sorted(case_report["python_stages"])
            report["cases"][case] = case_report

        browser.close()

    report["decision"] = decision_tree(report["cases"])
    fails = [
        (c, report["cases"][c].get("first_failing_stage"))
        for c in CASES
        if not report["cases"][c].get("passed_all_stages")
    ]
    if fails:
        c0, stage0 = fails[0]
        report["first_failing_stage_overall"] = stage0
        report["first_failing_case"] = c0
        if stage0 == "parent_postmessage_received":
            report["proposed_minimal_fix"] = (
                "Parent page never receives streamlit:setComponentValue — inspect component iframe "
                "target/origin and Streamlit component bridge registration."
            )
        elif stage0 in ("streamlit_frontend_widget_update", "websocket_widget_update"):
            report["proposed_minimal_fix"] = (
                "PostMessage arrives but Streamlit does not forward widget update — inspect widget "
                "key registration, mount lifecycle, and duplicate-key collisions on the failing case path."
            )
        elif stage0 in ("session_state_raw_received", "on_change_callback_entry"):
            report["proposed_minimal_fix"] = (
                "WebSocket update may reach server but on_change does not run — inspect callback "
                "registration location and whether fragment/rerun boundaries skip the callback pass."
            )
        elif stage0 in ("token_coercion_complete", "process_solo_component_wake_entered"):
            report["proposed_minimal_fix"] = (
                "on_change runs but wake processing aborts — inspect token coercion and "
                "process_solo_component_wake guards (owner, pick_index, seen token)."
            )
        elif stage0 == "pick_committed":
            report["proposed_minimal_fix"] = (
                "Wake delivery succeeds but pick does not commit — inspect expire tick/autopick path only "
                "(not timer architecture)."
            )
    report["finished_at"] = time.time()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "decision": report["decision"], "fails": fails}, indent=2))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
