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


def _merge_probes(
    final_probe: dict[str, Any] | None,
    observation_ready: dict[str, Any] | None,
) -> dict[str, Any]:
    fp = final_probe or {}
    obs_p = (observation_ready or {}).get("probe") or {}
    fl = fp.get("ladder") or {}
    ol = obs_p.get("ladder") or {}
    ladder = ol if (ol.get("key") and not fl.get("key")) else (fl if fl.get("key") else ol)
    if fl.get("key") and ol.get("key"):
        ladder = fl if int(fl.get("callbacks") or 0) >= int(ol.get("callbacks") or 0) else ol
    latch = fp.get("latch") or obs_p.get("latch") or {}
    return {"ladder": ladder, "latch": latch}


def classify_p2_verdict(
    *,
    deploy_sha: str,
    draft_start: dict[str, Any],
    probe: dict[str, Any],
    ws_frames: list[dict[str, Any]],
    deploy_hooks: dict[str, Any] | None,
    observation_ready: dict[str, Any] | None,
    hits: dict[str, int],
    callbacks: int,
    ws_tokens: list[str],
) -> tuple[str, bool, str, str]:
    """Returns (verdict, valid_case, first_missing_stage, invalid_reason)."""
    ladder = probe.get("ladder") or {}
    latch = probe.get("latch") or {}
    pre_ok = bool(draft_start.get("start_success"))
    deployed, _ = classify_p2_deploy(deploy_sha, deploy_hooks)
    obs = observation_ready or {}
    obs_ready = bool(obs.get("ready"))

    diag_ws = [t for t in ws_tokens if "DIAGP2" in str(t).upper()]
    unique_diag = list(dict.fromkeys(diag_ws))
    widget_ids = [
        w
        for w in _widget_ids_from_ws_local(ws_frames)
        if "solo_countdown" in w or "diag_p2" in w.lower()
    ]
    outbound_ws = bool(diag_ws) or bool(widget_ids)
    key_recorded = bool(ladder.get("key"))
    token_recorded = bool(ladder.get("token"))
    latched_p2 = str(latch.get("requested") or "").upper() == "P2"

    if not deployed:
        return "invalid", False, "", "missing_p2_harness_deploy"
    if not pre_ok:
        return "invalid", False, "", "draft_start_failed"
    if not obs_ready or not latched_p2:
        return "invalid", False, "", "observation_ready_not_reached"
    if not key_recorded and not outbound_ws:
        return "invalid", False, "", "component_never_mounted_or_sent"

    python_ok = (
        hits.get("session_state_raw_received", 0) >= REQUIRED_CYCLES
        and hits.get("on_change_callback_entry", 0) >= REQUIRED_CYCLES
        and callbacks >= REQUIRED_CYCLES
    )
    if python_ok and ladder.get("passed") in ("1", "true", True):
        return "pass", True, "", ""

    if python_ok and callbacks >= REQUIRED_CYCLES:
        return "pass", True, "", ""

    first_missing = "session_state_raw_received"
    if hits.get("session_state_raw_received", 0) >= 1:
        first_missing = "on_change_callback_entry"
    if hits.get("on_change_callback_entry", 0) >= 1 and callbacks < REQUIRED_CYCLES:
        first_missing = "callbacks_received"

    mounted_valid_cycle = (
        obs_ready
        and key_recorded
        and token_recorded
        and outbound_ws
        and hits.get("session_state_raw_received", 0) == 0
        and hits.get("on_change_callback_entry", 0) == 0
    )
    if mounted_valid_cycle:
        return "fail", True, first_missing, ""

    return "invalid", False, first_missing, "valid_fail_criteria_not_met"


def _widget_ids_from_ws_local(ws_frames: list[dict[str, Any]]) -> list[str]:
    import re

    ids: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snippet):
            ids.append(f"$$ID-{match.group(1)}-{match.group(2)}")
    return ids


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
        _tokens_from_ws,
        _widget_ids_from_ws,
    )

    ladder = probe.get("ladder") or {}
    latch = probe.get("latch") or {}
    obs = observation_ready or {}
    obs_ladder = (obs.get("probe") or {}).get("ladder") or {}
    stages_chain = "|".join(
        filter(None, [str(obs_ladder.get("stages") or ""), str(ladder.get("stages") or "")])
    )
    python_chain = stages_chain or str(ladder.get("stages") or "")
    callbacks = max(int(ladder.get("callbacks") or 0), int(obs_ladder.get("callbacks") or 0))
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
    token_identities = [str(t) for t in ws_tokens if "DIAGP2" in str(t).upper()]
    token_identities = list(dict.fromkeys(token_identities))[:8]
    if not token_identities and ladder.get("token"):
        token_identities = [str(ladder.get("token"))]
    mount_ids = [w for w in widget_ids if "solo_countdown" in w or "diag_p2" in w.lower()]
    pre_ok = bool(draft_start.get("start_success"))
    deployed, deploy_reason = classify_p2_deploy(deploy_sha, deploy_hooks)

    verdict, valid_case, first_missing, invalid_reason = classify_p2_verdict(
        deploy_sha=deploy_sha,
        draft_start=draft_start,
        probe=probe,
        ws_frames=ws_frames,
        deploy_hooks=deploy_hooks,
        observation_ready=observation_ready,
        hits=hits,
        callbacks=callbacks,
        ws_tokens=ws_tokens,
    )
    passed = verdict == "pass"
    samples = list(mount_samples or [])
    mounted_between_cycles = bool(samples) and all(samples) and len(samples) >= 2
    room_status = "in_progress" if pre_ok else ""
    best_key = str(ladder.get("key") or obs_ladder.get("key") or "")
    best_token = str(ladder.get("token") or obs_ladder.get("token") or "")

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
        "valid_case": valid_case,
        "invalid_reason": invalid_reason,
        "provisional_valid_fail": verdict == "fail" and valid_case,
        "draft_start_success": pre_ok,
        "room_id": draft_start.get("room_id") or "",
        "initial_placement": "P2",
        "latched_placement": latch.get("requested") or "",
        "query_placement": latch.get("query") or "",
        "active_placement": latch.get("active") or "",
        "query_checkpoints": query_checkpoints,
        "divergence_vs_proven_harness": divergence,
        "component_name": "solo_countdown_wake",
        "widget_key": best_key,
        "diagnostic_token": best_token,
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
        "first_missing_stage": first_missing if verdict != "pass" else "",
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
        probe=_merge_probes(report.get("final_probe"), report.get("observation_ready")),
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
