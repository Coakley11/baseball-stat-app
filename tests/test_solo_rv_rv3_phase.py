"""Tests for RV3 diagnostic state machine and runner ledger grading."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from live_draft_solo_rv3_phase import (
    RV3_PHASE_PRODUCTION_MOUNT,
    RV3_PHASE_SETUP,
    get_rv3_phase,
    init_rv3_run_state,
    is_rv3_rejected_token,
    rv3_blocks_diag_countdowns,
    rv3_declaration_allowed,
    token_matches_production_room,
)
from solo_rv_ladder_runner_state import rv3_ledger_invalid_reason, rv3_production_placement_invalid_reason


def _row(event: str, **fields):
    return {"event": event, "control_name": "RV3", **fields}


def test_rv3_setup_blocks_diag_countdowns():
    session = {"_solo_rv_ladder_step": "RV3"}
    init_rv3_run_state(session, "run-a")
    assert get_rv3_phase(session) == RV3_PHASE_SETUP
    assert rv3_blocks_diag_countdowns(session) is True


def test_rv3_rejects_parity_tokens():
    assert is_rv3_rejected_token("PARITY|0|1.0") is True
    assert is_rv3_rejected_token("PARITY|minimal|1.0") is True
    assert token_matches_production_room("ABCD1234|0|99.0", "ABCD1234") is True
    assert token_matches_production_room("PARITY|0|99.0", "ABCD1234") is False


def test_rv3_declaration_blocked_during_setup():
    session = {"_solo_rv_ladder_step": "RV3", "_solo_rv_run_id": "r1"}
    init_rv3_run_state(session, "r1")
    ok, reason = rv3_declaration_allowed(session, expected_token="ROOM|0|1.0", location="x")
    assert ok is False
    assert reason == "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"


def test_rv3_ledger_detects_parity_before_hydration():
    rows = [
        _row("production_setup_owner_established", expected_token="ROOM1234|0|10.0"),
        _row("declaration_attempt", expected_token="PARITY|0|10.0"),
        _row("real_room_hydrated", expected_token="ROOM1234|0|10.0", room_id="ROOM1234"),
    ]
    assert rv3_ledger_invalid_reason(rows) == "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"


def test_rv3_ledger_requires_setup_tail():
    rows = [
        _row("production_room_created", room_id="ROOM1234"),
        _row("production_draft_started", expected_token="ROOM1234|0|10.0"),
    ]
    assert rv3_ledger_invalid_reason(rows) == "INVALID_RV3_SETUP_NOT_COMPLETED"


def test_rv3_ledger_valid_minimal_mount_sequence():
    token = "ROOM1234|0|10.0"
    rows = [
        _row("production_room_creation_attempted"),
        _row("production_room_created", room_id="ROOM1234"),
        _row("production_draft_start_attempted"),
        _row("production_draft_started", expected_token=token),
        _row("production_setup_owner_established", expected_token=token),
        _row("rv3_setup_complete"),
        _row("rv3_setup_rerun_requested"),
        _row("production_room_reused", room_id="ROOM1234"),
        _row("real_room_hydrated", expected_token=token, room_id="ROOM1234", pick_index=0, deadline=10.0),
        _row("room_state_source"),
        _row("rv3_production_placement_entered"),
        _row(
            "declaration_attempt",
            expected_token=token,
            widget_key="solo_countdown_wake_solo_persistent",
            extra={"location": "ldr_page_entry_early_persistent"},
        ),
        _row("declaration_returned", expected_token=token),
    ]
    assert rv3_ledger_invalid_reason(rows) == ""
    assert rv3_production_placement_invalid_reason(rows) == ""


def test_rv3_hydrated_allows_declaration():
    session = {
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_run_id": "r1",
        "_solo_rv_rv3_phase": RV3_PHASE_PRODUCTION_MOUNT,
        "_solo_rv_rv3_real_room_hydrated": True,
    }
    session["_solo_rv_rv3_phase_run_id"] = "r1"
    try:
        from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY

        session[RV1_SETUP_OWNER_KEY] = {"room_id": "ROOM1234", "setup_completed": True, "owner_run_id": "r1"}
    except ImportError:
        pass
    ok, _reason = rv3_declaration_allowed(
        session, expected_token="ROOM1234|0|10.0", location="ldr_page_entry_early_persistent"
    )
    assert ok is True
