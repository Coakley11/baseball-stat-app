"""Unit tests for RV return-value binding ladder grading."""

from __future__ import annotations

from live_draft_solo_rv_binding_ladder import (
    grade_rv_control_validity,
    validate_rv_real_room_ledger,
    filter_observations_after_epoch,
)


def test_invalid_rv1_hydration_not_hydrated() -> None:
    reason = validate_rv_real_room_ledger(
        [
            {"event": "script_begin"},
            {"event": "rv_entrypoint_entered"},
        ],
        step="RV1",
        harness_room_id="ABCD1234",
    )
    assert reason == "INVALID_RV_REAL_ROOM_HYDRATION_not_hydrated"


def test_invalid_rv1_component_not_declared() -> None:
    reason = validate_rv_real_room_ledger(
        [
            {"event": "script_begin"},
            {"event": "rv_entrypoint_entered"},
            {"event": "real_room_hydrated", "room_id": "ABCD1234", "expected_token": "ABCD1234|0|1.0"},
            {"event": "rv_mount_failed", "extra": {"reason": "mount_error"}},
        ],
        step="RV1",
        harness_room_id="ABCD1234",
    )
    assert reason == "INVALID_RV_COMPONENT_NOT_DECLARED_mount_error"


def test_filter_epoch_removes_pre_navigation_timer() -> None:
    exp = {
        "double_production_send_analysis": {
            "timeline": [
                {"ts": 100.0, "stage": "timer_armed", "widget_key": "solo_countdown_wake_solo_persistent"},
                {"ts": 5000.0, "stage": "timer_armed", "widget_key": "solo_countdown_wake_solo_persistent"},
                {"ts": 5100.0, "stage": "transport_before_postMessage", "token_preview": "R|0|9.0"},
            ],
            "timer_armed_timestamps": [100.0, 5000.0],
        },
        "client_stages": ["timer_armed", "component_value_sent"],
    }
    reg = {"last": [{"ts_ms": 100.0}, {"ts_ms": 6000.0, "instance_id": "solo_x"}]}
    fexp, freg = filter_observations_after_epoch(exp, reg, epoch_ms=4000.0, expected_token="R|0|9.0", run_id="run-1")
    timer = fexp["double_production_send_analysis"]["timer_armed_timestamps"]
    assert timer == [5000.0]
    assert len(freg["last"]) == 1
    assert freg["run_id"] == "run-1"


def test_rv0_pass_return_value_delivery() -> None:
    rows = [
        {"phase": "before_mount", "expected_token": "PARITY|0|1.0", "widget_key": "solo_countdown_wake_solo_persistent", "script_run_id": "s1", "event": "declaration_attempt"},
        {
            "phase": "after_mount",
            "expected_token": "PARITY|0|1.0",
            "coalesced_value": "PARITY|0|1.0",
            "browser_delivery_seen": True,
            "widget_key": "solo_countdown_wake_solo_persistent",
            "script_run_id": "s1",
            "event": "declaration_returned",
        },
        {
            "phase": "post_delivery_redeclaration",
            "expected_token": "PARITY|0|1.0",
            "coalesced_value": "PARITY|0|1.0",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "script_run_id": "s1",
            "event": "post_delivery_redeclaration",
            "browser_delivery_seen": True,
        },
    ]
    exp = {
        "client_stages": ["timer_armed", "browser_deadline_crossed", "component_value_sent"],
        "token_sent": "PARITY|0|1.0",
        "double_production_send_analysis": {"timer_armed_timestamps": [1]},
    }
    browser = {
        "logical_send_count": 1,
        "raw_listener_count": 1,
        "unique_send_events": 1,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "parent_listener_on_app_window": True,
        "timer_arm_accounting": {"logical_timer_arms": 1, "raw_timer_arms": 1, "instrumentation_duplicate": False},
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
        "double_production_send_analysis": {"timer_armed_timestamps": [1]},
        "harness_room_id": "R1",
    }
    ledger = [
        {"event": "script_begin", "room_id": "R1"},
        {"event": "rv_entrypoint_entered"},
        {"event": "real_room_hydrated", "room_id": "R1", "expected_token": "x"},
        {"event": "declaration_attempt", "expected_token": "x", "widget_key": "k", "script_run_id": "s1"},
        {"event": "declaration_returned", "expected_token": "x", "widget_key": "k", "script_run_id": "s1"},
        {"event": "post_delivery_redeclaration", "expected_token": "x", "widget_key": "k", "script_run_id": "s1"},
    ]
    v, _ = grade_rv_control_validity(
        step="RV1",
        ledger=ledger,
        declaration_rows=[
            {"phase": "before_mount", "expected_token": "x", "widget_key": "k", "script_run_id": "s1", "event": "declaration_attempt"},
            {"phase": "after_mount", "expected_token": "x", "browser_delivery_seen": True, "widget_key": "k", "script_run_id": "s1", "event": "declaration_returned"},
            {"phase": "post_delivery_redeclaration", "expected_token": "x", "widget_key": "k", "script_run_id": "s1", "event": "post_delivery_redeclaration"},
        ],
        browser={
            "logical_send_count": 2,
            "raw_listener_count": 2,
            "unique_send_events": 2,
            "sending_iframe_identified": True,
            "sender_current_status": "current",
            "parent_listener_on_app_window": True,
            "timer_arm_accounting": {"logical_timer_arms": 1, "raw_timer_arms": 1},
        },
        expiration=exp,
    )
    assert v == "INVALID"


def test_fail_class_a_empty_binding() -> None:
    exp = {
        "client_stages": ["timer_armed", "browser_deadline_crossed", "component_value_sent"],
        "double_production_send_analysis": {"timer_armed_timestamps": [1]},
        "harness_room_id": "R1",
    }
    ledger = [
        {"event": "script_begin"},
        {"event": "rv_entrypoint_entered"},
        {"event": "real_room_hydrated", "room_id": "R1", "expected_token": "R|0|1.0"},
        {"event": "declaration_attempt", "expected_token": "R|0|1.0", "widget_key": "k", "script_run_id": "s1"},
        {"event": "declaration_returned", "expected_token": "R|0|1.0", "widget_key": "k", "script_run_id": "s1"},
        {"event": "post_delivery_redeclaration", "expected_token": "R|0|1.0", "widget_key": "k", "script_run_id": "s1"},
    ]
    browser = {
        "logical_send_count": 1,
        "raw_listener_count": 1,
        "unique_send_events": 1,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "parent_listener_on_app_window": True,
        "timer_arm_accounting": {"logical_timer_arms": 1, "raw_timer_arms": 1},
        "sender_row": {"instance_id": "solo_x", "is_current_registered_instance": True, "source_connected": True},
    }
    v, r = grade_rv_control_validity(
        step="RV1",
        ledger=ledger,
        declaration_rows=[
            {
                "phase": "before_mount",
                "expected_token": "R|0|1.0",
                "widget_key": "k",
                "script_run_id": "s1",
                "event": "declaration_attempt",
            },
            {
                "phase": "after_mount",
                "expected_token": "R|0|1.0",
                "coalesced_value": "",
                "browser_delivery_seen": True,
                "widget_key": "k",
                "script_run_id": "s1",
                "event": "declaration_returned",
            },
            {
                "phase": "post_delivery_redeclaration",
                "expected_token": "R|0|1.0",
                "coalesced_value": "",
                "widget_key": "k",
                "script_run_id": "s1",
                "event": "post_delivery_redeclaration",
                "browser_delivery_seen": True,
            },
        ],
        browser=browser,
        expiration=exp,
    )
    assert v == "FAIL"
    assert r == "FAIL_CLASS_A_empty_binding"
