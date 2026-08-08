"""Shared production Pause Draft click + delivery proof (Stage 1A-QUEUE harness)."""

from __future__ import annotations

import re
import time
from typing import Any

CANONICAL_PAUSE_CLICK_HELPER = "proven_pause_single_click"
PAUSE_DELIVERY_RESOLVED = "PAUSE_DELIVERY_RESOLVED"
PAUSE_BUTTON_LABEL = "Pause Draft"
RESUME_BUTTON_LABEL = "Resume Draft"

QUEUEUI_PAUSE1 = "QUEUEUI_PAUSE1 — immediate Pause Draft action did not register after successful Start/latch"
QUEUEUI_PAUSE1A = "QUEUEUI_PAUSE1A — room latched before Pause UI hydration"
QUEUEUI_PAUSE1B = "QUEUEUI_PAUSE1B — wrong/stale frame or Pause element"
QUEUEUI_PAUSE1C = "QUEUEUI_PAUSE1C — DOM click dispatched but no Streamlit back-message"
QUEUEUI_PAUSE1D = "QUEUEUI_PAUSE1D — Streamlit message sent but Pause callback absent"
QUEUEUI_PAUSE1E = "QUEUEUI_PAUSE1E — callback ran but server paused state not established"
QUEUEUI_PAUSE1F = "QUEUEUI_PAUSE1F — server paused but harness failed to recognize it"
QUEUEUI_PAUSE8 = "QUEUEUI_PAUSE8 — another exact supported Pause failure"

_PAUSE_PROBE_JS = """() => {
  const pauseRe = /Pause Draft/i;
  const resumeRe = /Resume Draft/i;
  function probeDoc(doc, frameUrl) {
    let pauseCount = 0, pauseDisabled = true, pauseVisible = false;
    let resumeCount = 0;
    for (const b of doc.querySelectorAll('button')) {
      const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
      if (pauseRe.test(t)) {
        pauseCount += 1;
        const r = b.getBoundingClientRect();
        pauseVisible = pauseVisible || (r.width > 0 && r.height > 0);
        if (!b.disabled) pauseDisabled = false;
      }
      if (resumeRe.test(t)) resumeCount += 1;
    }
    const hasLedger = !!doc.querySelector('#solo-production-ledger-diag');
    return { frameUrl, pauseCount, pauseDisabled, pauseVisible, resumeCount, hasLedger };
  }
  const out = [probeDoc(document, location.href || '')];
  for (const f of document.querySelectorAll('iframe')) {
    try { if (f.contentDocument) out.push(probeDoc(f.contentDocument, f.src || '')); } catch (e) {}
  }
  return out;
}"""


def inspect_pause_click_authority(page) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    try:
        probes = page.evaluate(_PAUSE_PROBE_JS) or []
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "frame_probes": []}
    pause_frames = [p for p in probes if int(p.get("pauseCount") or 0) > 0]
    enabled = [p for p in pause_frames if not p.get("pauseDisabled") and p.get("pauseVisible")]
    preferred = None
    for p in enabled:
        if p.get("hasLedger"):
            preferred = p
            break
    if preferred is None and enabled:
        preferred = enabled[0]
    return {
        "ok": True,
        "frame_probes": probes,
        "frames_with_pause": len(pause_frames),
        "enabled_pause_frames": len(enabled),
        "preferred_frame_url": (preferred or {}).get("frameUrl") or "",
        "pause_visible_any": len(pause_frames) > 0,
        "pause_enabled_any": len(enabled) > 0,
    }


def wait_for_authoritative_pause_control(
    page,
    *,
    max_wait_s: float = 45.0,
    poll_ms: int = 400,
    room_id: str = "",
) -> dict[str, Any]:
    """Poll until Pause Draft is visible+enabled in an authoritative frame (no arbitrary sleep)."""
    from run_production_solo_soak import dom_counts

    t0 = time.time()
    first_seen_ts = 0.0
    last_authority: dict[str, Any] = {}
    while time.time() - t0 < max_wait_s:
        authority = inspect_pause_click_authority(page)
        last_authority = authority
        counts = dom_counts(page) or {}
        pause_n = int(counts.get(PAUSE_BUTTON_LABEL) or 0)
        if authority.get("pause_enabled_any") or pause_n >= 1:
            if not first_seen_ts:
                first_seen_ts = time.time()
            if authority.get("pause_enabled_any"):
                return {
                    "ready": True,
                    "waited_s": round(time.time() - t0, 3),
                    "first_pause_visible_ts": first_seen_ts,
                    "poll_started_ts": t0,
                    "authority": authority,
                    "dom_pause_count": pause_n,
                    "room_id": room_id,
                }
        page.wait_for_timeout(poll_ms)
    return {
        "ready": False,
        "waited_s": round(time.time() - t0, 3),
        "first_pause_visible_ts": first_seen_ts or None,
        "poll_started_ts": t0,
        "authority": last_authority,
        "dom_pause_count": int((dom_counts(page) or {}).get(PAUSE_BUTTON_LABEL) or 0),
        "room_id": room_id,
    }


