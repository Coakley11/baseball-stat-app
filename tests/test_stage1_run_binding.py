"""Tests for lifecycle vs ledger run binding (QUEUE1C3A2O1)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_native_widget_transport import classify_queue1c3a_subcode
from stage1_run_binding import (
    capture_run_binding_snapshot,
    lifecycle_seq_from_render_trace,
    merge_run_binding_into_transport,
)


def test_lifecycle_vs_ledger_last_row_mismatch_detected() -> None:
    """EC8C116E: lifecycle 15 vs legacy transport last-row 12."""
    binding = {
        "phase": "pre_click",
        "lifecycle_current_script_run_seq": 15,
        "ledger_diag_script_run_seq": 15,
        "ledger_transport_grade_script_run_seq": 15,
        "ledger_last_row_script_run_seq": 12,
        "run_binding_consistent": True,
        "run_binding_mismatch_reasons": ["legacy_last_row_would_be_12"],
    }
    transport = merge_run_binding_into_transport(
        {"streamlit_outbound_after_click": True, "native_widget_event_observed_strict": False},
        binding,
    )
    assert transport["run_binding_consistent"] is True
    assert transport["script_run_seq_before"] == "15"
    assert transport["ledger_last_row_seq_before"] == 12


def test_run_binding_inconsistent_blocks_a2() -> None:
    binding = {
        "lifecycle_current_script_run_seq": 15,
        "ledger_transport_grade_script_run_seq": 12,
        "run_binding_consistent": False,
    }
    transport = merge_run_binding_into_transport(
        {
            "generic_component_traffic_only": True,
            "native_widget_event_observed_strict": False,
            "streamlit_outbound_after_click": True,
            "script_run_seq_changed": False,
        },
        binding,
    )
    sub = classify_queue1c3a_subcode(
        click_target={"is_st_base_button": True},
        transport=transport,
        render_trace_present=True,
        callback_trace_present=False,
        callback_entered=False,
        widget_liveness="live_this_run",
    )
    assert sub == "QUEUE1C3A2O1"
    assert transport.get("python_rerun_observability_blocked") is True


def test_lifecycle_from_render_trace() -> None:
    row = lifecycle_seq_from_render_trace(
        {
            "current_script_run_seq": "15",
            "actual_card_render_run_seq": "15",
            "probe_source": "actual_card_render",
            "widget_liveness": "live_this_run",
        }
    )
    assert row["lifecycle_current_script_run_seq"] == 15
    assert row["lifecycle_probe_source"] == "actual_card_render"


def test_relaxed_scv_alone_does_not_imply_rerun_when_binding_consistent() -> None:
    transport = {
        "native_widget_event_observed": True,
        "native_widget_event_observed_strict": False,
        "streamlit_outbound_after_click": True,
        "script_run_seq_changed": False,
        "run_binding_consistent": True,
        "generic_component_traffic_only": False,
    }
    sub = classify_queue1c3a_subcode(
        click_target={"is_st_base_button": True, "inside_st_tooltip": True},
        transport=transport,
        render_trace_present=True,
        callback_trace_present=False,
        callback_entered=False,
        widget_liveness="live_this_run",
    )
    assert sub == "QUEUE1C3A2"


def test_dom_capture_failure_o2() -> None:
    sub = classify_queue1c3a_subcode(
        click_target={"is_st_base_button": True},
        transport={"run_binding_consistent": True, "dom_capture_observability_failed": True},
        render_trace_present=True,
        callback_trace_present=False,
        callback_entered=False,
    )
    assert sub == "QUEUE1C3A2O2"
