"""Tests for shared production Start delivery helper (harness only)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def test_root_audit_and_stage1_use_proven_start_helper() -> None:
    root_src = (SCRIPTS / "run_queueui_root_predicate_audit.py").read_text(encoding="utf-8")
    stage_src = (SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    canon_src = (SCRIPTS / "p8_canonical_production_start.py").read_text(encoding="utf-8")
    assert "proven_start_single_click" in root_src
    assert "install_proven_start_context_scripts" in root_src
    assert "install_proven_start_context_scripts" in stage_src
    assert "proven_start_single_click" in canon_src


def test_classify_start4b_dom_click_no_backmsg() -> None:
    from scripts.p8_proven_start_delivery import START4B, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={"multiple_start_controls": False, "preferred_has_ledger": True},
            click={"dom_click_dispatched": True, "disabled_at_click": False},
            transport={"streamlit_backmsg_sent": False, "python_rerun_started": False, "websocket_hook_seen": True},
            proof={"callback_entered": False, "handler_entered": False, "room_id": ""},
        )
        == START4B
    )


def test_classify_start1_stale_wrong_frame() -> None:
    from scripts.p8_proven_start_delivery import START1, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={"multiple_start_controls": True, "preferred_has_ledger": False},
            click={"dom_click_dispatched": False, "click_stale_detached": True},
            transport={},
            proof={},
        )
        == START1
    )


def test_classify_start3_websocket_unavailable() -> None:
    from scripts.p8_proven_start_delivery import START3, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={"multiple_start_controls": False},
            click={"dom_click_dispatched": True, "disabled_at_click": False},
            transport={
                "streamlit_backmsg_sent": False,
                "python_rerun_started": False,
                "websocket_hook_seen": False,
                "aggregate_ws_entries": 0,
            },
            proof={"callback_entered": False},
        )
        == START3
    )


def test_classify_start5_callback_absent_after_message() -> None:
    from scripts.p8_proven_start_delivery import START5, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={"multiple_start_controls": False},
            click={"dom_click_dispatched": True},
            transport={"streamlit_backmsg_sent": True, "python_rerun_started": True, "websocket_hook_seen": True},
            proof={"callback_entered": False, "handler_entered": False},
        )
        == START5
    )


def test_classify_start6_handler_absent() -> None:
    from scripts.p8_proven_start_delivery import START6, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={"multiple_start_controls": False},
            click={"dom_click_dispatched": True},
            transport={"streamlit_backmsg_sent": True, "python_rerun_started": True},
            proof={"callback_entered": True, "handler_entered": False, "room_id": ""},
        )
        == START6
    )


def test_start_delivery_resolved_requires_callback_handler_room() -> None:
    from scripts.p8_proven_start_delivery import START_DELIVERY_RESOLVED, classify_start_delivery_outcome

    assert (
        classify_start_delivery_outcome(
            authority={},
            click={"dom_click_dispatched": True},
            transport={"streamlit_backmsg_sent": True},
            proof={"callback_entered": True, "handler_entered": True, "room_id": "6355A95D"},
        )
        == START_DELIVERY_RESOLVED
    )


def test_queue_step_blocked_until_room_latch() -> None:
    from scripts.p8_proven_start_delivery import queue_runner_must_not_run_until_room_latched

    with pytest.raises(RuntimeError, match="queue_step_blocked_until_room_latch"):
        queue_runner_must_not_run_until_room_latched(room_latch_proven=False, next_step="immediate_pause")
    queue_runner_must_not_run_until_room_latched(room_latch_proven=True, next_step="immediate_pause")


def test_canonical_chain_names_proven_click_helper() -> None:
    from scripts.p8_harness_start_classify import ROOM_LATCH_REFERENCE_CHAIN

    assert ROOM_LATCH_REFERENCE_CHAIN["start_click_helper"] == "dispatch_start_single_authoritative_click"
    proven = (SCRIPTS / "p8_proven_start_delivery.py").read_text(encoding="utf-8")
    assert "proven_start_single_click" in proven
    tree = ast.parse((SCRIPTS / "p8_canonical_production_start.py").read_text(encoding="utf-8"))
    names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "proven_start_single_click" in names


def test_duplicate_start_click_still_blocked() -> None:
    from scripts.p8_production_start_harness import dispatch_start_single_authoritative_click

    with pytest.raises(RuntimeError, match="duplicate_start_click_blocked"):
        dispatch_start_single_authoritative_click(None, [{"_start_click_count": 1}])
