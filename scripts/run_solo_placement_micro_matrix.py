"""P1 / P2a–P2d single-cycle micro isolation matrix (diagnostic harness)."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_placement_micro_matrix.json"
PLACEMENTS = ("P1", "P2A", "P2B", "P2C", "P2D")
WAIT_S = 28


def setup_url(placement: str) -> str:
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_delivery_diag=1"
        "&solo_micro_isolation=1"
        f"&solo_placement_micro={placement}"
        "&solo_component_diag=1"
        "&solo_diag_timer=10"
    )


def scrape_micro_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
          for(const x of roots()){
            const el=x&&x.querySelector('#solo-micro-isolation-diag');
            if(!el) continue;
            return {
              placement: el.getAttribute('data-placement')||'',
              source: el.getAttribute('data-source')||'',
              key: el.getAttribute('data-key')||'',
              token: el.getAttribute('data-token')||'',
              mount_run: el.getAttribute('data-mount-run')||'',
              expire_run: el.getAttribute('data-expire-run')||'',
              mount_widget_id: el.getAttribute('data-mount-widget-id')||'',
              send_widget_id: el.getAttribute('data-send-widget-id')||'',
              widget_ids_match: el.getAttribute('data-widget-ids-match')||'',
              reruns: el.getAttribute('data-reruns')||'',
              rerun_log: el.getAttribute('data-rerun-log')||'',
              stages: el.getAttribute('data-stages')||'',
              fragment: el.getAttribute('data-fragment')||'',
              complete: el.getAttribute('data-complete')||'',
              on_change: el.getAttribute('data-on-change')||'',
              raw_received: el.getAttribute('data-raw-received')||'',
              room_id: el.getAttribute('data-room-id')||'',
            };
          }
          return null;
        }"""
    )


def _widget_ids_from_ws(ws_frames: list[dict[str, Any]], key_sub: str) -> tuple[str, str]:
    mount_id = ""
    send_id = ""
    for frame in ws_frames:
        snip = str(frame.get("snippet") or "")
        if key_sub not in snip:
            continue
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snip):
            wid = f"$$ID-{match.group(1)}-{match.group(2)}"
            if key_sub in wid:
                if "expire_token" in snip or "setComponentValue" in snip or "DIAG" in snip:
                    send_id = send_id or wid
                mount_id = mount_id or wid
    if mount_id and not send_id:
        send_id = mount_id
    return mount_id, send_id


def _tokens_from_ws(ws_frames: list[dict[str, Any]], placement: str) -> list[str]:
    out: list[str] = []
    pref = f"DIAG{placement.upper()}"
    for frame in ws_frames:
        snip = str(frame.get("snippet") or "")
        for match in re.finditer(r"DIAG[A-Z0-9]+\|0\|[0-9.]+", snip):
            tok = match.group(0)
            if tok.startswith(pref) or placement == "P1":
                out.append(tok)
    return list(dict.fromkeys(out))


def classify_row(row: dict[str, Any]) -> str:
    if row.get("invalid_reason"):
        return "invalid"
    stages = str(row.get("stages") or "")
    raw = int(row.get("session_state_raw_received") or 0)
    oc = int(row.get("on_change_callback_entry") or 0)
    if raw >= 1 and oc >= 1:
        return "pass"
    if row.get("observation_ready") and row.get("outbound_token_count", 0) >= 1 and raw == 0 and oc == 0:
        return "fail"
    return "invalid"


