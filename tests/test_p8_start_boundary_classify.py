"""Tests for START boundary classifier."""

from __future__ import annotations

from scripts.p8_start_boundary_classify import (
    START4A,
    START4B,
    START4C,
    START6,
    START8,
    START9C,
    START_ACTION_DOM_CLICKED_BUT_SERVER_OUTCOME_UNRESOLVED,
    classify_start_boundary,
)


def test_click_no_backmsg_is_start4b() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": True, "streamlit_backmsg_sent": False},
        ledger_rows=[],
        authoritative_state={"in_progress": False, "setup_start_visible": True},
        start_proof={k: False for k in ("nonempty_room_id", "room_in_progress", "pick_index_zero", "deadline_present", "production_token_present", "countdown_mounted")},
    )
    assert out["classification"] == START4B


def test_backmsg_no_rerun_is_start4c() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": True, "streamlit_backmsg_sent": True},
        ledger_rows=[],
        authoritative_state={},
        start_proof={},
    )
    assert out["classification"] == START4C


def test_rerun_no_ldr_branch_start6() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": True, "streamlit_backmsg_sent": True, "python_rerun_started": True},
        ledger_rows=[{"event": "production_global_script_run_canary", "ts": 1.0}],
        authoritative_state={},
        start_proof={},
        click_ts=0.5,
    )
    assert out["classification"] == START6


def test_ldr_no_handler_start8() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": True, "streamlit_backmsg_sent": True, "python_rerun_started": True},
        ledger_rows=[
            {"event": "production_global_script_run_canary", "ts": 1.0},
            {"event": "production_live_draft_branch_canary", "ts": 1.1},
        ],
        authoritative_state={},
        start_proof={},
        click_ts=0.5,
    )
    assert out["classification"] == START8


def test_dom_click_server_unresolved() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": True, "streamlit_backmsg_sent": True, "python_rerun_started": True},
        ledger_rows=[
            {"event": "production_global_script_run_canary", "ts": 1.0},
            {"event": "production_live_draft_branch_canary", "ts": 1.1},
            {"event": "production_stage1_start_handler_entered", "ts": 1.2},
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        start_proof={k: False for k in ("nonempty_room_id", "room_in_progress", "pick_index_zero", "deadline_present", "production_token_present", "countdown_mounted")},
        click_ts=0.5,
    )
    assert out["classification"] in (
        START_ACTION_DOM_CLICKED_BUT_SERVER_OUTCOME_UNRESOLVED,
        "START9A — START_HANDLER_ENTERED_BUT_ROOM_CREATION_NOT_CALLED",
    )


def test_no_dom_click_start4a() -> None:
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={"selector_found": True, "dom_click_dispatched": False},
        ledger_rows=[],
        authoritative_state={},
        start_proof={},
    )
    assert out["classification"] == START4A


def test_no_ws_but_server_rerun_not_start4b() -> None:
    """Ledger proof of rerun/handler must override missing WS capture."""
    out = classify_start_boundary(
        ldr_surface={"setup_visible": True},
        click_transport={
            "selector_found": True,
            "dom_click_dispatched": True,
            "streamlit_backmsg_sent": False,
            "python_rerun_started": True,
        },
        ledger_rows=[
            {"event": "production_global_script_run_canary", "ts": 2.0},
            {"event": "production_live_draft_branch_canary", "ts": 2.1},
            {"event": "production_stage1_start_handler_entered", "ts": 2.15},
            {"event": "production_stage1_room_creation_entered", "ts": 2.18},
            {"event": "production_stage1_room_creation_exited", "ts": 2.2, "room_creation_success": True, "created_room_id": "ABC"},
        ],
        authoritative_state={"room_id": "", "in_progress": False},
        start_proof={k: False for k in ("nonempty_room_id", "room_in_progress", "pick_index_zero", "deadline_present", "production_token_present", "countdown_mounted")},
        click_ts=1.0,
    )
    assert out["classification"] == START9C
