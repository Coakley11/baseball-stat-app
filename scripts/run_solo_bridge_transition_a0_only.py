"""A0-only bridge transition run — frozen 90s token, room-state forensics."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_bridge_transition_a0_only.json"
OBSERVATION_S = 25
EXPECTED_DEPLOY_SHA = ""

SCRAPE_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  let trans = null;
  let client = null;
  const alerts = [];
  const text = roots().map(x=>x.body?x.body.innerText:'').join('\\n');
  for (const root of roots()) {
    const t = root.querySelector('#solo-bridge-transition-diag');
    if (t) trans = {
      control: t.getAttribute('data-control')||'',
      phase: t.getAttribute('data-phase')||'',
      expected_expire_token: t.getAttribute('data-expected-expire-token')||'',
      python_room_status: t.getAttribute('data-python-room-status')||'',
      python_room_id: t.getAttribute('data-python-room-id')||'',
      python_room_present: t.getAttribute('data-python-room-present')||'',
      provenance_b64: t.getAttribute('data-provenance-b64')||'',
      provenance: t.getAttribute('data-provenance')||'',
      valid_expiration_count: t.getAttribute('data-valid-expiration-count')||'0',
      room_ledger_b64: t.getAttribute('data-room-ledger-b64')||'',
      streamlit_session_id: t.getAttribute('data-streamlit-session-id')||'',
      script_run_counter: t.getAttribute('data-script-run-counter')||'',
      room_mutation_log_b64: t.getAttribute('data-room-mutation-log-b64')||'',
      room_mutation_audit_b64: t.getAttribute('data-room-mutation-audit-b64')||'',
      room_status_log: t.getAttribute('data-room-status-log')||'',
      stages: t.getAttribute('data-stages')||'',
    };
    const c = root.querySelector('#solo-expire-client');
    if (c) {
      client = {
        chain: c.getAttribute('data-chain')||'',
        chain_persisted: c.getAttribute('data-chain-persisted')||'',
        remounts: c.getAttribute('data-remounts')||'',
        token: c.getAttribute('data-token')||'',
      };
    }
  }
  const ctrl = (trans && trans.control) || 'A0';
  let persistKey = 'solo_bridge_' + ctrl + '_';
  const pyRoom = (trans && trans.python_room_id) || '';
  persistKey += pyRoom || 'setup';
  let persistLog = [];
  try {
    for (const root of roots()) {
      const ls = root.defaultView && root.defaultView.localStorage;
      if (!ls) continue;
      const raw = ls.getItem(persistKey);
      if (raw) { persistLog = JSON.parse(raw); break; }
    }
  } catch(e) {}
  const has_pause = /Pause Draft/i.test(text);
  const setup_visible = /Start New Live Draft/i.test(text) && /Draft Setup|Draft Mode/i.test(text);
  const active_ui = has_pause || /Solo live draft started/i.test(text) || /End\\/Delete Draft/i.test(text);
  const room_id = (text.match(/Room ID\\s+([A-F0-9]+)/i)||[])[1]||'';
  const page_url = window.location.href || '';
  let active_page = '';
  try {
    const q = new URL(page_url).searchParams.get('active_page') || '';
    active_page = q;
  } catch(e) {}
  return {
    trans, client, page_url, active_page,
    has_pause, setup_visible, active_ui, ui_room_id: room_id,
    persist_key: persistKey, persist_log: persistLog,
    text_len: text.length,
  };
}"""


def setup_url() -> str:
    return (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_delivery_diag=1"
        f"&solo_bridge_transition=A0"
        f"&solo_component_diag=1"
        f"&solo_diag_timer=10"
        f"&solo_bridge_a0_seconds=90"
    )


def _decode_b64_json(b64: str) -> Any:
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64 + "==="[: (4 - len(b64) % 4) % 4])
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _provenance_from_probe(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    b64 = str(probe.get("provenance_b64") or "").strip()
    decoded = _decode_b64_json(b64)
    if isinstance(decoded, list):
        return decoded, ""
    raw = probe.get("provenance") or "[]"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list) and parsed:
            return parsed, ""
    except json.JSONDecodeError as exc:
        return [], f"provenance_json_parse_error:{exc}"
    if not raw and not b64:
        return [], "provenance_empty"
    return [], "provenance_unreadable"


