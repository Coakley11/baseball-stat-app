"""Three-control bridge-transition Cloud matrix — A0, A1, B."""

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
OUT = ROOT / "data" / "solo_bridge_transition_matrix.json"
CONTROLS = ("A0", "A1", "B")
OBSERVATION_BY_CONTROL = {"A0": 130, "A1": 42, "B": 42}

SCRAPE_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  let trans = null;
  let client = null;
  let persistKey = '';
  let persistLog = [];
  const alerts = [];
  const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
  for (const root of roots()) {
    const t = root.querySelector('#solo-bridge-transition-diag');
    if (t) trans = {
      control: t.getAttribute('data-control')||'',
      phase: t.getAttribute('data-phase')||'',
      expected_expire_token: t.getAttribute('data-expected-expire-token')||'',
      args_before: t.getAttribute('data-args-before')||'',
      args_after: t.getAttribute('data-args-after')||'',
      python_room_status: t.getAttribute('data-python-room-status')||'',
      python_room_id: t.getAttribute('data-python-room-id')||'',
      valid_expiration_count: t.getAttribute('data-valid-expiration-count')||'0',
      provenance: t.getAttribute('data-provenance')||'',
      valid_events: t.getAttribute('data-valid-events')||'',
      post_activation: t.getAttribute('data-post-activation')||'',
      widget_popped: t.getAttribute('data-widget-popped')||'',
      room_status_log: t.getAttribute('data-room-status-log')||'',
    };
    const c = root.querySelector('#solo-expire-client');
    if (c) {
      client = {
        chain: c.getAttribute('data-chain')||'',
        chain_persisted: c.getAttribute('data-chain-persisted')||'',
        remounts: c.getAttribute('data-remounts')||'',
        token: c.getAttribute('data-token')||'',
        browser_zero_ts: c.getAttribute('data-browser-zero-ts')||'',
        component_sent_ts: c.getAttribute('data-component-sent-ts')||'',
      };
    }
    for (const el of root.querySelectorAll('[data-testid=\"stAlert\"], .stException')) {
      const a = String(el.innerText||'').replace(/\\s+/g,' ').trim();
      if (a) alerts.push(a.slice(0,400));
    }
  }
  const ctrl = (trans && trans.control) || '';
  const pyRoom = (trans && trans.python_room_id) || '';
  persistKey = pyRoom ? ('solo_bridge_' + ctrl + '_' + pyRoom) : '';
  if (!persistKey && ctrl) persistKey = 'solo_bridge_' + ctrl + '_setup';
  try {
    for (const root of roots()) {
      const raw = root.defaultView && root.defaultView.localStorage ? root.defaultView.localStorage.getItem(persistKey) : null;
      if (raw) { persistLog = JSON.parse(raw); break; }
    }
  } catch(e) {}
  const has_pause = /Pause Draft/i.test(text);
  const active_ui = has_pause || /Solo live draft started/i.test(text) || /End\\/Delete Draft/i.test(text);
  const room_id = (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'';
  return { trans, client, text_snippet: text.slice(0,1200), alerts: [...new Set(alerts)].slice(0,6), active_ui, has_pause, ui_room_id: room_id, persist_key: persistKey, persist_log: persistLog };
}"""


def setup_url(control: str) -> str:
    extra = "&solo_bridge_a0_seconds=90" if control == "A0" else ""
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_delivery_diag=1"
        f"&solo_bridge_transition={control}"
        f"&solo_component_diag=1"
        f"&solo_diag_timer=10"
        f"{extra}"
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


def _client_chain(snap: dict[str, Any]) -> str:
    client = dict(snap.get("client") or {})
    chain = str(client.get("chain_persisted") or client.get("chain") or "")
    if chain:
        return chain
    log = snap.get("persist_log") or []
    if isinstance(log, list):
        return "|".join(str(e.get("stage") or "") for e in log if isinstance(e, dict))
    return ""


def _provenance_events(probe: dict[str, Any]) -> list[dict[str, Any]]:
    raw = probe.get("provenance") or "[]"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return list(parsed) if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _count_provenance_matching(provenance: list[dict[str, Any]], expected: str) -> dict[str, int]:
    oc = sum(1 for e in provenance if e.get("source") == "on_change_callback" and e.get("actual_raw") == expected)
    raw = sum(1 for e in provenance if e.get("actual_raw") == expected)
    spurious = sum(
        1
        for e in provenance
        if e.get("source") == "on_change_callback"
        and e.get("actual_raw") == expected
        and not (e.get("browser_zero_cross_ts") and e.get("component_value_sent_ts"))
    )
    return {"matching_on_change": oc, "matching_raw": raw, "spurious_matching_without_client_ts": spurious}


def _valid_expiration_from_evidence(
    *,
    expected: str,
    client_chain: str,
    provenance: list[dict[str, Any]],
    browser_zero_ts: str,
    component_sent_ts: str,
    persist_log: list[Any],
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if not expected:
        return 0, ["expected_token_missing"]
    cs = set(p for p in client_chain.split("|") if p)
    if "browser_deadline_crossed" not in cs:
        reasons.append("no_browser_deadline_crossed_in_persisted_chain")
    if "component_value_sent" not in cs:
        reasons.append("no_component_value_sent_in_persisted_chain")
    on_change_hits = [
        e
        for e in provenance
        if e.get("source") == "on_change_callback" and str(e.get("actual_raw") or "") == expected
    ]
    if not on_change_hits and provenance:
        reasons.append("no_on_change_for_expected_token_in_provenance")
    elif not on_change_hits and not provenance:
        reasons.append("provenance_not_scraped_on_change_unverified")
    if reasons:
        return 0, reasons
    return 1, []


def _classify_control(
    *,
    control: str,
    draft_ok: bool,
    returned_to_setup: bool,
    room_latch_ok: bool,
    python_room_lost_ui_active: bool,
    post_activation_required: bool,
    post_activation_seen: bool,
    expected_token: str,
    valid_expiration_count: int,
    provenance: list[dict[str, Any]],
    client_chain: str,
    spurious_matching: int,
    client_cross_and_send: bool,
) -> tuple[str, str]:
    if not draft_ok:
        return "INVALID", "draft_start_failed"
    if returned_to_setup:
        return "INVALID", "returned_to_setup_lobby_during_observation"
    if python_room_lost_ui_active:
        return "INVALID", "python_room_lost_while_ui_active"
    if not room_latch_ok:
        return "INVALID", "latched_room_id_not_stable"
    if post_activation_required and not post_activation_seen:
        return "INVALID", "post_activation_timer_never_armed"
    if control != "A0" and not expected_token:
        return "INVALID", "expected_expire_token_missing"

    if client_cross_and_send and valid_expiration_count < 1:
        return "INCONCLUSIVE", "client_cross_send_without_proven_python_on_change"

    if valid_expiration_count >= 1:
        return "PASS", ""
    return "VALID_FAIL", "no_valid_expiration_delivery"


def _interpret_matrix(verdicts: dict[str, str]) -> dict[str, str]:
    a0 = verdicts.get("A0", "")
    a1 = verdicts.get("A1", "")
    b = verdicts.get("B", "")
    if a0 in ("INVALID", "INCONCLUSIVE"):
        return {
            "conclusion": "harness_or_a0_baseline_blocked",
            "detail": f"A0={a0} — fix harness or reproduce frozen bridge before comparing transitions.",
        }
    if a1 in ("INVALID", "INCONCLUSIVE") or b in ("INVALID", "INCONCLUSIVE"):
        return {
            "conclusion": "harness_blocked_transition_controls",
            "detail": f"A1={a1}, B={b} — unstable room or inconclusive provenance.",
        }
    if a0 == "PASS" and a1 in ("VALID_FAIL", "FAIL") and b == "PASS":
        return {
            "conclusion": "token_deadline_transition_defect",
            "detail": "A0 and B pass; A1 fails — token/deadline change after activation is the defect.",
        }
    if a0 == "PASS" and a1 == "PASS" and b in ("VALID_FAIL", "FAIL"):
        return {
            "conclusion": "actionable_transition_defect",
            "detail": "A0 and A1 pass; B fails — actionable false→true is the defect.",
        }
    if a0 == "PASS" and a1 == "PASS" and b == "PASS":
        return {
            "conclusion": "production_renderer_delta",
            "detail": "All three pass — production differs outside this diagnostic.",
        }
    if a0 in ("VALID_FAIL", "FAIL"):
        return {
            "conclusion": "a0_bridge_not_reproducible",
            "detail": "Frozen A0 baseline failed — investigate before production changes.",
        }
    return {"conclusion": "inconclusive", "detail": f"A0={a0}, A1={a1}, B={b}"}


def run_one_control(page, control: str, ws_frames: list[dict[str, Any]]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import clear_stale_solo_draft
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    obs_s = OBSERVATION_BY_CONTROL.get(control, 42)
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
    consecutive_inactive = 0
    returned_to_setup = False
    setup_return_snapshots: list[dict[str, Any]] = []
    post_activation_seen = False
    room_id_mismatches: list[dict[str, Any]] = []
    python_room_lost_streak = 0
    python_room_lost_ui_active = False

    while time.time() - t0 < obs_s:
        snap = page.evaluate(SCRAPE_JS)
        snap["elapsed_s"] = round(time.time() - t0, 1)
        probe = dict(snap.get("trans") or {})
        if probe.get("post_activation") in ("1", "true") or probe.get("expected_expire_token"):
            post_activation_seen = True
        ui_room = str(snap.get("ui_room_id") or "").strip().upper()
        py_status = str(probe.get("python_room_status") or "")
        py_room = str(probe.get("python_room_id") or "").strip().upper()
        if snap.get("active_ui"):
            was_in_progress = True
            consecutive_inactive = 0
        elif was_in_progress:
            consecutive_inactive += 1
            setup_return_snapshots.append(
                {
                    "elapsed_s": snap["elapsed_s"],
                    "ui_room_id": ui_room,
                    "python_room_id": py_room,
                    "python_room_status": py_status,
                    "latched_room_id": latched_room_id,
                }
            )
        if latched_room_id and ui_room and ui_room != latched_room_id:
            room_id_mismatches.append({"elapsed_s": snap["elapsed_s"], "latched": latched_room_id, "seen": ui_room})
        if (
            latched_room_id
            and snap.get("active_ui")
            and py_status in ("none", "unknown", "")
            and was_in_progress
        ):
            python_room_lost_streak += 1
            if python_room_lost_streak >= 2:
                python_room_lost_ui_active = True
        else:
            python_room_lost_streak = 0
        if consecutive_inactive >= 2:
            returned_to_setup = True
        samples.append(snap)
        page.wait_for_timeout(2000)

    final = page.evaluate(SCRAPE_JS)
    probe = dict(final.get("trans") or {})
    client = dict(final.get("client") or {})
    expected_token = str(probe.get("expected_expire_token") or "")
    provenance = _provenance_events(probe)
    matching = _count_provenance_matching(provenance, expected_token)
    client_chain = _client_chain(final)
    valid_n, valid_reasons = _valid_expiration_from_evidence(
        expected=expected_token,
        client_chain=client_chain,
        provenance=provenance,
        browser_zero_ts=str(client.get("browser_zero_ts") or ""),
        component_sent_ts=str(client.get("component_sent_ts") or ""),
        persist_log=list(final.get("persist_log") or []),
    )
    cs_set = set(p for p in client_chain.split("|") if p)
    client_cross_and_send = bool(
        expected_token and "browser_deadline_crossed" in cs_set and "component_value_sent" in cs_set
    )
    py_valid = int(probe.get("valid_expiration_count") or 0)
    valid_expiration_count = max(valid_n, py_valid)

    new_ws = ws_frames[ws_baseline:]
    widget_after, widget_send = _widget_ids_from_ws(new_ws, "solo_persistent")

    room_latch_ok = bool(draft_ok and latched_room_id and was_in_progress and not returned_to_setup and not room_id_mismatches)

    verdict, reason = _classify_control(
        control=control,
        draft_ok=draft_ok,
        returned_to_setup=returned_to_setup,
        room_latch_ok=room_latch_ok,
        python_room_lost_ui_active=python_room_lost_ui_active,
        post_activation_required=control != "A0",
        post_activation_seen=post_activation_seen or control == "A0",
        expected_token=expected_token,
        valid_expiration_count=valid_expiration_count,
        provenance=provenance,
        client_chain=client_chain,
        spurious_matching=matching["spurious_matching_without_client_ts"],
        client_cross_and_send=client_cross_and_send,
    )

    return {
        "control": control,
        "observation_seconds": obs_s,
        "url": url,
        "draft_start": draft,
        "latched_room_id": latched_room_id,
        "room_id_stable": room_latch_ok and not room_id_mismatches,
        "verdict": verdict,
        "reason": reason,
        "expected_expire_token": expected_token,
        "args_before_activation": probe.get("args_before") or "",
        "args_after_activation": probe.get("args_after") or "",
        "python_room_id_final": probe.get("python_room_id") or "",
        "python_room_status_final": probe.get("python_room_status") or "",
        "ui_room_id_final": final.get("ui_room_id") or "",
        "widget_id_before_activation": widget_before,
        "widget_id_after_activation": widget_after,
        "widget_id_changed": bool(widget_before and widget_after and widget_before != widget_after),
        "client_remount_count": int(client.get("remounts") or 0),
        "client_chain_persisted": client_chain,
        "browser_deadline_crossed": "browser_deadline_crossed" in set(client_chain.split("|")),
        "component_value_sent": "component_value_sent" in set(client_chain.split("|")),
        "browser_zero_ts": client.get("browser_zero_ts") or "",
        "component_sent_ts": client.get("component_sent_ts") or "",
        "valid_expiration_count": valid_expiration_count,
        "valid_expiration_reasons": valid_reasons,
        "token_provenance": provenance,
        "matching_on_change_unverified": matching["matching_on_change"],
        "spurious_matching_without_client_ts": matching["spurious_matching_without_client_ts"],
        "python_room_lost_ui_active": python_room_lost_ui_active,
        "returned_to_setup_during_observation": returned_to_setup,
        "persist_key": final.get("persist_key") or "",
        "persist_log_tail": (final.get("persist_log") or [])[-8:],
        "room_status_log": probe.get("room_status_log") or "",
        "widget_session_popped": probe.get("widget_popped") in ("1", "true"),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "design": "A0_frozen_90s_A1_token_switch_B_actionable_switch",
        "production_flush_disabled": True,
        "controls": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        report["deploy_sha"] = ""
        for control in CONTROLS:
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
            page = context.new_page()
            install_ws_and_postmessage_hooks(page, ws_frames)
            result = run_one_control(page, control, ws_frames)
            if not report["deploy_sha"]:
                report["deploy_sha"] = scrape_live_sha(page)
            report["controls"][control] = result
            context.close()
        browser.close()

    verdicts = {c: str(report["controls"].get(c, {}).get("verdict") or "") for c in CONTROLS}
    report["interpretation"] = _interpret_matrix(verdicts)
    report["first_valid_differing_control"] = _first_diff_control(report["controls"])
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "interpretation": report["interpretation"], "verdicts": verdicts}, indent=2))
    if any(v in ("INVALID", "INCONCLUSIVE") for v in verdicts.values()):
        return 2
    return 0


def _first_diff_control(controls: dict[str, Any]) -> str:
    order = ("A0", "A1", "B")
    passes = {c: controls.get(c, {}).get("verdict") == "PASS" for c in order}
    if passes.get("A0") and not passes.get("A1"):
        return "A1"
    if passes.get("A0") and passes.get("A1") and not passes.get("B"):
        return "B"
    if not passes.get("A0"):
        return "A0"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
