"""Gate B production setup/start tracing — harness only (no app changes)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
START_SCREENSHOT_DIR = ROOT / "data" / "p8_production_start_screenshots"

INVALID_PRODUCTION_EXPIRATION_TRACE = "INVALID_PRODUCTION_EXPIRATION_TRACE"

START1 = "START1 — WRONG_PAGE_OR_SURFACE"
START2 = "START2 — START_CONTROL_NOT_FOUND"
START3 = "START3 — START_CONTROL_DISABLED"
START4 = "START4 — CLICK_DID_NOT_REGISTER"
START5 = "START5 — FORM_SUBMIT_REQUIRED"
START6 = "START6 — RERUN_OR_NAVIGATION_INTERRUPTED"
START7 = "START7 — ROOM_CREATED_BUT_NOT_LATCHED"
START8 = "START8 — ROOM_STATUS_NOT_IN_PROGRESS"
START9 = "START9 — COUNTDOWN_NOT_MOUNTED_AFTER_VALID_START"
START10 = "START10 — OTHER"

START_PROOF_KEYS = (
    "nonempty_room_id",
    "room_in_progress",
    "pick_index_zero",
    "deadline_present",
    "production_token_present",
    "countdown_mounted",
)

START_BUTTON_KEY = "live_draft_start_btn"
START_BUTTON_LABEL = "Start New Live Draft"


def dispatch_start_single_authoritative_click(page, checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    """One Playwright locator click only (evaluate used for inspection)."""
    if checkpoints and checkpoints[-1].get("_start_click_count", 0) >= 1:
        raise RuntimeError("duplicate_start_click_blocked")
    from solo_draft_start_harness import SCAN_BUTTONS_JS, checkpoint

    buttons = page.evaluate(SCAN_BUTTONS_JS) or []
    matches = [b for b in buttons if START_BUTTON_LABEL in str(b.get("text") or "")]
    enabled = [m for m in matches if m.get("visible") and not m.get("disabled")]
    inspect: dict[str, Any] = {
        "selector_found": bool(matches),
        "start_matches": matches,
        "disabled_at_click": bool(matches) and not enabled,
        "selector": f"role=button[name=/{START_BUTTON_LABEL}/i]",
        "widget_key": START_BUTTON_KEY,
        "start_click_count": 1,
    }
    checkpoint(
        checkpoints,
        "start_single_click_inspect",
        matches=len(matches),
        enabled=len(enabled),
    )
    dom_click_dispatched = False
    click_dispatch_started_at = time.time()
    intercept = False
    bbox: dict[str, Any] = {}
    if enabled:
        name_re = re.compile(re.escape(START_BUTTON_LABEL), re.I)
        for frame in page.frames:
            try:
                loc = frame.get_by_role("button", name=name_re)
                if loc.count() < 1 or loc.first.is_disabled():
                    continue
                box = loc.first.bounding_box()
                if box:
                    bbox = dict(box)
                loc.first.click(timeout=15000, force=True)
                dom_click_dispatched = True
                checkpoint(checkpoints, "start_single_click_playwright", frame=frame.url[:80])
                break
            except Exception as exc:
                checkpoint(checkpoints, "start_single_click_frame_skip", error=str(exc)[:120])
        if not dom_click_dispatched:
            try:
                loc = page.get_by_role("button", name=name_re)
                if loc.count() >= 1 and not loc.first.is_disabled():
                    bbox = loc.first.bounding_box() or {}
                    loc.first.click(timeout=15000, force=True)
                    dom_click_dispatched = True
            except Exception as exc:
                inspect["click_error"] = str(exc)[:300]
    click_dispatch_completed_at = time.time()
    inspect.update(
        {
            "dom_click_dispatched": dom_click_dispatched,
            "click_timestamp": click_dispatch_completed_at,
            "click_dispatch_started_at": click_dispatch_started_at,
            "click_dispatch_completed_at": click_dispatch_completed_at,
            "bounding_box": bbox,
            "click_intercepted": intercept,
        }
    )
    checkpoint(checkpoints, "_start_click_count", _start_click_count=1)
    return inspect


def capture_start_click_transport(page, *, click_ts: float) -> dict[str, Any]:
    """Summarize WebSocket BackMsg evidence after the single click."""
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    raw_log = page.evaluate("() => (window.__p8WsBoundaryLog || []).slice()") or []
    outbound = [e for e in raw_log if isinstance(e, dict) and e.get("direction") == "outbound"]
    after = [
        e
        for e in outbound
        if float(e.get("wall_ts_ms") or 0) >= (click_ts * 1000.0 - 50.0)
    ]
    decodes: list[dict[str, Any]] = []
    backmsg_sent = False
    rerun_in_msg = False
    widget_key_in_msg = False
    for entry in after[:12]:
        # Harness cannot recover raw bytes from log; use frame hints only unless extended.
        hint = str(entry.get("frame_type_hint") or "")
        if "rerun" in hint or "widget" in hint or "backmsg" in hint:
            backmsg_sent = True
        if hint:
            decodes.append({"frame_type_hint": hint, "byte_len": entry.get("byte_len")})
    try:
        page_hash = page.evaluate(
            """() => {
              const el = document.querySelector('#solo-production-ledger-diag');
              return el ? (el.getAttribute('data-page-script-hash') || '') : '';
            }"""
        )
    except Exception:
        page_hash = ""
    return {
        "outbound_frames_after_click": len(after),
        "streamlit_backmsg_sent": backmsg_sent or len(after) > 0,
        "python_rerun_started": False,
        "page_script_hash": page_hash,
        "ws_log_sample": after[:5],
        "backmsg_decodes": decodes,
        "widget_key": START_BUTTON_KEY,
    }


def scrape_stage1_ledger_rows(page) -> list[dict[str, Any]]:
    from stage1_ledger_browser_extract import extract_stage1_ledger_from_page

    try:
        ext = extract_stage1_ledger_from_page(page)
        rows = ext.get("rows") if isinstance(ext.get("rows"), list) else []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:
        return []

def _ts() -> float:
    return time.time()


def _step(
    timeline: list[dict[str, Any]],
    *,
    step: str,
    page,
    state: dict[str, Any] | None = None,
    grade: dict[str, Any] | None = None,
    action: str = "",
    result: str = "",
    first_missing: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    row: dict[str, Any] = {
        "ts": _ts(),
        "step": step,
        "page_url": getattr(page, "url", "") if page else "",
        "action_attempted": action,
        "action_result": result,
        "first_missing_condition": first_missing,
    }
    if state:
        row.update(
            {
                "visible_surface": _visible_surface(state),
                "room_id": state.get("room_id") or "",
                "draft_status": "in_progress" if state.get("in_progress") else (
                    "setup" if state.get("setup_start_visible") else "unknown"
                ),
                "pick_index": state.get("pick_index"),
                "deadline": state.get("deadline"),
                "expected_token": state.get("production_token") or state.get("expire_token") or "",
                "countdown_mounted": _countdown_mounted(state),
            }
        )
    if grade:
        row["grade_checks"] = dict(grade.get("checks") or {})
        row["authoritative_grade_pass"] = bool(grade.get("pass"))
    if extra:
        row.update(extra)
    timeline.append(row)


def _visible_surface(state: dict[str, Any]) -> str:
    if state.get("setup_start_visible"):
        return "setup_lobby"
    if state.get("in_progress"):
        return "draft_in_progress"
    return "unknown"


def _countdown_mounted(state: dict[str, Any]) -> bool:
    try:
        from scripts.p8_diagnostic_setup import _countdown_mounted as _cm
    except ImportError:
        from p8_diagnostic_setup import _countdown_mounted as _cm  # type: ignore[no-redef]

    return _cm(state)


def start_proof_from_state(state: dict[str, Any], grade: dict[str, Any]) -> dict[str, bool]:
    checks = grade.get("checks") or {}
    return {
        "nonempty_room_id": bool(checks.get("nonempty_room_id")),
        "room_in_progress": bool(checks.get("room_in_progress")),
        "pick_index_zero": bool(checks.get("pick_index_zero")),
        "deadline_present": bool(checks.get("deadline_exists")),
        "production_token_present": bool(checks.get("production_token")),
        "countdown_mounted": _countdown_mounted(state),
    }


def all_start_proof_true(proof: dict[str, bool]) -> bool:
    return all(proof.get(k) for k in START_PROOF_KEYS)


def first_missing_start_proof(proof: dict[str, bool]) -> str:
    for k in START_PROOF_KEYS:
        if not proof.get(k):
            return k
    return ""


def classify_production_start_boundary(
    *,
    ldr_surface: dict[str, Any],
    click_result: dict[str, Any],
    state: dict[str, Any],
    grade: dict[str, Any],
    proof: dict[str, bool],
    draft_legacy: dict[str, Any] | None = None,
) -> str:
    """Map observed harness state to START1–START10."""
    url = str(state.get("url") or "")
    on_ldr = "Live Draft Room" in url or "active_page=Live" in url
    setup_visible = bool(state.get("setup_start_visible"))
    if not on_ldr and not setup_visible and not state.get("in_progress"):
        return START1
    if not ldr_surface.get("setup_visible") and not ldr_surface.get("live_draft_main_marker"):
        if not state.get("in_progress"):
            return START1

    matches = click_result.get("start_matches") or []
    enabled = [m for m in matches if m.get("visible") and not m.get("disabled")]
    if not matches and not state.get("in_progress"):
        return START2
    if matches and not enabled and not state.get("in_progress"):
        return START3

    clicked = bool(
        click_result.get("playwright_clicked")
        or click_result.get("evaluate_click_dispatched")
    )
    if draft_legacy and not clicked and not proof.get("nonempty_room_id"):
        return START4

    if click_result.get("url_changed") and not on_ldr and not proof.get("room_in_progress"):
        return START6

    checks = grade.get("checks") or {}
    rid = str(state.get("room_id") or "")
    if rid and not checks.get("room_in_progress"):
        if checks.get("nonempty_room_id"):
            return START8
        return START7
    if checks.get("nonempty_room_id") and not checks.get("fresh_room_id"):
        return START7
    if grade.get("pass") and not proof.get("countdown_mounted"):
        return START9
    if not checks.get("pick_index_zero") and checks.get("room_in_progress"):
        return START10
    if not checks.get("production_token") and checks.get("room_in_progress"):
        return START10
    missing = first_missing_start_proof(proof)
    if missing == "countdown_mounted" and all(
        proof.get(k) for k in START_PROOF_KEYS if k != "countdown_mounted"
    ):
        return START9
    if missing:
        return START10
    return START10


def _save_failure_screenshot(page, label: str) -> str:
    START_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = START_SCREENSHOT_DIR / f"{label}_{int(time.time())}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return ""


def wait_for_start_proof(
    page,
    *,
    prior_room_id: str,
    start_click_dispatched: bool,
    timeline: list[dict[str, Any]],
    max_wait_s: float = 90.0,
    poll_ms: int = 1500,
) -> dict[str, Any]:
    from production_draft_start_authoritative import (
        grade_authoritative_draft_start,
        scrape_authoritative_start_state,
    )

    t0 = time.time()
    last_state: dict[str, Any] = {}
    last_grade: dict[str, Any] = {}
    last_proof: dict[str, bool] = {}
    while time.time() - t0 < max_wait_s:
        last_state = scrape_authoritative_start_state(page)
        last_grade = grade_authoritative_draft_start(
            last_state,
            prior_room_id=prior_room_id,
            start_click_dispatched=start_click_dispatched,
        )
        last_proof = start_proof_from_state(last_state, last_grade)
        _step(
            timeline,
            step="state_poll",
            page=page,
            state=last_state,
            grade=last_grade,
            action="wait_for_start_proof",
            result="polling",
            first_missing=first_missing_start_proof(last_proof),
            extra={"elapsed_s": round(time.time() - t0, 2), "proof": last_proof},
        )
        if all_start_proof_true(last_proof):
            return {
                "valid": True,
                "authoritative_state": last_state,
                "authoritative_grade": last_grade,
                "start_proof": last_proof,
                "latched_room_id": str(last_state.get("room_id") or "").upper(),
                "elapsed_s": round(time.time() - t0, 2),
            }
        page.wait_for_timeout(poll_ms)

    return {
        "valid": False,
        "authoritative_state": last_state,
        "authoritative_grade": last_grade,
        "start_proof": last_proof,
        "elapsed_s": round(time.time() - t0, 2),
    }


def run_gate_b_production_start(
    page,
    setup_url: str,
    *,
    prior_room_id: str = "",
    auth_preflight: dict[str, Any] | None = None,
    browser_context: Any | None = None,
) -> dict[str, Any]:
    """Delegate to canonical shared start helper (single implementation)."""
    from p8_canonical_production_start import establish_single_solo_live_draft

    ctx = browser_context
    if ctx is None:
        try:
            ctx = page.context
        except Exception:
            ctx = None
    if ctx is None:
        return {
            "valid": False,
            "failure_boundary": f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP",
            "start_boundary": START10,
            "timeline": [],
        }
    result = establish_single_solo_live_draft(
        page,
        ctx,
        setup_url=setup_url,
        prior_room_id=prior_room_id,
        fresh_lobby_cleanup=True,
    )
    result.setdefault("timeline", [])
    if not result.get("valid"):
        from p8_production_start_harness import _save_failure_screenshot

        label = str(result.get("start_boundary") or "harness_start_fail").split(" ")[0].lower()
        result["screenshot"] = _save_failure_screenshot(page, label)
        result["failure_boundary"] = f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP"
    return result
