"""Probe parent postMessage + WS delivery stages on current Cloud build (no A-D wiring required)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
DIAG_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
OUT = Path(__file__).resolve().parent.parent / "data" / "solo_delivery_stage_probe.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from run_solo_diag_10s_controlled import (  # noqa: E402
    chain_hit,
    client_hit,
    scrape_snapshot,
    stages_from_chain,
)
from run_solo_delivery_isolation import install_ws_and_postmessage_hooks  # noqa: E402


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake, scrape_deploy_sha_from_page
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import click_btn, dom_counts, scrape_deploy_build, set_number

    report: dict[str, Any] = {
        "url": DIAG_URL,
        "observation_seconds": 36,
        "started_at": time.time(),
        "postmessage_events": [],
        "websocket_frames": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        ws_frames: list[dict[str, Any]] = []
        install_ws_and_postmessage_hooks(page, ws_frames)
        goto_and_wake(page, DIAG_URL, timeout_s=240)
        report["deploy_sha"] = scrape_deploy_sha_from_page(page) or scrape_deploy_build(page)
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
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 2

        poll_t0 = time.time()
        samples: list[dict[str, Any]] = []
        while time.time() - poll_t0 < 36:
            snap = scrape_snapshot(page)
            snap["elapsed_s"] = round(time.time() - poll_t0, 2)
            snap["postMessages"] = page.evaluate(
                "() => (window.__soloDeliveryPostMessages || []).slice(-20)"
            )
            samples.append(snap)
            page.wait_for_timeout(1000)

        browser.close()

    report["samples"] = samples
    report["websocket_frames"] = ws_frames[-30:]

    client_stages: set[str] = set()
    server_stages: set[str] = set()
    post_events: list[dict[str, Any]] = []
    for sample in samples:
        client = client_hit(sample)
        chain = chain_hit(sample)
        client_stages.update(stages_from_chain(str(client.get("chain") or "")))
        server_stages.update(stages_from_chain(str(chain.get("chain") or "")))
        post_events.extend(sample.get("postMessages") or [])

    report["client_stages"] = sorted(client_stages)
    report["server_stages"] = sorted(server_stages)
    report["postmessage_events"] = post_events[-20:]
    report["stage_hits"] = {
        "iframe_setComponentValue_called": "iframe_setComponentValue_called" in client_stages
        or "setComponentValue_called" in client_stages,
        "component_value_sent": "component_value_sent" in client_stages,
        "parent_postmessage_received": bool(post_events),
        "websocket_widget_update": bool(ws_frames),
        "on_change_callback_entry": "component_value_received" in server_stages,
        "pick_committed": "pick_committed" in server_stages,
    }

    order = [
        "iframe_setComponentValue_called",
        "component_value_sent",
        "parent_postmessage_received",
        "websocket_widget_update",
        "on_change_callback_entry",
        "pick_committed",
    ]
    report["first_failing_stage"] = next(
        (s for s in order if not report["stage_hits"].get(s)),
        "",
    )
    report["finished_at"] = time.time()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "first_failing": report["first_failing_stage"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