def _ordered_pause_click_frames(page):
    probes: list[dict[str, Any]] = []
    try:
        probes = page.evaluate(_PAUSE_PROBE_JS) or []
    except Exception:
        return list(page.frames)
    enabled = [
        p
        for p in probes
        if int(p.get("pauseCount") or 0) > 0 and not p.get("pauseDisabled") and p.get("pauseVisible")
    ]
    preferred_url = ""
    for p in enabled:
        if p.get("hasLedger"):
            preferred_url = str(p.get("frameUrl") or "")
            break
    if not preferred_url and enabled:
        preferred_url = str(enabled[0].get("frameUrl") or "")
    frames = list(page.frames)
    if preferred_url:
        matched = [f for f in frames if preferred_url.split("?")[0] in (f.url or "")]
        rest = [f for f in frames if f not in matched]
        return matched + rest
    return frames


def dispatch_proven_pause_click(page) -> dict[str, Any]:
    """Single authoritative Pause click (frame-aware, scroll, non-force first)."""
    name_re = re.compile(re.escape(PAUSE_BUTTON_LABEL), re.I)
    out: dict[str, Any] = {
        "selector": f"role=button[name=/{PAUSE_BUTTON_LABEL}/i]",
        "dom_click_dispatched": False,
        "disabled_at_click": True,
    }
    click_dispatch_started_at = time.time()
    dom_install: dict[str, Any] = {}
    click_frame = None
    for frame in _ordered_pause_click_frames(page):
        try:
            loc = frame.get_by_role("button", name=name_re)
            if loc.count() < 1 or loc.first.is_disabled():
                continue
            out["disabled_at_click"] = False
            try:
                from stage1_dom_click_capture import install_dom_click_capture_on_frame

                dom_install = install_dom_click_capture_on_frame(
                    frame,
                    frame_url_hint=str(frame.url or ""),
                    mode="pause",
                    button_label_re="Pause Draft",
                    button_test_id="stBaseButton-primary",
                )
            except ImportError:
                pass
            try:
                loc.first.scroll_into_view_if_needed(timeout=8000)
            except Exception:
                pass
            try:
                loc.first.click(timeout=12000)
            except Exception:
                loc.first.click(timeout=12000, force=True)
            out["dom_click_dispatched"] = True
            out["click_frame_url"] = (frame.url or "")[:200]
            out["click_frame_index"] = page.frames.index(frame) if frame in page.frames else -1
            click_frame = frame
            break
        except Exception as exc:
            err = str(exc)[:160]
            out.setdefault("frame_skip_errors", []).append(err)
            if "not attached" in err.lower() or "detached" in err.lower():
                out["click_stale_detached"] = True
    click_dispatch_completed_at = time.time()
    out["click_dispatch_started_at"] = click_dispatch_started_at
    out["click_dispatch_completed_at"] = click_dispatch_completed_at
    out["click_timestamp"] = click_dispatch_completed_at
    if dom_install:
        out["dom_click_capture_install"] = dom_install
    if click_frame is not None and out.get("dom_click_dispatched"):
        try:
            from stage1_dom_click_capture import read_dom_click_capture_from_frame

            events = read_dom_click_capture_from_frame(click_frame)
            out["browser_dom_click_events"] = events
            if dom_install.get("ok") and not events:
                out["dom_capture_observability_failed"] = True
        except ImportError:
            pass
    return out


def capture_pause_click_transport(page, *, click_ts: float) -> dict[str, Any]:
    from p8_proven_start_delivery import aggregate_ws_boundary_log

    raw_log = aggregate_ws_boundary_log(page)
    outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
    after = [e for e in outbound if float(e.get("wall_ts_ms") or 0) >= (click_ts * 1000.0 - 50.0)]
    backmsg = any(
        "widget" in str(e.get("frame_type_hint") or "").lower()
        or "backmsg" in str(e.get("frame_type_hint") or "").lower()
        for e in after
    )
    return {
        "outbound_frames_after_click": len(after),
        "streamlit_backmsg_sent": backmsg or len(after) > 0,
        "ws_log_sample": after[:5],
    }


def pause_server_proof_from_dom(page) -> dict[str, Any]:
    from run_production_solo_soak import dom_counts

    counts = dom_counts(page) or {}
    resume_n = int(counts.get(RESUME_BUTTON_LABEL) or 0)
    pause_n = int(counts.get(PAUSE_BUTTON_LABEL) or 0)
    return {
        "resume_draft_count": resume_n,
        "pause_draft_count": pause_n,
        "server_paused_ui": resume_n >= 1 and pause_n == 0,
        "paused_recognized": resume_n >= 1,
    }


