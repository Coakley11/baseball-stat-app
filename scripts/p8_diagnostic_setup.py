"""P8 focused diagnostic setup gate (harness only — no production app changes)."""

from __future__ import annotations

import re
import time
from typing import Any


def _page_heading_excerpt(page) -> str:
    try:
        from run_production_solo_soak import all_frames_text

        text = all_frames_text(page)
        priority = (
            "Start New Live Draft",
            "Time remaining",
            "Round 1",
            "On clock",
            "Pause Draft",
            "Live Draft Room",
            "Draft Setup",
        )
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for needle in priority:
            for s in lines:
                if needle in s and len(s) < 160:
                    return s[:200]
        for s in lines:
            if s and len(s) > 3 and len(s) < 120:
                if "Live Draft" in s or "Draft Room" in s:
                    return s[:200]
        return text[:200]
    except Exception:
        return ""


def _scrape_script_run_sequence(page) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-production-ledger-diag');
                if (!el) continue;
                const seq = el.getAttribute('data-script-run-seq') || el.getAttribute('data-run-seq') || '';
                const run = el.getAttribute('data-run-id') || '';
                return { script_run_sequence: seq, ledger_run_id: run, source: 'solo-production-ledger-diag' };
              }
              return { script_run_sequence: '', ledger_run_id: '', source: 'missing' };
            }"""
        ) or {}
    except Exception:
        return {"script_run_sequence": "", "ledger_run_id": "", "source": "error"}


def ensure_p8_ldr_setup_surface(page, *, setup_url: str) -> dict[str, Any]:
    """Harness-only: confirm Live Draft Room setup UI before draft start."""
    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from solo_draft_start_harness import click_sidebar_for_ldr, record_query_checkpoint

    out: dict[str, Any] = {"steps": []}
    if "active_page=Live+Draft+Room" not in page.url and "Live Draft Room" not in page.url:
        goto_and_wake(page, setup_url, timeout_s=120)
        page.wait_for_timeout(8000)
        out["steps"].append("navigated_to_ldr_url")
    label = click_sidebar_for_ldr(page, settle_ms=6000)
    out["steps"].append(f"sidebar_ldr:{label}")
    page.wait_for_timeout(4000)
    text = all_frames_text(page)
    if "Return to Live Draft" in text:
        try:
            from run_production_solo_soak import click_btn

            click_btn(page, "Return to Live Draft", wait_ms=4000)
            out["steps"].append("clicked_return_to_live_draft")
        except Exception:
            pass
    for _ in range(2):
        if "Start New Live Draft" in all_frames_text(page):
            break
        click_sidebar_for_ldr(page, settle_ms=4000)
        page.wait_for_timeout(3000)
        out["steps"].append("sidebar_ldr_retry")
    text_after = all_frames_text(page)
    out["setup_visible"] = "Start New Live Draft" in text_after
    out["live_draft_main_marker"] = any(
        m in text_after for m in ("Draft Setup", "Draft Mode", "Start New Live Draft", "Pause Draft")
    )
    out["url"] = page.url
    out["heading"] = _page_heading_excerpt(page)
    out["script_run"] = _scrape_script_run_sequence(page)
    if not out["setup_visible"] and not out["live_draft_main_marker"]:
        goto_and_wake(page, setup_url, timeout_s=120)
        page.wait_for_timeout(10000)
        click_sidebar_for_ldr(page, settle_ms=5000)
        page.wait_for_timeout(4000)
        out["steps"].append("recovery_goto_ldr_url")
        text_after = all_frames_text(page)
        out["setup_visible"] = "Start New Live Draft" in text_after
        out["live_draft_main_marker"] = "Draft Setup" in text_after or "Start New Live Draft" in text_after
    return out


def retry_draft_start_if_stalled(page, draft: dict[str, Any], *, setup_url: str) -> dict[str, Any]:
    """One harness retry when legacy observe failed but setup UI still visible."""
    from cloud_streamlit_wake import all_frames_text
    from solo_draft_start_harness import (
        dispatch_start_new_live_draft_click,
        observe_until_success_or_timeout,
    )

    if draft.get("start_success"):
        return draft
    if "Start New Live Draft" not in all_frames_text(page):
        return draft
    checkpoints: list[dict[str, Any]] = list(draft.get("checkpoints") or [])
    dispatch_start_new_live_draft_click(page, checkpoints)
    observe = observe_until_success_or_timeout(
        page,
        checkpoints,
        max_wait_s=60,
        setup_url=setup_url,
    )
    merged = dict(draft)
    merged.update(observe)
    merged["start_success"] = bool(observe.get("start_success"))
    merged["harness_start_retry"] = True
    merged["checkpoints"] = checkpoints
    return merged


def collect_setup_stage_diagnostics(
    page,
    *,
    draft: dict[str, Any] | None = None,
    auth_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from production_draft_start_authoritative import scrape_authoritative_start_state
    from run_production_solo_soak import all_frames_text, dom_counts

    auth_state = scrape_authoritative_start_state(page)
    text = all_frames_text(page)
    counts = dom_counts(page)
    flags = (draft or {}).get("flags") or {}
    setup_visible = "Start New Live Draft" in text
    on_ldr = "active_page=Live+Draft+Room" in page.url or "Live Draft Room" in page.url
    return {
        "url": page.url,
        "page_heading_excerpt": _page_heading_excerpt(page),
        "room_id": auth_state.get("room_id"),
        "room_status": "in_progress" if auth_state.get("in_progress") else ("setup" if setup_visible else "unknown"),
        "pick_index": auth_state.get("pick_index"),
        "deadline": auth_state.get("deadline"),
        "token": auth_state.get("production_token") or auth_state.get("expire_token"),
        "setup_controls_visible": setup_visible,
        "setup_page_disappeared_legacy_flag": bool(flags.get("setup_page_disappeared")),
        "setup_disappeared_because_navigation_succeeded": bool(
            auth_state.get("in_progress") and not setup_visible
        ),
        "returned_to_other_page": not on_ldr and not setup_visible,
        "streamlit_rerun_likely": setup_visible and bool(auth_state.get("in_progress")),
        "authenticated_restored": bool((auth_preflight or {}).get("authenticated_restored")),
        "pause_draft_count": auth_state.get("pause_draft_count"),
        "countdown_mount": auth_state.get("mount") or {},
        "countdown_mounted": str((auth_state.get("mount") or {}).get("mounted") or "") in ("1", "true"),
        "legacy_start_success": bool((draft or {}).get("start_success")),
        "legacy_first_missing": (draft or {}).get("first_missing_criterion"),
        "authoritative_in_progress": bool(auth_state.get("in_progress")),
        "script_run_seq_note": "from_production_ledger_dom_if_present",
        **(_scrape_script_run_sequence(page)),
    }


def _roster_validation_blocks_start(page) -> bool:
    try:
        from solo_draft_start_harness import MESSAGES_JS

        msgs = page.evaluate(MESSAGES_JS) or {}
        for alert in msgs.get("alerts") or []:
            if "Draft picks per team must be greater than or equal" in str(alert):
                return True
    except Exception:
        pass
    return False


def _countdown_mounted(auth_state: dict[str, Any]) -> bool:
    mount = auth_state.get("mount") or {}
    key = str(mount.get("key") or "")
    if key == "solo_countdown_wake_solo_persistent":
        return True
    if str(mount.get("mounted") or "") in ("1", "true") and str(mount.get("token") or ""):
        return True
    ui = auth_state.get("ui") or {}
    if ui.get("ccTimer") is not None:
        return True
    return bool(re.search(r"Time remaining:\s*10s", str(auth_state.get("text_excerpt") or ""), re.I))


def validate_p8_diagnostic_setup(
    page,
    draft: dict[str, Any],
    *,
    prior_room_id: str = "",
    auth_preflight: dict[str, Any] | None = None,
    max_wait_s: float = 75.0,
) -> dict[str, Any]:
    """
    Grade draft start from authoritative room state, not legacy setup-panel flags alone.
    """
    from production_draft_start_authoritative import (
        grade_authoritative_draft_start,
        scrape_authoritative_start_state,
    )

    t0 = time.time()
    timeline: list[dict[str, Any]] = []
    last_grade: dict[str, Any] = {}
    last_state: dict[str, Any] = {}
    while time.time() - t0 < max_wait_s:
        auth_state = scrape_authoritative_start_state(page)
        last_state = auth_state
        last_grade = grade_authoritative_draft_start(
            auth_state,
            prior_room_id=prior_room_id,
            start_click_dispatched=True,
        )
        diag = collect_setup_stage_diagnostics(page, draft=draft, auth_preflight=auth_preflight)
        diag["authoritative_grade_pass"] = bool(last_grade.get("pass"))
        diag["elapsed_setup_wait_s"] = round(time.time() - t0, 2)
        timeline.append(diag)
        if last_grade.get("pass") and _countdown_mounted(auth_state):
            rid = str(last_grade.get("room_id") or auth_state.get("room_id") or "").upper()
            return {
                "valid": True,
                "setup_gate": "PASS_AUTHORITATIVE_ROOM_STATE",
                "latched_room_id": rid,
                "visible_room_id": auth_state.get("visible_room_id") or rid,
                "draft_start_success": True,
                "in_progress": True,
                "authoritative_start": True,
                "authoritative_grade": last_grade,
                "authoritative_state": auth_state,
                "legacy_start_success": bool(draft.get("start_success")),
                "setup_stage_timeline": timeline,
                "setup_stage_final": diag,
            }
        page.wait_for_timeout(2000)

    final_diag = collect_setup_stage_diagnostics(page, draft=draft, auth_preflight=auth_preflight)
    checks = last_grade.get("checks") or {}
    boundary = "PRE_EXPIRATION_SETUP_UNKNOWN"
    if not checks.get("nonempty_room_id"):
        boundary = "PRE_EXPIRATION_SETUP_ROOM_NOT_CREATED"
    elif not checks.get("room_in_progress"):
        boundary = "PRE_EXPIRATION_SETUP_NOT_IN_PROGRESS"
    elif not checks.get("pick_index_zero"):
        boundary = "PRE_EXPIRATION_SETUP_PICK_INDEX"
    elif not checks.get("deadline_exists") or not checks.get("production_token"):
        boundary = "PRE_EXPIRATION_SETUP_DEADLINE_OR_TOKEN"
    elif _roster_validation_blocks_start(page):
        boundary = "PRE_EXPIRATION_SETUP_ROSTER_VALIDATION"
    elif not _countdown_mounted(last_state):
        boundary = "PRE_EXPIRATION_SETUP_COUNTDOWN_NOT_MOUNTED"
    elif draft.get("first_missing_criterion") == "setup_page_disappeared" and checks.get("room_in_progress"):
        boundary = "PRE_EXPIRATION_SETUP_LEGACY_FALSE_NEGATIVE"
    elif not draft.get("start_success"):
        boundary = "PRE_EXPIRATION_SETUP_DRAFT_START_LEGACY_FALSE"

    return {
        "valid": False,
        "verdict": "INVALID_DIAGNOSTIC_SETUP_ABORT",
        "reason": boundary,
        "failure_boundary": "PRE_EXPIRATION_SETUP",
        "draft_start": draft,
        "authoritative_grade": last_grade,
        "authoritative_state": last_state,
        "setup_stage_timeline": timeline,
        "setup_stage_final": final_diag,
        "legacy_first_missing": draft.get("first_missing_criterion"),
    }


def classify_focused_p8_outcome(
    *,
    setup_valid: bool,
    setup_abort_reason: str,
    python_chain: dict[str, Any],
    gate_rows: list[dict[str, Any]],
    browser_send: dict[str, Any],
    filtered_meta: dict[str, Any],
) -> str:
    if not setup_valid:
        return "INVALID_DIAGNOSTIC_SETUP_ABORT"

    pass_gates = [
        r
        for r in gate_rows
        if str(r.get("decision") or "") in ("pass_direct_component_return", "pass_same_key_session_state")
    ]
    if not browser_send.get("postmessage_attempted"):
        return "INVALID_DIAGNOSTIC_SETUP_ABORT"

    if not pass_gates and not python_chain.get("bound_in_python_surfaces"):
        return "P8BIND4 — DIRECT_RETURN_AND_SESSION_STATE_EMPTY"

    if pass_gates and not python_chain.get("bound_in_python_surfaces"):
        return "P8C7 — COMPONENT_RETURN_BOUND_ON_LATER_SCRIPT_RUN"

    obs = int(python_chain.get("delivery_only_observation_events") or 0)
    flush = int(python_chain.get("post_bind_flush_events") or 0)
    if pass_gates and not obs and not flush:
        return "P8C5 — POST_BIND_ORCHESTRATION_NOT_DISPATCHED"

    if (obs or flush) and not python_chain.get("return_value_session_bind_entry_events"):
        return "P8BIND6 — BOUND_VALUE_NOT_FORWARDED_TO_PROCESSING"

    if python_chain.get("reaches_process_with_exact_token") and pass_gates:
        snapshot_pass = any(
            str(g.get("expected_token_source") or "") == "validated_declaration_snapshot"
            for g in pass_gates
        )
        if not snapshot_pass:
            return "P8C7 — COMPONENT_RETURN_BOUND_ON_LATER_SCRIPT_RUN"
        prov_ok = _provenance_ok(filtered_meta.get("filtered_rows") or [], python_chain.get("exact_token") or "")
        if prov_ok:
            return "FOCUSED_P8_BINDING_PASS"

    if not python_chain.get("bound_in_python_surfaces"):
        return "P8BIND4 — DIRECT_RETURN_AND_SESSION_STATE_EMPTY"
    return "P8BIND6 — BOUND_VALUE_NOT_FORWARDED_TO_PROCESSING"


def _provenance_ok(rows: list[dict[str, Any]], token: str) -> bool:
    if not token:
        return False
    obs = [
        r
        for r in rows
        if isinstance(r, dict) and r.get("event") == "production_stage1_delivery_only_observation_completed"
    ]
    flush = [
        r for r in rows if isinstance(r, dict) and r.get("event") == "production_stage1_post_bind_actionable_flush"
    ]
    for row in obs + flush:
        bt = str(row.get("bound_token") or row.get("token") or "")
        src = str(row.get("bound_token_source") or row.get("candidate_source") or "")
        if bt != token:
            return False
        if src not in ("direct_component_return", "same_key_session_state"):
            if row.get("exact_match") is not True:
                return False
    return bool(obs or flush)


def score_bound_token_gate_rows(gate_rows: list[dict[str, Any]], expected_token: str) -> dict[str, Any]:
    expected = str(expected_token or "").strip()
    passing = [
        r
        for r in gate_rows
        if str(r.get("decision") or "")
        in ("pass_direct_component_return", "pass_same_key_session_state")
        and str(r.get("selected_bound_token") or r.get("exact_expected_expiration_token") or "") == expected
    ]
    failing_mount = [r for r in gate_rows if str(r.get("decision") or "") == "reject_mount_token_not_bound"]
    failing_pending = [r for r in gate_rows if str(r.get("decision") or "") == "reject_pending_token_not_bound"]
    return {
        "gate_event_count": len(gate_rows),
        "passing_gate_count": len(passing),
        "passing_gates": passing,
        "reject_mount_count": len(failing_mount),
        "reject_pending_count": len(failing_pending),
        "required_decisions": ["pass_direct_component_return", "pass_same_key_session_state"],
    }
