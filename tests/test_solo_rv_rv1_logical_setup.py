"""RV1 logical production setup / reuse grading (runner + diag helpers)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from live_draft_solo_rv_production_room_setup import (  # noqa: E402
    RV1_SETUP_OWNER_KEY,
    ensure_rv1_production_solo_room,
    room_state_fingerprint,
)
from solo_rv_ladder_runner_state import (  # noqa: E402
    analyze_rv1_logical_setup,
    rv1_logical_setup_invalid_reason,
)


def _row(event: str, **kwargs):
    return {"event": event, **kwargs}


def test_logical_valid_single_create_reuse_row() -> None:
    rows = [
        _row("production_room_created", room_id="ABCD", extra={"creation_event_id": "c1", "room_fingerprint": "fp1"}),
        _row("production_draft_started", room_id="ABCD", extra={"draft_start_event_id": "s1"}),
        _row("production_setup_owner_established", room_id="ABCD", extra={"room_fingerprint": "fp1"}),
        _row("production_room_reused", room_id="ABCD", script_run_seq=2),
        _row("real_room_hydrated", room_id="ABCD", expected_token="ABCD|0|1.0"),
        _row("declaration_attempt", expected_token="ABCD|0|1.0", script_run_seq=1),
        _row("declaration_returned", expected_token="ABCD|0|1.0", script_run_seq=1),
    ]
    assert rv1_logical_setup_invalid_reason(rows) == ""


def test_repeated_raw_labels_same_room_not_duplicate_creation() -> None:
    """052ab9b-style ledger: two created rows, one room ID — provenance unclear without event IDs."""
    rows = [
        _row("production_room_created", room_id="19924015", script_run_seq=1),
        _row("production_room_created", room_id="19924015", script_run_seq=2),
        _row("production_draft_started", room_id="19924015", script_run_seq=1),
        _row("production_draft_started", room_id="19924015", script_run_seq=2),
        _row(
            "real_room_hydrated",
            room_id="19924015",
            expected_token="19924015|0|1785196056.920",
            script_run_seq=2,
        ),
    ]
    reason = rv1_logical_setup_invalid_reason(rows)
    assert reason == "INVALID_RV_ROOM_REUSE_PROVENANCE_UNCLEAR"


def test_distinct_room_ids_invalid() -> None:
    rows = [
        _row("production_room_created", room_id="A", extra={"creation_event_id": "c1"}),
        _row("production_room_created", room_id="B", extra={"creation_event_id": "c2"}),
    ]
    assert rv1_logical_setup_invalid_reason(rows).startswith("INVALID_RV_DUPLICATE_ROOM_CREATION")


def test_second_draft_start_event_ids_invalid() -> None:
    rows = [
        _row("production_room_created", room_id="R1", extra={"creation_event_id": "c1", "room_fingerprint": "f1"}),
        _row("production_draft_started", room_id="R1", extra={"draft_start_event_id": "s1"}),
        _row("production_draft_started", room_id="R1", extra={"draft_start_event_id": "s2"}),
        _row("production_setup_owner_established", room_id="R1", extra={"room_fingerprint": "f1"}),
    ]
    assert rv1_logical_setup_invalid_reason(rows) == "INVALID_RV_DUPLICATE_DRAFT_START_multiple_start_event_ids"


def test_fingerprint_mismatch_invalid() -> None:
    rows = [
        _row("production_room_created", room_id="R1", extra={"creation_event_id": "c1", "room_fingerprint": "a"}),
        _row("production_setup_owner_established", room_id="R1", extra={"room_fingerprint": "b"}),
        _row("production_draft_started", room_id="R1", extra={"draft_start_event_id": "s1"}),
    ]
    info = analyze_rv1_logical_setup(rows)
    assert len(info["distinct_room_fingerprints"]) == 2


def test_second_rerun_reuses_without_init() -> None:
    st = MagicMock()
    pool = pd.DataFrame({"Player": [f"P{i}" for i in range(500)], "fullName": [f"P{i}" for i in range(500)]})
    room = {
        "draft_room_id": "TEST1234",
        "status": "in_progress",
        "pick_order": ["A", "B"],
        "current_pick_index": 0,
        "timer_deadline": 99999.0,
        "config": {"timer_seconds": 10},
    }
    session: dict = {
        "_solo_rv_run_id": "run-reuse",
        "_solo_rv_ladder_step": "RV1",
        "live_draft_team_count": 2,
        "live_draft_picks_per_team": 4,
        RV1_SETUP_OWNER_KEY: {
            "setup_completed": True,
            "owner_run_id": "run-reuse",
            "room_id": "TEST1234",
            "room_fingerprint": room_state_fingerprint(room),
            "creation_event_id": "c-existing",
            "draft_start_event_id": "s-existing",
            "room_object_id": id(room),
            "initial_pick": 0,
            "initial_deadline": 99999.0,
            "expected_token": "TEST1234|0|99999.0",
        },
        "live_draft_room": room,
    }
    with patch("streamlit_app.live_draft_init_room") as init_mock:
        with patch("streamlit_app.live_draft_start") as start_mock:
            result = ensure_rv1_production_solo_room(st, session, probe_placeholder=None)
    assert result.get("ok") and result.get("reused")
    init_mock.assert_not_called()
    start_mock.assert_not_called()
