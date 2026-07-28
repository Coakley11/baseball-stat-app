"""RV3-only duplicate global prepare_live_draft_state skip guard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from live_draft_setup_persist import (
    record_rv3_duplicate_live_draft_prepare_skipped,
    rv3_duplicate_live_draft_prepare_skip_active,
    should_skip_live_draft_state_prep,
)
from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY


def _in_progress_room(room_id: str = "DC0DED61") -> dict:
    return {
        "draft_room_id": room_id,
        "status": "in_progress",
        "draft_board": [{"Player": "A"}],
        "pick_deadline_epoch": 999.0,
    }


def _rv3_owner_session(*, run_id: str = "run-rv3-a", room_id: str = "DC0DED61", owner_run_id: str | None = None):
    return {
        "active_page": "Live Draft Room",
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_run_id": run_id,
        "live_draft_room": _in_progress_room(room_id),
        "live_draft_state": {"draft_room_id": room_id},
        RV1_SETUP_OWNER_KEY: {
            "setup_completed": True,
            "owner_run_id": owner_run_id if owner_run_id is not None else run_id,
            "room_id": room_id,
        },
    }


def test_rv3_owner_in_progress_skips_duplicate_global_prepare():
    session = _rv3_owner_session()
    assert rv3_duplicate_live_draft_prepare_skip_active(session) is True
    assert should_skip_live_draft_state_prep(session) is True


def test_rv3_wrong_owner_run_id_does_not_skip():
    session = _rv3_owner_session(owner_run_id="other-run")
    assert rv3_duplicate_live_draft_prepare_skip_active(session) is False
    assert should_skip_live_draft_state_prep(session) is False


def test_rv3_incomplete_setup_does_not_skip():
    session = _rv3_owner_session()
    session[RV1_SETUP_OWNER_KEY]["setup_completed"] = False
    assert rv3_duplicate_live_draft_prepare_skip_active(session) is False


def test_rv1_rv2_unchanged_in_progress_not_skipped():
    for step in ("RV1", "RV2", "RV0"):
        session = _rv3_owner_session()
        session["_solo_rv_ladder_step"] = step
        assert rv3_duplicate_live_draft_prepare_skip_active(session) is False
        assert should_skip_live_draft_state_prep(session) is False


def test_non_rv3_live_draft_pre_pick_still_skips_via_existing_rule():
    session = {"active_page": "Live Draft Room", "live_draft_room": None}
    assert rv3_duplicate_live_draft_prepare_skip_active(session) is False
    assert should_skip_live_draft_state_prep(session) is True


def test_normal_in_progress_without_rv3_does_not_skip():
    session = {
        "active_page": "Live Draft Room",
        "live_draft_room": _in_progress_room("NORMAL01"),
    }
    assert should_skip_live_draft_state_prep(session) is False


def test_record_skip_emits_ledger_row():
    session = _rv3_owner_session(run_id="run-ledger")
    st = MagicMock()
    st.session_state = session
    with patch("live_draft_solo_rv_control_probe.append_control_event") as append:
        record_rv3_duplicate_live_draft_prepare_skipped(
            st,
            session,
            prepare_location="ldr_prepare_live_draft_state",
            prepare_reason="ldr_room_restoration_reconciliation",
        )
    append.assert_called_once()
    args = append.call_args
    assert args[0][2] == "rv3_duplicate_live_draft_prepare_skipped"
    extra = args[1]["extra"]
    assert extra["solo_rv_run_id"] == "run-ledger"
    assert extra["prepare_location"] == "ldr_prepare_live_draft_state"
    assert extra["live_draft_room_present"] is True
    assert extra["canonical_live_draft_present"] is True


def test_clear_foreign_still_runs_outside_rv3_guard():
    """RV3 guard is skip-only; foreign clear is unchanged for normal sessions."""
    from live_draft_state import clear_foreign_live_draft_state

    session = {
        "active_page": "Live Draft Room",
        "live_draft_room": _in_progress_room("FOREIGN1"),
        "live_draft_state": {"draft_room_id": "OTHERROOM"},
    }
    assert should_skip_live_draft_state_prep(session) is False
    clear_foreign_live_draft_state(session, reason="test_foreign")
    assert session.get("live_draft_room") is None