def run_placement(
    page,
    placement: str,
    ws_frames: list[dict[str, Any]],
) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import scrape_live_sha
    from solo_draft_start_harness import (
        click_sidebar_for_ldr,
        execute_solo_draft_start_workflow,
        maybe_clear_stale_draft,
    )

    url = setup_url(placement)
    baseline = len(ws_frames)
    goto_and_wake(page, url, timeout_s=240)
    page.wait_for_timeout(5000)
    click_sidebar_for_ldr(page, settle_ms=6000)
    maybe_clear_stale_draft(page, [])
    room_id = ""
    draft_ok = True
    if placement != "P1":
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        draft_ok = bool(draft.get("start_success"))
        room_id = str(draft.get("room_id") or "")
    obs_ready = bool(probe.get("key")) if placement == "P1" else False
    if placement != "P1":
        obs_deadline = time.time() + 60
        while time.time() < obs_deadline:
            mp = scrape_micro_probe(page)
            if mp and mp.get("key") and mp.get("token"):
                obs_ready = True
                break
            page.wait_for_timeout(1000)

    deadline = time.time() + WAIT_S
    last_probe: dict[str, Any] | None = None
    while time.time() < deadline:
        last_probe = scrape_micro_probe(page)
        if last_probe and last_probe.get("complete") in ("1", "true", True):
            break
        if last_probe and "on_change_callback_entry" in str(last_probe.get("stages") or ""):
            break
        page.wait_for_timeout(1000)

    probe = last_probe or scrape_micro_probe(page) or {}
    key_sub = str(probe.get("key") or f"solo_countdown_wake_micro_{placement.lower()}")
    new_frames = ws_frames[baseline:]
    mount_wid, send_wid = _widget_ids_from_ws(new_frames, key_sub.split("_")[-1] if key_sub else placement.lower())
    if not mount_wid:
        mount_wid, send_wid = _widget_ids_from_ws(new_frames, "solo_countdown_wake_micro")
    tokens = _tokens_from_ws(new_frames, placement)
    stages = str(probe.get("stages") or "")
    row: dict[str, Any] = {
        "placement": placement,
        "source_location": probe.get("source") or "",
        "deploy_sha": scrape_live_sha(page),
        "room_id": probe.get("room_id") or room_id,
        "room_in_progress": draft_ok if placement != "P1" else None,
        "observation_ready": obs_ready if placement != "P1" else bool(probe.get("key")),
        "component_key": probe.get("key") or "",
        "mount_widget_id": mount_wid or probe.get("mount_widget_id") or "",
        "send_widget_id": send_wid or probe.get("send_widget_id") or "",
        "widget_ids_match": bool(mount_wid and send_wid and mount_wid == send_wid),
        "widget_registered_at_send_inferred": bool(mount_wid),
        "mount_script_run": probe.get("mount_run") or "",
        "expire_script_run": probe.get("expire_run") or "",
        "fragment_context": probe.get("fragment") or "",
        "rerun_log": probe.get("rerun_log") or "",
        "rerun_count": probe.get("reruns") or "",
        "outbound_token_count": len(tokens),
        "outbound_tokens": tokens,
        "session_state_raw_received": stages.count("session_state_raw_received"),
        "on_change_callback_entry": stages.count("on_change_callback_entry"),
        "stages": stages,
        "first_missing_stage": (
            "session_state_raw_received"
            if stages.count("session_state_raw_received") < 1
            else (
                "on_change_callback_entry"
                if stages.count("on_change_callback_entry") < 1
                else ""
            )
        ),
        "invalid_reason": "",
    }
    if not row["component_key"] and not tokens:
        row["invalid_reason"] = "never_mounted_or_sent"
    elif placement != "P1" and not draft_ok:
        row["invalid_reason"] = "draft_start_failed"
    row["verdict"] = classify_row(row)
    row["ws_frame_count"] = len(new_frames)
    return row


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "placements": [],
        "cloud_server_logs": "not_available_via_repo_automation; inspect Streamlit Cloud Manage app logs around expiration timestamps",
    }
    first_pass = ""
    first_fail = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)
        for placement in PLACEMENTS:
            row = run_placement(page, placement, ws_frames)
            report["placements"].append(row)
            if row["verdict"] == "pass" and not first_pass:
                first_pass = placement
            if row["verdict"] == "fail" and not first_fail:
                first_fail = placement
            if first_pass and first_fail:
                break
            page.wait_for_timeout(2000)
        browser.close()

    report["first_pass"] = first_pass
    report["first_fail"] = first_fail
    report["transition"] = (
        f"{first_pass}_pass_to_{first_fail}_fail"
        if first_pass and first_fail
        else (first_fail or first_pass or "none")
    )
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "transition": report["transition"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
