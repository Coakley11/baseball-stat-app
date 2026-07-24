"""Shared Cloud Solo draft-start workflow — same path as diagnose_solo_draft_start."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
DEFAULT_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_component_diag=1&solo_diag_timer=10"
)
ROOT = Path(__file__).resolve().parent.parent
HARNESS_PROVEN_FILE = ROOT / "data" / "solo_draft_start_harness_proven.json"
POST_CLICK_OBSERVE_S = 45
BROWSER_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
VIEWPORT = {"width": 1440, "height": 1400}

SCAN_BUTTONS_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const out = [];
  for (const root of roots()) {
    for (const b of root.querySelectorAll('button')) {
      const r = b.getBoundingClientRect();
      const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
      if (!t) continue;
      out.push({
        text: t,
        disabled: !!b.disabled,
        visible: r.width > 0 && r.height > 0,
      });
    }
  }
  return out;
}"""

SCAN_SETUP_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const numbers = [];
  const radios = [];
  let soloSelected = false;
  for (const root of roots()) {
    for (const inp of root.querySelectorAll('input[type=\"number\"]')) {
      numbers.push({
        aria: inp.getAttribute('aria-label') || '',
        value: inp.value,
        disabled: !!inp.disabled,
      });
    }
    for (const el of root.querySelectorAll('label')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t.includes('Solo Draft') || t.includes('Shared Multiplayer')) {
        const input = el.querySelector('input') || (el.htmlFor ? root.getElementById(el.htmlFor) : null);
        radios.push({ label: t, checked: input ? !!input.checked : null });
        if (t.includes('Solo Draft') && input && input.checked) soloSelected = true;
      }
    }
  }
  return { numbers, radios, soloSelected };
}"""

MESSAGES_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const alerts = [];
  for (const root of roots()) {
    for (const el of root.querySelectorAll('[data-testid=\"stAlert\"], [data-baseweb=\"notification\"], .stException')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t) alerts.push(t.slice(0, 500));
    }
  }
  return { alerts: [...new Set(alerts)] };
}"""

STATE_PROBE_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  let mount = null;
  let ladder = null;
  let latch = null;
  for (const root of roots()) {
    const m = root.querySelector('#solo-component-mount-diag');
    if (m) {
      mount = {
        diag_timer: m.getAttribute('data-diag-timer') || '',
        diag_remaining: m.getAttribute('data-diag-remaining') || '',
        mounted: m.getAttribute('data-mounted') || '',
        key: m.getAttribute('data-key') || '',
      };
    }
    const l = root.querySelector('#solo-placement-ladder-diag');
    if (l) {
      ladder = {
        placement: l.getAttribute('data-placement') || '',
        callbacks: l.getAttribute('data-callbacks') || '',
        key: l.getAttribute('data-key') || '',
        token: l.getAttribute('data-token') || '',
        passed: l.getAttribute('data-passed') || '',
      };
    }
    const lat = root.querySelector('#solo-placement-latch-diag');
    if (lat) {
      latch = {
        requested: lat.getAttribute('data-requested') || '',
        query_placement: lat.getAttribute('data-query-placement') || '',
        active: lat.getAttribute('data-active') || '',
      };
    }
  }
  const text = roots().map((x) => (x.body ? x.body.innerText : '')).join('\\n');
  const roomMatch = text.match(/Room ID\\s+([A-F0-9]+)/i);
  return {
    mount_probe: mount,
    ladder_probe: ladder,
    latch_probe: latch,
    has_pause: /Pause Draft/i.test(text),
    has_start_setup: /Start New Live Draft/i.test(text),
    has_pick: /Pick\\s+\\d+/i.test(text),
    room_id: roomMatch ? roomMatch[1] : '',
    time_remaining_10: /Time remaining[:\\s]+10/i.test(text),
  };
}"""

SIDEBAR_LDR_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  for (const root of roots()) {
    for (const el of root.querySelectorAll('label')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t.includes('Live Draft Room')) { el.click(); return t; }
    }
  }
  return '';
}"""

