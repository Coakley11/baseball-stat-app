"""DRAFT-START-ONLY reliability gate — live Cloud, authenticated, no expiration."""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
REQUIRED_CLOUD_SHA = "d986cda"
OUT = ROOT / "data" / "production_draft_start_only_gate.json"
SHOT_BEFORE = ROOT / "data" / "production_draft_start_only_gate_before.png"
SHOT_AFTER = ROOT / "data" / "production_draft_start_only_gate_after.png"
PROVISIONAL_ROOM_HINT = "6E7FD536"
POST_CLICK_POLL_S = 45
DIAG_TIMER_S = 60

from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from production_draft_start_authoritative import (  # noqa: E402
    classify_start_gate_failure,
    grade_authoritative_draft_start,
    scrape_authoritative_start_state,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402


def gate_setup_url() -> str:
    base = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_component_diag=1&solo_diag_timer={DIAG_TIMER_S}"
    )
    return append_suite_sid_to_url(base)


def _suite_sid(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    return str((q.get("suite_sid") or [""])[0])


def _record_start_button(page) -> dict[str, Any]:
    from solo_draft_start_harness import SCAN_BUTTONS_JS

    buttons = page.evaluate(SCAN_BUTTONS_JS)
    matches = [b for b in buttons if "Start New Live Draft" in str(b.get("text") or "")]
    enabled = [m for m in matches if m.get("visible") and not m.get("disabled")]
    return {
        "matches": matches,
        "enabled_count": len(enabled),
        "duplicate": len(matches) != 1,
    }


def _abandon_control_room(page, room_id: str) -> dict[str, Any]:
    from run_production_solo_soak import click_btn

    out: dict[str, Any] = {"room_id": room_id, "end_delete_clicked": False}
    try:
        click_btn(page, "End/Delete Draft", wait_ms=5000)
        out["end_delete_clicked"] = True
        page.wait_for_timeout(4000)
        click_btn(page, "Confirm End/Delete", wait_ms=5000)
        page.wait_for_timeout(6000)
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


def main() -> int:
    run_id = str(uuid.uuid4())
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    preflight = run_preflight()
    if not preflight.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby
    from run_solo_clean_verification import scrape_live_sha
    from solo_draft_start_harness import (
        SOLO_RADIO_JS,
        click_sidebar_for_ldr,
        dispatch_start_new_live_draft_click,
    )
    from run_production_solo_soak import set_number

    report: dict[str, Any] = {
        "run_id": run_id,
        "gate": "DRAFT_START_ONLY",
        "required_cloud_sha": REQUIRED_CLOUD_SHA,
        "diag_timer_seconds": DIAG_TIMER_S,
        "provisional_run_classification": "INVALID_STAGE1A_START_OBSERVATION",
        "provisional_room_hint": PROVISIONAL_ROOM_HINT,
        "started_at": time.time(),
    }
    page_errors: list[str] = []
    selector_timeline: list[dict[str, Any]] = []

    url = gate_setup_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()

        def _on_console(msg) -> None:
            if msg.type in ("error", "warning"):
                page_errors.append(f"{msg.type}:{msg.text}"[:300])

        page.on("console", _on_console)
        page.on("pageerror", lambda exc: page_errors.append(f"pageerror:{exc}"[:300]))

        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        live_sha = (scrape_live_sha(page) or "").lower()[:7]
        report["cloud_sha"] = live_sha
        if live_sha != REQUIRED_CLOUD_SHA:
            report["aborted"] = True
            report["abort_reason"] = "cloud_sha_mismatch"
            context.close()
            browser.close()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 1

        sid_before = _suite_sid(page.url)
        cleanup = ensure_fresh_setup_lobby(page)
        report["preflight_cleanup"] = cleanup
        prior_room = str(cleanup.get("detected_room_id") or "").strip().upper()

        click_sidebar_for_ldr(page, settle_ms=6000)
        pre_auth = scrape_authoritative_start_state(page)
        pre_btn = _record_start_button(page)
        report["step1_pre_click"] = {
            "url": page.url,
            "active_page_query": parse_qs(urlparse(page.url).query).get("active_page"),
            "start_button": pre_btn,
            "authoritative": pre_auth,
            "prior_room_id": prior_room,
        }
        page.screenshot(path=str(SHOT_BEFORE), full_page=True)

        page.evaluate(SOLO_RADIO_JS)
        page.wait_for_timeout(2000)
        set_number(page, "Number of Teams", "2")
        set_number(page, "Picks per Team", "8")
        page.wait_for_timeout(2000)

        checkpoints: list[dict[str, Any]] = []
        t_click = time.time()
        click_meta = dispatch_start_new_live_draft_click(page, checkpoints)
        click_meta["click_started_at"] = t_click
        click_meta["click_ended_at"] = time.time()
        click_meta["start_button_enabled_count"] = pre_btn.get("enabled_count")
        click_meta["evaluate_click_dispatched"] = any(
            c.get("step") == "start_click_evaluate_dispatched" for c in checkpoints
        )
        report["step2_click"] = click_meta
        report["click_checkpoints"] = checkpoints

        poll_deadline = time.time() + POST_CLICK_POLL_S
        best_grade: dict[str, Any] = {}
        best_state: dict[str, Any] = {}
        latched_at: float | None = None
        while time.time() < poll_deadline:
            state = scrape_authoritative_start_state(page)
            state["page_errors"] = list(page_errors)
            grade = grade_authoritative_draft_start(
                state,
                prior_room_id=prior_room,
                start_click_dispatched=bool(click_meta.get("evaluate_click_dispatched")),
            )
            selector_timeline.append(
                {
                    "ts": time.time(),
                    "elapsed_since_click_s": round(time.time() - t_click, 2),
                    "room_id": state.get("room_id"),
                    "pick_index": state.get("pick_index"),
                    "in_progress": state.get("in_progress"),
                    "deadline": state.get("deadline"),
                    "token_present": bool(state.get("production_token")),
                    "setup_start_visible": state.get("setup_start_visible"),
                    "pause_count": state.get("pause_draft_count"),
                    "authoritative_pass": grade.get("pass"),
                }
            )
            if grade.get("pass") and not best_grade.get("pass"):
                best_grade = grade
                best_state = state
                latched_at = time.time()
                break
            if grade.get("pass") or (
                state.get("room_id") and not best_state.get("room_id")
            ):
                best_grade = grade
                best_state = state
            page.wait_for_timeout(2000)

        sid_after = _suite_sid(page.url)
        session_continuity = {
            "suite_sid_before": sid_before,
            "suite_sid_after": sid_after,
            "session_changed": bool(sid_before and sid_after and sid_before != sid_after),
            "url_before_click": report["step1_pre_click"]["url"],
            "url_after_poll": page.url,
        }
        report["session_continuity"] = session_continuity
        report["selector_timeline"] = selector_timeline
        report["authoritative_final"] = best_state
        report["authoritative_grade"] = best_grade
        report["page_errors"] = page_errors
        report["console_excerpt"] = page_errors[:40]

        provisional = {
            "hint_room_id": PROVISIONAL_ROOM_HINT,
            "this_run_room_id": best_state.get("room_id"),
            "same_as_hint": str(best_state.get("room_id") or "").upper() == PROVISIONAL_ROOM_HINT,
            "interpretation": (
                "provisional timer_10 + setup_disappeared likely real start; "
                "playwright_clicked=false consistent with Streamlit rerun detaching button"
            ),
        }
        if best_grade.get("pass"):
            provisional["interpretation"] = (
                f"authoritative latch confirms new room {best_state.get('room_id')}; "
                "provisional 6E7FD536 was likely real start not latched by legacy harness"
            )
        report["step5_provisional_resolution"] = provisional

        page.screenshot(path=str(SHOT_AFTER), full_page=True)

        if best_grade.get("pass"):
            report["verdict"] = "PASS_DRAFT_START_LATCHED"
            report["control_room_abandon"] = _abandon_control_room(
                page, str(best_state.get("room_id") or "")
            )
            report["finished_at"] = time.time()
            context.close()
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"verdict": report["verdict"], "room_id": best_state.get("room_id"), "artifact": str(OUT)}))
            return 0

        boundary = classify_start_gate_failure(
            pre=report["step1_pre_click"],
            click=click_meta,
            post=best_state,
            grade=best_grade,
            session_continuity=session_continuity,
        )
        report["verdict"] = "FAIL"
        report["first_failure_boundary"] = boundary
        report["finished_at"] = time.time()
        context.close()
        browser.close()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"verdict": "FAIL", "boundary": boundary, "artifact": str(OUT)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
