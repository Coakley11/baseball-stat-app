"""Frame-aware active draft + queue UI readiness (Stage 1A-QUEUE harness)."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from stage1_queue_harness_flow import parse_pick_index_from_expire_token

ACTIVE_QUEUE_SURFACE_RESOLVED = "ACTIVE_QUEUE_SURFACE_RESOLVED"
QUEUE_ACTIVE_PAGE1 = (
    "QUEUE_ACTIVE_PAGE1 — paused active-draft surface not recognized by Stage 1A active-page gate"
)

QUEUE_ACTIVE_PAGE1A = "QUEUE_ACTIVE_PAGE1A — wrong/stale iframe selected"
QUEUE_ACTIVE_PAGE1B = "QUEUE_ACTIVE_PAGE1B — server ready, queue DOM still hydrating"
QUEUE_ACTIVE_PAGE1C = "QUEUE_ACTIVE_PAGE1C — room/pick in ledger but missing from DOM"
QUEUE_ACTIVE_PAGE1D = "QUEUE_ACTIVE_PAGE1D — queue controls require tab/expander activation"
QUEUE_ACTIVE_PAGE1E = "QUEUE_ACTIVE_PAGE1E — paused mode suppresses expected queue UI"
QUEUE_ACTIVE_PAGE1F = "QUEUE_ACTIVE_PAGE1F — active UI genuinely failed to render"
QUEUE_ACTIVE_PAGE8 = "QUEUE_ACTIVE_PAGE8 — another exact supported active-page condition"

# Legacy alias used by older abort paths until fully migrated.
QUEUEUI1 = "QUEUEUI1 — ACTIVE LIVE DRAFT PAGE NOT HYDRATED"

_ACTIVE_FRAME_PROBE_JS = """() => {
  function probeDoc(doc, frameUrl, frameIndex) {
    const text = String(doc.body ? doc.body.innerText || '' : '').slice(0, 120000);
    let roomId = '';
    const rm = text.match(/Room ID\\s+([A-F0-9]{6,12})/i);
    if (rm) roomId = rm[1].toUpperCase();
    let pickIndex = null;
    for (const pill of doc.querySelectorAll('.ld-pill, [data-testid=\"stMarkdownContainer\"]')) {
      const t = String(pill.innerText || '').replace(/\\s+/g, ' ').trim();
      const pm = t.match(/^Pick\\s+(\\d+)/i);
      if (pm) pickIndex = parseInt(pm[1], 10);
    }
    let addToQueue = 0;
    for (const b of doc.querySelectorAll('button')) {
      const r = b.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const t = String(b.innerText || '').replace(/\\s+/g, ' ').trim();
      if (/Add to Queue/i.test(t)) addToQueue += 1;
    }
    const boardRows = doc.querySelectorAll('[data-testid=\"stDataFrame\"] tbody tr').length;
    let pauseCount = 0, resumeCount = 0;
    for (const b of doc.querySelectorAll('button')) {
      const t = String(b.innerText || '').replace(/\\s+/g, ' ').trim();
      if (/Pause Draft/i.test(t)) pauseCount += 1;
      if (/Resume Draft/i.test(t)) resumeCount += 1;
    }
    let expireToken = '';
    let diagDeadline = '';
    let mountKey = '';
    const mount = doc.querySelector('#solo-component-mount-diag');
    if (mount) {
      expireToken = mount.getAttribute('data-token') || '';
      diagDeadline = mount.getAttribute('data-diag-deadline') || mount.getAttribute('data-deadline') || '';
      mountKey = mount.getAttribute('data-key') || '';
    }
    const hasLedger = !!doc.querySelector('#solo-stage1-production-ledger, #solo-production-ledger-diag');
    const isAppFrame = String(frameUrl || '').includes('/~/+/');
    return {
      frameIndex,
      frameUrl: frameUrl || '',
      roomId,
      pickIndex,
      addToQueue,
      boardRows,
      pauseCount,
      resumeCount,
      expireToken,
      diagDeadline,
      mountKey,
      hasLedger,
      isAppFrame,
      textLen: text.length,
    };
  }
  const out = [];
  out.push(probeDoc(document, location.href || '', 0));
  let idx = 1;
  for (const f of document.querySelectorAll('iframe')) {
    try {
      if (f.contentDocument) {
        out.push(probeDoc(f.contentDocument, f.src || '', idx));
        idx += 1;
      }
    } catch (e) {}
  }
  return out;
}"""


def _score_frame_probe(probe: dict[str, Any]) -> int:
    score = 0
    if probe.get("isAppFrame"):
        score += 40
    if probe.get("hasLedger"):
        score += 25
    if int(probe.get("addToQueue") or 0) > 0:
        score += 30
    if int(probe.get("boardRows") or 0) > 0:
        score += 15
    if probe.get("roomId"):
        score += 10
    if probe.get("expireToken"):
        score += 10
    if int(probe.get("pauseCount") or 0) + int(probe.get("resumeCount") or 0) > 0:
        score += 8
    score += min(int(probe.get("textLen") or 0) // 5000, 10)
    return score


def scrape_frame_aware_active_observation(
    page,
    *,
    start_val: dict[str, Any] | None = None,
    frame_probes: list[dict[str, Any]] | None = None,
    ledger_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-frame signals + merged observation (preferred frame attribution)."""
    start_val = dict(start_val or {})
    probes: list[dict[str, Any]] = list(frame_probes or [])
    if not probes:
        try:
            raw = page.evaluate(_ACTIVE_FRAME_PROBE_JS) or []
            probes = [p for p in raw if isinstance(p, dict)]
        except Exception as exc:
            probes = [{"error": str(exc)[:200]}]

    ranked = sorted(probes, key=_score_frame_probe, reverse=True)
    preferred = ranked[0] if ranked else {}
    alt_with_queue = [p for p in probes if int(p.get("addToQueue") or 0) > 0]
    alt_with_room = [p for p in probes if str(p.get("roomId") or "").upper()]

    def _sum(field: str) -> int:
        return sum(int(p.get(field) or 0) for p in probes if isinstance(p, dict))

    latched = str(start_val.get("latched_room_id") or "").upper()
    expected_tok = str(
        start_val.get("expected_token")
        or start_val.get("production_token")
        or start_val.get("expire_token")
        or ""
    ).strip()
    pick0_tok = str(preferred.get("expireToken") or "").strip() or expected_tok
    pick_index = preferred.get("pickIndex")
    if pick_index in (None, ""):
        pick_index = start_val.get("pick_index")
    if pick_index in (None, "") and pick0_tok:
        pick_index = parse_pick_index_from_expire_token(pick0_tok)
    visible_room = str(preferred.get("roomId") or "").upper()
    if not visible_room:
        for p in alt_with_room:
            visible_room = str(p.get("roomId") or "").upper()
            if visible_room:
                break

    pick0_deadline = str(preferred.get("diagDeadline") or "").strip()
    if not pick0_deadline and start_val.get("deadline") not in (None, ""):
        pick0_deadline = str(start_val.get("deadline"))

    ledger = dict(ledger_snapshot or {})
    ledger_room = str(ledger.get("room_id") or "").upper()
    ledger_pick = ledger.get("pick_index")

    return {
        "frame_probes": probes,
        "preferred_frame_index": preferred.get("frameIndex"),
        "preferred_frame_url": preferred.get("frameUrl") or "",
        "preferred_frame_score": _score_frame_probe(preferred) if preferred else 0,
        "frames_with_add_to_queue": len(alt_with_queue),
        "frames_with_room_text": len(alt_with_room),
        "visible_room_id": visible_room,
        "pick_index": pick_index,
        "pick0_token_ui": pick0_tok,
        "pick0_deadline_ui": pick0_deadline,
        "pause_draft_count": _sum("pauseCount") or int(preferred.get("pauseCount") or 0),
        "resume_draft_count": _sum("resumeCount") or int(preferred.get("resumeCount") or 0),
        "board_rows": max(int(preferred.get("boardRows") or 0), _sum("boardRows")),
        "add_to_queue_button_count": max(int(preferred.get("addToQueue") or 0), _sum("addToQueue")),
        "countdown_or_timer_present": bool(pick0_deadline or pick0_tok or preferred.get("mountKey")),
        "mount_key": preferred.get("mountKey"),
        "server_latched_room_id": latched,
        "server_expected_token": expected_tok,
        "ledger_room_id": ledger_room,
        "ledger_pick_index": ledger_pick,
        "signal_sources": {
            "visible_room_id": "preferred_frame" if preferred.get("roomId") else ("ledger" if ledger_room else "start_val"),
            "pick_index": "preferred_frame"
            if preferred.get("pickIndex") not in (None, "")
            else ("expected_token" if expected_tok else "start_val"),
            "add_to_queue_button_count": "any_frame_sum",
        },
    }


