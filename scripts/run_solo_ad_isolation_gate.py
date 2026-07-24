"""Poll for 6108c9c+ isolation wiring, run clean A-D with fresh session per case."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
ISOLATION_ANCHOR_SHA = "6108c9c"
OUT = ROOT / "data" / "solo_ad_isolation_gate.json"
OUT_POLL = ROOT / "data" / "solo_deploy_poll_isolation_build.json"
COMPONENT_NAME = "solo_countdown_wake"

DELIVERY_CHAIN = [
    "iframe_script_loaded",
    "render_event_received",
    "token_received",
    "deadline_received",
    "browser_deadline_crossed",
    "setComponentValue_called",
    "component_value_sent",
    "websocket_widget_value_frame",
    "session_state_raw_received",
    "on_change_callback_entry",
    "component_return_value_received",
    "token_processed",
    "pick_committed",
    "new_deadline_installed",
]


def sha_is_ancestor(ancestor: str, descendant: str) -> bool:
    descendant = str(descendant or "").strip().lower()[:7]
    ancestor = str(ancestor or "").strip().lower()[:7]
    if not descendant or not ancestor:
        return False
    if descendant == ancestor:
        return True
    try:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=ROOT,
                capture_output=True,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def sha_includes_isolation_build(short_sha: str) -> bool:
    return sha_is_ancestor(ISOLATION_ANCHOR_SHA, str(short_sha or "").lower()[:7])


def scrape_live_sha(page) -> str:
    from run_solo_clean_verification import scrape_live_sha as _s

    return _s(page)


def poll_until_isolation_build(*, max_wait_s: int = 7200, interval_s: int = 30) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    url = f"{BASE}/?active_page=Live%20Draft%20Room"
    report: dict[str, Any] = {
        "isolation_anchor": ISOLATION_ANCHOR_SHA,
        "started_at": time.time(),
        "attempts": [],
        "ready": False,
        "live_sha": "",
    }
    deadline = time.time() + max_wait_s
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        while time.time() < deadline:
            goto_and_wake(page, url, timeout_s=120)
            sha = scrape_live_sha(page)
            ok = sha_includes_isolation_build(sha)
            row = {"ts": time.time(), "sha": sha, "includes_isolation_build": ok}
            report["attempts"].append(row)
            print(json.dumps(row), flush=True)
            if ok:
                report["ready"] = True
                report["live_sha"] = sha
                break
            time.sleep(interval_s)
        browser.close()
    report["finished_at"] = time.time()
    OUT_POLL.parent.mkdir(parents=True, exist_ok=True)
    OUT_POLL.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _parse_log(log_attr: str) -> list[dict[str, Any]]:
    if not log_attr:
        return []
    try:
        parsed = json.loads(str(log_attr).replace("'", '"'))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _chain_stages(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _count(chain: str, stage: str) -> int:
    return str(chain or "").count(stage)


def start_fresh_solo_draft(page) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_production_solo_soak import click_btn, dom_counts, set_number
    from run_solo_clean_verification import clear_stale_solo_draft

    setup_url = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_diag_timer=10"
    )
    goto_and_wake(page, setup_url, timeout_s=240)
    clear_stale_solo_draft(page)
    set_number(page, "Number of Teams", "2")
    set_number(page, "Picks per Team", "8")
    page.wait_for_timeout(2000)
    click_btn(page, "Start New Live Draft", wait_ms=3000)
    meta: dict[str, Any] = {"draft_active": False, "room_id": "", "diag_timer_ok": False}
    t0 = time.time()
    while time.time() - t0 < 120:
        body = page.inner_text("body", timeout=15000)
        if "Room ID" in body:
            import re

            m = re.search(r"Room ID\s+([A-F0-9]+)", body, re.I)
            if m:
                meta["room_id"] = m.group(1)
        counts = dom_counts(page)
        if int(counts.get("Pause Draft") or 0) >= 1 and meta.get("room_id"):
            meta["draft_active"] = True
            mount = page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    const m = root.querySelector('#solo-component-mount-diag');
                    if (m) return m.getAttribute('data-diag-timer')||'';
                  }
                  return '';
                }"""
            )
            meta["diag_timer_ok"] = str(mount) == "10"
            if meta["diag_timer_ok"]:
                break
        page.wait_for_timeout(1000)
    return meta


