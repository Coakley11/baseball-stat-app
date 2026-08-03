"""Stage 1A-QUEUE harness: active page gate, precondition blocks, manual assist verification."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_harness_observability import (  # noqa: E402
    QUEUE1,
    QUEUE6,
    QUEUEUI1,
    build_stage1a_queue_precondition_block,
    evaluate_active_live_page_gate,
    verify_manual_queue_capture,
)


def _start_val(*, room: str = "ABCD1234") -> dict:
    return {
        "latched_room_id": room,
        "visible_room_id": room,
        "in_progress": True,
        "expected_token": f"{room}|0|100.0",
        "room_latch_pass": True,
    }


def _obs_pass(*, room: str = "ABCD1234") -> dict:
    return {
        "visible_room_id": room,
        "pick_index": 0,
        "pick0_token_ui": f"{room}|0|100.0",
        "pick0_deadline_ui": "100.0",
        "pause_draft_count": 1,
        "board_rows": 1,
        "add_to_queue_button_count": 3,
        "countdown_or_timer_present": True,
    }


def test_active_live_page_gate_pass() -> None:
    ev = evaluate_active_live_page_gate(_obs_pass(), start_val=_start_val())
    assert ev["passed"] is True
    assert all(ev["checks"].values())


def test_active_live_page_gate_fails_without_ui_hydration() -> None:
    obs = _obs_pass()
    obs["pause_draft_count"] = 0
    obs["add_to_queue_button_count"] = 0
    obs["countdown_or_timer_present"] = False
    obs["pick0_token_ui"] = ""
    obs["visible_room_id"] = ""
    ev = evaluate_active_live_page_gate(obs, start_val=_start_val())
    assert ev["passed"] is False


def test_server_latch_alone_does_not_pass_gate() -> None:
    obs = {
        "visible_room_id": "",
        "pick_index": None,
        "pick0_token_ui": "",
        "pick0_deadline_ui": "",
        "pause_draft_count": 0,
        "board_rows": 0,
        "add_to_queue_button_count": 0,
        "countdown_or_timer_present": False,
    }
    ev = evaluate_active_live_page_gate(obs, start_val=_start_val())
    assert ev["passed"] is False
    assert ev["checks"]["latched_room_visible_agrees"] is False


def test_precondition_block_not_run_classification() -> None:
    block = build_stage1a_queue_precondition_block(
        first_boundary=QUEUEUI1,
        reason="active_live_draft_page_not_hydrated",
    )
    assert block["stage1a_queue_functional_outcome"] == "NOT_RUN"
    assert block["stage1a_queue_execution_status"] == "BLOCKED_BEFORE_EXPIRATION"
    assert block["first_boundary"] == QUEUEUI1
    assert block["verdict"] == "BLOCKED"


def test_manual_assist_queue_verification_three_players() -> None:
    meta = {
        "queue_order": ["Alpha One", "Beta Two", "Gamma Three"],
        "queue_players_before": [{"name": "Alpha One"}, {"name": "Beta Two"}, {"name": "Gamma Three"}],
        "top_queued_player": {"name": "Alpha One"},
        "expected_autopick_candidate": {"name": "Zulu Top"},
    }
    v = verify_manual_queue_capture(meta, min_players=3)
    assert v["ok"] is True
    assert meta["autopick_differs_from_top_queue"] is True


def test_manual_assist_aborts_incomplete_queue() -> None:
    meta = {
        "queue_order": ["Only One"],
        "queue_players_before": [{"name": "Only One"}],
        "top_queued_player": {"name": "Only One"},
        "expected_autopick_candidate": {"name": "Other"},
    }
    v = verify_manual_queue_capture(meta, min_players=3)
    assert v["ok"] is False
    assert v["first_boundary"] == QUEUE1


def test_top_queue_must_differ_from_expected_autopick() -> None:
    meta = {
        "queue_order": ["Same Guy", "B Two", "C Three"],
        "queue_players_before": [{"name": "Same Guy"}, {"name": "B Two"}, {"name": "C Three"}],
        "top_queued_player": {"name": "Same Guy"},
        "expected_autopick_candidate": {"name": "Same Guy Extra"},
    }
    v = verify_manual_queue_capture(meta, min_players=3)
    assert v["ok"] is False
    assert v["first_boundary"] == QUEUE6
