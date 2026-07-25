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
  const iframes = [];
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
      token_before: t.getAttribute('data-token-before')||'',
      deadline_before: t.getAttribute('data-deadline-before')||'',
      token_after: t.getAttribute('data-token-after')||'',
      deadline_after: t.getAttribute('data-deadline-after')||'',
      args_before: t.getAttribute('data-args-before')||'',
      args_after: t.getAttribute('data-args-after')||'',
      room_status: t.getAttribute('data-room-status')||'',
      room_id: t.getAttribute('data-room-id')||'',
      on_change_count: t.getAttribute('data-on-change-count')||'',
      stages: t.getAttribute('data-stages')||'',
      widget_id_before: t.getAttribute('data-widget-id-before')||'',
      widget_id_after: t.getAttribute('data-widget-id-after')||'',
      client_remounts: t.getAttribute('data-client-remounts')||'',
      same_key: t.getAttribute('data-same-key')||'',
      token_unchanged: t.getAttribute('data-token-unchanged')||'',
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
    if (ch) chain = {
      last: ch.getAttribute('data-last')||'',
      chain: ch.getAttribute('data-chain')||'',
      owner: ch.getAttribute('data-owner')||'',
    };
    for (const f of root.querySelectorAll('iframe')) {
      try {
        iframes.push({ src: (f.src||'').slice(0,500), path: f.getAttribute('data-testid')||'' });
      } catch(e){}
    }
  }
  const setup_lobby = /Start New Live Draft/i.test(text) && !/Pause Draft/i.test(text) && /Draft Setup/i.test(text);
  const active_room = /Pause Draft/i.test(text) || /Solo live draft started/i.test(text);
  return { trans, client, chain, iframes, text_len: text.length, setup_lobby: setup_lobby && !active_room, active_room, room_id: (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'' };
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
        if key_sub in snippet and "solo_countdown_wake" in snippet:
            for match in re.finditer(r"\$\$ID-([a-f0-9-]+)-([^\\\"'\s]+)", snippet):
                wid = f"$$ID-{match.group(1)}-{match.group(2)}"
                send_id = wid
    if mount_id and not send_id:
        send_id = mount_id
    return mount_id, send_id


def _stages(chain: str) -> set[str]:
    return {p for p in str(chain or "").split("|") if p}


def _classify_control(
    control: str,
    *,
    draft_ok: bool,
    returned_to_setup: bool,
    probe: dict[str, Any],
    client: dict[str, Any],
    delivery_stages: str,
) -> tuple[str, str]:
    if not draft_ok:
        return "INVALID", "draft_start_failed"
    if returned_to_setup:
        return "INVALID", "returned_to_setup_lobby_during_observation"
    client_chain = str(client.get("chain") or "")
    cs = _stages(client_chain)
    ds = _stages(delivery_stages)
    oc = delivery_stages.count("on_change_callback_entry")
    raw = delivery_stages.count("session_state_raw_received")
    if "browser_deadline_crossed" not in cs and "component_value_sent" not in cs:
        if not probe.get("token"):
            return "INVALID", "probe_never_mounted"
        return "FAIL", "no_browser_zero_crossing"
    if "component_value_sent" in cs and raw >= 1 and oc >= 1:
        return "PASS", ""
    if "component_value_sent" in cs and (raw == 0 and oc == 0):
        return "FAIL", "client_sent_no_python_on_change"
    return "INCONCLUSIVE", "partial_chain"


def _interpret(a_verdict: str, b_verdict: str) -> dict[str, str]:
    if a_verdict == "INVALID":
        return {
            "conclusion": "reestablish_bridge_control",
            "detail": "Control A invalid — original bridge baseline not reproducible in this harness.",
        }
    if a_verdict == "PASS" and b_verdict == "FAIL":
        return {
            "conclusion": "inert_to_active_transition_defect",
            "detail": "Stable key insufficient; inert→active argument change or component replacement breaks delivery.",
        }
    if a_verdict == "PASS" and b_verdict == "PASS":
        return {
            "conclusion": "production_renderer_delta",
            "detail": "Transition is not the sole defect — compare production renderer/surrounding code outside this paired mount.",
        }
    if a_verdict == "FAIL" and b_verdict == "FAIL":
        return {
            "conclusion": "shared_delivery_failure",
            "detail": "Both controls fail delivery — inspect shared early LDR path or Cloud harness.",
        }
    return {
        "conclusion": "inconclusive",
        "detail": f"Control A={a_verdict}, Control B={b_verdict} — refine harness or extend observation.",
    }


def run_one_control(
    page,
    control: str,
    ws_frames: list[dict[str, Any]],
) -> dict[str, Any]:
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = setup_url(control)
    ws_baseline = len(ws_frames)

    draft = execute_solo_draft_start_workflow(page, url, navigate=True)
    draft_ok = bool(draft.get("start_success"))

    pre = page.evaluate(SCRAPE_JS)
    widget_before = ""
    new_ws_pre = ws_frames[ws_baseline:]
    widget_before, _ = _widget_ids_from_ws(new_ws_pre, "solo_persistent")

    t0 = time.time()
    samples: list[dict[str, Any]] = []
    was_active = False
    returned_to_setup = False

    def _in_setup_lobby(text: str) -> bool:
        active = "Pause Draft" in text or "Solo live draft started" in text
        return (
            not active
            and "Start New Live Draft" in text
            and ("Draft Setup" in text or "Draft Mode" in text)
        )

    while time.time() - t0 < OBSERVATION_S:
        snap = page.evaluate(SCRAPE_JS)
        snap["elapsed_s"] = round(time.time() - t0, 1)
        samples.append(snap)
        if snap.get("active_room"):
            was_active = True
        if was_active and snap.get("setup_lobby"):
            returned_to_setup = True
        page.wait_for_timeout(2000)

    final = page.evaluate(SCRAPE_JS)
    client = dict(final.get("client") or {})
    probe = dict(final.get("trans") or {})
    chain = dict(final.get("chain") or {})
    new_ws = ws_frames[ws_baseline:]
    widget_mount, widget_send = _widget_ids_from_ws(new_ws, "solo_persistent")

    delivery_stages = str(probe.get("stages") or "")
    verdict, reason = _classify_control(
        control,
        draft_ok=draft_ok,
        returned_to_setup=returned_to_setup,
        probe=probe,
        client=client,
        delivery_stages=delivery_stages,
    )

    pre_trans = dict(pre.get("trans") or {})
    token_before = probe.get("token_before") or pre_trans.get("token") or ""
    token_after = probe.get("token_after") or probe.get("token") or ""
    wid_before = widget_before or probe.get("widget_id_before") or ""
    wid_after = widget_mount or probe.get("widget_id_after") or ""

    return {
        "control": control,
        "url": url,
        "draft_start": draft,
        "verdict": verdict,
        "invalid_reason": reason if verdict == "INVALID" else "",
        "fail_reason": reason if verdict == "FAIL" else "",
        "returned_to_setup_during_observation": returned_to_setup,
        "was_active_room": was_active,
        "component_key": probe.get("key") or "solo_countdown_wake_solo_persistent",
        "token_before_start": token_before,
        "deadline_before_start": probe.get("deadline_before") or pre_trans.get("deadline") or "",
        "token_after_activation": token_after,
        "deadline_after_activation": probe.get("deadline_after") or probe.get("deadline") or "",
        "args_before_activation": probe.get("args_before") or "",
        "args_after_activation": probe.get("args_after") or "",
        "token_unchanged_control_a": probe.get("token_unchanged") in ("1", "true"),
        "widget_id_before_activation": wid_before,
        "widget_id_after_activation": wid_after,
        "widget_id_at_send": widget_send,
        "widget_id_changed_inert_to_active": bool(wid_before and wid_after and wid_before != wid_after),
        "client_remount_count": int(client.get("remounts") or 0),
        "client_chain_final": client.get("chain") or "",
        "browser_deadline_crossed": "browser_deadline_crossed" in _stages(client.get("chain") or ""),
        "component_value_sent": "component_value_sent" in _stages(client.get("chain") or ""),
        "session_state_raw_count": delivery_stages.count("session_state_raw_received"),
        "on_change_count": int(probe.get("on_change_count") or 0) or delivery_stages.count("on_change_callback_entry"),
        "server_chain_final": chain.get("chain") or "",
        "room_status_final": probe.get("room_status") or "",
        "room_status_log": probe.get("room_status_log") or "",
        "iframe_snapshots": final.get("iframes") or [],
        "samples_count": len(samples),
        "ws_frame_count": len(new_ws),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "observation_seconds": OBSERVATION_S,
        "production_flush_disabled": True,
        "controls": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

        report["deploy_sha"] = ""
        for control in ("A", "B"):
            page = browser.new_page(viewport={"width": 1440, "height": 1400})
            install_ws_and_postmessage_hooks(page, ws_frames)
            result = run_one_control(page, control, ws_frames)
            if not report["deploy_sha"]:
                report["deploy_sha"] = scrape_live_sha(page)
            report["controls"][control] = result
            page.close()
        browser.close()

    a_v = str(report["controls"].get("A", {}).get("verdict") or "")
    b_v = str(report["controls"].get("B", {}).get("verdict") or "")
    report["interpretation"] = _interpret(a_v, b_v)
    diff: dict[str, Any] = {}
    ca = report["controls"].get("A") or {}
    cb = report["controls"].get("B") or {}
    for field in (
        "token_before_start",
        "token_after_activation",
        "widget_id_before_activation",
        "widget_id_after_activation",
        "widget_id_changed_inert_to_active",
        "client_remount_count",
        "browser_deadline_crossed",
        "component_value_sent",
        "on_change_count",
    ):
        if ca.get(field) != cb.get(field):
            diff[field] = {"A": ca.get(field), "B": cb.get(field)}
    report["first_concrete_difference"] = diff
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "interpretation": report["interpretation"], "A": a_v, "B": b_v, "diff": diff}, indent=2))
    return 0 if a_v != "INVALID" and b_v != "INVALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
