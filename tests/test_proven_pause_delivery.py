"""Regression tests for proven Pause delivery (Stage 1A-QUEUE harness)."""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def test_classify_pause1a_not_hydrated() -> None:
    from scripts.p8_proven_pause_delivery import QUEUEUI_PAUSE1A, classify_pause_delivery_outcome

    assert (
        classify_pause_delivery_outcome(
            hydration_wait={"ready": False},
            click={"dom_click_dispatched": False},
            transport={},
            server_proof={},
        )
        == QUEUEUI_PAUSE1A
    )


def test_classify_pause1c_no_backmsg() -> None:
    from scripts.p8_proven_pause_delivery import QUEUEUI_PAUSE1C, classify_pause_delivery_outcome

    assert (
        classify_pause_delivery_outcome(
            hydration_wait={"ready": True},
            click={"dom_click_dispatched": True},
            transport={"streamlit_backmsg_sent": False},
            server_proof={"paused_recognized": False},
        )
        == QUEUEUI_PAUSE1C
    )


def test_pause_delivery_resolved_requires_resume() -> None:
    from scripts.p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED, classify_pause_delivery_outcome

    assert (
        classify_pause_delivery_outcome(
            hydration_wait={"ready": True},
            click={"dom_click_dispatched": True},
            transport={"streamlit_backmsg_sent": True},
            server_proof={"paused_recognized": True, "resume_draft_count": 1},
        )
        == PAUSE_DELIVERY_RESOLVED
    )


def test_queue_setup_uses_proven_pause() -> None:
    src = (SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    assert "proven_pause_single_click" in src


def test_pause_abort_uses_specific_classification() -> None:
    src = (SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    assert "pause_classification" in src


def test_queue_seed_blocked_until_pause() -> None:
    from scripts.p8_proven_pause_delivery import queue_runner_must_not_seed_until_pause_proven

    import pytest

    with pytest.raises(RuntimeError, match="queue_seed_blocked"):
        queue_runner_must_not_seed_until_pause_proven(pause_proven=False)


def test_focused_pause_gate_exists() -> None:
    assert (SCRIPTS / "run_production_bridge_pause_only_gate.py").is_file()
