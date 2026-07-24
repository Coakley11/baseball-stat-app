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
OUT_CASE_D_PROOF = ROOT / "data" / "solo_isolation_case_d_proof.json"
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


def ensure_live_draft_room_for_deploy_probe(page) -> None:
    """Deploy marker renders on Live Draft Room body; cold URL loads often stay on restored page."""
    from solo_draft_start_harness import click_sidebar_for_ldr
    from run_solo_clean_verification import scrape_live_sha

    if scrape_live_sha(page):
        return
    click_sidebar_for_ldr(page)


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
            ensure_live_draft_room_for_deploy_probe(page)
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


def case_setup_url(case: str) -> str:
    """All diagnostic query params present before observation — no post-start navigation."""
    letter = str(case or "D").strip().upper()
    if letter not in ("A", "B", "C", "D"):
        letter = "D"
    if letter == "A":
        return f"{BASE}/?solo_delivery_diag=1&solo_delivery_case=A"
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_diag_timer=10"
        f"&solo_delivery_diag=1&solo_delivery_case={letter}"
    )


def _token_room_id(client: dict[str, Any]) -> str:
    parts = str(client.get("token") or "").split("|")
    return parts[0].strip() if parts and parts[0].strip() else ""


def probe_case_session_ui(page, *, harness_room_id: str = "") -> dict[str, Any]:
    import re

    from cloud_streamlit_wake import all_frames_text
    from run_production_solo_soak import dom_counts
    from solo_draft_start_harness import STATE_PROBE_JS

    state = page.evaluate(STATE_PROBE_JS)
    counts = dom_counts(page)
    text = all_frames_text(page)
    room_id = str(state.get("room_id") or "")
    if not room_id:
        m = re.search(r"Room ID\s+([A-F0-9]+)", text, re.I)
        if m:
            room_id = m.group(1)
    if not room_id and harness_room_id:
        room_id = harness_room_id
    setup_visible = "Start New Live Draft" in text
    pause_visible = int(counts.get("Pause Draft") or 0) >= 1
    mount = state.get("mount_probe") or {}
    return {
        "room_id": room_id,
        "setup_lobby_visible": setup_visible,
        "pause_draft_visible": pause_visible,
        "diag_timer_10": str(mount.get("diag_timer") or "") == "10",
        "mount_probe": mount,
        "dom_counts": counts,
        "page_url": page.url,
    }


