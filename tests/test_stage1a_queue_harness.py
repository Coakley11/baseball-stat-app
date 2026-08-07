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


def test_queue_setup_order_pause_before_active_gate() -> None:
    from stage1_queue_harness_flow import QUEUE_SETUP_ORDER_AFTER_START

    steps = list(QUEUE_SETUP_ORDER_AFTER_START)
    assert steps.index("immediate_pause") < steps.index("active_page_gate_while_paused")
    assert steps.index("active_page_gate_while_paused") < steps.index("queue_seed_while_paused")
    assert steps.index("queue_verification_while_paused") < steps.index("resume_after_queue_proven")
    assert steps.index("resume_after_queue_proven") < steps.index("wait_real_expiration")


def test_gate_while_paused_allows_frozen_deadline() -> None:
    obs = _obs_pass()
    obs["pick0_deadline_ui"] = ""
    obs["pause_draft_count"] = 0
    obs["resume_draft_count"] = 1
    ev = evaluate_active_live_page_gate(obs, start_val=_start_val(), while_paused=True)
    assert ev["checks"]["pick0_deadline_ui_present"] is True
    assert ev["checks"]["pause_draft_or_live_control"] is True


def test_visible_pete_alonso_without_structured_scraper() -> None:
    from stage1_queue_harness_flow import build_queue_evidence_hierarchy, visible_queue_names_from_excerpt

    excerpt = "Draft queue\n\nPete Alonso\n\n✕\n\nClear Draft Queue\n"
    assert "Pete Alonso" in visible_queue_names_from_excerpt(excerpt)
    meta = {
        "add_actions": [{"clicked": True}, {"clicked": True}, {"clicked": True}],
        "queue_excerpt_before": excerpt,
        "queue_order": [],
        "queue_container": {"players": []},
    }
    ev = build_queue_evidence_hierarchy(meta, min_players=3)
    assert ev["deliberate_add_clicks_succeeded"] is True
    assert ev["visible_queue_satisfied"] is False  # only one visible name in excerpt
    meta["add_actions"] = [{"clicked": True}] * 3
    meta["queue_excerpt_before"] = "Draft queue\n\nPete Alonso\n\nA Two\n\nB Three\n\nClear Draft Queue\n"
    ev2 = build_queue_evidence_hierarchy(meta, min_players=3)
    assert ev2["queue_setup_proven"] is True
    assert ev2["harness_scraper_observation_gap"] is True


def test_scraper_gap_does_not_equal_app_failure_classification() -> None:
    from stage1_queue_harness_flow import build_queue_evidence_hierarchy

    meta = {
        "add_actions": [{"clicked": True}] * 3,
        "queue_excerpt_before": "Draft queue\n\nPete Alonso\n\nX Y\n\nZ W\n\nClear Draft Queue\n",
        "queue_order": [],
        "queue_container": {"players": []},
    }
    ev = build_queue_evidence_hierarchy(meta, min_players=3)
    assert ev["harness_scraper_observation_gap"] is True
    assert ev["queue_setup_proven"] is True


def test_resolve_solo_diag_timer_queue_vs_core() -> None:
    import importlib.util
    import os
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_production_stage1_authenticated.py"
    spec = importlib.util.spec_from_file_location("run_production_stage1_authenticated_timer", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    saved = {
        k: os.environ.pop(k, None)
        for k in ("STAGE1A_SOLO_DIAG_TIMER", "SOLO_DIAG_TIMER", "STAGE1A_MODE")
    }
    try:
        spec.loader.exec_module(mod)
        assert mod.resolve_solo_diag_timer(stage1a_mode="CORE") == "10"
        assert mod.resolve_solo_diag_timer(stage1a_mode="QUEUE") == "120"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_pick_index_parsed_from_token_when_ui_null() -> None:
    from stage1_queue_harness_flow import parse_pick_index_from_expire_token, pick_index_zero_from_observation

    assert parse_pick_index_from_expire_token("ABCD|0|123.4") == 0
    assert parse_pick_index_from_expire_token("ABCD|1|123.4") == 1
    obs = {"pick_index": None, "pick0_token_ui": "ROOM|0|999.0"}
    assert pick_index_zero_from_observation(obs) is True
