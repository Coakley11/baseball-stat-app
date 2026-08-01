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
) -> dict[str, Any]:
    """
    One setup + one start click + state-based proof gate (no duplicate starts).
    """
    from cloud_streamlit_wake import all_frames_text
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface
    from production_draft_start_authoritative import scrape_authoritative_start_state
    from solo_draft_start_harness import (
        SCAN_SETUP_JS,
        SOLO_RADIO_JS,
        checkpoint,
        dispatch_start_new_live_draft_click,
        ensure_solo_setup_picks_meet_roster,
        maybe_clear_stale_draft,
        set_number_via_playwright,
    )

    timeline: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    out: dict[str, Any] = {
        "timeline": timeline,
        "checkpoints": checkpoints,
        "start_attempts": 1,
    }

    ldr = ensure_p8_ldr_setup_surface(page, setup_url=setup_url)
    out["ldr_surface"] = ldr
    state = scrape_authoritative_start_state(page)
    _step(
        timeline,
        step="live_draft_page_visible",
        page=page,
        state=state,
        action="ensure_p8_ldr_setup_surface",
        result="ok" if ldr.get("setup_visible") or ldr.get("live_draft_main_marker") else "fail",
        first_missing="" if (ldr.get("setup_visible") or ldr.get("live_draft_main_marker")) else "setup_not_visible",
        extra={"ldr_steps": ldr.get("steps"), "heading": ldr.get("heading")},
    )
    if not (ldr.get("setup_visible") or ldr.get("live_draft_main_marker") or state.get("in_progress")):
        out["screenshot"] = _save_failure_screenshot(page, "start1_surface")
        out["start_boundary"] = START1
        out["valid"] = False
        out["failure_boundary"] = f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP"
        return out

    setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
    if not setup_scan.get("soloSelected"):
        page.evaluate(SOLO_RADIO_JS)
        page.wait_for_timeout(2000)
        setup_scan = page.evaluate(SCAN_SETUP_JS) or {}
    _step(
        timeline,
        step="solo_mode_selected",
        page=page,
        state=scrape_authoritative_start_state(page),
        action="select_solo_radio",
        result="ok" if setup_scan.get("soloSelected") else "fail",
        first_missing="" if setup_scan.get("soloSelected") else "solo_not_selected",
        extra={"radios": setup_scan.get("radios")},
    )

    maybe_clear_stale_draft(page, checkpoints)
    set_number_via_playwright(page, "Number of Teams", "2")
    picks_gate = ensure_solo_setup_picks_meet_roster(page, checkpoints)
    page.wait_for_timeout(1500)
    _step(
        timeline,
        step="setup_lobby_ready",
        page=page,
        state=scrape_authoritative_start_state(page),
        action="configure_teams_picks",
        result="ok" if picks_gate.get("picks_ok") else "partial",
        extra={"picks_gate": picks_gate},
    )

    if state.get("in_progress") and _countdown_mounted(state):
        proof = start_proof_from_state(
            state,
            {
                "checks": {
                    "nonempty_room_id": bool(state.get("room_id")),
                    "room_in_progress": True,
                    "pick_index_zero": state.get("pick_index") == 0,
                    "deadline_exists": bool(state.get("deadline")),
                    "production_token": bool(state.get("production_token")),
                }
            },
        )
        if all_start_proof_true(proof):
            out["valid"] = True
            out["authoritative_state"] = state
            out["latched_room_id"] = str(state.get("room_id") or "").upper()
            out["start_proof"] = proof
            out["reused_existing_room"] = True
            return out

    click = dispatch_start_new_live_draft_click(page, checkpoints)
    evaluate_dispatched = any(
        c.get("step") == "start_click_evaluate_dispatched" and c.get("evaluate_clicked")
        for c in checkpoints
    )
    click["evaluate_click_dispatched"] = evaluate_dispatched
    url_changed = any(c.get("url_changed") for c in checkpoints if c.get("step") == "streamlit_rerun_detected")
    click["url_changed"] = url_changed
    label = "Start New Live Draft"
    _step(
        timeline,
        step="start_action_submitted",
        page=page,
        state=scrape_authoritative_start_state(page),
        action=f"click:{label}",
        result="submitted" if (click.get("playwright_clicked") or evaluate_dispatched) else "not_registered",
        extra={
            "start_selector": "button[role=button]:has-text('Start New Live Draft')",
            "start_label": label,
            "start_matches": click.get("start_matches"),
            "playwright_clicked": click.get("playwright_clicked"),
            "evaluate_click_dispatched": evaluate_dispatched,
        },
    )

    proof_wait = wait_for_start_proof(
        page,
        prior_room_id=prior_room_id,
        start_click_dispatched=bool(click.get("playwright_clicked") or evaluate_dispatched),
        timeline=timeline,
        max_wait_s=90.0,
    )
    out.update(proof_wait)
    out["start_click"] = click
    draft_legacy = {"start_success": False, "first_missing_criterion": ""}

    if proof_wait.get("valid"):
        out["setup_gate"] = "PASS_POSITIVE_START_PROOF"
        return out

    state_f = proof_wait.get("authoritative_state") or {}
    grade_f = proof_wait.get("authoritative_grade") or {}
    proof_f = proof_wait.get("start_proof") or {}
    boundary = classify_production_start_boundary(
        ldr_surface=ldr,
        click_result=click,
        state=state_f,
        grade=grade_f,
        proof=proof_f,
        draft_legacy=draft_legacy,
    )
    out["start_boundary"] = boundary
    out["valid"] = False
    out["failure_boundary"] = f"{INVALID_PRODUCTION_EXPIRATION_TRACE} — PRE_EXPIRATION_SETUP"
    out["screenshot"] = _save_failure_screenshot(page, boundary.split(" ")[0].lower())
    _step(
        timeline,
        step="start_proof_failed",
        page=page,
        state=state_f,
        grade=grade_f,
        action="gate",
        result="fail",
        first_missing=first_missing_start_proof(proof_f),
        extra={"start_boundary": boundary},
    )
    return out
