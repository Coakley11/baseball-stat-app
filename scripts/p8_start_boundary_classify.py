"""Classify Live Draft start pipeline boundaries (harness)."""

from __future__ import annotations

from typing import Any

START1 = "START1 — WRONG_PAGE_OR_SURFACE"
START2 = "START2 — START_CONTROL_NOT_FOUND"
START3 = "START3 — START_CONTROL_DISABLED_OR_OBSCURED"
START4A = "START4A — DOM_CLICK_NOT_DISPATCHED"
START4B = "START4B — DOM_CLICK_DISPATCHED_BUT_NO_STREAMLIT_BACKMSG"
START4C = "START4C — STREAMLIT_BACKMSG_SENT_BUT_NO_PYTHON_RERUN"
START5 = "START5 — FORM_SUBMIT_REQUIRED_OR_WRONG_CONTROL"
START6 = "START6 — PYTHON_RERUN_OCCURRED_BUT_LDR_BRANCH_SKIPPED"
START7 = "START7 — LDR_BRANCH_RAN_BUT_BUTTON_VALUE_FALSE"
START8 = "START8 — BUTTON_TRUE_BUT_START_HANDLER_NOT_ENTERED"
START9A = "START9A — START_HANDLER_ENTERED_BUT_ROOM_CREATION_NOT_CALLED"
START9B = "START9B — ROOM_CREATION_CALLED_AND_FAILED"
START9C = "START9C — ROOM_CREATED_BUT_SESSION_STATE_NOT_LATCHED"
START9D = "START9D — ROOM_LATCHED_BUT_STATUS_NOT_IN_PROGRESS"
START9E = "START9E — IN_PROGRESS_ROOM_EXISTS_BUT_COUNTDOWN_NOT_MOUNTED"
START10 = "START10 — OTHER"
START_ACTION_DOM_CLICKED_BUT_SERVER_OUTCOME_UNRESOLVED = (
    "START_ACTION_DOM_CLICKED_BUT_SERVER_OUTCOME_UNRESOLVED"
)
START_PIPELINE_PASS = "START_PIPELINE_PASS"

EVENT_GLOBAL = "production_global_script_run_canary"
EVENT_LDR = "production_live_draft_branch_canary"
EVENT_BTN_VAL = "production_stage1_start_button_value"
EVENT_HANDLER_IN = "production_stage1_start_handler_entered"
EVENT_HANDLER_OUT = "production_stage1_start_handler_exited"
EVENT_ROOM_IN = "production_stage1_room_creation_entered"
EVENT_ROOM_OUT = "production_stage1_room_creation_exited"


