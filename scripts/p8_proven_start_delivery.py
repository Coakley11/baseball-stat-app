"""Shared production Start click + delivery proof (root audit + Stage 1A). Harness only."""

from __future__ import annotations

import time
from typing import Any

CANONICAL_START_CLICK_HELPER = "proven_start_single_click"
START_DELIVERY_RESOLVED = "START_DELIVERY_RESOLVED"

START1 = "START1 — stale/wrong frame"
START2 = "START2 — disabled/replaced widget"
START3 = "START3 — websocket/widget transport unavailable"
START4B = "START4B — click dispatched but no Streamlit back-message"
START5 = "START5 — Streamlit message sent but callback absent"
START6 = "START6 — callback entered but handler absent"
START8 = "START8 — another exact first-supported failure"

_FRAME_PROBE_JS = """() => {
  const nameRe = /Start New Live Draft/i;
  function probeDoc(doc, frameUrl) {
    let hasStart = false, hasLedger = false, startDisabled = true, startVisible = false, startCount = 0;
    for (const b of doc.querySelectorAll('button')) {
      const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!nameRe.test(t)) continue;
      startCount += 1;
      const r = b.getBoundingClientRect();
      startVisible = startVisible || (r.width > 0 && r.height > 0);
      if (!b.disabled) startDisabled = false;
      hasStart = true;
    }
    hasLedger = !!doc.querySelector('#solo-production-ledger-diag');
    return { frameUrl, hasStart, hasLedger, startDisabled, startVisible, startCount };
  }
  const out = [];
  out.push(probeDoc(document, location.href || ''));
  for (const f of document.querySelectorAll('iframe')) {
    try {
      if (f.contentDocument) out.push(probeDoc(f.contentDocument, f.src || ''));
    } catch (e) {}
  }
  return out;
}"""

_WS_AGG_JS = """() => {
  function logsFrom(win) {
    try { return (win.__p8WsBoundaryLog || []).slice(); } catch (e) { return []; }
  }
  let all = logsFrom(window);
  for (const f of document.querySelectorAll('iframe')) {
    try {
      if (f.contentWindow) all = all.concat(logsFrom(f.contentWindow));
    } catch (e) {}
  }
  return all;
}"""

