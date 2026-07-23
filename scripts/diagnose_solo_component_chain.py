"""Diagnose Solo countdown component chain on production Cloud (build-confirmed)."""

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
OUT = Path(__file__).resolve().parent.parent / "data" / "solo_component_chain_diagnosis.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

SCRAPE_IFRAMES_JS = """() => {
  const frames = [];
  function scan(root, depth, path) {
    if (!root) return;
    const client = root.querySelector('#solo-expire-client');
    const mount = root.querySelector('#solo-component-mount-diag');
    const chain = root.querySelector('#solo-expire-chain');
    if (client || mount || chain) {
      frames.push({
        path,
        depth,
        client: client ? {
          last: client.getAttribute('data-last') || '',
          chain: client.getAttribute('data-chain') || '',
          remounts: client.getAttribute('data-remounts') || '',
          deadline: client.getAttribute('data-deadline') || '',
          token: client.getAttribute('data-token') || '',
          remaining_ms: client.getAttribute('data-remaining-ms') || '',
          browser_time: client.getAttribute('data-browser-time') || '',
          checkpoint: client.getAttribute('data-checkpoint') || '',
        } : null,
        mount: mount ? {
          mounted: mount.getAttribute('data-mounted') || '',
          reason: mount.getAttribute('data-reason') || '',
          key: mount.getAttribute('data-key') || '',
          draft_id: mount.getAttribute('data-draft-id') || '',
          pick_index: mount.getAttribute('data-pick-index') || '',
          deadline: mount.getAttribute('data-deadline') || '',
          remaining: mount.getAttribute('data-remaining') || '',
          mount_count: mount.getAttribute('data-mount-count') || '',
          key_changed: mount.getAttribute('data-key-changed') || '',
          deadline_changed: mount.getAttribute('data-deadline-changed') || '',
          token: mount.getAttribute('data-token') || '',
        } : null,
        chain: chain ? {
          owner: chain.getAttribute('data-owner') || '',
          commits: chain.getAttribute('data-commits') || '',
          last: chain.getAttribute('data-last') || '',
          chain: chain.getAttribute('data-chain') || '',
        } : null,
      });
    }
    for (const iframe of root.querySelectorAll('iframe')) {
      try {
        if (iframe.contentDocument) {
          scan(iframe.contentDocument, depth + 1, path + '>iframe');
        }
      } catch (e) {}
    }
  }
  scan(document, 0, 'top');
  let iframeCount = document.querySelectorAll('iframe').length;
  return { iframe_count: iframeCount, hits: frames };
}"""


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake, scrape_deploy_sha_from_page
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import click_btn, dom_counts, scrape_deploy_build, set_number

    report: dict[str, Any] = {
        "url": DIAG_URL,
        "started_at": time.time(),
        "console": [],
        "samples": [],
        "answers": {},
        "first_failing_stage": "",
        "root_cause": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})

        def on_console(msg) -> None:
            text = msg.text or ""
            if "solo" in text.lower() or "countdown" in text.lower() or "streamlit" in text.lower():
                report["console"].append({"type": msg.type, "text": text[:500]})

        page.on("console", on_console)
        goto_and_wake(page, DIAG_URL, timeout_s=240)
        report["deploy_sha"] = scrape_deploy_sha_from_page(page) or scrape_deploy_build(page)
        if "End/Delete Draft" in page.inner_text("body"):
            click_btn(page, "End/Delete Draft", wait_ms=4000)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(1000)
        click_btn(page, "Start New Live Draft")
        active = False
        t0 = time.time()
        while time.time() - t0 < 120:
            d = dom_counts(page)
            if int(d.get("Pause Draft") or 0) >= 1:
                active = True
                break
            page.wait_for_timeout(1000)
        report["draft_active"] = active
        report["dom_at_start"] = d

        # Poll for ~25s (10s timer + margin) while keeping page active
        poll_t0 = time.time()
        while time.time() - poll_t0 < 25:
            snap = page.evaluate(SCRAPE_IFRAMES_JS)
            snap["elapsed_s"] = round(time.time() - poll_t0, 1)
            report["samples"].append(snap)
            page.mouse.move(200, 200)
            page.wait_for_timeout(2000)

        browser.close()

    last = report["samples"][-1] if report["samples"] else {"hits": []}
    hits = list(last.get("hits") or [])
    client_hits = [h for h in hits if h.get("client")]
    mount_hits = [h for h in hits if h.get("mount")]
    chain_hits = [h for h in hits if h.get("chain")]

    client = (client_hits[0].get("client") if client_hits else {}) or {}
    mount = (mount_hits[0].get("mount") if mount_hits else {}) or {}
    chain = (chain_hits[0].get("chain") if chain_hits else {}) or {}

    all_client_chains = []
    for sample in report["samples"]:
        for hit in sample.get("hits") or []:
            c = hit.get("client") or {}
            ch = str(c.get("chain") or "")
            if ch and ch not in all_client_chains:
                all_client_chains.append(ch)

    report["answers"] = {
        "1_component_iframe_mounted": bool(client_hits),
        "2_javascript_executes": any(
            "iframe_script_loaded" in ch or "render_event_received" in ch for ch in all_client_chains
        ),
        "3_receives_deadline_and_token": bool(client.get("deadline")) and bool(client.get("token")),
        "4_deadline_valid": bool(client.get("deadline")) and float(client.get("deadline") or 0) > 0,
        "5_iframe_remount_before_zero": int(client.get("remounts") or 0) > 1,
        "6_widget_key_changes": mount.get("key_changed") == "1",
        "7_deadline_regenerated_on_rerun": mount.get("deadline_changed") == "1",
        "8_component_removed_by_fragment": not bool(client_hits) and bool(mount_hits),
        "9_countdown_continues_while_waiting": any(
            "lifecycle_checkpoint" in ch for ch in all_client_chains
        ),
        "10_probe_used_component_iframe": bool(client_hits),
    }
    report["client_final"] = client
    report["mount_final"] = mount
    report["chain_final"] = chain
    report["client_chains_seen"] = all_client_chains
    report["iframe_hits_final"] = hits

    stages = [
        "iframe_script_loaded",
        "render_event_received",
        "token_received",
        "deadline_received",
        "countdown_started",
        "lifecycle_checkpoint",
        "browser_deadline_crossed",
        "setComponentValue_called",
        "component_value_sent",
    ]
    seen_stages = set()
    for ch in all_client_chains:
        for part in ch.split("|"):
            if part:
                seen_stages.add(part)
    for stage in stages:
        if stage not in seen_stages:
            report["first_failing_stage"] = stage
            break

    if not client_hits:
        report["root_cause"] = "component_iframe_not_found_in_dom"
    elif "iframe_script_loaded" not in seen_stages:
        report["root_cause"] = "component_script_never_executed"
    elif "render_event_received" not in seen_stages:
        report["root_cause"] = "streamlit_render_event_never_received"
    elif "render_rejected" in seen_stages or "deadline_already_expired" in seen_stages:
        report["root_cause"] = "invalid_or_already_expired_deadline"
    elif mount.get("deadline_changed") == "1" or int(client.get("remounts") or 0) > 2:
        report["root_cause"] = "rerun_remount_or_deadline_shift_before_zero_crossing"
    elif "browser_deadline_crossed" not in seen_stages:
        report["root_cause"] = "countdown_never_reached_zero_in_component_iframe"
    elif "component_value_sent" not in seen_stages:
        report["root_cause"] = "zero_crossed_but_setComponentValue_not_called"
    else:
        report["root_cause"] = "client_chain_complete_python_not_confirmed"

    report["duration_s"] = round(time.time() - float(report["started_at"]), 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "deploy_sha", "draft_active", "first_failing_stage", "root_cause",
        "answers", "client_final", "mount_final", "chain_final",
    )}, indent=2))
    print("saved", OUT)
    return 0 if report["root_cause"] == "client_chain_complete_python_not_confirmed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