def ledger_checkpoint_from_page(page, *, run_id: str = "", room_id: str = "") -> dict[str, Any]:
    """Best-effort room/pick from production ledger scrape."""
    out: dict[str, Any] = {"room_id": "", "pick_index": None, "paused": None}
    try:
        from stage1_frame2_parent_boundary import scrape_stage1_ledger_all_frames
        from stage1_harness_observability import decode_ledger_b64_padded

        snap = scrape_stage1_ledger_all_frames(page)
        best = snap.get("best") or {}
        if not best.get("b64"):
            return out
        decoded = decode_ledger_b64_padded(str(best.get("b64") or ""))
        rows = list(decoded.get("rows") or [])
        rid = str(room_id or "").upper()
        run = str(run_id or "").strip()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if run and str(row.get("run_id") or row.get("diagnostic_run_id") or "") not in ("", run):
                if str(row.get("run_id") or row.get("diagnostic_run_id") or "") != run:
                    continue
            rroom = str(row.get("room_id") or "").upper()
            if rid and rroom and rroom != rid:
                continue
            if rroom:
                out["room_id"] = rroom
            if row.get("pick_index") is not None:
                try:
                    out["pick_index"] = int(row.get("pick_index"))
                except (TypeError, ValueError):
                    pass
            ev = str(row.get("event") or "")
            if "paused" in ev.lower():
                out["paused"] = True
            if out["room_id"] and out["pick_index"] is not None:
                break
    except Exception:
        pass
    return out


