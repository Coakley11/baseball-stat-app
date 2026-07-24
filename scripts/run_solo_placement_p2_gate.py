"""Single valid P2 placement-ladder observation (diagnostic harness only)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
P2_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_delivery_diag=1"
    "&solo_placement_ladder=P2"
    "&solo_component_diag=1"
    "&solo_diag_timer=10"
)
PROVEN_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
OUT = ROOT / "data" / "solo_placement_p2_gate.json"
REQUIRED_CYCLES = 4
OBSERVE_S = 150


def scrape_ladder_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o}
          let ladder=null, latch=null;
          for(const x of roots()){
            const l=x&&x.querySelector('#solo-placement-ladder-diag');
            if(l) ladder={
              placement:l.getAttribute('data-placement')||'',
              passed:l.getAttribute('data-passed')||'',
              callbacks:parseInt(l.getAttribute('data-callbacks')||'0',10),
              key:l.getAttribute('data-key')||'',
              token:l.getAttribute('data-token')||'',
              stages:l.getAttribute('data-stages')||'',
              rerun:l.getAttribute('data-rerun')||'',
            };
            const t=x&&x.querySelector('#solo-placement-latch-diag');
            if(t) latch={
              requested:t.getAttribute('data-requested')||'',
              query:t.getAttribute('data-query-placement')||'',
              active:t.getAttribute('data-active')||'',
            };
          }
          return {ladder, latch};
        }"""
    )


def finalize_p2(
    *,
    deploy_sha: str,
    draft_start: dict[str, Any],
    probe: dict[str, Any],
    ws_frames: list[dict[str, Any]],
    proven_draft: dict[str, Any] | None,
) -> dict[str, Any]:
    from run_solo_delivery_matrix_2x2 import (
        _count_stage,
        _python_delivery_complete,
        _tokens_from_ws,
        _widget_ids_from_ws,
    )

    ladder = probe.get("ladder") or {}
    latch = probe.get("latch") or {}
    python_chain = str(ladder.get("stages") or "")
    callbacks = int(ladder.get("callbacks") or 0)
    ws_tokens = _tokens_from_ws(ws_frames)
    widget_ids = _widget_ids_from_ws(ws_frames)
    hits = {
        "session_state_raw_received": python_chain.count("session_state_raw_received"),
        "on_change_callback_entry": python_chain.count("on_change_callback_entry"),
        "websocket_widget_value_frame": len(ws_frames),
        "setComponentValue_called": 0,
        "browser_deadline_crossed": 0,
    }
    python_ok, python_fail = _python_delivery_complete(
        callbacks=callbacks,
        hits=hits,
        dup=0,
        json_blob="",
        component="solo_countdown_wake",
        ws_tokens=ws_tokens,
    )
    mount_ids = [w for w in widget_ids if "solo_countdown" in w or "diag_p2" in w.lower()]
    pre_ok = bool(draft_start.get("start_success"))
    valid = (
        pre_ok
        and bool(ladder.get("placement") == "P2" or latch.get("requested") == "P2")
        and bool(ladder.get("key"))
        and python_ok
    )
    passed = valid and callbacks >= REQUIRED_CYCLES and ladder.get("passed") in ("1", "true", True)
    verdict = "pass" if passed else ("fail" if valid else "invalid")

    query_checkpoints = [
        c for c in (draft_start.get("checkpoints") or []) if str(c.get("step", "")).startswith("query_")
    ]
    divergence = None
    if proven_draft and not pre_ok:
        divergence = {"note": "proven_compare_not_run"}

    return {
        "deploy_sha": deploy_sha,
        "setup_url": P2_SETUP_URL,
        "verdict": verdict,
        "valid_case": valid,
        "draft_start_success": pre_ok,
        "room_id": draft_start.get("room_id") or "",
        "latched_placement": latch.get("requested") or "",
        "query_placement": latch.get("query") or "",
        "active_placement": latch.get("active") or "",
        "query_checkpoints": query_checkpoints,
        "divergence_vs_proven_harness": divergence,
        "component_name": "solo_countdown_wake",
        "widget_key": ladder.get("key") or "",
        "diagnostic_token": ladder.get("token") or "",
        "callbacks_received": callbacks,
        "session_state_raw_received": hits["session_state_raw_received"],
        "on_change_callback_entry": hits["on_change_callback_entry"],
        "ws_token_samples": ws_tokens[-10:],
        "ws_frame_count": len(ws_frames),
        "streamlit_widget_ids_seen": widget_ids[-12:],
        "widget_registered_at_expiration": bool(mount_ids),
        "rerun_count": int(ladder.get("rerun") or 0),
        "duplicate_token_count": 0,
        "first_missing_stage": python_fail if verdict != "pass" else "",
        "draft_start": draft_start,
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time(), "p2_setup_url": P2_SETUP_URL}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)

        deploy_sha = ""
        draft = execute_solo_draft_start_workflow(page, P2_SETUP_URL, navigate=True)
        report["draft_start"] = draft
        deploy_sha = scrape_live_sha(page) or deploy_sha

        if not draft.get("start_success"):
            report["final"] = finalize_p2(
                deploy_sha=deploy_sha,
                draft_start=draft,
                probe=scrape_ladder_probe(page),
                ws_frames=ws_frames,
                proven_draft=None,
            )
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"artifact": str(OUT), "verdict": report["final"]["verdict"]}, indent=2))
            return 0

        deadline = time.time() + OBSERVE_S
        while time.time() < deadline:
            snap = scrape_ladder_probe(page)
            cb = int((snap.get("ladder") or {}).get("callbacks") or 0)
            passed = (snap.get("ladder") or {}).get("passed") in ("1", "true")
            if cb >= REQUIRED_CYCLES and passed:
                break
            page.wait_for_timeout(1000)

        report["final_probe"] = scrape_ladder_probe(page)
        report["ws_frames"] = ws_frames[-80:]
        deploy_sha = scrape_live_sha(page) or deploy_sha
        browser.close()

    report["final"] = finalize_p2(
        deploy_sha=deploy_sha,
        draft_start=draft,
        probe=report.get("final_probe") or {},
        ws_frames=list(report.get("ws_frames") or ws_frames),
        proven_draft=None,
    )
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "verdict": report["final"]["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
