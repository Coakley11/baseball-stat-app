"""Tests for lifecycle vs ledger run binding (QUEUE1C3A2O1)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_native_widget_transport import classify_queue1c3a_subcode
from stage1_run_binding import (
    BINDING_MODE_CONTROL_ONLY,
    BINDING_MODE_RECOMMENDATION_WIDGET,
    capture_run_binding_snapshot,
    compute_run_binding_verdict,
    control_only_pause_binding_passes,
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


def test_control_only_pause_binding_pass_no_lifecycle() -> None:
    """1865D12C pattern: max=10, last=9, no diag, no rec-card lifecycle."""
    ok, reasons, meta = compute_run_binding_verdict(
        binding_mode=BINDING_MODE_CONTROL_ONLY,
        lifecycle_seq=None,
        transport_grade_seq=10,
        ledger_last=9,
        ledger_diag_seq=None,
    )
    assert ok is True
    assert meta["lifecycle_not_applicable"] is True
    assert meta["ledger_last_row_stale"] is True
    assert "lifecycle_seq_missing" not in reasons
    assert any("last_row_stale" in r for r in reasons)


def test_control_only_fails_without_transport_grade() -> None:
    ok, reasons, _meta = compute_run_binding_verdict(
        binding_mode=BINDING_MODE_CONTROL_ONLY,
        lifecycle_seq=None,
        transport_grade_seq=None,
        ledger_last=9,
        ledger_diag_seq=None,
    )
    assert ok is False
    assert "ledger_transport_seq_missing" in reasons


def test_francisco_missing_lifecycle_fails_recommendation_binding() -> None:
    ok, reasons, meta = compute_run_binding_verdict(
        binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
        lifecycle_seq=None,
        transport_grade_seq=10,
        ledger_last=9,
        ledger_diag_seq=None,
    )
    assert ok is False
    assert meta["lifecycle_not_applicable"] is False
    assert "lifecycle_seq_missing" in reasons


def test_francisco_lifecycle_vs_ledger_mismatch_o1() -> None:
    ok, reasons, _meta = compute_run_binding_verdict(
        binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
        lifecycle_seq=15,
        transport_grade_seq=12,
        ledger_last=12,
        ledger_diag_seq=12,
    )
    assert ok is False
    assert any("lifecycle_15_vs_ledger_grade_12" in r for r in reasons)


def test_control_only_pause_binding_passes_helper() -> None:
    pre = {
        "binding_mode": BINDING_MODE_CONTROL_ONLY,
        "run_binding_consistent": True,
        "ledger_transport_grade_script_run_seq": 10,
    }
    assert control_only_pause_binding_passes(
        pre,
        pause_delivery_resolved=True,
        dom_events_non_empty=True,
        dom_install_ok=True,
    )


def test_pause_trusted_dom_chain_recognized() -> None:
    events = [
        {"type": "pointerdown", "is_trusted": True},
        {"type": "mousedown", "is_trusted": True},
        {"type": "pointerup", "is_trusted": True},
        {"type": "mouseup", "is_trusted": True},
        {"type": "click", "is_trusted": True, "target_testid": "stBaseButton-secondary"},
    ]
    trusted_click = [e for e in events if e.get("type") == "click" and e.get("is_trusted")]
    assert len(trusted_click) == 1