def _client_chain(snap: dict[str, Any]) -> str:
    client = dict(snap.get("client") or {})
    chain = str(client.get("chain_persisted") or client.get("chain") or "")
    if chain:
        return chain
    log = snap.get("persist_log") or []
    if isinstance(log, list):
        return "|".join(str(e.get("stage") or "") for e in log if isinstance(e, dict))
    return ""


def _active_page_from_url(url: str) -> str:
    try:
        q = parse_qs(urlparse(url).query)
        return str(q.get("active_page", [""])[0])
    except Exception:
        return ""


def _classify_room_discrepancy(
    *,
    latched_room_id: str,
    python_room_id: str,
    python_room_status: str,
    python_room_present: bool,
    ui_room_id: str,
    active_ui: bool,
    has_pause: bool,
    setup_visible: bool,
    text_len: int,
    prev_ui_room: str,
    prev_page_url: str,
    page_url: str,
) -> str:
    py_absent = not python_room_present and python_room_status in ("none", "unknown", "")
    if not latched_room_id or not was_in_progress_heuristic(active_ui, has_pause):
        return "not_in_observation_window"

    if py_absent and active_ui:
        if not ui_room_id and text_len < 800:
            return "temporary_scrape_failure_or_collapsed_dom"
        if not ui_room_id and has_pause:
            return "stale_active_ui_pause_without_room_line"
        if ui_room_id and ui_room_id != latched_room_id:
            return "python_room_replaced_by_other_room_in_browser"
        if ui_room_id == latched_room_id:
            return "python_room_genuinely_removed_ui_shows_latched_room"
        return "python_room_genuinely_removed_ui_active_ambiguous"

    if python_room_id and latched_room_id and python_room_id != latched_room_id:
        return "python_room_replaced"

    if page_url != prev_page_url and prev_page_url:
        return "streamlit_navigation_or_session_url_change"

    if ui_room_id and prev_ui_room and ui_room_id != prev_ui_room and ui_room_id != latched_room_id:
        return "browser_dom_room_id_changed"

    if setup_visible and has_pause:
        return "stale_mixed_setup_and_active_controls"

    return "consistent"


def was_in_progress_heuristic(active_ui: bool, has_pause: bool) -> bool:
    return bool(active_ui or has_pause)


def _normalize_sample(
    snap: dict[str, Any],
    *,
    ts: float,
    elapsed_s: float,
    latched_room_id: str,
    prev: dict[str, Any] | None,
) -> dict[str, Any]:
    probe = dict(snap.get("trans") or {})
    py_id = str(probe.get("python_room_id") or "").strip().upper()
    py_status = str(probe.get("python_room_status") or "")
    py_present = probe.get("python_room_present") in ("1", "true", "True") or bool(py_id and py_status not in ("none", ""))
    ui_room = str(snap.get("ui_room_id") or "").strip().upper()
    chain = _client_chain(snap)
    prev = prev or {}
    probe = dict(snap.get("trans") or {})
    discrepancy = _classify_room_discrepancy(
        latched_room_id=latched_room_id,
        python_room_id=py_id,
        python_room_status=py_status,
        python_room_present=py_present,
        ui_room_id=ui_room,
        active_ui=bool(snap.get("active_ui")),
        has_pause=bool(snap.get("has_pause")),
        setup_visible=bool(snap.get("setup_visible")),
        text_len=int(snap.get("text_len") or 0),
        prev_ui_room=str(prev.get("ui_room_id") or ""),
        prev_page_url=str(prev.get("page_url") or ""),
        page_url=str(snap.get("page_url") or ""),
    )
    return {
        "ts": ts,
        "elapsed_s": elapsed_s,
        "python_live_draft_room_present": py_present,
        "python_room_id": py_id,
        "python_room_status": py_status,
        "active_page": snap.get("active_page") or _active_page_from_url(str(snap.get("page_url") or "")),
        "browser_visible_room_id": ui_room,
        "pause_draft_visible": bool(snap.get("has_pause")),
        "setup_controls_visible": bool(snap.get("setup_visible")),
        "expected_expire_token": str(probe.get("expected_expire_token") or ""),
        "streamlit_session_id": str(probe.get("streamlit_session_id") or ""),
        "script_run_counter": str(probe.get("script_run_counter") or ""),
        "delivery_stage_chain": str(probe.get("stages") or ""),
        "client_chain_stages": chain,
        "room_discrepancy_class": discrepancy,
        "page_url": snap.get("page_url") or "",
        "text_len": snap.get("text_len"),
    }


