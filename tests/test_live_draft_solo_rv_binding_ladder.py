"""Unit tests for RV return-value binding ladder grading."""

from __future__ import annotations

from live_draft_solo_rv_binding_ladder import grade_rv_control_validity


def test_rv0_pass_return_value_delivery() -> None:
    rows = [
        {"phase": "rv_rv0_shell_before_mount", "expected_token": "PARITY|0|1.0"},
        {
            "phase": "rv_rv0_shell_after_mount",
            "expected_token": "PARITY|0|1.0",
            "coalesced_value": "PARITY|0|1.0",
            "browser_delivery_seen": True,
        },
    ]
    exp = {
        "client_stages": ["timer_armed", "browser_deadline_crossed", "component_value_sent"],
        "token_sent": "PARITY|0|1.0",
    }
    browser = {
        "logical_send_count": 1,
        "raw_listener_count": 1,
        "unique_send_events": 1,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "sender_row": {"instance_id": "solo_x", "is_current_registered_instance": True, "source_connected": True},
    }
    v, r = grade_rv_control_validity(
        step="RV0",
        ledger=[],
        declaration_rows=rows,
        browser=browser,
        expiration=exp,
    )
    assert v == "PASS_RETURN_VALUE_DELIVERY"


def test_invalid_when_logical_send_not_one() -> None:
    exp = {
        "client_stages": ["timer_armed", "browser_deadline_crossed", "component_value_sent"],
    }
    v, _ = grade_rv_control_validity(
        step="RV1",
        ledger=[],
        declaration_rows=[{"phase": "after_mount", "expected_token": "x", "browser_delivery_seen": True}],
        browser={
            "logical_send_count": 2,
            "raw_listener_count": 2,
            "unique_send_events": 2,
            "sending_iframe_identified": True,
            "sender_current_status": "current",
        },
        expiration=exp,
    )
    assert v == "INVALID"


def test_fail_class_a_empty_binding() -> None:
    exp = {
        "client_stages": ["timer_armed", "browser_deadline_crossed", "component_value_sent"],
    }
    browser = {
        "logical_send_count": 1,
        "raw_listener_count": 1,
        "unique_send_events": 1,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "sender_row": {"instance_id": "solo_x", "is_current_registered_instance": True, "source_connected": True},
    }
    v, r = grade_rv_control_validity(
        step="RV1",
        ledger=[],
        declaration_rows=[
            {
                "phase": "after_mount",
                "expected_token": "R|0|1.0",
                "coalesced_value": "",
                "browser_delivery_seen": True,
            },
        ],
        browser=browser,
        expiration=exp,
    )
    assert v == "FAIL"
    assert r == "FAIL_CLASS_A_empty_binding"