_SCRIPT_SEQ_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  for (const root of roots()) {
    const el = root.querySelector('#solo-production-ledger-diag');
    if (!el) continue;
    return {
      script_run_seq: el.getAttribute('data-script-run-seq') || el.getAttribute('data-run-seq') || '',
      run_id: el.getAttribute('data-run-id') || '',
    };
  }
  return { script_run_seq: '', run_id: '' };
}"""


def install_proven_start_context_scripts(context) -> dict[str, Any]:
    """Install observer, ledger, and WebSocket boundary hooks on every frame."""
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT

    installed: list[str] = []
    for label, script in (
        ("harness_top_observer", HARNESS_TOP_OBSERVER_INIT_SCRIPT),
        ("ledger_durable", LEDGER_DURABLE_INIT_SCRIPT),
        ("p8_ws_boundary", P8_WS_BOUNDARY_INIT_SCRIPT),
    ):
        try:
            context.add_init_script(script)
            installed.append(label)
        except Exception:
            pass
    return {"installed": installed, "helper": "install_proven_start_context_scripts"}


def inspect_start_click_authority(page) -> dict[str, Any]:
    """Frame-level Start control inventory (reject stale top-only evidence)."""
    probes: list[dict[str, Any]] = []
    try:
        probes = page.evaluate(_FRAME_PROBE_JS) or []
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "frame_probes": []}
    start_frames = [p for p in probes if p.get("hasStart")]
    ledger_frames = [p for p in probes if p.get("hasLedger")]
    enabled_frames = [p for p in start_frames if not p.get("startDisabled") and p.get("startVisible")]
    total_starts = sum(int(p.get("startCount") or 0) for p in probes)
    preferred = None
    for p in enabled_frames:
        if p.get("hasLedger"):
            preferred = p
            break
    if preferred is None and enabled_frames:
        preferred = enabled_frames[0]
    return {
        "ok": True,
        "top_level_page_url": getattr(page, "url", ""),
        "frame_probes": probes,
        "frames_with_start": len(start_frames),
        "frames_with_ledger": len(ledger_frames),
        "enabled_start_frames": len(enabled_frames),
        "total_start_controls": total_starts,
        "multiple_start_controls": total_starts > 1,
        "preferred_frame_url": (preferred or {}).get("frameUrl") or "",
        "preferred_has_ledger": bool((preferred or {}).get("hasLedger")),
    }


def wait_start_widget_stable(page, *, stable_ms: int = 600, max_wait_s: float = 12.0) -> dict[str, Any]:
    """Wait until ledger script_run_seq stops changing (rerun settled)."""
    t0 = time.time()
    last_seq = ""
    stable_since = time.time()
    while time.time() - t0 < max_wait_s:
        snap = page.evaluate(_SCRIPT_SEQ_JS) or {}
        seq = str(snap.get("script_run_seq") or "")
        if seq and seq == last_seq:
            if (time.time() - stable_since) * 1000.0 >= stable_ms:
                return {"stable": True, "script_run_seq": seq, "waited_s": round(time.time() - t0, 3)}
        else:
            last_seq = seq
            stable_since = time.time()
        page.wait_for_timeout(150)
    return {"stable": False, "script_run_seq": last_seq, "waited_s": round(time.time() - t0, 3)}


def aggregate_ws_boundary_log(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_WS_AGG_JS) or []
        return [e for e in raw if isinstance(e, dict)]
    except Exception:
        return []


def websocket_open_at_click(page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                  function openIn(win) {
                    try {
                      if (win.__p8WsBoundaryLog && win.__p8WsBoundaryLog.length) return true;
                    } catch (e) {}
                    return false;
                  }
                  if (openIn(window)) return true;
                  for (const f of document.querySelectorAll('iframe')) {
                    try { if (f.contentWindow && openIn(f.contentWindow)) return true; } catch (e) {}
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        return False


def proven_start_single_click(page, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Single authoritative Start click used by root audit and Stage 1A canonical start.
    Requires bound frame inspection, stable widget, click, transport timing, ledger rerun proof.
    """
    from p8_production_start_harness import (
        START_BUTTON_KEY,
        capture_start_click_transport,
        dispatch_start_single_authoritative_click,
        scrape_stage1_ledger_rows,
    )

    authority = inspect_start_click_authority(page)
    stability = wait_start_widget_stable(page)
    pre_seq = str((page.evaluate(_SCRIPT_SEQ_JS) or {}).get("script_run_seq") or "")
    pre_rows = scrape_stage1_ledger_rows(page)
    pre_canary = max(
        (int(r.get("script_run_seq") or 0) for r in pre_rows if r.get("event") == "production_global_script_run_canary"),
        default=0,
    )
    click_dispatch_started_at = time.time()
    click = dispatch_start_single_authoritative_click(page, checkpoints)
    click["start_click_helper"] = CANONICAL_START_CLICK_HELPER
    click["click_authority"] = authority
    click["pre_click_stability"] = stability
    click["pre_click_script_run_seq"] = pre_seq
    click["websocket_hook_seen"] = websocket_open_at_click(page)
    page.wait_for_timeout(400)
    click_ts = float(click.get("click_timestamp") or time.time())
    transport = capture_start_click_transport(page, click_ts=click_ts)
    transport["aggregate_ws_entries"] = len(aggregate_ws_boundary_log(page))
    post_rows = scrape_stage1_ledger_rows(page)
    post_canary = max(
        (int(r.get("script_run_seq") or 0) for r in post_rows if r.get("event") == "production_global_script_run_canary"),
        default=0,
    )
    post_seq = str((page.evaluate(_SCRIPT_SEQ_JS) or {}).get("script_run_seq") or "")
    transport["python_rerun_started"] = bool(
        transport.get("python_rerun_started") or post_canary > pre_canary or (post_seq and post_seq != pre_seq)
    )
    transport["timing_ms"] = {
        "dispatch_started_ms": int(click_dispatch_started_at * 1000),
        "dispatch_completed_ms": int(float(click.get("click_dispatch_completed_at") or click_ts) * 1000),
        "transport_capture_ms": int(time.time() * 1000),
        "dispatch_duration_ms": int(
            (float(click.get("click_dispatch_completed_at") or click_ts) - click_dispatch_started_at) * 1000
        ),
    }
    transport["widget_key"] = START_BUTTON_KEY
    return {"click": click, "transport": transport, "pre_canary_seq": pre_canary, "post_canary_seq": post_canary}


