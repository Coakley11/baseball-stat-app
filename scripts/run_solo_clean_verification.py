"""Poll for ca10b70+ tracing build, run clean 10s gate, optional A-D isolation."""

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
TRACING_ANCHOR_SHA = "ca10b70"
FIX_ANCHOR_SHA = "4d73e84"
STALE_SHAS = frozenset({"3acc761", "dc5a6d7", "6cc34f2", "3c2eb41", "b9d635e"})

OUT_POLL = ROOT / "data" / "solo_deploy_poll_tracing_build.json"
OUT_CLEAN = ROOT / "data" / "solo_clean_10s_diagnostic.json"
OUT_ISOLATION = ROOT / "data" / "solo_delivery_isolation_clean.json"

FULL_CHAIN = [
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

COMPONENT_NAME = "solo_countdown_wake"


def sha_is_ancestor(ancestor: str, descendant: str) -> bool:
    descendant = str(descendant or "").strip().lower()[:7]
    ancestor = str(ancestor or "").strip().lower()[:7]
    if not descendant or not ancestor:
        return False
    if descendant == ancestor:
        return True
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sha_includes_tracing_build(short_sha: str) -> bool:
    short_sha = str(short_sha or "").strip().lower()[:7]
    if not short_sha or short_sha in STALE_SHAS:
        return False
    if short_sha == TRACING_ANCHOR_SHA:
        return True
    return sha_is_ancestor(TRACING_ANCHOR_SHA, short_sha) and sha_is_ancestor(
        FIX_ANCHOR_SHA, short_sha
    )


def scrape_live_sha(page) -> str:
    from cloud_streamlit_wake import scrape_deploy_sha_from_page
    from run_production_solo_soak import scrape_deploy_build

    return str(scrape_deploy_sha_from_page(page) or scrape_deploy_build(page) or "").lower()[:7]


def poll_until_tracing_build(*, max_wait_s: int = 7200, interval_s: int = 30) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    url = f"{BASE}/?active_page=Live%20Draft%20Room"
    report: dict[str, Any] = {
        "tracing_anchor": TRACING_ANCHOR_SHA,
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
            ok = sha_includes_tracing_build(sha)
            row = {"ts": time.time(), "sha": sha, "includes_tracing_build": ok}
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
        parsed = json.loads(str(log_attr).replace("'", '"'))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _client_chain_stages(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _count_substage(chain: str, name: str) -> int:
    return str(chain or "").count(name)


def clear_stale_solo_draft(page) -> None:
    from run_production_solo_soak import click_btn

    try:
        body = page.inner_text("body", timeout=15000)
    except Exception:
        body = ""
    if "End/Delete Draft" in body:
        click_btn(page, "End/Delete Draft", wait_ms=6000)
        page.wait_for_timeout(2000)


def preflight_fresh_solo_draft(page, *, expected_sha: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_production_solo_soak import click_btn, dom_counts, scrape_expire_chain, set_number

    setup_url = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_diag_timer=10"
    )
    goto_and_wake(page, setup_url, timeout_s=240)
    clear_stale_solo_draft(page)
    live_sha = scrape_live_sha(page)
    set_number(page, "Number of Teams", "2")
    set_number(page, "Picks per Team", "8")
    page.wait_for_timeout(1500)
    click_btn(page, "Start New Live Draft", wait_ms=2500)
    active = False
    mount: dict[str, Any] = {}
    t0 = time.time()
    while time.time() - t0 < 120:
        if int(dom_counts(page).get("Pause Draft") or 0) >= 1:
            active = True
        mount = page.evaluate(
            """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            const m = root.querySelector('#solo-component-mount-diag');
            if (m) return {
              diag_timer: m.getAttribute('data-diag-timer')||'',
              diag_remaining: m.getAttribute('data-diag-remaining')||'',
              mounted: m.getAttribute('data-mounted')||'',
              key: m.getAttribute('data-key')||'',
            };
          }
          return {};
        }"""
        )
        if active and str(mount.get("diag_timer") or "") == "10":
            break
        page.wait_for_timeout(1000)
    live_sha = scrape_live_sha(page) or live_sha
    body = page.inner_text("body", timeout=20000)
    rem_s = str((mount or {}).get("diag_remaining") or "")
    rem_ok = rem_s.isdigit() and 0 < int(rem_s) <= 10
    timer_ok = (
        "Time remaining: 10s" in body
        or "Time remaining: 10" in body
        or (str((mount or {}).get("diag_timer") or "") == "10" and rem_ok)
    )
    return {
        "deploy_sha": live_sha,
        "deploy_sha_matches": sha_includes_tracing_build(live_sha),
        "expected_sha": expected_sha,
        "solo_component_diag_active": "solo_component_diag=1" in setup_url,
        "draft_active": active,
        "mount_probe": mount,
        "ten_second_ui": timer_ok,
        "ten_second_diag_timer": str((mount or {}).get("diag_timer") or "") == "10",
        "ten_second_diag_remaining": rem_s,
        "component_mount_hint": str((mount or {}).get("mounted") or "") == "1"
        or bool((mount or {}).get("key")),
        "preflight_ok": active
        and sha_includes_tracing_build(live_sha)
        and str((mount or {}).get("diag_timer") or "") == "10"
        and timer_ok,
    }


def run_clean_10s(page, *, deploy_sha: str) -> dict[str, Any]:
    from run_production_solo_soak import scrape_expire_chain, scrape_state
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_diag_10s_controlled import client_hit, scrape_snapshot

    ws_frames: list[dict[str, Any]] = []
    install_ws_and_postmessage_hooks(page, ws_frames)

    report: dict[str, Any] = {
        "deploy_sha": deploy_sha,
        "observation_seconds": 36,
        "started_at": time.time(),
        "samples": [],
        "ws_frames": [],
    }
    state_before = scrape_state(page)
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
    report["ws_frames"] = ws_frames[-40:]

    client_chain = str(best_client.get("chain") or "")
    client_stages: set[str] = set()
    for sample in report["samples"]:
        client_stages.update(_client_chain_stages(str(client_hit(sample).get("chain") or "")))

    server_stages: set[str] = set()
    server_log: list[dict[str, Any]] = []
    for sample in report["samples"]:
        ec = sample.get("expire_chain") or {}
        server_stages.update(_client_chain_stages(str(ec.get("chain") or "")))
        server_log.extend(_parse_chain_log(str(ec.get("log") or "")))
    final_ec = report.get("expire_chain_final") or {}
    server_stages.update(_client_chain_stages(str(final_ec.get("chain") or "")))
    server_log.extend(_parse_chain_log(str(final_ec.get("log") or "")))

    token_raw = str(best_client.get("token") or "")
    widget_key = ""
    m = re.search(r"solo_countdown_wake_[A-Za-z0-9]+_\d+", client_chain + json.dumps(final_ec))
    if m:
        widget_key = m.group(0)
    if not widget_key:
        widget_key = str((report["samples"][-1].get("expire_chain") or {}).get("component_return") or "")
    mount_samples = []
    for sample in report["samples"]:
        for hit in sample.get("hits") or []:
            if hit.get("mount"):
                mount_samples.append(hit["mount"])
    if mount_samples and not widget_key:
        widget_key = str(mount_samples[-1].get("key") or "")

    remount_count = _count_substage(client_chain, "iframe_remount")
    if best_client.get("remounts"):
        remount_count = max(remount_count, int(best_client.get("remounts") or 0))
    resend_count = _count_substage(client_chain, "expire_token_resend_allowed")

    ws_token_frame = any(
        token_raw and token_raw.split("|")[0] in str(f.get("snippet") or "") and token_raw in str(f.get("snippet") or "")
        for f in ws_frames
    ) or any(
        token_raw and token_raw in str(f.get("snippet") or "") for f in ws_frames
    )

    on_change_rows = [r for r in server_log if r.get("stage") == "on_change_callback_entry"]
    return_rows = [r for r in server_log if r.get("stage") == "component_return_value_received"]
    recv_rows = [r for r in server_log if r.get("stage") == "component_value_received"]
    token_proc_rows = [r for r in server_log if r.get("stage") == "token_processed"]
    pick_rows = [r for r in server_log if r.get("stage") == "pick_committed"]
    dup_reject = [r for r in server_log if r.get("stage") == "expire_rejected" and r.get("reason") == "duplicate_token"]

    on_change_deliveries = sum(1 for r in recv_rows + token_proc_rows if r.get("delivery_via") == "on_change")
    return_deliveries = sum(1 for r in recv_rows + token_proc_rows if r.get("delivery_via") == "return_value")
    if on_change_deliveries == 0 and on_change_rows:
        on_change_deliveries = len(on_change_rows)
    if return_deliveries == 0 and return_rows:
        return_deliveries = len(return_rows)

    pick_before = state_before.get("pick")
    pick_after = (report.get("state_final") or {}).get("pick")
    board_before = int(state_before.get("boardRows") or 0)
    board_after = int((report.get("state_final") or {}).get("boardRows") or 0)
    pick_delta = None
    if pick_before is not None and pick_after is not None:
        pick_delta = int(pick_after) - int(pick_before)
    board_delta = board_after - board_before

    chain_status = {
        "iframe_script_loaded": "iframe_script_loaded" in client_stages,
        "render_event_received": "render_event_received" in client_stages,
        "token_received": "token_received" in client_stages,
        "deadline_received": "deadline_received" in client_stages,
        "browser_deadline_crossed": "browser_deadline_crossed" in client_stages,
        "setComponentValue_called": "setComponentValue_called" in client_stages
        or "iframe_setComponentValue_called" in client_stages,
        "component_value_sent": "component_value_sent" in client_stages,
        "websocket_widget_value_frame": ws_token_frame,
        "session_state_raw_received": "session_state_raw_received" in server_stages,
        "on_change_callback_entry": "on_change_callback_entry" in server_stages,
        "component_return_value_received": "component_return_value_received" in server_stages,
        "token_processed": "token_processed" in server_stages,
        "pick_committed": "pick_committed" in server_stages or pick_delta == 1 or board_delta == 1,
        "new_deadline_installed": "new_deadline_installed" in server_stages,
    }

    sent_count = _count_substage(client_chain, "component_value_sent")
    duplicate_callback_count = max(0, len(on_change_rows) + len(return_rows) - 1)
    duplicate_pick_count = max(0, (pick_delta or 0) - 1, board_delta - 1, len(pick_rows) - 1)

    first_missing = next((s for s in FULL_CHAIN if not chain_status.get(s)), "")

    report.update(
        {
            "client_stages": sorted(client_stages),
            "server_stages": sorted(server_stages),
            "full_chain_status": chain_status,
            "first_missing_stage": first_missing,
            "widget_key": widget_key,
            "component_name": COMPONENT_NAME,
            "raw_token": token_raw,
            "iframe_remount_count": remount_count,
            "expire_token_resend_allowed_count": resend_count,
            "on_change_delivery_count": on_change_deliveries,
            "return_value_delivery_count": return_deliveries,
            "duplicate_callback_count": duplicate_callback_count,
            "duplicate_pick_count": duplicate_pick_count,
            "component_value_sent_count": sent_count,
            "pick_delta": pick_delta,
            "board_delta": board_delta,
            "server_log_tail": server_log[-20:],
        }
    )

    if first_missing:
        report["decision"] = f"FAIL_{first_missing}"
        if chain_status.get("component_value_sent") and first_missing in (
            "websocket_widget_value_frame",
            "session_state_raw_received",
            "on_change_callback_entry",
        ):
            report["interpretation"] = (
                "4d73e84 resend/return-value candidate rejected — iframe sent token but "
                "Streamlit/Python did not receive it on tracing build."
            )
    elif duplicate_pick_count > 0:
        report["decision"] = "FAIL_duplicate_pick"
    elif pick_delta not in (1, None) and board_delta != 1:
        report["decision"] = "FAIL_pick_not_one"
    else:
        report["decision"] = "PASS_clean_10s_full_chain"

    report["finished_at"] = time.time()
    return report


def run_case_isolation(case: str, *, deploy_sha: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import click_btn, dom_counts, scrape_expire_chain, set_number
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_diag_10s_controlled import client_hit, scrape_snapshot

    case_report: dict[str, Any] = {"case": case, "deploy_sha": deploy_sha, "samples": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        ws_frames: list[dict[str, Any]] = []
        install_ws_and_postmessage_hooks(page, ws_frames)

        setup_url = (
            f"{BASE}/?active_page=Live%20Draft%20Room"
            "&solo_component_diag=1&solo_diag_timer=10"
        )
        goto_and_wake(page, setup_url, timeout_s=240)
        clear_stale_solo_draft(page)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(1500)
        click_btn(page, "Start New Live Draft", wait_ms=2500)
        active = False
        t0 = time.time()
        while time.time() - t0 < 120:
            if int(dom_counts(page).get("Pause Draft") or 0) >= 1:
                active = True
                break
            page.wait_for_timeout(1000)
        case_report["draft_active"] = active
        if not active:
            case_report["verdict"] = "invalid"
            case_report["reason"] = "draft_not_active"
            context.close()
            browser.close()
            return case_report

        case_url = (
            f"{BASE}/?active_page=Live%20Draft%20Room"
            "&solo_component_diag=1&solo_diag_timer=10"
            f"&solo_delivery_diag=1&solo_delivery_case={case}"
        )
        goto_and_wake(page, case_url, timeout_s=180)
        page.wait_for_timeout(2500)

        poll_t0 = time.time()
        best_client: dict[str, Any] = {}
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
            case_report["samples"].append(snap)
            client = client_hit(snap)
            if len(str(client.get("chain") or "")) >= len(str(best_client.get("chain") or "")):
                best_client = client
            page.wait_for_timeout(1000)

        context.close()
        browser.close()

    client_chain = str(best_client.get("chain") or "")
    client_stages = _client_chain_stages(client_chain)
    sent = "component_value_sent" in client_stages or "setComponentValue_called" in client_stages
    mounted = "render_event_received" in client_stages or "iframe_script_loaded" in client_stages

    if not mounted and not client_chain:
        case_report["verdict"] = "invalid"
        case_report["reason"] = "zero_probes"
    elif not sent:
        case_report["verdict"] = "fail"
        case_report["first_missing"] = "setComponentValue_called_or_component_value_sent"
    else:
        ec = case_report["samples"][-1].get("expire_chain") if case_report["samples"] else {}
        server_log = _parse_chain_log(str((ec or {}).get("log") or ""))
        has_python = any(
            r.get("stage") in ("session_state_raw_received", "on_change_callback_entry", "component_value_received")
            for r in server_log
        )
        case_report["verdict"] = "pass" if has_python else "fail"
        case_report["first_missing"] = "" if has_python else "python_delivery"

    case_report["client_chain"] = client_chain
    case_report["client_stages"] = sorted(client_stages)
    case_report["setComponentValue_proven"] = sent
    case_report["component_mounted_proven"] = mounted or bool(client_chain)
    return case_report


def main() -> int:
    poll = poll_until_tracing_build()
    if not poll.get("ready"):
        print("DEPLOY_TIMEOUT waiting for", TRACING_ANCHOR_SHA, flush=True)
        return 2

    live_sha = str(poll.get("live_sha") or "")
    print("DEPLOY_READY", live_sha, flush=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        pre = preflight_fresh_solo_draft(page, expected_sha=live_sha)
        clean: dict[str, Any] = {"preflight": pre}
        if not pre.get("preflight_ok"):
            clean["decision"] = "FAIL_preflight"
            OUT_CLEAN.write_text(json.dumps(clean, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 2
        clean.update(run_clean_10s(page, deploy_sha=live_sha))
        context.close()
        browser.close()

    OUT_CLEAN.parent.mkdir(parents=True, exist_ok=True)
    OUT_CLEAN.write_text(json.dumps(clean, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: clean.get(k) for k in ("decision", "first_missing_stage", "interpretation", "deploy_sha")}, indent=2))

    if str(clean.get("decision") or "").startswith("PASS"):
        return 0

    iso_report: dict[str, Any] = {"deploy_sha": live_sha, "cases": {}}
    first_valid_fail = ""
    for case in ("A", "B", "C", "D"):
        cr = run_case_isolation(case, deploy_sha=live_sha)
        iso_report["cases"][case] = cr
        if cr.get("verdict") == "fail" and not first_valid_fail:
            first_valid_fail = case
    iso_report["first_valid_failing_case"] = first_valid_fail
    OUT_ISOLATION.write_text(json.dumps(iso_report, indent=2, default=str), encoding="utf-8")
    print("isolation", OUT_ISOLATION, "first_valid_failing_case", first_valid_fail)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
