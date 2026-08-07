"""Regression tests for LDR application phase vs auth hydration (harness-only)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def test_start_success_moves_phase_to_active_draft() -> None:
    from scripts.stage1_application_phase import ACTIVE_DRAFT, SETUP_LOBBY, classify_ldr_phase_from_state

    lobby = classify_ldr_phase_from_state(
        {"in_progress": False, "room_id": "", "setup_start_visible": True},
        start_inspect={"visible": True, "enabled": True},
    )
    assert lobby["application_phase"] == SETUP_LOBBY
    active = classify_ldr_phase_from_state(
        {"in_progress": True, "room_id": "8749861D", "setup_start_visible": False},
        start_inspect={"visible": False, "enabled": False},
    )
    assert active["application_phase"] == ACTIVE_DRAFT


def test_auth_complete_after_start_not_hydrate7_root() -> None:
    from scripts.stage1_application_phase import (
        ACTIVE_DRAFT,
        APP_PHASE_ACTIVE_DRAFT,
        EXPECTED_PHASE_SETUP_LOBBY,
        classify_hydration_timeout,
    )

    polls = [
        {
            "is_authenticated": True,
            "auth_session_complete": True,
            "restore_block": "",
            "start_enabled": False,
        }
    ]
    out = classify_hydration_timeout(
        expected_application_phase=EXPECTED_PHASE_SETUP_LOBBY,
        hydration_polls=polls,
        application_phase=ACTIVE_DRAFT,
        standalone_start_consumed=False,
    )
    assert APP_PHASE_ACTIVE_DRAFT in out["failure_classification"]
    assert out.get("mislabeled_as_auth_hydrate7") is True


def test_sequence1_when_standalone_start_consumed() -> None:
    from scripts.stage1_application_phase import (
        ACTIVE_DRAFT,
        EXPECTED_PHASE_SETUP_LOBBY,
        QUEUE_HARNESS_SEQUENCE1,
        classify_hydration_timeout,
    )

    polls = [{"is_authenticated": True, "auth_session_complete": True, "restore_block": "", "start_enabled": False}]
    out = classify_hydration_timeout(
        expected_application_phase=EXPECTED_PHASE_SETUP_LOBBY,
        hydration_polls=polls,
        application_phase=ACTIVE_DRAFT,
        standalone_start_consumed=True,
    )
    assert out["failure_classification"] == QUEUE_HARNESS_SEQUENCE1


def test_auth_only_passes_without_start() -> None:
    from scripts.bridge_hydration_waiter import bound_bridge_auth_only_passes, bound_bridge_hydration_passes

    bound = {
        "session_flag_present": True,
        "is_authenticated": True,
        "auth_session_complete": True,
        "current_restore_blocked_reason": "",
        "apply_authenticated_user_ok": True,
    }
    assert bound_bridge_auth_only_passes(bound, suite_sid="abc", url_sid="abc", bridge_load_ok=True)
    assert not bound_bridge_hydration_passes(
        bound,
        suite_sid="abc",
        url_sid="abc",
        bridge_load_ok=True,
        start_enabled=False,
        start_visible=True,
        require_start=True,
    )
    assert bound_bridge_hydration_passes(
        bound,
        suite_sid="abc",
        url_sid="abc",
        bridge_load_ok=True,
        start_enabled=True,
        start_visible=True,
        require_start=True,
    )


def test_stage1_queue_uses_proven_start_in_canonical() -> None:
    canon = (SCRIPTS / "p8_canonical_production_start.py").read_text(encoding="utf-8")
    assert "proven_start_single_click" in canon
    stage1 = (SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    assert "establish_single_solo_live_draft" in stage1
    assert "no separate Start-only pre-proof" in stage1


def test_queue_order_pause_after_latch() -> None:
    from scripts.stage1_queue_harness_flow import QUEUE_SETUP_ORDER_AFTER_START

    steps = list(QUEUE_SETUP_ORDER_AFTER_START)
    assert steps.index("room_latch_proof") < steps.index("immediate_pause")
    assert steps.index("immediate_pause") < steps.index("queue_seed_while_paused")


def test_standalone_start_gate_records_consumed_state() -> None:
    gate = (SCRIPTS / "run_production_bridge_start_only_gate.py").read_text(encoding="utf-8")
    assert "setup_state_consumed" in gate
    assert "harness_end_live_draft_room" in gate


def test_waiter_supports_expected_application_phase() -> None:
    src = (SCRIPTS / "playwright_auth_bridge_restore_harness.py").read_text(encoding="utf-8")
    assert "expected_application_phase" in src
    assert "bound_bridge_auth_only_passes" in src


def test_single_room_no_duplicate_start_helper_guard() -> None:
    from scripts.p8_production_start_harness import dispatch_start_single_authoritative_click

    import pytest

    with pytest.raises(RuntimeError, match="duplicate_start_click_blocked"):
        dispatch_start_single_authoritative_click(None, [{"_start_click_count": 1}])


def test_queue_setup_from_same_start_operation() -> None:
    """Queue flow continues from canonical start in the same runner (no split process)."""
    tree = ast.parse((SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8"))
    src = ast.unparse(tree)
    assert "queue_immediate_pause_after_start" in src
    assert "establish_single_solo_live_draft" in src