def wait_for_start_callback_handler_proof(
    page,
    *,
    click_ts: float,
    max_wait_s: float = 90.0,
) -> dict[str, Any]:
    from p8_production_start_harness import scrape_stage1_ledger_rows

    t0 = time.time()
    callback_entered = False
    handler_entered = False
    room_id = ""
    run_id = ""
    session_id = ""
    while time.time() - t0 < max_wait_s:
        rows = scrape_stage1_ledger_rows(page)
        for r in rows:
            if float(r.get("ts") or 0) < click_ts - 0.05:
                continue
            ev = str(r.get("event") or "")
            if ev == "production_stage1_start_callback_entered":
                callback_entered = True
            if ev == "production_stage1_start_handler_entered":
                handler_entered = True
            if ev == "production_stage1_start_handler_exited" and r.get("created_room_id"):
                room_id = str(r.get("created_room_id") or "").upper()
            if not run_id:
                run_id = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
            if not session_id:
                session_id = str(r.get("streamlit_session_id") or "")
        if handler_entered and room_id:
            break
        if callback_entered and handler_entered:
            page.wait_for_timeout(2000)
            rows = scrape_stage1_ledger_rows(page)
            for r in rows:
                if str(r.get("event") or "") == "production_stage1_start_handler_exited":
                    room_id = str(r.get("created_room_id") or room_id or "").upper()
            if room_id:
                break
        page.wait_for_timeout(1500)
    return {
        "callback_entered": callback_entered,
        "handler_entered": handler_entered,
        "room_id": room_id,
        "diagnostic_run_id": run_id,
        "streamlit_session_id": session_id,
        "elapsed_s": round(time.time() - t0, 2),
    }


def classify_start_delivery_outcome(
    *,
    authority: dict[str, Any],
    click: dict[str, Any],
    transport: dict[str, Any],
    proof: dict[str, Any],
) -> str:
    """Focused Start-only classification (not queue-engine)."""
    if proof.get("handler_entered") and proof.get("callback_entered") and proof.get("room_id"):
        return START_DELIVERY_RESOLVED
    if authority.get("multiple_start_controls") and not authority.get("preferred_has_ledger"):
        return START1
    if click.get("disabled_at_click"):
        return START2
    if not click.get("dom_click_dispatched"):
        if click.get("click_stale_detached"):
            return START1
        return START2
    if not transport.get("websocket_hook_seen") and not transport.get("aggregate_ws_entries"):
        if not transport.get("python_rerun_started") and not proof.get("callback_entered"):
            return START3
    if click.get("dom_click_dispatched") and not transport.get("streamlit_backmsg_sent"):
        if not transport.get("python_rerun_started") and not proof.get("callback_entered"):
            return START4B
    if transport.get("streamlit_backmsg_sent") or transport.get("python_rerun_started"):
        if not proof.get("callback_entered"):
            return START5
    if proof.get("callback_entered") and not proof.get("handler_entered"):
        return START6
    return START8


def queue_runner_must_not_run_until_room_latched(*, room_latch_proven: bool, next_step: str) -> None:
    if room_latch_proven:
        return
    blocked = (
        "pause",
        "queue",
        "seed",
        "resume",
        "expiration",
        "claim",
        "autopick",
        "commit",
    )
    step = str(next_step or "").lower()
    if any(b in step for b in blocked):
        raise RuntimeError(f"queue_step_blocked_until_room_latch:{next_step}")