def _first_missing_provenance_stage(
    *,
    expected: str,
    client_chain: str,
    provenance: list[dict[str, Any]],
    on_change_count: int,
) -> str:
    cs = set(p for p in client_chain.split("|") if p)
    if "browser_deadline_crossed" not in cs:
        return "browser_deadline_crossed"
    if "component_value_sent" not in cs:
        return "component_value_sent"
    if not expected:
        return "expected_token"
    oc = [e for e in provenance if e.get("source") == "on_change_callback" and e.get("actual_raw") == expected]
    if provenance:
        if not oc:
            return "python_session_state_on_change_for_expected_token"
        if len(oc) != 1:
            return "on_change_exactly_once"
        return ""
    if on_change_count <= 0:
        return "python_session_state_on_change_for_expected_token"
    if on_change_count != 1:
        return "on_change_exactly_once"
    return ""


def _on_change_count_from_stages(stages: str, expected: str) -> int:
    if not stages or not expected:
        return stages.count("on_change_callback_entry_matching_token")
    return stages.count("on_change_callback_entry_matching_token")


def _classify_a0(
    *,
    draft_ok: bool,
    latched_room_id: str,
    room_stable: bool,
    python_room_lost_confirmed: bool,
    stale_ui_confirmed: bool,
    provenance_error: str,
    client_cross_and_send: bool,
    valid_pass: bool,
    on_change_once: bool,
    session_has_token: bool,
    session_changed: bool,
    matching_on_change_count: int,
) -> tuple[str, str]:
    if not draft_ok:
        return "INVALID", "draft_start_failed"
    if session_changed:
        return "INVALID", "streamlit_session_or_navigation_discontinuity"
    if python_room_lost_confirmed:
        return "INVALID", "python_genuinely_lost_room_while_ui_active"
    if stale_ui_confirmed:
        return "INVALID", "browser_stale_active_ui"
    if not room_stable:
        return "INVALID", "room_not_stable_throughout"
    if (provenance_error or matching_on_change_count == 0) and client_cross_and_send and matching_on_change_count == 0:
        if provenance_error:
            return "INVALID", f"token_provenance_unestablishable:{provenance_error}"
        if not session_has_token:
            return "VALID_FAIL", "client_sent_no_python_session_state_receipt"
    if valid_pass and on_change_once and session_has_token and client_cross_and_send:
        return "PASS", ""
    if room_stable and client_cross_and_send and not session_has_token:
        return "VALID_FAIL", "client_sent_no_python_session_state_receipt"
    if room_stable and client_cross_and_send:
        return "VALID_FAIL", "client_sent_python_receipt_not_exactly_once"
    return "INVALID", "observation_incomplete_or_ambiguous"