def run_one_case(case: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_expire_chain
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_diag_10s_controlled import client_hit, mount_hit, scrape_snapshot

    report: dict[str, Any] = {"case": case, "samples": []}
    ws_frames: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        install_ws_and_postmessage_hooks(page, ws_frames)

        draft_meta = start_fresh_solo_draft(page)
        report["draft_start"] = draft_meta
        if not draft_meta.get("draft_active"):
            report["verdict"] = "invalid"
            report["reason"] = "fresh_solo_draft_not_active"
            context.close()
            browser.close()
            return report

        report["deploy_sha"] = scrape_live_sha(page)
        case_url = (
            f"{BASE}/?active_page=Live%20Draft%20Room"
            "&solo_component_diag=1&solo_diag_timer=10"
            f"&solo_delivery_diag=1&solo_delivery_case={case}"
        )
        goto_and_wake(page, case_url, timeout_s=180)
        page.wait_for_timeout(3000)
        report["deploy_sha_after_case_nav"] = scrape_live_sha(page)

        best_client: dict[str, Any] = {}
        best_mount: dict[str, Any] = {}
        poll_t0 = time.time()
        while time.time() - poll_t0 < 36:
            snap = scrape_snapshot(page)
            snap["elapsed_s"] = round(time.time() - poll_t0, 2)
            snap["expire_chain"] = scrape_expire_chain(page)
            snap["delivery"] = page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    const el = root.querySelector('#solo-delivery-diag');
                    if (el) return {
                      case: el.getAttribute('data-case')||'',
                      key: el.getAttribute('data-key')||'',
                      stages: el.getAttribute('data-stages')||'',
                    };
                  }
                  return {};
                }"""
            )
            report["samples"].append(snap)
            client = client_hit(snap)
            mount = mount_hit(snap)
            if len(str(client.get("chain") or "")) >= len(str(best_client.get("chain") or "")):
                best_client = client
            if mount:
                best_mount = mount
            page.wait_for_timeout(1000)

        context.close()
        browser.close()

    client_chain = str(best_client.get("chain") or "")
    stages = _chain_stages(client_chain)
    delivery = report["samples"][-1].get("delivery") if report["samples"] else {}
    widget_key = str(delivery.get("key") or best_mount.get("key") or "")
    if not widget_key and best_client.get("token"):
        parts = str(best_client.get("token")).split("|")
        if parts:
            widget_key = f"solo_countdown_wake_{parts[0]}_{parts[1] if len(parts)>1 else 0}"

    raw_token = str(best_client.get("token") or "")
    lobby_only = "Start New Live Draft" in (
        report["samples"][-1].get("text", "")[:4000] if report["samples"] else ""
    ) and "Pause Draft" not in (report["samples"][-1].get("text", "") if report["samples"] else "")

    component_mounted = bool(
        {"iframe_script_loaded", "render_event_received", "token_received", "deadline_received"} & stages
    )
    has_widget_key = bool(widget_key.strip())
    has_token_deadline = "token_received" in stages and "deadline_received" in stages
    setcomp = "setComponentValue_called" in stages or "iframe_setComponentValue_called" in stages
    sent = "component_value_sent" in stages

    valid = (
        not lobby_only
        and component_mounted
        and has_widget_key
        and has_token_deadline
        and setcomp
        and bool(client_chain)
    )

    server_log: list[dict[str, Any]] = []
    server_chain = ""
    for sample in report["samples"]:
        ec = sample.get("expire_chain") or {}
        server_chain = str(ec.get("chain") or server_chain)
        server_log.extend(_parse_log(str(ec.get("log") or "")))
    server_stages = _chain_stages(server_chain)
    for row in server_log:
        server_stages.add(str(row.get("stage") or ""))

    ws_token_frames = [
        f
        for f in ws_frames
        if raw_token and raw_token in str(f.get("snippet") or "")
    ]
    on_change_count = sum(1 for r in server_log if r.get("stage") == "on_change_callback_entry")
    return_count = sum(1 for r in server_log if r.get("stage") == "component_return_value_received")
    token_proc_count = sum(1 for r in server_log if r.get("stage") == "token_processed")
    pick_count = sum(1 for r in server_log if r.get("stage") == "pick_committed")

    chain_hits = {
        "iframe_script_loaded": "iframe_script_loaded" in stages,
        "render_event_received": "render_event_received" in stages,
        "token_received": "token_received" in stages,
        "deadline_received": "deadline_received" in stages,
        "browser_deadline_crossed": "browser_deadline_crossed" in stages,
        "setComponentValue_called": setcomp,
        "component_value_sent": sent,
        "websocket_widget_value_frame": bool(ws_token_frames),
        "session_state_raw_received": "session_state_raw_received" in server_stages,
        "on_change_callback_entry": "on_change_callback_entry" in server_stages,
        "component_return_value_received": "component_return_value_received" in server_stages,
        "token_processed": "token_processed" in server_stages,
        "pick_committed": "pick_committed" in server_stages,
        "new_deadline_installed": "new_deadline_installed" in server_stages,
    }
    first_missing = next((s for s in DELIVERY_CHAIN if not chain_hits.get(s)), "")

    report.update(
        {
            "verdict": "invalid" if not valid else ("pass" if not first_missing else "fail"),
            "valid_case": valid,
            "invalid_reason": ""
            if valid
            else (
                "lobby_only"
                if lobby_only
                else "missing_mount_key_token_or_setComponentValue"
            ),
            "component_name": COMPONENT_NAME,
            "widget_key": widget_key,
            "raw_token": raw_token,
            "iframe_remount_count": _count(client_chain, "iframe_remount"),
            "setComponentValue_count": _count(client_chain, "setComponentValue_called")
            + _count(client_chain, "iframe_setComponentValue_called"),
            "component_value_sent_count": _count(client_chain, "component_value_sent"),
            "websocket_widget_value_frame_count": len(ws_token_frames),
            "session_state_raw_received": "session_state_raw_received" in server_stages,
            "on_change_callback_count": on_change_count,
            "return_value_count": return_count,
            "token_processed_count": token_proc_count,
            "pick_count": pick_count,
            "client_chain": client_chain,
            "client_stages": sorted(stages),
            "server_stages": sorted(server_stages),
            "chain_hits": chain_hits,
            "first_missing_stage": first_missing if valid else "",
        }
    )
    return report


def decision_tree(cases: dict[str, Any]) -> tuple[str, str, str]:
    def v(c: str) -> str:
        return str((cases.get(c) or {}).get("verdict") or "")

    valid_cases = [c for c in "ABCD" if v(c) in ("pass", "fail")]
    first_valid_fail = next((c for c in "ABCD" if v(c) == "fail"), "")

    if not valid_cases:
        return "", "", "No valid cases — deployment or harness issue, not isolation conclusion."

    if v("A") == "fail" and first_valid_fail == "A":
        return (
            "A",
            "If standalone minimal repro passes on Cloud, investigate Baseball app shell or component loading.",
            "Defer production code change until standalone repro vs Case A is compared on same build.",
        )
    if v("A") == "pass" and v("B") == "fail" and first_valid_fail == "B":
        return (
            "B",
            "Solo route context interferes with delivery after app shell path works.",
            "Smallest fix: adjust Solo route mount timing/placement only after confirming B first_missing_stage.",
        )
    if v("B") in ("pass",) and v("C") == "fail" and first_valid_fail == "C":
        return (
            "C",
            "Normal placement or production component frontend/declaration interferes.",
            "Smallest fix: align normal-slot direct mount with passing B pattern (no new retry architecture).",
        )
    if v("C") == "pass" and v("D") == "fail" and first_valid_fail == "D":
        return (
            "D",
            "Production wrapper/callback registration is defective.",
            "Smallest fix: wrapper on_change/session_state registration only (no timer/remount changes).",
        )
    if all(v(c) == "pass" for c in valid_cases):
        return "", "All valid cases pass delivery chain.", "No production fix indicated by isolation."
    return first_valid_fail, "Mixed valid results — inspect first_missing_stage per case.", ""


def main() -> int:
    poll = poll_until_isolation_build()
    if not poll.get("ready"):
        print("DEPLOY_TIMEOUT waiting for", ISOLATION_ANCHOR_SHA, flush=True)
        return 2

    live_sha = str(poll.get("live_sha") or "")
    print("DEPLOY_READY", live_sha, flush=True)

    report: dict[str, Any] = {
        "isolation_anchor": ISOLATION_ANCHOR_SHA,
        "deploy_sha_poll": live_sha,
        "started_at": time.time(),
        "cases": {},
    }
    for case in ("A", "B", "C", "D"):
        print("CASE", case, flush=True)
        report["cases"][case] = run_one_case(case)

    first_fail, decision, proposed = decision_tree(report["cases"])
    report["first_valid_failing_case"] = first_fail
    report["decision"] = decision
    report["proposed_minimal_fix"] = proposed
    report["finished_at"] = time.time()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("artifact", OUT)
    print(json.dumps({"first_valid_failing_case": first_fail, "decision": decision}, indent=2))
    return 0 if not first_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
