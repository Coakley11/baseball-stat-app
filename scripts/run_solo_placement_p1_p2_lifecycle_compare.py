"""One-cycle P1 vs P2 lifecycle comparison (diagnostic harness only)."""

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
OUT = ROOT / "data" / "solo_placement_p1_p2_lifecycle.json"
POLL_MS = 800
OBSERVE_S = 14


LIFECYCLE_SCRAPE_JS = """() => {
  function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
  let ladder=null, latch=null, expire=null, mount=null;
  const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
  for(const x of roots()){
    const l=x.querySelector('#solo-placement-ladder-diag');
    if(l) ladder={
      placement:l.getAttribute('data-placement')||'',
      key:l.getAttribute('data-key')||'',
      token:l.getAttribute('data-token')||'',
      rerun:l.getAttribute('data-rerun')||'',
      mount_run:l.getAttribute('data-mount-run')||'',
      fragment:l.getAttribute('data-fragment')||'',
      callbacks:l.getAttribute('data-callbacks')||'',
      harness:l.getAttribute('data-p2-harness')||'',
    };
    const t=x.querySelector('#solo-placement-latch-diag');
    if(t) latch={
      requested:t.getAttribute('data-requested')||'',
      query:t.getAttribute('data-query-placement')||'',
      active:t.getAttribute('data-active')||'',
    };
    const e=x.querySelector('#solo-expire-chain');
    if(e) expire={
      owner:e.getAttribute('data-owner')||'',
      chain:e.getAttribute('data-chain')||'',
    };
    const m=x.querySelector('#solo-component-mount-diag');
    if(m) mount={
      key:m.getAttribute('data-key')||'',
      mounted:m.getAttribute('data-mounted')||'',
      diag_timer:m.getAttribute('data-diag-timer')||'',
    };
  }
  return {
    ladder, latch, expire_chain: expire, component_mount: mount,
    has_start_setup: /Start New Live Draft/i.test(text),
    has_pause: /Pause Draft/i.test(text),
    room_id: (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'',
  };
}"""


def _widget_ids_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\\s]+)", snippet):
            ids.append(f"$$ID-{match.group(1)}-{match.group(2)}")
    return ids


def _tokens_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"DIAG[A-Z0-9]+\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
    return tokens