def run_a0(page, ws_frames: list[dict[str, Any]]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_solo_clean_verification import clear_stale_solo_draft, scrape_live_sha
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = setup_url()
    ws_baseline = len(ws_frames)
    goto_and_wake(page, url, timeout_s=240)
    deploy_sha = scrape_live_sha(page)
    clear_stale_solo_draft(page)
    draft = execute_solo_draft_start_workflow(page, url, navigate=False)
    draft_ok = bool(draft.get("start_success"))
    latched_room_id = str(draft.get("room_id") or "").strip().upper()

    t0 = time.time()
    samples: list[dict[str, Any]] = []
    prev_norm: dict[str, Any] | None = None
    was_in_progress = False
    python_loss_streak = 0
    python_room_lost_confirmed = False
    stale_ui_streak = 0
    stale_ui_confirmed = False
    room_id_mismatches: list[dict[str, Any]] = []
    session_ids_seen: set[str] = set()
    session_changed = False
    baseline_page_url = ""

    while time.time() - t0 < OBSERVATION_S:
        snap = page.evaluate(SCRAPE_JS)
        elapsed = round(time.time() - t0, 1)
        ts = time.time()
        norm = _normalize_sample(snap, ts=ts, elapsed_s=elapsed, latched_room_id=latched_room_id, prev=prev_norm)
        samples.append(norm)
        sid = str(norm.get("streamlit_session_id") or "").strip()
        if sid:
            session_ids_seen.add(sid)
            if len(session_ids_seen) > 1:
                session_changed = True
        page_url = str(norm.get("page_url") or "")
        if not baseline_page_url and page_url:
            baseline_page_url = page_url
        elif page_url and baseline_page_url and page_url != baseline_page_url:
            if "active_page=" in page_url and "active_page=" in baseline_page_url:
                session_changed = True
        if str(norm.get("room_discrepancy_class") or "") == "streamlit_navigation_or_session_url_change":
            session_changed = True

        if norm.get("pause_draft_visible") or snap.get("active_ui"):
            was_in_progress = True

        ui_room = str(norm.get("browser_visible_room_id") or "")
        if latched_room_id and ui_room and ui_room != latched_room_id:
            room_id_mismatches.append({"elapsed_s": elapsed, "latched": latched_room_id, "seen": ui_room})

        disc = str(norm.get("room_discrepancy_class") or "")
        if disc in (
            "python_room_genuinely_removed_ui_shows_latched_room",
            "python_room_genuinely_removed_ui_active_ambiguous",
            "python_room_replaced",
            "python_room_replaced_by_other_room_in_browser",
        ):
            if snap.get("active_ui") or norm.get("pause_draft_visible"):
                python_loss_streak += 1
                if python_loss_streak >= 2:
                    python_room_lost_confirmed = True
        else:
            python_loss_streak = 0

        if disc in ("stale_active_ui_pause_without_room_line", "stale_mixed_setup_and_active_controls"):
            stale_ui_streak += 1
            if stale_ui_streak >= 2:
                stale_ui_confirmed = True
        elif disc == "temporary_scrape_failure_or_collapsed_dom":
            pass
        else:
            stale_ui_streak = 0

        prev_norm = norm
        if python_room_lost_confirmed and was_in_progress and elapsed >= 5:
            break
        page.wait_for_timeout(2000)

    final = page.evaluate(SCRAPE_JS)
    probe = dict(final.get("trans") or {})
    expected = str(probe.get("expected_expire_token") or "")
    client_chain = _client_chain(final)
    cs = set(p for p in client_chain.split("|") if p)
    client_cross_and_send = bool(
        expected and "browser_deadline_crossed" in cs and "component_value_sent" in cs
    )
    provenance, prov_err = _provenance_from_probe(probe)
    if prov_err.startswith("provenance_json_parse_error"):
        prov_err = "provenance_json_parse_error"
    stages_chain = str(probe.get("stages") or "")
    stage_oc = _on_change_count_from_stages(stages_chain, expected)

    on_change_events = [e for e in provenance if e.get("source") == "on_change_callback" and e.get("actual_raw") == expected]
    matching_on_change_count = len(on_change_events) if on_change_events else stage_oc
    on_change_once = matching_on_change_count == 1
    session_has_token = matching_on_change_count >= 1 or int(probe.get("valid_expiration_count") or 0) >= 1

    first_missing = _first_missing_provenance_stage(
        expected=expected,
        client_chain=client_chain,
        provenance=provenance,
        on_change_count=matching_on_change_count,
    )
    if prov_err and not provenance:
        if first_missing == "" and not client_cross_and_send:
            first_missing = "token_provenance_unestablishable"
        elif first_missing == "":
            first_missing = "python_session_state_on_change_for_expected_token"

    room_stable = bool(
        draft_ok
        and latched_room_id
        and was_in_progress
        and not room_id_mismatches
        and not python_room_lost_confirmed
        and not stale_ui_confirmed
    )

    valid_pass = client_cross_and_send and on_change_once and session_has_token and room_stable

    verdict, reason = _classify_a0(
        draft_ok=draft_ok,
        latched_room_id=latched_room_id,
        room_stable=room_stable,
        python_room_lost_confirmed=python_room_lost_confirmed,
        stale_ui_confirmed=stale_ui_confirmed,
        provenance_error=prov_err,
        client_cross_and_send=client_cross_and_send,
        valid_pass=valid_pass,
        on_change_once=on_change_once,
        session_has_token=session_has_token,
        session_changed=session_changed,
        matching_on_change_count=matching_on_change_count,
    )

    room_ledger = _decode_b64_json(str(probe.get("room_ledger_b64") or ""))
    mutation_log = _decode_b64_json(str(probe.get("room_mutation_log_b64") or ""))
    mutation_audit = _decode_b64_json(str(probe.get("room_mutation_audit_b64") or ""))

    first_present_to_absent: dict[str, Any] = {}
    if isinstance(mutation_audit, dict):
        fpa = mutation_audit.get("first_present_to_absent")
        if isinstance(fpa, dict):
            first_present_to_absent = fpa
    audit_mutations = (
        mutation_audit.get("mutations") if isinstance(mutation_audit, dict) else None
    )

    first_loss = next(
        (
            s
            for s in samples
            if not s.get("python_live_draft_room_present")
            and s.get("elapsed_s", 0) >= 4
            and was_in_progress
        ),
        None,
    )

    first_mutation = ""
    first_mutation_detail: dict[str, Any] = {}
    if first_present_to_absent:
        first_mutation_detail = dict(first_present_to_absent)
        first_mutation = str(
            first_present_to_absent.get("reason")
            or first_present_to_absent.get("function")
            or first_present_to_absent.get("path")
            or first_present_to_absent.get("kind")
            or ""
        )
    elif isinstance(audit_mutations, list) and audit_mutations:
        for row in audit_mutations:
            if not isinstance(row, dict):
                continue
            op = str(row.get("operation") or "")
            if op in ("pop", "delete", "clear") and row.get("prev_room_id"):
                first_mutation_detail = row
                first_mutation = str(row.get("reason") or row.get("function") or op)
                break
    elif isinstance(mutation_log, list) and mutation_log:
        first_mutation_detail = dict(mutation_log[0]) if isinstance(mutation_log[0], dict) else {}
        first_mutation = str(first_mutation_detail.get("path") or first_mutation_detail.get("kind") or "")

    return {
        "control": "A0",
        "deploy_sha": deploy_sha,
        "deploy_sha_expected": EXPECTED_DEPLOY_SHA,
        "observation_seconds": OBSERVATION_S,
        "url": url,
        "draft_start": draft,
        "latched_room_id": latched_room_id,
        "verdict": verdict,
        "reason": reason,
        "python_truly_lost_room": python_room_lost_confirmed,
        "browser_stale_active_ui": stale_ui_confirmed,
        "room_id_mismatches": room_id_mismatches,
        "expected_expire_token": expected,
        "client_chain_persisted": client_chain,
        "browser_deadline_crossed": "browser_deadline_crossed" in cs,
        "component_value_sent": "component_value_sent" in cs,
        "token_provenance": provenance,
        "provenance_read_error": prov_err,
        "on_change_matching_token_count": matching_on_change_count,
        "matching_on_change_count": matching_on_change_count,
        "first_missing_provenance_stage": first_missing,
        "session_continuity_ok": not session_changed,
        "streamlit_session_ids_seen": sorted(session_ids_seen),
        "valid_expiration_count_server": int(probe.get("valid_expiration_count") or 0),
        "streamlit_session_id_probe": probe.get("streamlit_session_id") or "",
        "script_run_counter_probe": probe.get("script_run_counter") or "",
        "room_ledger_tail": room_ledger[-12:] if isinstance(room_ledger, list) else room_ledger,
        "room_mutation_log": mutation_log if isinstance(mutation_log, list) else [],
        "room_mutation_audit": mutation_audit if isinstance(mutation_audit, dict) else mutation_audit,
        "first_present_to_absent_mutation": first_present_to_absent,
        "first_room_mutation_path": first_mutation,
        "first_room_mutation_detail": first_mutation_detail,
        "first_python_room_loss_sample": first_loss,
        "observation_samples": samples,
        "ws_frame_count": len(ws_frames) - ws_baseline,
        "persist_key": final.get("persist_key"),
    }


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "runner_commit_note": "room_mutation_audit_short_obs",
        "observation_mode": "short_stop_on_room_loss",
        "cloud_build": EXPECTED_DEPLOY_SHA,
        "production_flush_disabled": True,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        install_ws_and_postmessage_hooks(page, ws_frames)
        report["a0"] = run_a0(page, ws_frames)
        context.close()
        browser.close()

    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    a0 = report["a0"]
    print(
        json.dumps(
            {
                "artifact": str(OUT),
                "verdict": a0.get("verdict"),
                "reason": a0.get("reason"),
                "deploy_sha": a0.get("deploy_sha"),
            },
            indent=2,
        )
    )
    return 0 if a0.get("verdict") in ("PASS", "VALID_FAIL") else 2


if __name__ == "__main__":
    raise SystemExit(main())