def evaluate_server_active_draft_ready(
    observation: dict[str, Any],
    *,
    start_val: dict[str, Any],
    while_paused: bool = False,
    auth_complete: bool = True,
) -> dict[str, Any]:
    start_val = dict(start_val or {})
    obs = dict(observation or {})
    latched = str(start_val.get("latched_room_id") or "").upper()
    expected_tok = str(
        obs.get("server_expected_token")
        or start_val.get("expected_token")
        or start_val.get("production_token")
        or ""
    ).strip()
    pick0_tok = str(obs.get("pick0_token_ui") or "").strip() or expected_tok
    ledger_room = str(obs.get("ledger_room_id") or "").upper()
    room_ok = bool(latched) and (
        latched == str(obs.get("visible_room_id") or "").upper()
        or latched in pick0_tok.upper()
        or latched == ledger_room
        or bool(start_val.get("room_latch_pass"))
    )
    try:
        pick_i = int(obs.get("pick_index")) if obs.get("pick_index") not in (None, "") else None
    except (TypeError, ValueError):
        pick_i = None
    if pick_i is None and obs.get("ledger_pick_index") is not None:
        try:
            pick_i = int(obs.get("ledger_pick_index"))
        except (TypeError, ValueError):
            pick_i = None
    if pick_i is None and start_val.get("pick_index") is not None:
        try:
            pick_i = int(start_val.get("pick_index"))
        except (TypeError, ValueError):
            pick_i = None
    if pick_i is None and pick0_tok:
        pick_i = parse_pick_index_from_expire_token(pick0_tok)
    pick_zero = pick_i == 0
    in_progress = bool(start_val.get("in_progress")) or bool(start_val.get("room_latch_pass"))
    paused = while_paused or int(obs.get("resume_draft_count") or 0) >= 1
    token_present = bool(pick0_tok) and (not latched or latched in pick0_tok.upper())
    checks = {
        "room_latch_identity": room_ok,
        "lifecycle_in_progress": in_progress,
        "pick_index_zero": pick_zero,
        "expiration_token_or_server_deadline": token_present
        or bool(obs.get("pick0_deadline_ui"))
        or bool(start_val.get("deadline")),
        "paused_state": paused,
        "authentication_complete": auth_complete,
    }
    return {"ready": all(checks.values()), "checks": checks, "pick_index_resolved": pick_i}


