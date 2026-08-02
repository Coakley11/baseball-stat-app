"""Regression tests for focused P8 binding setup harness (harness-only)."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.p8_focused_setup_classify import (
    FOCUSED_SETUP_TRACE,
    SETUP3,
    SETUP4,
    SETUP5,
    SETUP6,
    SETUP7,
    SETUP8,
    SETUP10,
    classify_focused_setup_boundary,
    setup_disappearance_is_not_room_not_created,
)

ROOT = Path(__file__).resolve().parent.parent


def test_focused_binding_uses_establish_single_solo_live_draft() -> None:
    src = (ROOT / "scripts" / "run_production_p8_binding_diagnostic.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "establish_single_solo_live_draft" in names
    assert "execute_solo_draft_start_workflow" not in names
    assert "p8_focused_production_url" in names
    assert "solo_p8_focused_binding=1" in src
    assert "solo_p8_harness_run_id" in src
    assert "p8_binding_" in src and ".out" in src
    assert "INVALID_FOCUSED_GATE_NOT_DEPLOYED" in src
    assert "acquire_focused_diagnostic_lock" in src


def test_setup_disappearance_alone_not_room_not_created() -> None:
    assert setup_disappearance_is_not_room_not_created(
        legacy_first_missing="setup_page_disappeared",
        room_hint="6AB33309",
    )
    assert not setup_disappearance_is_not_room_not_created(
        legacy_first_missing="setup_page_disappeared",
        room_hint="",
    )


def test_room_in_ledger_outside_filter_is_latch_reconciliation_or_setup8() -> None:
    from scripts.p8_focused_setup_classify import ACCEPTED_ROOM_CREATED

    out6 = classify_focused_setup_boundary(
        start_result={
            "valid": False,
            "room_latch_pass": False,
            "room_id": "6AB33309",
            "handler_entered": True,
            "room_creation_success": True,
            "expected_token": "6AB33309|0|1",
            "start_click": {"dom_click_dispatched": True},
            "start_audit_reconcile": {"handler_entered_count": 1, "handler_exited_count": 1},
        }
    )
    assert out6["focused_p8_outcome"] == ACCEPTED_ROOM_CREATED

    out8 = classify_focused_setup_boundary(
        start_result={"valid": False, "handler_entered": True, "room_id": "ABC12345"},
        observability_empty=True,
    )
    assert out8["classification"] == SETUP8


def test_page_replacement_after_click_is_setup7() -> None:
    out = classify_focused_setup_boundary(
        start_result={
            "valid": False,
            "start_click": {"dom_click_dispatched": True},
            "identity_timeline": [
                {"page_object_id": "1", "streamlit_session_id": "s", "page_url": "https://x/?active_page=Live"},
                {"page_object_id": "2", "streamlit_session_id": "s", "page_url": "https://x/?active_page=Live"},
            ],
        }
    )
    assert out["classification"] == SETUP7


def test_handler_without_room_creation_is_setup4() -> None:
    out = classify_focused_setup_boundary(
        start_result={
            "valid": False,
            "handler_entered": True,
            "room_creation_success": False,
            "start_click": {"dom_click_dispatched": True},
            "start_audit_reconcile": {"handler_entered_count": 1, "by_event": {}},
        }
    )
    assert out["classification"] == SETUP4


def test_click_without_handler_is_setup3() -> None:
    out = classify_focused_setup_boundary(
        start_result={
            "valid": False,
            "start_click": {"dom_click_dispatched": True},
            "start_audit_reconcile": {},
        }
    )
    assert out["classification"] == SETUP3


def test_legacy_disappear_with_room_hint_is_latch_reconciliation_not_setup6() -> None:
    from scripts.p8_focused_setup_classify import ACCEPTED_ROOM_CREATED, classify_focused_setup_boundary

    out = classify_focused_setup_boundary(
        start_result={
            "valid": False,
            "handler_entered": True,
            "room_id": "6AB33309",
            "expected_token": "6AB33309|0|1.0",
            "deadline": 1.0,
            "start_click": {"dom_click_dispatched": True},
        },
        legacy_draft={
            "first_missing_criterion": "setup_page_disappeared",
            "checkpoints": [{"step": "room_id_detected", "room_id": "6AB33309"}],
        },
    )
    assert out["focused_p8_outcome"] == ACCEPTED_ROOM_CREATED
    assert "SETUP6" not in out["classification"]


def test_durable_handoff_module_unchanged_in_focused_diagnostic() -> None:
    src = (ROOT / "scripts" / "run_production_p8_binding_diagnostic.py").read_text(encoding="utf-8")
    assert "live_draft_prod_callback_handoff" not in src
    handoff = (ROOT / "live_draft_prod_callback_handoff.py").read_text(encoding="utf-8")
    assert "write_callback_handoff_from_on_change" in handoff


def test_focused_mode_no_claim_in_classify_outcome() -> None:
    from scripts.p8_diagnostic_setup import classify_focused_p8_outcome

    out = classify_focused_p8_outcome(
        setup_valid=True,
        setup_abort_reason="",
        python_chain={"delivery_only_observation_events": 0, "observation_zero_claims": True},
        gate_rows=[{"decision": "pass_durable_callback_handoff", "selected_bound_token": "tok"}],
        browser_send={"postmessage_attempted": True},
        filtered_meta={"filtered_rows": []},
        observability_valid=True,
    )
    assert "claim" not in out.lower() or "PASS" in out
