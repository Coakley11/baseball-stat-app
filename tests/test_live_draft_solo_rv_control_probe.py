"""Tests for stable RV control probe ledger."""

from __future__ import annotations

from live_draft_solo_rv_binding_ladder import grade_rv_control_validity
from live_draft_solo_rv_control_probe import ledger_to_declaration_rows


def _browser_ok() -> dict:
    return {
        "logical_send_count": 1,
        "raw_listener_count": 1,
        "unique_send_events": 1,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "parent_listener_on_app_window": True,
        "timer_arm_accounting": {"raw_timer_arms": 2, "logical_timer_arms": 1, "instrumentation_duplicate": True},
        "sender_row": {"instance_id": "solo_x", "is_current_registered_instance": True, "source_connected": True},
    }


def test_invalid_probe_missing() -> None:
    v, r = grade_rv_control_validity(
        step="RV0",
        ledger=[],
        declaration_rows=[],
        browser=_browser_ok(),
        expiration={
            "client_stages": ["browser_deadline_crossed"],
            "token_sent": "T",
            "double_production_send_analysis": {"timer_armed_timestamps": [1]},
        },
    )
    assert v == "INVALID"
    assert r == "INVALID_PYTHON_DECLARATION_PROBE_MISSING"


def test_ledger_mapping_and_pass() -> None:
    ledger = [
        {
            "event": "declaration_attempt",
            "expected_token": "PARITY|0|1.0",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "streamlit_session_id": "s1",
        },
        {
            "event": "declaration_returned",
            "expected_token": "PARITY|0|1.0",
            "coalesced_value": "PARITY|0|1.0",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "streamlit_session_id": "s1",
            "browser_send_seen": True,
        },
        {
            "event": "post_delivery_redeclaration",
            "expected_token": "PARITY|0|1.0",
            "coalesced_value": "PARITY|0|1.0",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "streamlit_session_id": "s1",
        },
    ]
    rows = ledger_to_declaration_rows(ledger)
    exp = {
        "client_stages": ["browser_deadline_crossed", "component_value_sent"],
        "token_sent": "PARITY|0|1.0",
        "double_production_send_analysis": {"timer_armed_timestamps": [1, 2]},
    }
    v, _ = grade_rv_control_validity(step="RV0", ledger=[], declaration_rows=rows, browser=_browser_ok(), expiration=exp)
    assert v == "PASS_RETURN_VALUE_DELIVERY"