def wait_for_pause_server_proof(page, *, click_ts: float, max_wait_s: float = 20.0) -> dict[str, Any]:
    t0 = time.time()
    last: dict[str, Any] = {}
    while time.time() - t0 < max_wait_s:
        last = pause_server_proof_from_dom(page)
        if last.get("paused_recognized"):
            last["elapsed_s"] = round(time.time() - t0, 3)
            last["click_ts"] = click_ts
            return last
        page.wait_for_timeout(500)
    last["elapsed_s"] = round(time.time() - t0, 3)
    last["click_ts"] = click_ts
    last["timed_out"] = True
    return last


def classify_pause_delivery_outcome(
    *,
    hydration_wait: dict[str, Any],
    click: dict[str, Any],
    transport: dict[str, Any],
    server_proof: dict[str, Any],
) -> str:
    if server_proof.get("paused_recognized"):
        return PAUSE_DELIVERY_RESOLVED
    if not hydration_wait.get("ready"):
        return QUEUEUI_PAUSE1A
    if not click.get("dom_click_dispatched"):
        if click.get("click_stale_detached"):
            return QUEUEUI_PAUSE1B
        return QUEUEUI_PAUSE1B
    if click.get("dom_click_dispatched") and not transport.get("streamlit_backmsg_sent"):
        return QUEUEUI_PAUSE1C
    if transport.get("streamlit_backmsg_sent") and not server_proof.get("paused_recognized"):
        return QUEUEUI_PAUSE1E
    if server_proof.get("resume_draft_count", 0) >= 1 and not server_proof.get("paused_recognized"):
        return QUEUEUI_PAUSE1F
    return QUEUEUI_PAUSE8


def proven_pause_single_click(
    page,
    *,
    room_id: str = "",
    latch_completed_ts: float | None = None,
    max_hydration_wait_s: float = 45.0,
) -> dict[str, Any]:
    """Wait for Pause control, click once, prove Resume appears."""
    hydration = wait_for_authoritative_pause_control(
        page, max_wait_s=max_hydration_wait_s, room_id=room_id
    )
    timing: dict[str, Any] = {
        "latch_completed_ts": latch_completed_ts,
        "pause_hydration_ready_ts": time.time() if hydration.get("ready") else None,
        "first_pause_visible_ts": hydration.get("first_pause_visible_ts"),
        "pause_wait_started_ts": hydration.get("poll_started_ts"),
        "pause_wait_duration_s": hydration.get("waited_s"),
    }
    if latch_completed_ts and hydration.get("first_pause_visible_ts"):
        timing["ms_latch_to_first_pause_visible"] = int(
            (float(hydration["first_pause_visible_ts"]) - float(latch_completed_ts)) * 1000
        )
    if not hydration.get("ready"):
        return {
            "paused": False,
            "pause_click_helper": CANONICAL_PAUSE_CLICK_HELPER,
            "pause_hydration_wait": hydration,
            "pause_timing": timing,
            "pause_classification": QUEUEUI_PAUSE1A,
            "pause_error": "pause_control_not_hydrated",
        }
    authority = inspect_pause_click_authority(page)
    pause_obs: dict[str, Any] = {}
    pre_bind: dict[str, Any] = {}
    try:
        from stage1_run_binding import capture_run_binding_snapshot

        pre_bind = capture_run_binding_snapshot(page, phase="pre_click")
    except ImportError:
        pass
    click = dispatch_proven_pause_click(page)
    click_ts = float(click.get("click_timestamp") or time.time())
    timing["pause_click_dispatch_ts"] = click_ts
    try:
        from stage1_run_binding import capture_run_binding_snapshot

        post_bind = capture_run_binding_snapshot(
            page,
            frame_url_hint=str(click.get("click_frame_url") or ""),
            phase="post_click",
        )
        pause_obs = {
            "pre_click_run_binding": pre_bind,
            "post_click_run_binding": post_bind,
            "browser_dom_click_events": click.get("browser_dom_click_events"),
            "dom_click_capture_install": click.get("dom_click_capture_install"),
        }
    except ImportError:
        pass
    transport = capture_pause_click_transport(page, click_ts=click_ts)
    server_proof = wait_for_pause_server_proof(page, click_ts=click_ts)
    classification = classify_pause_delivery_outcome(
        hydration_wait=hydration,
        click=click,
        transport=transport,
        server_proof=server_proof,
    )
    return {
        "paused": classification == PAUSE_DELIVERY_RESOLVED,
        "pause_click_helper": CANONICAL_PAUSE_CLICK_HELPER,
        "pause_hydration_wait": hydration,
        "pause_click_authority": authority,
        "pause_click": click,
        "pause_click_transport": transport,
        "pause_click_observability": pause_obs,
        "pause_server_proof": server_proof,
        "pause_timing": timing,
        "pause_classification": classification,
        "resume_draft_count_after_pause": server_proof.get("resume_draft_count"),
        "pause_draft_count_after_pause": server_proof.get("pause_draft_count"),
    }


def queue_runner_must_not_seed_until_pause_proven(*, pause_proven: bool) -> None:
    if pause_proven:
        return
    raise RuntimeError("queue_seed_blocked_until_pause_proven")
