"""Paired bridge-transition Cloud run — Control A vs Control B at early LDR."""

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
OBSERVATION_S = 36
OUT = ROOT / "data" / "solo_bridge_transition_paired.json"

SCRAPE_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  let trans = null;
  let client = null;
  let chain = null;
  const alerts = [];
  const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
  for (const root of roots()) {
    const t = root.querySelector('#solo-bridge-transition-diag');
    if (t) trans = {
      control: t.getAttribute('data-control')||'',
      key: t.getAttribute('data-key')||'',
      phase: t.getAttribute('data-phase')||'',
      actionable: t.getAttribute('data-actionable')||'',
      token: t.getAttribute('data-token')||'',
      deadline: t.getAttribute('data-deadline')||'',
      expected_expire_token: t.getAttribute('data-expected-expire-token')||'',
      token_before: t.getAttribute('data-token-before')||'',
      deadline_before: t.getAttribute('data-deadline-before')||'',
      token_after: t.getAttribute('data-token-after')||'',
      deadline_after: t.getAttribute('data-deadline-after')||'',
      args_before: t.getAttribute('data-args-before')||'',
      args_after: t.getAttribute('data-args-after')||'',
      room_status: t.getAttribute('data-room-status')||'',
      room_id: t.getAttribute('data-room-id')||'',
      matching_on_change_count: t.getAttribute('data-matching-on-change-count')||'',
      matching_raw_count: t.getAttribute('data-matching-raw-count')||'',
      stages: t.getAttribute('data-stages')||'',
      post_activation: t.getAttribute('data-post-activation')||'',
      room_status_log: t.getAttribute('data-room-status-log')||'',
    };
    const c = root.querySelector('#solo-expire-client');
    if (c) client = {
      last: c.getAttribute('data-last')||'',
      chain: c.getAttribute('data-chain')||'',
      remounts: c.getAttribute('data-remounts')||'',
      deadline: c.getAttribute('data-deadline')||'',
      token: c.getAttribute('data-token')||'',
      remaining_ms: c.getAttribute('data-remaining-ms')||'',
    };
    const ch = root.querySelector('#solo-expire-chain');
    if (ch) chain = { last: ch.getAttribute('data-last')||'', chain: ch.getAttribute('data-chain')||'', owner: ch.getAttribute('data-owner')||'' };
    for (const el of root.querySelectorAll('[data-testid=\"stAlert\"], .stException')) {
      const a = String(el.innerText||'').replace(/\\s+/g,' ').trim();
      if (a) alerts.push(a.slice(0,400));
    }
  }
  const has_pause = /Pause Draft/i.test(text);
  const setup_lobby = /Start New Live Draft/i.test(text) && /Draft Setup|Draft Mode/i.test(text);
  const active_room = has_pause || /Solo live draft started/i.test(text) || /End\\/Delete Draft/i.test(text);
  const lobby_only = setup_lobby && !active_room;
  const room_id = (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'';
  const end_delete = (text.match(/End\\/Delete Draft/gi)||[]).length;
  return { trans, client, chain, text_snippet: text.slice(0,1200), alerts: [...new Set(alerts)].slice(0,6), lobby_only, active_room, has_pause, room_id, end_delete_visible: end_delete };
}"""


def setup_url(control: str) -> str:
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_delivery_diag=1"
        f"&solo_bridge_transition={control}"
        f"&solo_component_diag=1"
        f"&solo_diag_timer=10"
    )


def _widget_ids_from_ws(ws_frames: list[dict[str, Any]], key_sub: str) -> tuple[str, str]:
    mount_id = ""
    send_id = ""
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\s]+)", snippet):
            wid = f"$$ID-{match.group(1)}-{match.group(2)}"
            if key_sub.lower() in wid.lower() or "solo_persistent" in wid.lower():
                if not mount_id:
                    mount_id = wid
                send_id = wid
    if mount_id and not send_id:
        send_id = mount_id
    return mount_id, send_id


def _stages(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _count_matching_stages(stages: str, expected: str) -> dict[str, int]:
    if not expected:
        return {"matching_on_change": 0, "matching_raw": 0}
    oc = stages.count("on_change_callback_entry_matching_token")
    raw = stages.count("session_state_raw_received_matching_token")
    return {"matching_on_change": oc, "matching_raw": raw}


def _classify_control(
    *,
    draft_ok: bool,
    returned_to_setup: bool,
    setup_return_detail: dict[str, Any],
    room_latch_ok: bool,
    post_activation_seen: bool,
    expected_token: str,
    client: dict[str, Any],
    matching: dict[str, int],
) -> tuple[str, str]:
    if not draft_ok:
        return "INVALID", "draft_start_failed"
    if returned_to_setup:
        return "INVALID", "returned_to_setup_lobby_during_observation"
    if not room_latch_ok:
        return "INVALID", "latched_room_id_not_stable_in_progress"
    if not post_activation_seen:
        return "INVALID", "post_activation_timer_never_armed"
    if not expected_token:
        return "INVALID", "expected_expire_token_missing"
    cs = _stages(str(client.get("chain") or ""))
    if "browser_deadline_crossed" not in cs or "component_value_sent" not in cs:
        return "FAIL", "no_browser_zero_crossing_after_activation"
    if matching.get("matching_on_change", 0) >= 1 and matching.get("matching_raw", 0) >= 1:
        return "PASS", ""
    if "component_value_sent" in cs:
        return "FAIL", "client_sent_no_matching_token_on_change"
    return "FAIL", "no_browser_zero_crossing_after_activation"


def _setup_return_reason(snapshots: list[dict[str, Any]]) -> str:
    if not snapshots:
        return ""
    last = snapshots[-1]
    alerts = last.get("alerts") or []
    if alerts:
        return str(alerts[0])[:500]
    if last.get("end_delete_visible"):
        return "setup_lobby_visible_with_end_delete_control"
    return "two_consecutive_lobby_only_samples_after_in_progress"


def _interpret(a_verdict: str, b_verdict: str) -> dict[str, str]:
    if a_verdict == "INVALID" or b_verdict == "INVALID":
        if a_verdict == "INVALID":
            return {
                "conclusion": "invalid_harness_or_control_a",
                "detail": "Control A invalid — fix harness or re-establish baseline before production changes.",
            }
        return {
            "conclusion": "invalid_harness_control_b",
            "detail": "Control B invalid — room or post-activation observation failed.",
        }
    if a_verdict == "PASS" and b_verdict in ("FAIL", "VALID_FAIL"):
        return {
            "conclusion": "actionable_transition_defect",
            "detail": "Only difference is actionable false→true; same key and post-activation token.",
        }
    if a_verdict == "PASS" and b_verdict == "PASS":
        return {
            "conclusion": "production_renderer_delta",
            "detail": "Paired mount delivers for both; production differs outside this diagnostic.",
        }
    if a_verdict in ("FAIL", "VALID_FAIL"):
        return {
            "conclusion": "reestablish_bridge_control",
            "detail": "Control A did not pass — re-establish bridge baseline before production changes.",
        }
    return {"conclusion": "inconclusive", "detail": f"A={a_verdict}, B={b_verdict}"}


def _delivery_verdict_label(base: str) -> str:
    if base == "FAIL":
        return "VALID_FAIL"
    return base


def run_one_control(page, control: str, ws_frames: list[dict[str, Any]]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import clear_stale_solo_draft
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = setup_url(control)
    ws_baseline = len(ws_frames)

    goto_and_wake(page, url, timeout_s=240)
    clear_stale_solo_draft(page)

    draft = execute_solo_draft_start_workflow(page, url, navigate=False)
    draft_ok = bool(draft.get("start_success"))
    latched_room_id = str(draft.get("room_id") or "").strip().upper()

    widget_before, _ = _widget_ids_from_ws(ws_frames[ws_baseline:], "solo_persistent")

    t0 = time.time()
    samples: list[dict[str, Any]] = []
    was_in_progress = False
    consecutive_lobby = 0
    returned_to_setup = False
    setup_return_snapshots: list[dict[str, Any]] = []
    post_activation_seen = False
    room_id_mismatches: list[dict[str, Any]] = []

    while time.time() - t0 < OBSERVATION_S:
        snap = page.evaluate(SCRAPE_JS)
        snap["elapsed_s"] = round(time.time() - t0, 1)
        probe = dict(snap.get("trans") or {})
        if probe.get("post_activation") in ("1", "true") or probe.get("expected_expire_token"):
            post_activation_seen = True
        page_room = str(snap.get("room_id") or probe.get("room_id") or "").strip().upper()
        if snap.get("has_pause") or snap.get("active_room"):
            was_in_progress = True
            consecutive_lobby = 0
        elif was_in_progress:
            consecutive_lobby += 1
            setup_return_snapshots.append(
                {
                    "elapsed_s": snap["elapsed_s"],
                    "alerts": snap.get("alerts") or [],
                    "page_room_id": page_room,
                    "latched_room_id": latched_room_id,
                    "end_delete_visible": snap.get("end_delete_visible"),
                    "text_snippet": str(snap.get("text_snippet") or "")[:500],
                }
            )
        else:
            consecutive_lobby = 0
        if latched_room_id and page_room and page_room != latched_room_id:
            room_id_mismatches.append(
                {"elapsed_s": snap["elapsed_s"], "latched": latched_room_id, "seen": page_room}
            )
        if consecutive_lobby >= 2:
            returned_to_setup = True
        samples.append(snap)
        page.wait_for_timeout(2000)

    final = page.evaluate(SCRAPE_JS)
    client = dict(final.get("client") or {})
    probe = dict(final.get("trans") or {})
    delivery_stages = str(probe.get("stages") or "")
    expected_token = str(probe.get("expected_expire_token") or probe.get("token_after") or "")
    matching = _count_matching_stages(delivery_stages, expected_token)
    matching["matching_on_change"] = max(
        matching["matching_on_change"], int(probe.get("matching_on_change_count") or 0)
    )
    matching["matching_raw"] = max(matching["matching_raw"], int(probe.get("matching_raw_count") or 0))

    new_ws = ws_frames[ws_baseline:]
    widget_after, widget_send = _widget_ids_from_ws(new_ws, "solo_persistent")

    room_latch_ok = bool(
        draft_ok
        and latched_room_id
        and was_in_progress
        and not returned_to_setup
        and not room_id_mismatches
    )

    verdict, reason = _classify_control(
        draft_ok=draft_ok,
        returned_to_setup=returned_to_setup,
        setup_return_detail=setup_return_snapshots[-1] if setup_return_snapshots else {},
        room_latch_ok=room_latch_ok,
        post_activation_seen=post_activation_seen,
        expected_token=expected_token,
        client=client,
        matching=matching,
    )
    verdict = _delivery_verdict_label(verdict)

    client_token = str(client.get("token") or "")
    session_state_matches = client_token == expected_token and "component_value_sent" in _stages(
        client.get("chain") or ""
    )

    return {
        "control": control,
        "url": url,
        "draft_start": draft,
        "latched_room_id": latched_room_id,
        "room_id_stable": room_latch_ok and not room_id_mismatches,
        "verdict": verdict,
        "invalid_reason": reason if verdict == "INVALID" else "",
        "fail_reason": reason if verdict in ("FAIL", "VALID_FAIL") else "",
        "returned_to_setup_during_observation": returned_to_setup,
        "setup_return_reason": _setup_return_reason(setup_return_snapshots),
        "setup_return_evidence": setup_return_snapshots[-3:] if setup_return_snapshots else [],
        "room_id_mismatches": room_id_mismatches,
        "was_in_progress": was_in_progress,
        "post_activation_seen": post_activation_seen,
        "component_key": probe.get("key") or "solo_countdown_wake_solo_persistent",
        "expected_expire_token": expected_token,
        "args_before_activation": probe.get("args_before") or "",
        "args_after_activation": probe.get("args_after") or "",
        "token_before_start": probe.get("token_before") or "",
        "token_after_activation": probe.get("token_after") or probe.get("token") or "",
        "widget_id_before_activation": widget_before,
        "widget_id_after_activation": widget_after,
        "widget_id_at_expiration_frame": widget_send,
        "widget_id_changed_inert_to_active": bool(
            widget_before and widget_after and widget_before != widget_after
        ),
        "client_remount_count": int(client.get("remounts") or 0),
        "client_chain_final": client.get("chain") or "",
        "browser_deadline_crossed": "browser_deadline_crossed" in _stages(client.get("chain") or ""),
        "component_value_sent": "component_value_sent" in _stages(client.get("chain") or ""),
        "client_token_at_cross": client_token,
        "session_state_raw_matches_expected_token": session_state_matches,
        "matching_on_change_count": matching["matching_on_change"],
        "matching_raw_count": matching["matching_raw"],
        "duplicate_matching_callbacks": matching["matching_on_change"] > 1 or matching["matching_raw"] > 1,
        "room_status_log": probe.get("room_status_log") or "",
        "samples_count": len(samples),
        "ws_frame_count": len(new_ws),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "observation_seconds": OBSERVATION_S,
        "design": "placeholder_deadline_at_setup_same_10s_token_after_in_progress",
        "production_flush_disabled": True,
        "controls": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        report["deploy_sha"] = ""
        for control in ("A", "B"):
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
            page = context.new_page()
            install_ws_and_postmessage_hooks(page, ws_frames)
            result = run_one_control(page, control, ws_frames)
            if not report["deploy_sha"]:
                report["deploy_sha"] = scrape_live_sha(page)
            report["controls"][control] = result
            context.close()
        browser.close()

    a_v = str(report["controls"].get("A", {}).get("verdict") or "")
    b_v = str(report["controls"].get("B", {}).get("verdict") or "")
    report["interpretation"] = _interpret(a_v, b_v)
    ca = report["controls"].get("A") or {}
    cb = report["controls"].get("B") or {}
    diff: dict[str, Any] = {}
    for field in (
        "expected_expire_token",
        "args_before_activation",
        "args_after_activation",
        "widget_id_before_activation",
        "widget_id_after_activation",
        "widget_id_changed_inert_to_active",
        "browser_deadline_crossed",
        "component_value_sent",
        "matching_on_change_count",
        "post_activation_seen",
    ):
        if ca.get(field) != cb.get(field):
            diff[field] = {"A": ca.get(field), "B": cb.get(field)}
    report["first_concrete_difference"] = diff
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(OUT),
                "interpretation": report["interpretation"],
                "A": a_v,
                "B": b_v,
                "diff": diff,
            },
            indent=2,
        )
    )
    return 0 if a_v != "INVALID" and b_v != "INVALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
