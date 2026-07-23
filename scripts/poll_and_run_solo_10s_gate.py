"""Poll Streamlit Cloud until fix build 4d73e84+, then run gated 10s Solo expiration test."""

from __future__ import annotations

import json
import re
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
DIAG_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
FIX_ANCHOR_SHA = "4d73e84"
STALE_SHAS = frozenset({"3acc761", "dc5a6d7", "6cc34f2", "3c2eb41", "b9d635e"})
OUT_POLL = ROOT / "data" / "solo_deploy_poll_fix_build.json"
OUT_GATE = ROOT / "data" / "solo_10s_gate_result.json"

REQUIRED_CHAIN = [
    "browser_deadline_crossed",
    "setComponentValue_called",
    "component_value_sent",
    "websocket_widget_value_update",
    "session_state_raw_received",
    "on_change_callback_entry",
    "token_processed",
    "pick_committed",
    "new_deadline_installed",
]


def sha_includes_fix(short_sha: str) -> bool:
    short_sha = str(short_sha or "").strip().lower()[:7]
    if not short_sha or short_sha in STALE_SHAS:
        return False
    if short_sha == FIX_ANCHOR_SHA:
        return True
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", FIX_ANCHOR_SHA, short_sha],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return short_sha not in STALE_SHAS and short_sha >= FIX_ANCHOR_SHA


def scrape_live_sha(page) -> str:
    from cloud_streamlit_wake import scrape_deploy_sha_from_page
    from run_production_solo_soak import scrape_deploy_build

    return str(scrape_deploy_sha_from_page(page) or scrape_deploy_build(page) or "").lower()[:7]