def evaluate_queue_ui_ready(observation: dict[str, Any]) -> dict[str, Any]:
    obs = dict(observation or {})
    add_btns = int(obs.get("add_to_queue_button_count") or 0)
    board_rows = int(obs.get("board_rows") or 0)
    checks = {
        "add_to_queue_control_present": add_btns >= 1,
        "board_or_player_surface": board_rows >= 1 or add_btns >= 1,
    }
    return {"ready": all(checks.values()), "checks": checks}


def classify_active_page_boundary(
    *,
    observation: dict[str, Any],
    server_eval: dict[str, Any],
    queue_eval: dict[str, Any],
    surface_activation_attempted: bool = False,
) -> str:
    if server_eval.get("ready") and queue_eval.get("ready"):
        return ACTIVE_QUEUE_SURFACE_RESOLVED
    obs = dict(observation or {})
    probes = list(obs.get("frame_probes") or [])
    any_frame_queue = int(obs.get("frames_with_add_to_queue") or 0) > 0
    preferred_queue = int(obs.get("add_to_queue_button_count") or 0) > 0
    ledger_room = str(obs.get("ledger_room_id") or "").upper()
    visible_room = str(obs.get("visible_room_id") or "").upper()
    latched = str(obs.get("server_latched_room_id") or "").upper()

    if any_frame_queue and not preferred_queue:
        return QUEUE_ACTIVE_PAGE1A
    if server_eval.get("ready") and not queue_eval.get("ready"):
        if ledger_room == latched and not visible_room:
            return QUEUE_ACTIVE_PAGE1C
        if surface_activation_attempted and not any_frame_queue:
            return QUEUE_ACTIVE_PAGE1D
        if int(obs.get("resume_draft_count") or 0) >= 1 and not any_frame_queue:
            return QUEUE_ACTIVE_PAGE1E
        return QUEUE_ACTIVE_PAGE1B
    if not server_eval.get("ready"):
        if probes and max((_score_frame_probe(p) for p in probes if isinstance(p, dict)), default=0) < 20:
            return QUEUE_ACTIVE_PAGE1A
        return QUEUE_ACTIVE_PAGE1F
    return QUEUE_ACTIVE_PAGE8


# Navigation-only labels for surface activation (must never match Add to Queue).
QUEUE_SURFACE_NAV_LABELS: tuple[str, ...] = (
    "Available Players",
    "Watchlist",
    "Draft from lists",
    "Recommendations",
)


def surface_activation_labels_are_navigation_only() -> bool:
    """Regression guard: activation list must not include queue-mutating controls."""
    forbidden = re.compile(r"Add to Queue|Add-to-Queue|On Clock|Draft Assistant|Draft Player", re.I)
    return not any(forbidden.search(lbl) for lbl in QUEUE_SURFACE_NAV_LABELS)


