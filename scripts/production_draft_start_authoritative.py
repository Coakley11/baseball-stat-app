"""Authoritative Solo draft-start grading for production harnesses (DOM + mount probe)."""

from __future__ import annotations

import re
from typing import Any


def scrape_authoritative_start_state(page) -> dict[str, Any]:
    from run_production_solo_soak import all_frames_text, dom_counts, scrape_state

    text = all_frames_text(page)
    counts = dom_counts(page)
    ui = scrape_state(page)
    mount = page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          let out = {};
          for (const root of roots()) {
            const el = root.querySelector('#solo-component-mount-diag');
            if (!el) continue;
            out = {
              mounted: el.getAttribute('data-mounted') || '',
              draft_id: el.getAttribute('data-draft-id') || '',
              pick_index: el.getAttribute('data-pick-index') || '',
              deadline: el.getAttribute('data-deadline') || '',
              token: el.getAttribute('data-token') || '',
              diag_deadline: el.getAttribute('data-diag-deadline') || '',
              diag_remaining: el.getAttribute('data-diag-remaining') || '',
              diag_timer: el.getAttribute('data-diag-timer') || '',
              remaining: el.getAttribute('data-remaining') || '',
              key: el.getAttribute('data-key') || '',
            };
          }
          let python_room_id = '';
          for (const root of roots()) {
            const ko = root.querySelector('#solo-key-ownership-diag');
            if (!ko) continue;
            const b64 = ko.getAttribute('data-key-ownership-b64')||'';
            if (!b64) continue;
            try {
              const pad = b64 + '==='.slice((4 - b64.length % 4) % 4);
              const payload = JSON.parse(atob(pad));
              const rows = payload.rows || [];
              const last = rows.length ? rows[rows.length-1] : payload;
              python_room_id = String(last.live_draft_room_id || last.room_id || '').trim();
            } catch(e) {}
          }
          return { mount: out, python_room_id };
        }"""
    )
    mount_row = (mount or {}).get("mount") or {}
    python_rid = str((mount or {}).get("python_room_id") or "").strip().upper()
    visible_m = re.search(r"Room ID\s+([A-F0-9]+)", text, re.I)
    visible_rid = (visible_m.group(1) if visible_m else "").strip().upper()
    room_id = visible_rid or python_rid
    pick_ui = ui.get("pick")
    try:
        pick_mount = int(mount_row.get("pick_index") or -1)
    except (TypeError, ValueError):
        pick_mount = -1
    pick_index = pick_ui if pick_ui is not None else (pick_mount if pick_mount >= 0 else None)
    deadline_raw = (
        mount_row.get("diag_deadline")
        or mount_row.get("deadline")
        or ui.get("timer")
    )
    has_deadline = deadline_raw not in (None, "", "0", 0)
    token = str(mount_row.get("token") or "").strip()
    draft_id = str(mount_row.get("draft_id") or "").strip()
    derived_token = ""
    if not token and draft_id and pick_index is not None and has_deadline:
        derived_token = f"{draft_id}|{int(pick_index)}|{deadline_raw}"
    production_token = token or derived_token
    pause_count = int(counts.get("Pause Draft") or 0)
    setup_visible = "Start New Live Draft" in text
    in_progress_ui = pause_count >= 1 or (
        bool(room_id) and not setup_visible and (has_deadline or ui.get("ccTimer") is not None)
    )
    timer_seconds = mount_row.get("diag_timer") or mount_row.get("remaining") or ui.get("timer")
    return {
        "url": page.url,
        "visible_room_id": visible_rid,
        "python_room_id": python_rid,
        "room_id": room_id,
        "pick_index": pick_index,
        "deadline": deadline_raw,
        "production_token": production_token,
        "expire_token": token,
        "derived_token": derived_token,
        "mount": mount_row,
        "ui": ui,
        "pause_draft_count": pause_count,
        "setup_start_visible": setup_visible,
        "in_progress": in_progress_ui,
        "timer_seconds": timer_seconds,
        "has_pick_controls": int(counts.get("Draft Player") or 0) >= 1 or bool(re.search(r"Pick\\s+\\d+", text, re.I)),
        "text_excerpt": text[:2400],
    }


def grade_authoritative_draft_start(
    state: dict[str, Any],
    *,
    prior_room_id: str = "",
    start_click_dispatched: bool = False,
) -> dict[str, Any]:
    rid = str(state.get("room_id") or "").strip().upper()
    pick = state.get("pick_index")
    checks = {
        "nonempty_room_id": bool(rid) and len(rid) >= 6,
        "room_in_progress": bool(state.get("in_progress")),
        "pick_index_zero": pick is not None and int(pick) == 0,
        "deadline_exists": bool(state.get("deadline")) or state.get("ui", {}).get("timer") is not None,
        "production_token": bool(state.get("production_token")),
        "fresh_room_id": not prior_room_id or rid != prior_room_id.strip().upper(),
        "single_start_click_dispatched": start_click_dispatched,
    }
    passed = all(
        checks[k]
        for k in (
            "nonempty_room_id",
            "room_in_progress",
            "pick_index_zero",
            "deadline_exists",
            "production_token",
            "fresh_room_id",
        )
    )
    return {"pass": passed, "checks": checks, "room_id": rid}


def classify_start_gate_failure(
    *,
    pre: dict[str, Any],
    click: dict[str, Any],
    post: dict[str, Any],
    grade: dict[str, Any],
    session_continuity: dict[str, Any],
) -> str:
    if session_continuity.get("session_changed"):
        return "F. SESSION_CHANGED_DURING_START"
    alerts = " ".join(str(x) for x in (post.get("page_errors") or [])).lower()
    if "traceback" in alerts or "exception" in post.get("text_excerpt", "").lower():
        return "G. APPLICATION_EXCEPTION"
    enabled = click.get("start_button_enabled_count") or 0
    if enabled == 0 and not click.get("evaluate_click_dispatched"):
        return "A. START_BUTTON_NOT_AVAILABLE"
    if not click.get("evaluate_click_dispatched") and not click.get("playwright_clicked"):
        return "B. CLICK_NOT_DISPATCHED"
    checks = grade.get("checks") or {}
    if not checks.get("nonempty_room_id"):
        return "C. ROOM_NOT_CREATED"
    if checks.get("nonempty_room_id") and not checks.get("room_in_progress"):
        return "D. ROOM_CREATED_BUT_DRAFT_NOT_STARTED"
    if grade.get("pass"):
        return ""
    return "E. DRAFT_STARTED_BUT_HARNESS_NOT_LATCHED"
