"""Compare outgoing widget updates: standalone minimal vs Case A vs Case B."""

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

OUT = ROOT / "data" / "solo_widget_update_comparison.json"
BASE = os.environ.get(
    "SOLO_ISOLATION_BASE_URL",
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app",
)
MINIMAL_URL = os.environ.get("MINIMAL_WAKE_REPRO_URL", BASE.rstrip("/"))
REQUIRED_STANDALONE = 4


def _pull_post_messages(page, store: dict[str, Any]) -> None:
    msgs = page.evaluate(
        """() => {
          const bag = window.__soloWidgetCompare && window.__soloWidgetCompare.postMessages;
          return Array.isArray(bag) ? bag.slice() : [];
        }"""
    )
    store["post_messages"] = msgs or []


def _run_standalone_minimal(page, store: dict[str, Any]) -> dict[str, Any]:
    from solo_widget_update_compare import install_compare_hooks, scrape_client_chain, summarize_environment

    install_compare_hooks(page, store)
    page.goto(MINIMAL_URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(5000)
    deadline = time.time() + 120
    while time.time() < deadline:
        _pull_post_messages(page, store)
        probe = page.evaluate(
            """() => {
              const el = document.querySelector('#repro-result');
              return {
                passed: el ? el.getAttribute('data-passed') : '',
                callbacks: el ? parseInt(el.getAttribute('data-callbacks') || '0', 10) : 0,
              };
            }"""
        )
        if int(probe.get("callbacks") or 0) >= REQUIRED_STANDALONE or probe.get("passed") == "true":
            break
        page.wait_for_timeout(1000)
    _pull_post_messages(page, store)
    scrape = scrape_client_chain(page)
    return summarize_environment(
        label="standalone_minimal_cloud",
        component_name="minimal_wake_repro",
        scrape=scrape,
        ws_frames=list(store.get("ws_frames") or []),
        post_messages=list(store.get("post_messages") or []),
        page_url=page.url,
    )


def _run_case_a(page, store: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from solo_widget_update_compare import install_compare_hooks, scrape_client_chain, summarize_environment

    install_compare_hooks(page, store)
    url = case_a_url()
    goto_and_wake(page, url, timeout_s=240)
    page.wait_for_timeout(5000)
    deadline = time.time() + 120
    while time.time() < deadline:
        _pull_post_messages(page, store)
        snap = scrape_case_a(page)
        cb = int((snap.get("case_a") or {}).get("callbacks") or 0)
        if cb >= REQUIRED_STANDALONE or (snap.get("case_a") or {}).get("passed") in ("1", "true"):
            break
        page.wait_for_timeout(1000)
    _pull_post_messages(page, store)
    scrape = scrape_client_chain(page)
    scrape["case_a"] = (scrape_case_a(page).get("case_a") or {})
    return summarize_environment(
        label="app_shell_case_a",
        component_name="minimal_wake_repro",
        scrape=scrape,
        ws_frames=list(store.get("ws_frames") or []),
        post_messages=list(store.get("post_messages") or []),
        page_url=page.url,
    )


def _run_case_b_summary() -> dict[str, Any]:
    from run_solo_ad_isolation_gate import case_setup_url, run_one_case
    from solo_widget_update_compare import summarize_environment

    case_report = run_one_case("B")
    scrape: dict[str, Any] = {
        "solo_expire_client": None,
        "delivery": None,
        "case_a": None,
        "repro_client": None,
    }
    best_client: dict[str, Any] = {}
    for sample in case_report.get("samples") or []:
        for hit in sample.get("hits") or []:
            client = hit.get("client") or {}
            if len(str(client.get("chain") or "")) >= len(str(best_client.get("chain") or "")):
                best_client = client
    if best_client:
        scrape["solo_expire_client"] = {
            "chain": best_client.get("chain"),
            "last": best_client.get("last"),
            "token": best_client.get("token"),
        }
    activation = case_report.get("case_activation") or {}
    scrape["delivery"] = {
        "key": case_report.get("widget_key"),
        "stages": "|".join(
            k for k, v in (case_report.get("chain_hits") or {}).items() if v and k.endswith("_received") or k in ("on_change_callback_entry",)
        ),
        "rerun": activation.get("ui_after_settle", {}).get("mount_probe"),
    }
    python = {
        "python_stages": [
            k
            for k, v in (case_report.get("chain_hits") or {}).items()
            if v
            and k
            in (
                "session_state_raw_received",
                "on_change_callback_entry",
                "component_return_value_received",
                "token_processed",
                "pick_committed",
            )
        ],
        "callback_count": 0,
        "callbacks": [],
        "cycles_done": None,
        "diag": {"widget_key": case_report.get("widget_key"), "raw_token": case_report.get("raw_token")},
    }
    env = summarize_environment(
        label="solo_route_case_b",
        component_name="solo_countdown_wake",
        scrape=scrape,
        ws_frames=list(case_report.get("_ws_frames") or []),
        post_messages=[],
        page_url=str(activation.get("page_url_after_start") or case_setup_url("B")),
    )
    env["python_session_state_result"] = python
    env["first_missing_stage"] = case_report.get("first_missing_stage")
    env["valid_case"] = case_report.get("valid_case")
    return env


def main() -> int:
    from playwright.sync_api import sync_playwright
    from solo_widget_update_compare import diff_environments

    report: dict[str, Any] = {"started_at": time.time(), "environments": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        for runner in (_run_standalone_minimal, _run_case_a):
            context = browser.new_context(viewport={"width": 1440, "height": 1200})
            page = context.new_page()
            store: dict[str, Any] = {"ws_frames": [], "post_messages": []}
            env = runner(page, store)
            env["ws_frame_samples"] = (store.get("ws_frames") or [])[-5:]
            env["postmessage_samples"] = (store.get("post_messages") or [])[-5:]
            report["environments"].append(env)
            context.close()
        browser.close()

    report["environments"].append(_run_case_b_summary())
    report["first_concrete_difference"] = diff_environments(report["environments"])
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "diff": report["first_concrete_difference"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