def _analyze_disappearance(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    last_with: dict[str, Any] | None = None
    first_without: dict[str, Any] | None = None
    for row in timeline:
        has_ladder = bool((row.get("dom") or {}).get("ladder"))
        if has_ladder:
            last_with = row
        elif last_with and not first_without:
            first_without = row
    if not last_with or not first_without:
        return {"reason": "no_disappearance_observed", "last_with": last_with, "first_without": first_without}
    dom_after = first_without.get("dom") or {}
    return {
        "reason": "ladder_probe_absent_after_rerun",
        "last_ladder_present_ts": last_with.get("ts"),
        "first_ladder_missing_ts": first_without.get("ts"),
        "at_missing": {
            "has_start_setup": dom_after.get("has_start_setup"),
            "has_pause": dom_after.get("has_pause"),
            "production_wake_owner": (dom_after.get("expire_chain") or {}).get("owner"),
            "component_mount_diag": dom_after.get("component_mount"),
            "latch": dom_after.get("latch"),
        },
        "inferred": (
            "p2_diagnostic_branch_not_re_entered"
            if not dom_after.get("ladder") and dom_after.get("has_start_setup")
            else (
                "production_wake_or_mount_diag_visible"
                if (dom_after.get("expire_chain") or {}).get("owner") == "wake"
                or (dom_after.get("component_mount") or {}).get("diag_timer")
                else "st_stop_truncated_page_without_ladder_rerender"
            )
        ),
    }


def _poll_placement(
    page,
    *,
    placement: str,
    ws_frames: list[dict[str, Any]],
    baseline_ws: int,
) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []
    t0 = time.time()
    mount_widget_ids: list[str] = []
    send_widget_ids: list[str] = []
    reruns_seen: list[str] = []
    while time.time() - t0 < OBSERVE_S:
        dom = page.evaluate(LIFECYCLE_SCRAPE_JS)
        new_frames = ws_frames[baseline_ws:]
        wids = _widget_ids_from_ws(new_frames)
        toks = _tokens_from_ws(new_frames)
        for w in wids:
            if placement == "P1" and "diag_p1" in w.lower():
                if w not in mount_widget_ids:
                    mount_widget_ids.append(w)
            if placement == "P2" and "diag_p2" in w.lower():
                if w not in mount_widget_ids:
                    mount_widget_ids.append(w)
        for w in wids:
            if "solo_countdown" in w and any(t in str(f.get("snippet") or "") for t in toks for f in new_frames):
                send_widget_ids.append(w)
        rr = str((dom.get("ladder") or {}).get("rerun") or "")
        if rr and (not reruns_seen or reruns_seen[-1] != rr):
            reruns_seen.append(rr)
        timeline.append(
            {
                "ts": round(time.time() - t0, 2),
                "dom": dom,
                "ws_tokens_new": toks[-4:],
                "widget_ids_new": [w for w in wids if "solo_countdown" in w or f"diag_{placement.lower()}" in w.lower()][-4:],
            }
        )
        page.wait_for_timeout(POLL_MS)
    disappearance = _analyze_disappearance(timeline)
    ladder_rows = [r for r in timeline if (r.get("dom") or {}).get("ladder")]
    first = ladder_rows[0]["dom"]["ladder"] if ladder_rows else {}
    last = ladder_rows[-1]["dom"]["ladder"] if ladder_rows else {}
    return {
        "placement": placement,
        "observe_s": OBSERVE_S,
        "timeline": timeline,
        "mount_script_run_at_first_ladder": first.get("mount_run") or "",
        "mount_script_run_at_last_ladder": last.get("mount_run") or "",
        "fragment_at_first_ladder": first.get("fragment") or "",
        "fragment_at_last_ladder": last.get("fragment") or "",
        "widget_ids_at_mount": mount_widget_ids,
        "widget_ids_at_outbound_send": list(dict.fromkeys(send_widget_ids)),
        "widget_registered_at_send_inferred": bool(mount_widget_ids)
        and all(w in mount_widget_ids for w in send_widget_ids),
        "component_key": first.get("key") or last.get("key") or "",
        "raw_token": first.get("token") or last.get("token") or "",
        "rerun_values_seen": reruns_seen,
        "rerun_count_delta": max(0, len(reruns_seen) - 1) if reruns_seen else 0,
        "ladder_disappearance": disappearance,
        "production_wake_replaced_diag": any(
            (r.get("dom") or {}).get("expire_chain", {}) and (r.get("dom") or {}).get("expire_chain", {}).get("owner") == "wake"
            and not (r.get("dom") or {}).get("ladder")
            for r in timeline
        ),
        "st_stop_inferred": any(
            not (r.get("dom") or {}).get("ladder")
            and not (r.get("dom") or {}).get("has_pause")
            and (r.get("dom") or {}).get("latch")
            for r in timeline[1:]
        ),
        "latched_on_every_poll": [
            {
                "ts": r["ts"],
                "requested": ((r.get("dom") or {}).get("latch") or {}).get("requested"),
                "active": ((r.get("dom") or {}).get("latch") or {}).get("active"),
                "ladder_present": bool((r.get("dom") or {}).get("ladder")),
            }
            for r in timeline
        ],
    }


def run_p1(page, ws_frames: list[dict[str, Any]]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import scrape_live_sha
    from solo_draft_start_harness import click_sidebar_for_ldr, maybe_clear_stale_draft

    url = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        "&solo_delivery_diag=1&solo_placement_ladder=P1"
        "&solo_component_diag=1&solo_diag_timer=10"
    )
    baseline = len(ws_frames)
    goto_and_wake(page, url, timeout_s=240)
    page.wait_for_timeout(5000)
    click_sidebar_for_ldr(page, settle_ms=6000)
    maybe_clear_stale_draft(page, [])
    page.wait_for_timeout(2000)
    sha = scrape_live_sha(page)
    poll = _poll_placement(page, placement="P1", ws_frames=ws_frames, baseline_ws=baseline)
    poll["deploy_sha"] = sha
    poll["setup_url"] = url
    poll["draft_started"] = False
    return poll


def run_p2(page, ws_frames: list[dict[str, Any]]) -> dict[str, Any]:
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_placement_p2_gate import P2_SETUP_URL, wait_p2_observation_ready
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    baseline = len(ws_frames)
    draft = execute_solo_draft_start_workflow(page, P2_SETUP_URL, navigate=True)
    obs = wait_p2_observation_ready(page, max_wait_s=45)
    poll = _poll_placement(page, placement="P2", ws_frames=ws_frames, baseline_ws=baseline)
    poll["deploy_sha"] = scrape_live_sha(page)
    poll["setup_url"] = P2_SETUP_URL
    poll["draft_started"] = bool(draft.get("start_success"))
    poll["room_id"] = draft.get("room_id") or ""
    poll["observation_ready"] = obs
    return poll


def _diff_summary(p1: dict[str, Any], p2: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_concrete_boundary": (
            "P2 enters in-draft pre-owner mount with st.stop(); P1 mounts at LDR entry without draft start"
            if p1.get("draft_started") is False and p2.get("draft_started")
            else "placement_entry_path"
        ),
        "p1_fragment": p1.get("fragment_at_first_ladder"),
        "p2_fragment": p2.get("fragment_at_first_ladder"),
        "p1_mount_run": p1.get("mount_script_run_at_first_ladder"),
        "p2_mount_run": p2.get("mount_script_run_at_last_ladder"),
        "p1_ladder_stable": len([r for r in p1.get("timeline", []) if (r.get("dom") or {}).get("ladder")]) > 3,
        "p2_ladder_stable": len([r for r in p2.get("timeline", []) if (r.get("dom") or {}).get("ladder")]) > 3,
        "p2_disappearance": p2.get("ladder_disappearance"),
        "issue_a_first_expiration": (
            "WS outbound DIAGP2 observed with session_state_raw_received=0 (same on P1 if WS without Python)"
        ),
        "issue_b_probe_loss": p2.get("ladder_disappearance", {}).get("inferred"),
        "same_lifecycle_cause": (
            p2.get("ladder_disappearance", {}).get("inferred")
            == "st_stop_truncated_page_without_ladder_rerender"
            and not p2.get("production_wake_replaced_diag")
        ),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {"started_at": time.time()}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)
        report["p1"] = run_p1(page, ws_frames)
        page.wait_for_timeout(3000)
        report["p2"] = run_p2(page, ws_frames)
        browser.close()
    report["comparison"] = _diff_summary(report["p1"], report["p2"])
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
