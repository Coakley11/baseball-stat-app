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


def classify_p2_deploy(deploy_sha: str, hooks: dict[str, Any] | None) -> tuple[bool, str]:
    """P2 harness is live when latch + stable in-draft stop shipped (bca439f+)."""
    _ = deploy_sha
    h = hooks or {}
    if h.get("p2_harness_v2") and h.get("latch_probe_present"):
        return True, "latch_and_harness_v2"
    if h.get("latch_probe_present"):
        return True, "latch_probe"
    return False, "missing_p2_harness_deploy"


def scrape_p2_deploy_hooks(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
          let latch=false, harnessV2=false;
          for(const x of roots()){
            if(x&&x.querySelector('#solo-placement-latch-diag')) latch=true;
            const l=x&&x.querySelector('#solo-placement-ladder-diag');
            if(l && l.getAttribute('data-p2-harness')==='v2') harnessV2=true;
          }
          return {latch_probe_present: latch, p2_harness_v2: harnessV2};
        }"""
    )


def wait_p2_observation_ready(page, *, max_wait_s: int = 45) -> dict[str, Any]:
    """Require ladder P2 mounted with key+token before the 4-cycle soak."""
    deadline = time.time() + max_wait_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        snap = scrape_ladder_probe(page)
        last = snap
        ladder = snap.get("ladder") or {}
        latch = snap.get("latch") or {}
        if (
            str(ladder.get("placement") or "").upper() == "P2"
            and ladder.get("key")
            and ladder.get("token")
            and str(latch.get("requested") or "").upper() in ("P2", "")
        ):
            return {"ready": True, "probe": snap, "wait_s": round(max_wait_s - (deadline - time.time()), 1)}
        page.wait_for_timeout(1000)
    return {"ready": False, "probe": last, "wait_s": max_wait_s}


def compare_query_checkpoints(
    p2_checkpoints: list[dict[str, Any]],
    proven_checkpoints: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not proven_checkpoints:
        return None
    p2_by_step = {c.get("step"): c for c in p2_checkpoints if str(c.get("step", "")).startswith("query_")}
    prov_by_step = {c.get("step"): c for c in proven_checkpoints if str(c.get("step", "")).startswith("query_")}
    for step in (
        "query_initial_url",
        "query_after_sidebar",
        "query_before_start",
        "query_after_start_click",
        "query_first_rerun_after_start",
        "query_in_progress_room",
    ):
        p2_row = p2_by_step.get(step)
        pr_row = prov_by_step.get(step)
        if pr_row and not p2_row:
            return {"first_divergence": step, "kind": "missing_on_p2", "proven": pr_row}
        if p2_row and pr_row:
            if bool(p2_row.get("query_ok_vs_setup")) != bool(pr_row.get("query_ok_vs_setup")):
                return {
                    "first_divergence": step,
                    "kind": "query_ok_mismatch",
                    "p2": p2_row,
                    "proven": pr_row,
                }
    return {"first_divergence": None, "kind": "aligned_on_recorded_steps"}


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
    deploy_hooks: dict[str, Any] | None = None,
    observation_ready: dict[str, Any] | None = None,
    mount_samples: list[bool] | None = None,
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
    token_identities = [str(t) for t in ws_tokens if "DIAGP2" in str(t).upper()][:8]
    if not token_identities and ladder.get("token"):
        token_identities = [str(ladder.get("token"))]
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
    deployed, deploy_reason = classify_p2_deploy(deploy_sha, deploy_hooks)
    obs = observation_ready or {}
    valid = (
        pre_ok
        and deployed
        and bool(obs.get("ready"))
        and bool(ladder.get("placement") == "P2" or latch.get("requested") == "P2")
        and bool(ladder.get("key"))
        and python_ok
    )
    passed = valid and callbacks >= REQUIRED_CYCLES and ladder.get("passed") in ("1", "true", True)
    verdict = "pass" if passed else ("fail" if valid else "invalid")
    samples = list(mount_samples or [])
    mounted_between_cycles = bool(samples) and all(samples) and len(samples) >= 2
    room_status = "in_progress" if pre_ok else ""

    query_checkpoints = [
        c for c in (draft_start.get("checkpoints") or []) if str(c.get("step", "")).startswith("query_")
    ]
    divergence = None
    if proven_draft:
        divergence = compare_query_checkpoints(
            query_checkpoints,
            [c for c in (proven_draft.get("checkpoints") or []) if str(c.get("step", "")).startswith("query_")],
        )
    elif not pre_ok:
        divergence = {"note": "proven_compare_not_run_start_failed"}

    return {
        "deploy_sha": deploy_sha,
        "p2_harness_deployed": deployed,
        "p2_harness_deploy_reason": deploy_reason,
        "observation_ready": obs,
        "setup_url": P2_SETUP_URL,
        "verdict": verdict,
        "valid_case": valid,
        "draft_start_success": pre_ok,
        "room_id": draft_start.get("room_id") or "",
        "initial_placement": "P2",
        "latched_placement": latch.get("requested") or "",
        "query_placement": latch.get("query") or "",
        "active_placement": latch.get("active") or "",
        "query_checkpoints": query_checkpoints,
        "divergence_vs_proven_harness": divergence,
        "component_name": "solo_countdown_wake",
        "widget_key": ladder.get("key") or "",
        "diagnostic_token": ladder.get("token") or "",
        "token_identities": token_identities,
        "callbacks_received_out_of_4": callbacks,
        "callbacks_received": callbacks,
        "session_state_raw_received": hits["session_state_raw_received"],
        "on_change_callback_entry": hits["on_change_callback_entry"],
        "ws_token_samples": ws_tokens[-10:],
        "ws_frame_count": len(ws_frames),
        "streamlit_widget_ids_seen": widget_ids[-12:],
        "widget_registered_at_expiration": bool(mount_ids),
        "rerun_count": int(ladder.get("rerun") or 0),
        "duplicate_token_count": 0,
        "diagnostic_mounted_between_cycles": mounted_between_cycles,
        "ladder_mount_sample_count": len(samples),
        "active_room_status": room_status,
        "first_missing_stage": python_fail if verdict != "pass" else "",
        "artifact_path": str(OUT),
        "draft_start": draft_start,
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time(), "p2_setup_url": P2_SETUP_URL}

    proven_draft: dict[str, Any] | None = None
    proven_path = ROOT / "data" / "solo_draft_start_harness_proven.json"
    if proven_path.is_file():
        try:
            proven_blob = json.loads(proven_path.read_text(encoding="utf-8"))
            if isinstance(proven_blob.get("last_success"), dict):
                proven_draft = proven_blob["last_success"]
        except (json.JSONDecodeError, OSError):
            proven_draft = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)

        deploy_sha = ""
        draft = execute_solo_draft_start_workflow(page, P2_SETUP_URL, navigate=True)
        report["draft_start"] = draft
        deploy_sha = scrape_live_sha(page) or deploy_sha
        deploy_hooks = scrape_p2_deploy_hooks(page)
        report["deploy_hooks_after_start"] = deploy_hooks

        if not draft.get("start_success"):
            report["final"] = finalize_p2(
                deploy_sha=deploy_sha,
                draft_start=draft,
                probe=scrape_ladder_probe(page),
                ws_frames=ws_frames,
                proven_draft=proven_draft,
                deploy_hooks=deploy_hooks,
            )
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"artifact": str(OUT), "verdict": report["final"]["verdict"]}, indent=2))
            return 0

        obs_ready = wait_p2_observation_ready(page)
        report["observation_ready"] = obs_ready
        if not obs_ready.get("ready"):
            report["final_probe"] = obs_ready.get("probe") or scrape_ladder_probe(page)
            report["ws_frames"] = ws_frames[-80:]
            deploy_sha = scrape_live_sha(page) or deploy_sha
            browser.close()
            report["final"] = finalize_p2(
                deploy_sha=deploy_sha,
                draft_start=draft,
                probe=report.get("final_probe") or {},
                ws_frames=list(report.get("ws_frames") or ws_frames),
                proven_draft=proven_draft,
                deploy_hooks=deploy_hooks,
                observation_ready=obs_ready,
            )
            report["finished_at"] = time.time()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"artifact": str(OUT), "verdict": report["final"]["verdict"]}, indent=2))
            return 0

        deadline = time.time() + OBSERVE_S
        mount_samples: list[bool] = []
        while time.time() < deadline:
            snap = scrape_ladder_probe(page)
            mount_samples.append(bool((snap.get("ladder") or {}).get("placement") == "P2"))
            cb = int((snap.get("ladder") or {}).get("callbacks") or 0)
            passed = (snap.get("ladder") or {}).get("passed") in ("1", "true")
            if cb >= REQUIRED_CYCLES and passed:
                break
            page.wait_for_timeout(1000)

        report["final_probe"] = scrape_ladder_probe(page)
        report["mount_samples"] = mount_samples
        report["ws_frames"] = ws_frames[-80:]
        deploy_sha = scrape_live_sha(page) or deploy_sha
        browser.close()

    report["final"] = finalize_p2(
        deploy_sha=deploy_sha,
        draft_start=draft,
        probe=report.get("final_probe") or {},
        ws_frames=list(report.get("ws_frames") or ws_frames),
        proven_draft=proven_draft,
        deploy_hooks=report.get("deploy_hooks_after_start"),
        observation_ready=report.get("observation_ready"),
        mount_samples=list(report.get("mount_samples") or []),
    )
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "verdict": report["final"]["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