SOLO_RADIO_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  for (const root of roots()) {
    for (const el of root.querySelectorAll('label')) {
      const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t.includes('Solo Draft')) { el.click(); return true; }
    }
  }
  return false;
}"""


def click_sidebar_for_ldr(page, *, settle_ms: int = 8000) -> str:
    label = str(page.evaluate(SIDEBAR_LDR_JS) or "")
    page.wait_for_timeout(settle_ms)
    return label


def _isolation_case_from_url(setup_url: str) -> str:
    import urllib.parse

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(setup_url).query)
    letter = str((qs.get("solo_delivery_case") or [""])[0]).strip().upper()
    return letter if letter in ("A", "B", "C", "D") else ""


def isolation_case_start_ok(
    isolation_case: str,
    seen_steps: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    """A/B mounts truncate Live Draft chrome; accept latched room + timer when Pause never appears."""
    if isolation_case not in ("A", "B"):
        return False
    if not seen_steps.get("room_id_detected"):
        return False
    if seen_steps.get("toast_detected"):
        return True
    if state.get("time_remaining_10") or seen_steps.get("timer_10_detected"):
        return True
    return False


def checkpoint(checkpoints: list[dict[str, Any]], step: str, **fields: Any) -> None:
    row = {"ts": time.time(), "step": step, **fields}
    checkpoints.append(row)


def _success_toast_detected(msgs: dict[str, Any]) -> bool:
    for alert in msgs.get("alerts") or []:
        low = str(alert).lower()
        if "solo live draft started" in low or "room id" in low:
            return True
    return False


def evaluate_start_success(state: dict[str, Any], counts: dict[str, int], msgs: dict[str, Any]) -> dict[str, bool]:
    mount = state.get("mount_probe") or {}
    setup_gone = not state.get("has_start_setup")
    return {
        "setup_page_disappeared": setup_gone,
        "success_toast_or_room_id": _success_toast_detected(msgs) or bool(state.get("room_id")),
        "room_in_progress": bool(state.get("has_pause")) and bool(state.get("room_id")),
        "pause_draft_control": int(counts.get("Pause Draft") or 0) >= 1,
        "current_pick_controls": bool(state.get("has_pick"))
        or int(counts.get("Draft Player") or 0) >= 1,
        "diag_mount_present": mount is not None,
        "diag_timer_10": str(mount.get("diag_timer") or "") == "10",
    }


def _placement_from_setup_url(setup_url: str) -> str:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(setup_url).query)
    return str((qs.get("solo_placement_ladder") or [""])[0]).strip().upper()


def query_params_snapshot(page_url: str) -> dict[str, Any]:
    low = (page_url or "").lower()
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(page_url or "").query)
    return {
        "page_url": page_url,
        "solo_delivery_diag": "solo_delivery_diag=1" in low,
        "solo_placement_ladder": str((parsed.get("solo_placement_ladder") or [""])[0]).upper(),
        "solo_component_diag": "solo_component_diag=1" in low,
        "solo_diag_timer_10": "solo_diag_timer=10" in low,
    }


def query_ok_vs_setup(setup_url: str, page_url: str) -> bool:
    expected = urllib.parse.parse_qs(urllib.parse.urlparse(setup_url).query)
    actual = urllib.parse.parse_qs(urllib.parse.urlparse(page_url).query)
    for key, vals in expected.items():
        if not vals:
            continue
        if key not in actual:
            return False
        if str(actual[key][0]) != str(vals[0]):
            return False
    return True


def record_query_checkpoint(
    checkpoints: list[dict[str, Any]],
    step: str,
    *,
    setup_url: str,
    page_url: str,
) -> dict[str, Any]:
    snap = query_params_snapshot(page_url)
    snap["query_ok_vs_setup"] = query_ok_vs_setup(setup_url, page_url)
    checkpoint(checkpoints, step, **snap)
    return snap


def start_success_criteria_met(
    flags: dict[str, bool],
    seen_steps: dict[str, bool] | None = None,
    *,
    placement: str = "",
    state: dict[str, Any] | None = None,
) -> bool:
    seen = seen_steps or {}
    st = state or {}
    ladder = st.get("ladder_probe") or {}
    latch = st.get("latch_probe") or {}
    if placement == "P2":
        effective = {
            "setup_page_disappeared": bool(flags.get("setup_page_disappeared"))
            or bool(seen.get("pause_draft_detected")),
            "success_toast_or_room_id": bool(flags.get("success_toast_or_room_id"))
            or bool(seen.get("toast_detected"))
            or bool(seen.get("room_id_detected")),
            "room_in_progress": bool(flags.get("room_in_progress"))
            or (bool(seen.get("room_id_detected")) and bool(seen.get("pause_draft_detected"))),
            "pause_draft_control": bool(flags.get("pause_draft_control"))
            or bool(seen.get("pause_draft_detected")),
            "latched_placement_p2": str(latch.get("requested") or "").upper() == "P2"
            or str(ladder.get("placement") or "").upper() == "P2"
            or bool(seen.get("placement_p2_requested")),
        }
        return all(effective.values())
    effective = {
        "setup_page_disappeared": bool(flags.get("setup_page_disappeared"))
        or bool(seen.get("pause_draft_detected")),
        "success_toast_or_room_id": bool(flags.get("success_toast_or_room_id"))
        or bool(seen.get("toast_detected"))
        or bool(seen.get("room_id_detected")),
        "room_in_progress": bool(flags.get("room_in_progress"))
        or (bool(seen.get("room_id_detected")) and bool(seen.get("pause_draft_detected"))),
        "pause_draft_control": bool(flags.get("pause_draft_control"))
        or bool(seen.get("pause_draft_detected")),
        "current_pick_controls": bool(flags.get("current_pick_controls"))
        or bool(flags.get("pause_draft_control"))
        or bool(seen.get("pause_draft_detected")),
        "diag_mount_present": bool(flags.get("diag_mount_present"))
        or bool(seen.get("diag_mount_detected")),
        "diag_timer_10": bool(flags.get("diag_timer_10"))
        or bool(seen.get("diag_mount_detected")),
    }
    required = (
        "setup_page_disappeared",
        "success_toast_or_room_id",
        "room_in_progress",
        "pause_draft_control",
        "current_pick_controls",
        "diag_mount_present",
        "diag_timer_10",
    )
    return all(effective.get(k) for k in required)


def detect_active_draft_needs_clear(page) -> dict[str, Any]:
    from cloud_streamlit_wake import all_frames_text
    from run_production_solo_soak import dom_counts

    text = all_frames_text(page)
    counts = dom_counts(page)
    pause = int(counts.get("Pause Draft") or 0) >= 1
    has_setup_start = "Start New Live Draft" in text
    has_room_line = "Room ID" in text
    # Active in-room UI: Pause visible, or room line without setup lobby.
    needs_clear = pause or (has_room_line and not has_setup_start)
    return {
        "needs_clear": needs_clear,
        "pause_draft_count": counts.get("Pause Draft"),
        "has_setup_start": has_setup_start,
        "has_room_line": has_room_line,
    }


def wait_for_setup_lobby_after_clear(page, *, max_wait_s: int = 90) -> bool:
    from cloud_streamlit_wake import all_frames_text
    from run_production_solo_soak import dom_counts

    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        if "Start New Live Draft" in all_frames_text(page):
            if int(dom_counts(page).get("Pause Draft") or 0) == 0:
                return True
        page.wait_for_timeout(2000)
    return False


def maybe_clear_stale_draft(page, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    probe = detect_active_draft_needs_clear(page)
    checkpoint(checkpoints, "stale_draft_probe", **probe)
    if not probe.get("needs_clear"):
        return {"cleared": False, "reason": "fresh_context_no_active_draft"}
    click_btn(page, "End/Delete Draft", wait_ms=6000)
    checkpoint(checkpoints, "end_delete_click_sent")
    page.wait_for_timeout(3000)
    lobby_ok = wait_for_setup_lobby_after_clear(page)
    checkpoint(checkpoints, "clear_rerun_complete", setup_lobby_visible=lobby_ok)
    return {"cleared": True, "setup_lobby_visible": lobby_ok}


def dispatch_start_new_live_draft_click(page, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    """Same click sequence as diagnose_solo_draft_start (evaluate + Playwright locator)."""
    from run_production_solo_soak import click_btn

    buttons = page.evaluate(SCAN_BUTTONS_JS)
    start_matches = [b for b in buttons if "Start New Live Draft" in str(b.get("text") or "")]
    enabled = [
        m for m in start_matches if m.get("visible") and not m.get("disabled")
    ]
    checkpoint(
        checkpoints,
        "start_button_visible_enabled",
        matches=len(start_matches),
        enabled=len(enabled),
        duplicate=len(start_matches) != 1,
    )
    url_before = page.url
    click_btn(page, "Start New Live Draft", wait_ms=1500)
    checkpoint(checkpoints, "start_click_evaluate_dispatched")
    playwright_clicked = False
    try:
        loc = page.get_by_role("button", name=re.compile(r"Start New Live Draft", re.I))
        if loc.count() >= 1 and not loc.first.is_disabled():
            loc.first.click(timeout=15000)
            playwright_clicked = True
            checkpoint(checkpoints, "start_click_playwright_dispatched")
    except Exception as exc:
        checkpoint(checkpoints, "start_click_playwright_error", error=str(exc)[:300])
    page.wait_for_timeout(2000)
    url_after = page.url
    checkpoint(
        checkpoints,
        "streamlit_rerun_detected",
        url_before=url_before,
        url_after=url_after,
        url_changed=url_before != url_after,
    )
    return {
        "start_matches": start_matches,
        "playwright_clicked": playwright_clicked,
    }


def observe_until_success_or_timeout(
    page,
    checkpoints: list[dict[str, Any]],
    *,
    max_wait_s: int = POST_CLICK_OBSERVE_S,
    isolation_case: str = "",
    placement: str = "",
    setup_url: str = "",
) -> dict[str, Any]:
    from run_production_solo_soak import dom_counts

    seen_steps = {
        "toast_detected": False,
        "room_id_detected": False,
        "room_id": "",
        "pause_draft_detected": False,
        "diag_mount_detected": False,
        "timer_10_detected": False,
        "placement_p2_requested": placement == "P2",
    }
    timeline: list[dict[str, Any]] = []
    t0 = time.time()
    final: dict[str, Any] = {}
    while time.time() - t0 < max_wait_s:
        state = page.evaluate(STATE_PROBE_JS)
        msgs = page.evaluate(MESSAGES_JS)
        counts = dom_counts(page)
        flags = evaluate_start_success(state, counts, msgs)
        elapsed = round(time.time() - t0, 1)
        row = {"elapsed_s": elapsed, "state": state, "counts": counts, "flags": flags, "msgs": msgs}
        timeline.append(row)
        final = row
        if not seen_steps["toast_detected"] and _success_toast_detected(msgs):
            seen_steps["toast_detected"] = True
            checkpoint(checkpoints, "toast_detected", alerts=msgs.get("alerts"))
        if not seen_steps["room_id_detected"] and state.get("room_id"):
            seen_steps["room_id_detected"] = True
            seen_steps["room_id"] = str(state.get("room_id") or "")
            checkpoint(checkpoints, "room_id_detected", room_id=state.get("room_id"))
        if not seen_steps["pause_draft_detected"] and int(counts.get("Pause Draft") or 0) >= 1:
            seen_steps["pause_draft_detected"] = True
            checkpoint(checkpoints, "pause_draft_detected", counts=counts)
            record_query_checkpoint(
                checkpoints,
                "query_in_progress_room",
                setup_url=setup_url,
                page_url=page.url,
            )
        mount = state.get("mount_probe") or {}
        if not seen_steps["diag_mount_detected"] and str(mount.get("diag_timer") or "") == "10":
            seen_steps["diag_mount_detected"] = True
            checkpoint(checkpoints, "diagnostic_mount_detected", mount_probe=mount)
        if not seen_steps.get("timer_10_detected") and state.get("time_remaining_10"):
            seen_steps["timer_10_detected"] = True
            checkpoint(checkpoints, "timer_10_detected")
        if start_success_criteria_met(
            flags,
            seen_steps,
            placement=placement,
            state=state,
        ):
            record_query_checkpoint(
                checkpoints,
                "query_first_rerun_after_start",
                setup_url=setup_url,
                page_url=page.url,
            )
            checkpoint(checkpoints, "start_success_all_criteria", flags=flags, seen=seen_steps)
            return {
                "start_success": True,
                "room_id": state.get("room_id") or seen_steps.get("room_id") or "",
                "flags": flags,
                "timeline": timeline,
                "elapsed_s": elapsed,
            }
        if isolation_case_start_ok(isolation_case, seen_steps, state):
            checkpoint(
                checkpoints,
                "start_success_isolation_ab",
                isolation_case=isolation_case,
                seen=seen_steps,
            )
            return {
                "start_success": True,
                "room_id": state.get("room_id") or seen_steps.get("room_id") or "",
                "flags": flags,
                "timeline": timeline,
                "elapsed_s": elapsed,
                "isolation_ab_start": True,
            }
        page.wait_for_timeout(2000)
    flags = final.get("flags") or {}
    checkpoint(
        checkpoints,
        "start_failed_timeout",
        flags=flags,
        first_missing=_first_missing_criterion(flags),
    )
    return {
        "start_success": False,
        "room_id": (final.get("state") or {}).get("room_id"),
        "flags": flags,
        "timeline": timeline,
        "elapsed_s": round(time.time() - t0, 1),
        "first_missing_criterion": _first_missing_criterion(flags),
    }


def _first_missing_criterion(flags: dict[str, bool]) -> str:
    order = (
        "setup_page_disappeared",
        "success_toast_or_room_id",
        "room_in_progress",
        "pause_draft_control",
        "current_pick_controls",
        "diag_mount_present",
        "diag_timer_10",
    )
    for k in order:
        if not flags.get(k):
            return k
    return ""


def first_checkpoint_divergence(
    passing: list[dict[str, Any]], failing: list[dict[str, Any]]
) -> dict[str, Any]:
    pass_steps = {c["step"] for c in passing}
    fail_steps = {c["step"] for c in failing}
    for i, fc in enumerate(failing):
        step = fc["step"]
        if step not in pass_steps:
            return {"divergence": "fail_only_step", "step": step, "row": fc, "index": i}
        pc = next((c for c in passing if c["step"] == step), None)
        if pc and step == "start_success_all_criteria":
            if fc.get("flags") != pc.get("flags"):
                return {"divergence": "criteria_mismatch", "step": step, "pass": pc, "fail": fc}
    return {"divergence": "unknown", "pass_count": len(passing), "fail_count": len(failing)}


def execute_solo_draft_start_workflow(
    page,
    setup_url: str = DEFAULT_SETUP_URL,
    *,
    navigate: bool = True,
) -> dict[str, Any]:
    """Run the exact diagnostic draft-start path on an existing page."""
    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from run_production_solo_soak import set_number
    from run_solo_clean_verification import scrape_live_sha

    checkpoints: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "setup_url": setup_url,
        "started_at": time.time(),
        "checkpoints": checkpoints,
    }
    if navigate:
        wake = goto_and_wake(page, setup_url, timeout_s=240)
        report["wake"] = wake
        page.wait_for_timeout(6000)
        record_query_checkpoint(checkpoints, "query_initial_url", setup_url=setup_url, page_url=page.url)

    sidebar_label = click_sidebar_for_ldr(page, settle_ms=8000)
    checkpoint(checkpoints, "sidebar_clicked", label=sidebar_label)
    record_query_checkpoint(checkpoints, "query_after_sidebar", setup_url=setup_url, page_url=page.url)

    setup_visible = "Start New Live Draft" in all_frames_text(page)
    qsnap = record_query_checkpoint(checkpoints, "query_setup_visible", setup_url=setup_url, page_url=page.url)
    checkpoint(
        checkpoints,
        "setup_visible",
        visible=setup_visible,
        deploy_sha=scrape_live_sha(page),
        page_url=page.url,
        query_ok=bool(qsnap.get("query_ok_vs_setup")),
        placement=_placement_from_setup_url(setup_url),
    )

    setup_before = page.evaluate(SCAN_SETUP_JS)
    if not setup_before.get("soloSelected"):
        page.evaluate(SOLO_RADIO_JS)
        page.wait_for_timeout(3000)
        setup_before = page.evaluate(SCAN_SETUP_JS)
    checkpoint(
        checkpoints,
        "solo_radio_selected",
        solo_selected=bool(setup_before.get("soloSelected")),
        radios=setup_before.get("radios"),
    )

    report["clear_stale"] = maybe_clear_stale_draft(page, checkpoints)
    teams_ok = set_number(page, "Number of Teams", "2")
    picks_ok = set_number(page, "Picks per Team", "8")
    page.wait_for_timeout(2500)
    setup_after = page.evaluate(SCAN_SETUP_JS)
    checkpoint(
        checkpoints,
        "setup_fields_interacted",
        set_teams=teams_ok,
        set_picks=picks_ok,
        numbers=setup_after.get("numbers"),
    )
    record_query_checkpoint(checkpoints, "query_before_start", setup_url=setup_url, page_url=page.url)

    report["start_click"] = dispatch_start_new_live_draft_click(page, checkpoints)
    record_query_checkpoint(checkpoints, "query_after_start_click", setup_url=setup_url, page_url=page.url)
    iso_case = _isolation_case_from_url(setup_url)
    placement = _placement_from_setup_url(setup_url)
    observe = observe_until_success_or_timeout(
        page,
        checkpoints,
        isolation_case=iso_case,
        placement=placement,
        setup_url=setup_url,
    )
    report.update(observe)
    report["start_success"] = bool(observe.get("start_success"))
    report["finished_at"] = time.time()
    return report


def run_fresh_context_start(setup_url: str = DEFAULT_SETUP_URL) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=BROWSER_LAUNCH_ARGS)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        report = execute_solo_draft_start_workflow(page, setup_url, navigate=True)
        context.close()
        browser.close()
    return report


def harness_proven_on_disk() -> bool:
    if not HARNESS_PROVEN_FILE.is_file():
        return False
    try:
        data = json.loads(HARNESS_PROVEN_FILE.read_text(encoding="utf-8"))
        return bool(data.get("proven")) and int(data.get("consecutive_passes") or 0) >= 3
    except (json.JSONDecodeError, OSError):
        return False
