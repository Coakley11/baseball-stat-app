"""RV3 room continuity restore, mount gating, and runner grading."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from live_draft_solo_rv3_phase import (
    RV3_MOUNT_OK_THIS_RUN_KEY,
    RV3_PHASE_POST_DELIVERY,
    rv3_declaration_allowed,
    rv3_on_script_run_begin,
)
from live_draft_solo_rv3_room_continuity import (
    extract_micro_cycle_binding_token,
    restore_rv3_run_scoped_room,
    rv3_reuse_owned_room_only,
)
from live_draft_solo_rv_production_room_setup import RV1_SETUP_OWNER_KEY, room_state_fingerprint
from solo_rv_browser_observation import grade_rv_python_binding
from solo_rv_ladder_runner_state import rv3_room_continuity_invalid_reason


class _Stub:
    def empty(self):
        return self


def _owner_room():
    return {
        "draft_room_id": "438B2C1F",
        "status": "in_progress",
        "current_pick_index": 0,
        "pick_order": ["a", "b"],
        "timer_deadline": 1785209351.458,
        "config": {"timer_seconds": 60},
    }


def test_restore_rv3_from_canonical_blob():
    room = _owner_room()
    token = "438B2C1F|0|1785209351.458"
    session = {
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_run_id": "run-1",
        RV1_SETUP_OWNER_KEY: {
            "setup_completed": True,
            "owner_run_id": "run-1",
            "room_id": "438B2C1F",
            "initial_pick": 0,
            "expected_token": token,
            "room_fingerprint": room_state_fingerprint(room),
        },
    }
    from live_draft_state import room_to_persist_dict

    session["live_draft_state"] = room_to_persist_dict(room)
    session.pop("live_draft_room", None)
    out = restore_rv3_run_scoped_room(session)
    assert out.get("ok") is True
    assert str(session["live_draft_room"]["draft_room_id"]).upper() == "438B2C1F"


def test_post_delivery_reuse_never_creates():
    session = {
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_run_id": "run-1",
        "_solo_rv_rv3_phase": RV3_PHASE_POST_DELIVERY,
        RV1_SETUP_OWNER_KEY: {
            "setup_completed": True,
            "owner_run_id": "run-1",
            "room_id": "438B2C1F",
            "initial_pick": 0,
            "expected_token": "438B2C1F|0|1.0",
        },
    }
    st = _Stub()
    result = rv3_reuse_owned_room_only(st, session)
    assert result.get("ok") is False
    assert result.get("invalid") == "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"


def test_declaration_blocked_without_mount_ok_this_run():
    session = {
        "_solo_rv_ladder_step": "RV3",
        "_solo_rv_run_id": "r1",
        "_solo_rv_rv3_phase": RV3_PHASE_POST_DELIVERY,
        "_solo_rv_rv3_real_room_hydrated": True,
        RV1_SETUP_OWNER_KEY: {"room_id": "438B2C1F", "setup_completed": True, "owner_run_id": "r1"},
    }
    session["_solo_rv_rv3_phase_run_id"] = "r1"
    rv3_on_script_run_begin(session)
    ok, reason = rv3_declaration_allowed(session, expected_token="438B2C1F|0|1.0", location="x")
    assert ok is False
    assert reason == "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"


def test_micro_cycle_result_graded_as_token():
    repr_row = (
        "MicroCycleResult(widget_key='solo_countdown_wake_solo_persistent', "
        "token='438B2C1F|0|1785209351.458', delivered=False, raw_received=True, "
        "on_change_fired=False, stages=[], should_stop=False, "
        "component_return='438B2C1F|0|1785209351.458')"
    )
    assert extract_micro_cycle_binding_token(repr_row) == "438B2C1F|0|1785209351.458"
    rows = [
        {
            "event": "post_delivery_redeclaration",
            "expected_token": "438B2C1F|0|1785209351.458",
            "component_return": repr_row,
            "coalesced_value": repr_row,
            "session_state_after": "",
        }
    ]
    verdict, _ = grade_rv_python_binding(rows, expected_token="438B2C1F|0|1785209351.458")
    assert verdict == "PASS_RETURN_VALUE_DELIVERY"


def test_runner_room_continuity_after_mount_fail():
    token = "438B2C1F|0|1785209351.458"
    rows = [
        {"event": "real_room_hydrated", "expected_token": token},
        {"event": "declaration_returned", "expected_token": token},
        {"event": "rv_mount_failed", "extra": {"reason": "rv3_post_setup_without_live_room"}},
        {"event": "declaration_attempt", "expected_token": token},
    ]
    assert rv3_room_continuity_invalid_reason(rows) == "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"