def try_activate_queue_player_surface(
    page,
    *,
    start_val: dict[str, Any] | None = None,
    run_id: str = "",
    record_per_step: bool = False,
) -> dict[str, Any]:
    """Open likely tabs/sections so Add-to-Queue controls can appear (harness-only)."""
    from run_production_stage1_authenticated import _streamlit_app_frame

    start_val = dict(start_val or {})
    frame = _streamlit_app_frame(page)
    labels = QUEUE_SURFACE_NAV_LABELS
    steps: list[dict[str, Any]] = []
    for label in labels:
        step: dict[str, Any] = {"label": label, "clicked": False, "ts": time.time()}
        try:
            if label == "Available Players":
                loc2 = frame.get_by_text(re.compile(r"Available Players", re.I))
            else:
                loc = frame.get_by_role("button", name=re.compile(re.escape(label), re.I))
                if loc.count() > 0:
                    loc.first.click(timeout=2500)
                    step["clicked"] = True
                    step["via"] = "role_button"
                    loc2 = None
                else:
                    loc2 = frame.get_by_text(re.compile(re.escape(label), re.I))
            if loc2 is not None and loc2.count() > 0:
                loc2.first.click(timeout=2500)
                step["clicked"] = True
                step["via"] = "text"
        except Exception as exc:
            step["error"] = str(exc)[:120]
        if step.get("clicked"):
            page.wait_for_timeout(1200)
        if record_per_step or step.get("clicked"):
            ledger = ledger_checkpoint_from_page(
                page, run_id=run_id, room_id=str(start_val.get("latched_room_id") or "")
            )
            obs = scrape_frame_aware_active_observation(page, start_val=start_val, ledger_snapshot=ledger)
            server = evaluate_server_active_draft_ready(obs, start_val=start_val, while_paused=True)
            queue = evaluate_queue_ui_ready(obs)
            step["frame_index"] = obs.get("preferred_frame_index")
            step["frame_url"] = obs.get("preferred_frame_url")
            step["board_rows"] = obs.get("board_rows")
            step["add_to_queue_button_count"] = obs.get("add_to_queue_button_count")
            step["visible_room_id"] = obs.get("visible_room_id")
            step["pick_index"] = obs.get("pick_index")
            step["pause_draft_count"] = obs.get("pause_draft_count")
            step["resume_draft_count"] = obs.get("resume_draft_count")
            step["server_active_draft_ready"] = server
            step["queue_ui_ready"] = queue
        steps.append(step)
    return {"steps": steps, "any_clicked": any(s.get("clicked") for s in steps)}


def evaluate_active_live_page_gate(
    observation: dict[str, Any],
    *,
    start_val: dict[str, Any],
    while_paused: bool = False,
    auth_complete: bool = True,
    surface_activation_attempted: bool = False,
) -> dict[str, Any]:
    """Two-tier gate: server active draft + queue UI readiness."""
    obs = dict(observation or {})
    server = evaluate_server_active_draft_ready(
        obs, start_val=start_val, while_paused=while_paused, auth_complete=auth_complete
    )
    queue = evaluate_queue_ui_ready(obs)
    passed = bool(server.get("ready") and queue.get("ready"))
    classification = (
        ACTIVE_QUEUE_SURFACE_RESOLVED
        if passed
        else classify_active_page_boundary(
            observation=obs,
            server_eval=server,
            queue_eval=queue,
            surface_activation_attempted=surface_activation_attempted,
        )
    )
    latched = str(start_val.get("latched_room_id") or "").upper()
    legacy_checks = {
        "latched_room_visible_agrees": latched == str(obs.get("visible_room_id") or "").upper(),
        "room_in_progress": bool(start_val.get("in_progress")) or bool(start_val.get("room_latch_pass")),
        "pick_index_zero": server.get("checks", {}).get("pick_index_zero", False),
        "pick0_token_ui_present": server.get("checks", {}).get("expiration_token_or_server_deadline", False),
        "pick0_deadline_ui_present": bool(obs.get("pick0_deadline_ui")) or while_paused,
        "pause_draft_or_live_control": int(obs.get("pause_draft_count") or 0) >= 1
        or int(obs.get("resume_draft_count") or 0) >= 1
        or while_paused,
        "board_or_recommendation_surface": queue.get("checks", {}).get("board_or_player_surface", False),
        "add_to_queue_control_present": queue.get("checks", {}).get("add_to_queue_control_present", False),
        "countdown_or_timer_declaration": bool(obs.get("countdown_or_timer_present")) or while_paused,
    }
    return {
        "passed": passed,
        "classification": classification,
        "server_active_draft_ready": server,
        "queue_ui_ready": queue,
        "checks": legacy_checks,
        "latched_room_id": latched,
        "visible_room_id": str(obs.get("visible_room_id") or "").upper(),
        "observation": obs,
    }