def finalize_case_verdict(
    report: dict[str, Any],
    *,
    case: str,
    ws_frames: list[dict[str, Any]],
    room_id_before: str,
    activation: dict[str, Any],
) -> dict[str, Any]:
    best_client: dict[str, Any] = report.pop("_best_client", {})
    best_mount: dict[str, Any] = report.pop("_best_mount", {})
    client_chain = str(best_client.get("chain") or "")
    stages = _chain_stages(client_chain)
    delivery = report["samples"][-1].get("delivery") if report.get("samples") else {}
    widget_key = str(delivery.get("key") or best_mount.get("key") or "")
    if not widget_key and best_client.get("token"):
        parts = str(best_client.get("token")).split("|")
        if parts:
            widget_key = f"solo_countdown_wake_{parts[0]}_{parts[1] if len(parts)>1 else 0}"

    raw_token = str(best_client.get("token") or "")
    token_room = _token_room_id(best_client)
    ui = activation.get("ui_after_settle") or {}
    last_ui = (
        (report.get("samples") or [])[-1].get("session_ui")
        if report.get("samples")
        else None
    ) or ui
    samples = report.get("samples") or []
    any_pause = any(
        bool((s.get("session_ui") or {}).get("pause_draft_visible")) for s in samples
    ) or bool(ui.get("pause_draft_visible"))
    any_room_in_poll = any(
        bool(str((s.get("session_ui") or {}).get("room_id") or "")) for s in samples
    )
    room_after = str(
        ui.get("room_id")
        or last_ui.get("room_id")
        or token_room
        or (room_id_before if (any_room_in_poll or any_pause or token_room) else "")
    )
    token_matches_harness = bool(room_id_before) and token_room == room_id_before
    returned_to_lobby = (
        bool(room_id_before)
        and not any_pause
        and not token_matches_harness
        and not bool(str(ui.get("room_id") or "") == room_id_before)
    )
    room_id_conflict = (
        bool(room_id_before)
        and bool(token_room)
        and token_room != room_id_before
    )
    room_preserved = bool(room_id_before) and not returned_to_lobby and not room_id_conflict and (
        room_after == room_id_before
        or token_matches_harness
        or (any_pause and token_room in ("", room_id_before))
    )
    lobby_only = returned_to_lobby or (not bool(room_id_before) and not any_pause)

    if returned_to_lobby:
        report["verdict"] = "invalid"
        report["valid_case"] = False
        report["invalid_reason"] = "lobby_only"
        report["reason"] = report["invalid_reason"]
        activation["room_id_preserved"] = False
        activation["streamlit_session_preserved"] = False
        report["case_activation"] = activation
        return report

    if room_id_conflict:
        report["verdict"] = "invalid"
        report["valid_case"] = False
        report["invalid_reason"] = "case_activation_lost_room_id"
        report["reason"] = report["invalid_reason"]
        activation["room_id_preserved"] = False
        report["case_activation"] = activation
        return report

    component_mounted = bool(
        {"iframe_script_loaded", "render_event_received", "token_received", "deadline_received"} & stages
    )
    has_widget_key = bool(widget_key.strip())
    has_token_deadline = "token_received" in stages and "deadline_received" in stages
    setcomp = "setComponentValue_called" in stages or "iframe_setComponentValue_called" in stages
    crossed = "browser_deadline_crossed" in stages

    pause_ok = bool(ui.get("pause_draft_visible")) or (
        case in ("A", "B") and (any_pause or token_matches_harness)
    )
    diag_ok = bool(ui.get("diag_timer_10")) or case in ("A", "B")

    valid = (
        not lobby_only
        and room_preserved
        and pause_ok
        and diag_ok
        and component_mounted
        and has_widget_key
        and has_token_deadline
        and setcomp
        and crossed
        and bool(client_chain)
    )

    server_log: list[dict[str, Any]] = []
    server_chain = ""
    for sample in report.get("samples") or []:
        ec = sample.get("expire_chain") or {}
        server_chain = str(ec.get("chain") or server_chain)
        server_log.extend(_parse_log(str(ec.get("log") or "")))
    server_stages = _chain_stages(server_chain)
    for row in server_log:
        server_stages.add(str(row.get("stage") or ""))

    ws_token_frames = [
        f for f in ws_frames if raw_token and raw_token in str(f.get("snippet") or "")
    ]
    on_change_count = sum(1 for r in server_log if r.get("stage") == "on_change_callback_entry")
    return_count = sum(1 for r in server_log if r.get("stage") == "component_return_value_received")
    token_proc_count = sum(1 for r in server_log if r.get("stage") == "token_processed")
    pick_count = sum(1 for r in server_log if r.get("stage") == "pick_committed")
    dup_on_change = max(0, on_change_count - 1) if on_change_count > 1 else 0
    dup_pick = max(0, pick_count - 1) if pick_count > 1 else 0

    chain_hits = {
        "iframe_script_loaded": "iframe_script_loaded" in stages,
        "render_event_received": "render_event_received" in stages,
        "token_received": "token_received" in stages,
        "deadline_received": "deadline_received" in stages,
        "browser_deadline_crossed": crossed,
        "setComponentValue_called": setcomp,
        "component_value_sent": "component_value_sent" in stages,
        "websocket_widget_value_frame": bool(ws_token_frames),
        "session_state_raw_received": "session_state_raw_received" in server_stages,
        "on_change_callback_entry": "on_change_callback_entry" in server_stages,
        "component_return_value_received": "component_return_value_received" in server_stages,
        "token_processed": "token_processed" in server_stages,
        "pick_committed": "pick_committed" in server_stages,
        "new_deadline_installed": "new_deadline_installed" in server_stages,
    }
    first_missing = next((s for s in DELIVERY_CHAIN if not chain_hits.get(s)), "")
    first_delivery = next(
        (s for s in DELIVERY_CHAIN if chain_hits.get(s)),
        "",
    )

    activation["room_id_preserved"] = room_preserved
    activation["returned_to_lobby"] = returned_to_lobby
    activation["room_id_after_case_activation"] = room_after or activation.get("room_id_after_case_activation")

    report.update(
        {
            "verdict": "invalid"
            if not valid
            else ("pass" if not first_missing else "fail"),
            "valid_case": valid,
            "invalid_reason": ""
            if valid
            else (
                "lobby_only"
                if lobby_only
                else "missing_prerequisites_or_delivery_probe"
            ),
            "component_name": COMPONENT_NAME,
            "widget_key": widget_key,
            "raw_token": raw_token,
            "iframe_remount_count": _count(client_chain, "iframe_remount"),
            "setComponentValue_count": _count(client_chain, "setComponentValue_called")
            + _count(client_chain, "iframe_setComponentValue_called"),
            "component_value_sent_count": _count(client_chain, "component_value_sent"),
            "browser_deadline_crossed": crossed,
            "websocket_widget_value_frame_count": len(ws_token_frames),
            "session_state_raw_received": "session_state_raw_received" in server_stages,
            "on_change_callback_count": on_change_count,
            "return_value_count": return_count,
            "token_processed_count": token_proc_count,
            "pick_count": pick_count,
            "duplicate_on_change_count": dup_on_change,
            "duplicate_pick_count": dup_pick,
            "first_delivery_stage_reached": first_delivery,
            "client_chain": client_chain,
            "chain_hits": chain_hits,
            "first_missing_stage": first_missing if valid else "",
            "case_activation": activation,
        }
    )
    return report