def poll_until_fix_build(*, max_wait_s: int = 7200, interval_s: int = 30) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    url = f"{BASE}/?active_page=Live%20Draft%20Room"
    report: dict[str, Any] = {
        "fix_anchor": FIX_ANCHOR_SHA,
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
            ok = sha_includes_fix(sha)
            row = {"ts": time.time(), "sha": sha, "includes_fix": ok}
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


def _parse_chain_log(log_attr: str) -> list[dict[str, Any]]:
    if not log_attr:
        return []
    try:
        parsed = json.loads(log_attr.replace("'", '"'))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _stages_from_client_chain(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _aggregate_server_stages(samples: list[dict[str, Any]]) -> tuple[set[str], list[dict[str, Any]]]:
    stages: set[str] = set()
    logs: list[dict[str, Any]] = []
    for sample in samples:
        chain = sample.get("expire_chain") or {}
        stages.update(_stages_from_client_chain(chain.get("chain") or ""))
        logs.extend(_parse_chain_log(str(chain.get("log") or "")))
    return stages, logs


def run_controlled_10s(*, deploy_sha: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import click_btn, dom_counts, scrape_expire_chain, scrape_state, set_number
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_diag_10s_controlled import (
        chain_hit,
        client_hit,
        scrape_snapshot,
        stages_from_chain,
    )

    report: dict[str, Any] = {
        "deploy_sha": deploy_sha,
        "url": DIAG_URL,
        "observation_seconds": 36,
        "started_at": time.time(),
        "ws_value_frames": [],
        "samples": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        ws_frames: list[dict[str, Any]] = []
        install_ws_and_postmessage_hooks(page, ws_frames)
        goto_and_wake(page, DIAG_URL, timeout_s=240)
        if "End/Delete Draft" in page.inner_text("body"):
            click_btn(page, "End/Delete Draft", wait_ms=5000)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(1500)
        state_before = scrape_state(page)
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
            report["decision"] = "FAIL_draft_not_active"
            browser.close()
            return report

        poll_t0 = time.time()
        best_client: dict[str, Any] = {}
        while time.time() - poll_t0 < 36:
            snap = scrape_snapshot(page)
            snap["elapsed_s"] = round(time.time() - poll_t0, 2)
            snap["expire_chain"] = scrape_expire_chain(page)
            snap["state"] = scrape_state(page)
            report["samples"].append(snap)
            client = client_hit(snap)
            if len(str(client.get("chain") or "")) >= len(str(best_client.get("chain") or "")):
                best_client = client
            page.wait_for_timeout(1000)

        report["state_final"] = scrape_state(page)
        report["expire_chain_final"] = scrape_expire_chain(page)
        browser.close()

    client_stages = _stages_from_client_chain(best_client.get("chain") or "")
    for sample in report["samples"]:
        client_stages.update(stages_from_chain(str(client_hit(sample).get("chain") or "")))

    server_stages, server_log = _aggregate_server_stages(report["samples"])
    final_chain = report.get("expire_chain_final") or {}
    server_stages.update(stages_from_chain(str(final_chain.get("chain") or "")))
    server_log.extend(_parse_chain_log(str(final_chain.get("log") or "")))

    value_frames = []
    token_hint = str(best_client.get("token") or "")
    draft_id = token_hint.split("|")[0] if token_hint else ""
    for frame in ws_frames:
        snip = str(frame.get("snippet") or "")
        if "solo_countdown_wake" in snip and draft_id and draft_id in snip:
            if "expire_token" in snip or token_hint.split("|")[0] in snip:
                value_frames.append(frame)
        if token_hint and token_hint in snip:
            value_frames.append(frame)
    post_zero_frames = [
        f
        for f in ws_frames
        if draft_id
        and draft_id in str(f.get("snippet") or "")
        and "solo_countdown_wake" in str(f.get("snippet") or "")
        and f.get("ts", 0) >= report["started_at"] + 8
    ]
    report["ws_value_frames"] = post_zero_frames[-12:] or value_frames[-12:]

    pick_before = state_before.get("pick")
    pick_after = (report.get("state_final") or {}).get("pick")
    board_before = int(state_before.get("boardRows") or 0)
    board_after = int((report.get("state_final") or {}).get("boardRows") or 0)
    pick_delta = None
    if pick_before is not None and pick_after is not None:
        pick_delta = int(pick_after) - int(pick_before)
    board_delta = board_after - board_before

    sent_count = sum(
        str(client_hit(s).get("chain") or "").count("component_value_sent")
        for s in report["samples"]
    )
    resend_allowed = "expire_token_resend_allowed" in client_stages
    second_sent_after_resend = sent_count >= 2 and resend_allowed

    recv_rows = [r for r in server_log if r.get("stage") == "component_value_received"]
    on_change_rows = [r for r in server_log if r.get("stage") == "on_change_callback_entry"]
    return_rows = [r for r in server_log if r.get("stage") == "component_return_value_received"]
    token_processed_rows = [r for r in server_log if r.get("stage") == "token_processed"]
    pick_commit_rows = [r for r in server_log if r.get("stage") == "pick_committed"]
    duplicate_reject_rows = [
        r for r in server_log if r.get("stage") == "expire_rejected" and r.get("reason") == "duplicate_token"
    ]

    delivery_vias = {str(r.get("delivery_via") or "") for r in recv_rows + token_processed_rows if r.get("delivery_via")}
    paths: list[str] = []
    if any(r.get("delivery_via") == "on_change" for r in recv_rows + token_processed_rows) or on_change_rows:
        paths.append("on_change")
    if any(r.get("delivery_via") == "return_value" for r in recv_rows + token_processed_rows) or return_rows:
        paths.append("return_value")
    if resend_allowed and (second_sent_after_resend or any(r.get("delivery_via") for r in recv_rows)):
        paths.append("resend_after_remount")

    ws_frame_hit = bool(post_zero_frames) or any(
        token_hint and token_hint in str(f.get("snippet") or "") for f in ws_frames
    )
    server_received = "component_value_received" in server_stages or "session_state_raw_received" in server_stages

    chain_hits = {
        "browser_deadline_crossed": "browser_deadline_crossed" in client_stages,
        "setComponentValue_called": "setComponentValue_called" in client_stages
        or "iframe_setComponentValue_called" in client_stages,
        "component_value_sent": "component_value_sent" in client_stages,
        "websocket_widget_value_update": ws_frame_hit or server_received,
        "session_state_raw_received": "session_state_raw_received" in server_stages,
        "on_change_callback_entry": "on_change_callback_entry" in server_stages,
        "token_processed": "token_processed" in server_stages or "component_value_received" in server_stages,
        "pick_committed": "pick_committed" in server_stages or pick_delta == 1 or board_delta == 1,
        "new_deadline_installed": "new_deadline_installed" in server_stages,
    }

    first_missing = next((s for s in REQUIRED_CHAIN if not chain_hits.get(s)), "")
    exactly_one_pick = pick_delta == 1 or board_delta == 1
    commits_dom = int(str(final_chain.get("commits") or "0") or 0)

    report.update(
        {
            "client_stages": sorted(client_stages),
            "server_stages": sorted(server_stages),
            "chain_hits": chain_hits,
            "websocket_frame_hit": ws_frame_hit,
            "websocket_confirmed_via_server": server_received and not ws_frame_hit,
            "first_missing_stage": first_missing,
            "expire_token_resend_allowed": resend_allowed,
            "component_value_sent_count": sent_count,
            "component_value_received_count": len(recv_rows),
            "on_change_callback_count": len(on_change_rows),
            "return_value_callback_count": len(return_rows),
            "token_processed_count": len(token_processed_rows),
            "pick_committed_count": len(pick_commit_rows) or commits_dom,
            "duplicate_token_reject_count": len(duplicate_reject_rows),
            "delivery_paths_observed": paths,
            "delivery_vias_logged": sorted(v for v in delivery_vias if v),
            "pick_delta": pick_delta,
            "board_delta": board_delta,
            "exactly_one_pick": exactly_one_pick,
        }
    )

    if first_missing:
        report["decision"] = f"FAIL_missing_{first_missing}"
    elif not exactly_one_pick:
        report["decision"] = "FAIL_pick_count_not_one"
    elif report["pick_committed_count"] > 1 or pick_delta not in (None, 1) or board_delta > 1:
        report["decision"] = "FAIL_duplicate_pick"
    elif report["on_change_callback_count"] + report["return_value_callback_count"] > 2:
        report["decision"] = "FAIL_duplicate_callback"
    else:
        report["decision"] = "PASS_controlled_10s_full_chain"

    report["finished_at"] = time.time()
    return report


def main() -> int:
    poll = poll_until_fix_build()
    if not poll.get("ready"):
        print("DEPLOY_TIMEOUT waiting for fix build", FIX_ANCHOR_SHA, flush=True)
        return 2

    live_sha = str(poll.get("live_sha") or "")
    print("DEPLOY_READY", live_sha, flush=True)

    gate = run_controlled_10s(deploy_sha=live_sha)
    gate["deploy_poll"] = {"live_sha": live_sha, "fix_anchor": FIX_ANCHOR_SHA}
    OUT_GATE.parent.mkdir(parents=True, exist_ok=True)
    OUT_GATE.write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: gate.get(k) for k in ("decision", "first_missing_stage", "delivery_paths_observed", "exactly_one_pick")}, indent=2))

    if not str(gate.get("decision") or "").startswith("PASS"):
        print("Running A-D delivery isolation on confirmed fix build...", flush=True)
        iso = subprocess.run(
            [sys.executable, str(_SCRIPTS / "run_solo_delivery_isolation.py")],
            cwd=ROOT,
        )
        gate["isolation_exit_code"] = iso.returncode
        OUT_GATE.write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
        return 1

    print("Running four natural expirations + interaction matrix (production soak)...", flush=True)
    soak = subprocess.run([sys.executable, str(_SCRIPTS / "run_production_solo_soak.py")], cwd=ROOT)
    gate["soak_exit_code"] = soak.returncode
    OUT_GATE.write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
    return 0 if soak.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
