"""Tests for lifecycle vs current app-generation vs historical ledger (QUEUE1C3A2O1)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_native_widget_transport import classify_queue1c3a_subcode
from stage1_run_binding import (
    BINDING_MODE_CONTROL_ONLY,
    BINDING_MODE_RECOMMENDATION_WIDGET,
    compute_recommendation_widget_binding,
    compute_run_binding_verdict,
    control_only_pause_binding_passes,
    lifecycle_seq_from_render_trace,
    merge_run_binding_into_transport,
)


def test_lifecycle_vs_ledger_last_row_mismatch_detected() -> None:
    """Historical ledger last row may lag; transport grade uses current app diag."""
    ok, notes, meta = compute_recommendation_widget_binding(
        lifecycle_seq=15,
        lifecycle_room_id="ROOM1",
        current_diag={
            "probe_id": "solo-stage1-current-run-diag",
            "script_run_seq": "15",
            "streamlit_session_id": "s1",
            "room_id": "ROOM1",
        },
        ledger_max=12,
        ledger_last=12,
    )
    assert ok is True
    assert meta["ledger_history_lag"] is True
    assert meta["lifecycle_vs_current_diag_match"] is True
    assert "rec_lifecycle" in meta["binding_authorities"]


def test_run_binding_inconsistent_blocks_a2() -> None:
    binding = {
        "lifecycle_current_script_run_seq": 15,
        "current_app_diag_seq": 12,
        "ledger_transport_grade_script_run_seq": 12,
        "run_binding_consistent": False,
        "binding_mode": BINDING_MODE_RECOMMENDATION_WIDGET,
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
            "room_id": "ABCD1234",
            "probe_source": "actual_card_render",
            "widget_liveness": "live_this_run",
        }
    )
    assert row["lifecycle_current_script_run_seq"] == 15
    assert row["lifecycle_room_id"] == "ABCD1234"


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


def test_recommendation_pass_when_lifecycle_and_current_diag_agree_ledger_lags() -> None:
    ok, notes, meta = compute_recommendation_widget_binding(
        lifecycle_seq=18,
        lifecycle_room_id="29732FA8",
        current_diag={
            "probe_id": "solo-stage1-current-run-diag",
            "script_run_seq": "18",
            "streamlit_session_id": "31123542-4194-4ce7-b69d-2327125cda90",
            "room_id": "29732FA8",
        },
        ledger_max=16,
        ledger_last=16,
    )
    assert ok is True
    assert meta["ledger_history_lag"] is True
    assert any("ledger_history_lag" in n for n in notes)


def test_recommendation_fail_when_current_sources_disagree() -> None:
    ok, notes, _meta = compute_recommendation_widget_binding(
        lifecycle_seq=18,
        lifecycle_room_id="ROOM1",
        current_diag={
            "probe_id": "solo-stage1-current-run-diag",
            "script_run_seq": "17",
            "streamlit_session_id": "s1",
            "room_id": "ROOM1",
        },
        ledger_max=16,
        ledger_last=9,
    )
    assert ok is False
    assert any("lifecycle_18_vs_current_app_diag_17" in n for n in notes)


def test_recommendation_blocked_when_current_diag_missing() -> None:
    ok, notes, _meta = compute_recommendation_widget_binding(
        lifecycle_seq=18,
        lifecycle_room_id="ROOM1",
        current_diag={},
        ledger_max=16,
        ledger_last=16,
    )
    assert ok is False
    assert "current_app_diag_missing" in notes


def test_session_mismatch_fails_binding() -> None:
    ok, notes, _meta = compute_recommendation_widget_binding(
        lifecycle_seq=18,
        lifecycle_room_id="ROOM1",
        current_diag={
            "probe_id": "solo-stage1-current-run-diag",
            "script_run_seq": "18",
            "streamlit_session_id": "",
            "room_id": "ROOM1",
        },
        ledger_max=16,
        ledger_last=16,
    )
    assert ok is False
    assert "current_app_diag_session_missing" in notes


def test_room_mismatch_fails_binding() -> None:
    ok, notes, _meta = compute_recommendation_widget_binding(
        lifecycle_seq=18,
        lifecycle_room_id="ROOM1",
        current_diag={
            "probe_id": "solo-stage1-current-run-diag",
            "script_run_seq": "18",
            "streamlit_session_id": "s1",
            "room_id": "OTHERROOM",
        },
        ledger_max=16,
        ledger_last=16,
        expected_room_id="ROOM1",
    )
    assert ok is False
    assert any(n.startswith("room_mismatch") for n in notes)


def test_control_only_pause_binding_pass_no_lifecycle() -> None:
    ok, _notes, meta = compute_run_binding_verdict(
        binding_mode=BINDING_MODE_CONTROL_ONLY,
        lifecycle_seq=None,
        transport_grade_seq=10,
        ledger_last=9,
        ledger_diag_seq=None,
        current_diag={"probe_id": "solo-stage1-current-run-diag", "script_run_seq": 10},
        ledger_max=10,
    )
    assert ok is True
    assert meta["lifecycle_not_applicable"] is True


def test_control_only_pause_binding_passes_helper() -> None:
    pre = {
        "binding_mode": BINDING_MODE_CONTROL_ONLY,
        "run_binding_consistent": True,
        "current_app_diag_seq": 10,
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