def default_active_surface_wait_s() -> float:
    env = str(os.environ.get("ACTIVE_QUEUE_SURFACE_WAIT_S") or os.environ.get("STAGE1A_ACTIVE_PAGE_WAIT_S") or "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return 120.0


def wait_for_active_queue_surface(
    page,
    *,
    start_val: dict[str, Any],
    timeout_s: float | None = None,
    while_paused: bool = False,
    auth_complete: bool = True,
    run_id: str = "",
) -> dict[str, Any]:
    """Poll frame-aware observation until queue can be seeded or boundary classifies failure."""
    t_end = time.time() + (timeout_s if timeout_s is not None else default_active_surface_wait_s())
    pause_ack_ts = float(start_val.get("pause_ack_ts") or time.time())
    timing: dict[str, Any] = {
        "pause_acknowledged_ts": pause_ack_ts,
        "first_active_frame_hydration_ts": None,
        "first_room_pick_evidence_ts": None,
        "first_board_row_ts": None,
        "first_add_to_queue_ts": None,
        "surface_activation": None,
    }
    surface_done = False
    last_eval: dict[str, Any] = {"passed": False}
    while time.time() < t_end:
        if while_paused and not surface_done:
            pre_queue_names: list[str] = []
            post_queue_names: list[str] = []
            try:
                from run_production_stage1_authenticated import scrape_queue_container_state
                from stage1_queue_seed_harness import queue_names_from_state

                pre_c = scrape_queue_container_state(page)
                pre_queue_names = queue_names_from_state(pre_c, str(pre_c.get("excerpt") or ""))
            except Exception:
                pre_queue_names = []
            timing["surface_activation"] = try_activate_queue_player_surface(
                page,
                start_val=start_val,
                run_id=run_id,
                record_per_step=True,
            )
            try:
                post_c = scrape_queue_container_state(page)
                post_queue_names = queue_names_from_state(post_c, str(post_c.get("excerpt") or ""))
            except Exception:
                post_queue_names = []
            pre_set = {n.lower() for n in pre_queue_names if n}
            post_set = {n.lower() for n in post_queue_names if n}
            timing["queue_names_before_surface_activation"] = pre_queue_names
            timing["queue_names_after_surface_activation"] = post_queue_names
            timing["surface_activation_queue_mutation"] = bool(post_set - pre_set)
            surface_done = True
        ledger = ledger_checkpoint_from_page(
            page, run_id=run_id, room_id=str(start_val.get("latched_room_id") or "")
        )
        obs = scrape_frame_aware_active_observation(page, start_val=start_val, ledger_snapshot=ledger)
        now = time.time()
        if timing["first_active_frame_hydration_ts"] is None and obs.get("preferred_frame_url"):
            timing["first_active_frame_hydration_ts"] = now
        if timing["first_room_pick_evidence_ts"] is None and (
            obs.get("visible_room_id") or obs.get("pick0_token_ui") or obs.get("ledger_room_id")
        ):
            timing["first_room_pick_evidence_ts"] = now
        if timing["first_board_row_ts"] is None and int(obs.get("board_rows") or 0) > 0:
            timing["first_board_row_ts"] = now
        if timing["first_add_to_queue_ts"] is None and int(obs.get("add_to_queue_button_count") or 0) > 0:
            timing["first_add_to_queue_ts"] = now
        last_eval = evaluate_active_live_page_gate(
            obs,
            start_val=start_val,
            while_paused=while_paused,
            auth_complete=auth_complete,
            surface_activation_attempted=surface_done,
        )
        if last_eval.get("passed"):
            last_eval["timing"] = timing
            return last_eval
        page.wait_for_timeout(2000)
    if "observation" not in last_eval:
        ledger = ledger_checkpoint_from_page(
            page, run_id=run_id, room_id=str(start_val.get("latched_room_id") or "")
        )
        obs = scrape_frame_aware_active_observation(page, start_val=start_val, ledger_snapshot=ledger)
        last_eval = evaluate_active_live_page_gate(
            obs,
            start_val=start_val,
            while_paused=while_paused,
            auth_complete=auth_complete,
            surface_activation_attempted=surface_done,
        )
    last_eval["timing"] = timing
    return last_eval


def wait_for_active_live_page_gate(
    page,
    *,
    start_val: dict[str, Any],
    timeout_s: float | None = None,
    while_paused: bool = False,
    auth_complete: bool = True,
    run_id: str = "",
) -> dict[str, Any]:
    """Backward-compatible entry used by Stage 1A-QUEUE runner."""
    return wait_for_active_queue_surface(
        page,
        start_val=start_val,
        timeout_s=timeout_s,
        while_paused=while_paused,
        auth_complete=auth_complete,
        run_id=run_id,
    )