def _rows(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [r for r in events if isinstance(r, dict) and str(r.get("event") or "") == name]


def _after_ts(rows: list[dict[str, Any]], click_ts: float) -> list[dict[str, Any]]:
    if not click_ts:
        return rows
    return [r for r in rows if float(r.get("ts") or 0) >= click_ts - 0.05]


def _start_success_proven(
    audit: dict[str, Any],
    reconciled_audit: dict[str, Any],
    authoritative_state: dict[str, Any],
    click_transport: dict[str, Any],
) -> bool:
    created = str(
        reconciled_audit.get("inferred_created_room_id")
        or authoritative_state.get("room_id")
        or ""
    ).strip()
    if audit.get("handler_exited") and created:
        return True
    if audit.get("room_creation_exited") and created:
        return True
    if audit.get("handler_entered") and created and authoritative_state.get("in_progress"):
        return True
    if (
        click_transport.get("dom_click_dispatched")
        and created
        and (audit.get("handler_entered") or reconciled_audit.get("handler_entered_count"))
    ):
        return True
    return False


def _button_rows_for_click_run(
    rows: list[dict[str, Any]],
    *,
    click_ts: float,
    handler_entered: bool,
) -> list[dict[str, Any]]:
    btn = _rows(rows, EVENT_BTN_VAL)
    if not btn or not click_ts:
        return btn
    if handler_entered:
        seqs = [int(r.get("script_run_seq") or 0) for r in btn if float(r.get("ts") or 0) <= click_ts + 2.0]
        click_run = min(seqs) if seqs else 0
        if click_run:
            return [r for r in btn if int(r.get("script_run_seq") or 0) <= click_run]
        return [r for r in btn if float(r.get("ts") or 0) <= click_ts + 1.0]
    return btn[-3:]


def classify_start_boundary(
    *,
    ldr_surface: dict[str, Any],
    click_transport: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    authoritative_state: dict[str, Any],
    start_proof: dict[str, bool],
    click_ts: float = 0.0,
    reconciled_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return classification and first missing server event."""
    rows = _after_ts(ledger_rows, click_ts)
    recon = reconciled_audit or {}
    audit: dict[str, Any] = {
        "global_canary": bool(_rows(rows, EVENT_GLOBAL)),
        "ldr_branch_canary": bool(_rows(rows, EVENT_LDR)),
        "button_value_rows": len(_rows(rows, EVENT_BTN_VAL)),
        "handler_entered": max(len(_rows(rows, EVENT_HANDLER_IN)), int(recon.get("handler_entered_count") or 0)),
        "handler_exited": max(len(_rows(rows, EVENT_HANDLER_OUT)), int(recon.get("handler_exited_count") or 0)),
        "room_creation_entered": len(_rows(rows, EVENT_ROOM_IN)),
        "room_creation_exited": max(
            len(_rows(rows, EVENT_ROOM_OUT)),
            int(recon.get("room_creation_exited_count") or 0),
        ),
        "reconciled_audit_used": bool(recon),
    }
    dom_clicked = bool(click_transport.get("dom_click_dispatched"))
    ws_sent = bool(click_transport.get("streamlit_backmsg_sent"))
    rerun_seen = bool(click_transport.get("python_rerun_started")) or audit["global_canary"]
    server_chain_started = rerun_seen or audit["handler_entered"] > 0 or audit["ldr_branch_canary"]

    if not ldr_surface.get("setup_visible") and not ldr_surface.get("live_draft_main_marker"):
        if not authoritative_state.get("in_progress"):
            return _out(START1, audit, "setup_surface_not_visible")

    if not click_transport.get("selector_found"):
        return _out(START2, audit, "start_control_not_found")

    if click_transport.get("disabled_at_click"):
        return _out(START3, audit, "start_control_disabled")

    if click_transport.get("click_intercepted"):
        return _out(START3, audit, "click_obscured")

    if not dom_clicked:
        return _out(START4A, audit, "dom_click_not_dispatched")

    if dom_clicked and not ws_sent and not server_chain_started:
        audit["ws_capture_empty_supplemental_only"] = True
        return _out(START4B, audit, "no_streamlit_backmsg_after_click")

    if ws_sent and not rerun_seen and not server_chain_started:
        return _out(START4C, audit, "no_python_rerun_canary")

    if rerun_seen and not audit["ldr_branch_canary"]:
        return _out(START6, audit, "ldr_branch_canary_missing")

    if _start_success_proven(audit, recon, authoritative_state, click_transport):
        audit["start_success_supersedes_transient_button"] = True
        if all(start_proof.values()):
            return _out(START_PIPELINE_PASS, audit, "")
        if str(authoritative_state.get("room_id") or recon.get("inferred_created_room_id") or ""):
            return _out(START_PIPELINE_PASS, audit, "start_success_with_partial_ui_proof")

    btn_rows = _button_rows_for_click_run(
        rows, click_ts=click_ts, handler_entered=audit["handler_entered"] > 0
    )
    if btn_rows and not any(r.get("on_click_callback_armed") for r in btn_rows):
        if not any(r.get("start_pending") for r in btn_rows):
            if not _start_success_proven(audit, recon, authoritative_state, click_transport):
                return _out(START7, audit, "button_value_not_armed")

    if audit["ldr_branch_canary"] and not audit["handler_entered"]:
        inferred = str(recon.get("inferred_created_room_id") or "").strip()
        if inferred or audit["handler_exited"] or audit["room_creation_exited"]:
            audit["start8_suppressed"] = "authoritative_room_or_handler_in_reconciled_ledger"
        else:
            return _out(START8, audit, "start_handler_not_entered")

    if audit["handler_entered"] and not audit["room_creation_entered"]:
        if dom_clicked and ws_sent and rerun_seen:
            return _out(START9A, audit, "room_creation_not_entered")

    room_out = _rows(rows, EVENT_ROOM_OUT)
    if audit["room_creation_entered"] and room_out and not any(
        r.get("room_creation_success") for r in room_out
    ):
        return _out(START9B, audit, "room_creation_failed")

    if room_out and any(r.get("room_creation_success") for r in room_out):
        if not str(authoritative_state.get("room_id") or ""):
            return _out(START9C, audit, "room_not_in_session_state")

    if str(authoritative_state.get("room_id") or "") and not authoritative_state.get("in_progress"):
        return _out(START9D, audit, "status_not_in_progress")

    if authoritative_state.get("in_progress") and not start_proof.get("countdown_mounted"):
        if all(start_proof.get(k) for k in start_proof if k != "countdown_mounted"):
            return _out(START9E, audit, "countdown_not_mounted")

    if dom_clicked and ws_sent and not any(
        [
            audit["handler_entered"],
            audit["room_creation_entered"],
            str(authoritative_state.get("room_id") or ""),
        ]
    ):
        return _out(START_ACTION_DOM_CLICKED_BUT_SERVER_OUTCOME_UNRESOLVED, audit, "server_chain_unresolved")

    if all(start_proof.values()):
        return _out(START_PIPELINE_PASS, audit, "")

    return _out(START10, audit, "unmapped_start_state")


def _out(code: str, audit: dict[str, Any], missing: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_missing_server_event": missing,
        "audit": audit,
    }