def run_one_case(case: str) -> dict[str, Any]:
    if str(case or "").upper() == "A":
        from run_case_a_app_shell_gate import run_case_a_gate

        return run_case_a_gate()

    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_expire_chain
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_diag_10s_controlled import client_hit, mount_hit, scrape_snapshot
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    report: dict[str, Any] = {"case": case, "samples": []}
    ws_frames: list[dict[str, Any]] = []
    setup_url = case_setup_url(case)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        install_ws_and_postmessage_hooks(page, ws_frames)

        draft_meta = execute_solo_draft_start_workflow(page, setup_url, navigate=True)
        report["draft_start"] = draft_meta
        if not draft_meta.get("start_success"):
            report["verdict"] = "invalid"
            report["reason"] = "fresh_solo_draft_not_active"
            context.close()
            browser.close()
            return report

        room_id_before = str(draft_meta.get("room_id") or "")
        activation: dict[str, Any] = {
            "setup_url": setup_url,
            "room_id_before_observation": room_id_before,
            "post_start_navigation": "none",
            "page_url_after_start": page.url,
            "streamlit_session_preserved": True,
        }
        report["deploy_sha"] = scrape_live_sha(page)
        page.wait_for_timeout(4000)
        ui_after = probe_case_session_ui(page, harness_room_id=room_id_before)
        activation["ui_after_settle"] = ui_after
        activation["room_id_after_case_activation"] = ui_after.get("room_id") or room_id_before
        activation["room_id_preserved"] = bool(room_id_before) and (
            str(ui_after.get("room_id") or room_id_before) == room_id_before
            or bool(ui_after.get("pause_draft_visible"))
        )
        activation["delivery_case_in_url"] = f"solo_delivery_case={case.upper()}" in page.url

        best_client: dict[str, Any] = {}
        best_mount: dict[str, Any] = {}
        poll_t0 = time.time()
        while time.time() - poll_t0 < 36:
            snap = scrape_snapshot(page)
            snap["elapsed_s"] = round(time.time() - poll_t0, 2)
            snap["expire_chain"] = scrape_expire_chain(page)
            snap["session_ui"] = probe_case_session_ui(page, harness_room_id=room_id_before)
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

    report["_best_client"] = best_client
    report["_best_mount"] = best_mount
    report["_ws_frames"] = ws_frames[-40:]
    return finalize_case_verdict(
        report,
        case=case,
        ws_frames=ws_frames,
        room_id_before=room_id_before,
        activation=activation,
    )


def run_case_d_proof() -> dict[str, Any]:
    """Single-case proof: Case D armed in initial URL, no navigation after start."""
    if not __import__("solo_draft_start_harness", fromlist=["harness_proven_on_disk"]).harness_proven_on_disk():
        return {"error": "harness_not_proven"}
    report = run_one_case("D")
    report["proof"] = "case_d_same_session"
    OUT_CASE_D_PROOF.parent.mkdir(parents=True, exist_ok=True)
    OUT_CASE_D_PROOF.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def decision_tree(cases: dict[str, Any]) -> tuple[str, str, str]:
    def v(c: str) -> str:
        raw = str((cases.get(c) or {}).get("verdict") or "")
        if c == "A" and raw == "pass":
            return "pass"
        if c == "A" and raw == "fail":
            return "fail"
        return raw

    valid_cases = [c for c in "ABCD" if v(c) in ("pass", "fail")]
    first_valid_fail = next((c for c in "ABCD" if v(c) == "fail"), "")

    if not valid_cases:
        return "", "", "No valid cases — deployment or harness issue, not isolation conclusion."

    if v("A") == "fail" and first_valid_fail == "A":
        return (
            "A",
            "App-shell minimal repro fails while standalone passes — compare Baseball shell "
            "widget registration / script-run lifecycle vs standalone.",
            "Diagnostic-only: align Case A mount order with standalone repro; no production timer changes.",
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


def case_d_proof_passed() -> bool:
    if not OUT_CASE_D_PROOF.is_file():
        return False
    try:
        data = json.loads(OUT_CASE_D_PROOF.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(data.get("valid_case")) and str(data.get("verdict") or "") in ("pass", "fail")


def main() -> int:
    import sys

    from solo_draft_start_harness import HARNESS_PROVEN_FILE, harness_proven_on_disk

    if len(sys.argv) > 1 and sys.argv[1] == "--case-d-proof":
        if not harness_proven_on_disk():
            print("HARNESS_NOT_PROVEN", HARNESS_PROVEN_FILE, flush=True)
            return 3
        proof = run_case_d_proof()
        print(
            json.dumps(
                {
                    "artifact": str(OUT_CASE_D_PROOF),
                    "verdict": proof.get("verdict"),
                    "valid_case": proof.get("valid_case"),
                    "room_preserved": (proof.get("case_activation") or {}).get("room_id_preserved"),
                },
                indent=2,
            )
        )
        return 0 if proof.get("valid_case") else 1

    if not harness_proven_on_disk():
        print(
            "HARNESS_NOT_PROVEN — run scripts/run_solo_draft_start_reliability_gate.py "
            f"(3/3 greens required). Expected: {HARNESS_PROVEN_FILE}",
            flush=True,
        )
        return 3

    if not case_d_proof_passed():
        print(
            "CASE_D_PROOF_REQUIRED — run: python scripts/run_solo_ad_isolation_gate.py --case-d-proof",
            flush=True,
        )
        return 4

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
