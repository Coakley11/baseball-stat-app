"""Runner-only RV1 browser observation grading."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from solo_rv_browser_observation import (
    analyze_timer_arms_identity,
    combine_rv1_verdicts,
    filter_observations_by_run_identity,
    grade_rv1_python_binding,
    grade_rv_post_delivery_lane,
    validate_rv_browser_delivery,
)


def test_grade_rv1_python_binding_coalesced():
    token = "ROOM|0|123.456"
    rows = [
        {"event": "real_room_hydrated", "run_id": "r1", "expected_token": token},
        {
            "event": "declaration_returned",
            "run_id": "r1",
            "coalesced_value": token,
        },
    ]
    verdict, reason = grade_rv1_python_binding(rows, expected_token=token)
    assert verdict == "PASS_RETURN_VALUE_DELIVERY"


def test_browser_delivery_pass_without_post_delivery_ledger():
    browser = {
        "logical_send_count": 1,
        "unique_send_events": 1,
        "browser_send_proven": True,
        "parent_listener_on_app_window": True,
        "sending_iframe_identified": True,
        "sender_current_status": "current",
        "token_sent": "R|0|9.0",
        "transport_send_evidence": {"token_match": True},
    }
    ok, reason = validate_rv_browser_delivery(
        browser=browser,
        expiration={"client_stages": ["component_value_sent"], "deduped_logical_sends": [{"ts": 9000, "token": "R|0|9.0"}]},
        control_probe_rows=[{"event": "rv3_production_placement_entered"}],
        expected_token="R|0|9.0",
    )
    assert ok is True
    assert reason == "PASS"
    lane, _ = grade_rv_post_delivery_lane([], expected_token="R|0|9.0", browser_send_ts=9.0)
    assert lane.startswith("INCOMPLETE")


def test_combine_python_pass_browser_timer_miss():
    from solo_rv_browser_observation import combine_rv_control_verdicts

    overall, reason, py, br, life, warnings = combine_rv_control_verdicts(
        setup_invalid="",
        python_verdict="PASS_RETURN_VALUE_DELIVERY",
        python_reason="ok",
        browser_delivery_ok=True,
        browser_delivery_reason="PASS",
        lifecycle_lane="WARN_TIMER_ARM_EVENT_NOT_OBSERVED",
        observability_warnings=["WARN_TIMER_ARM_EVENT_NOT_OBSERVED"],
    )
    assert py == "PASS_RETURN_VALUE_DELIVERY"
    assert br == "PASS"
    assert life == "WARN_TIMER_ARM_EVENT_NOT_OBSERVED"
    assert overall == "PASS_WITH_OBSERVABILITY_WARN"
    assert "WARN_TIMER_ARM" in reason


def test_combine_python_pass_browser_delivery_fail():
    from solo_rv_browser_observation import combine_rv_control_verdicts

    overall, reason, py, br, _life, _w = combine_rv_control_verdicts(
        setup_invalid="",
        python_verdict="PASS_RETURN_VALUE_DELIVERY",
        python_reason="ok",
        browser_delivery_ok=False,
        browser_delivery_reason="INVALID_BROWSER_SEND_COUNT_0_need_1",
        lifecycle_lane="PASS",
        observability_warnings=[],
    )
    assert overall == "INVALID"
    assert py == "PASS_RETURN_VALUE_DELIVERY"


def test_filter_keeps_pre_declaration_timer_arm():
    identity = {
        "solo_rv_run_id": "run-1",
        "room_id": "ABCD",
        "expected_token": "ABCD|0|9.0",
        "widget_key": "solo_countdown_wake_solo_persistent",
        "deadline": 9.0,
    }
    exp = {
        "double_production_send_analysis": {
            "timeline": [
                {
                    "stage": "timer_armed",
                    "ts": 1000.0,
                    "token_preview": "ABCD|0|9.0",
                    "widget_key": "solo_countdown_wake_solo_persistent",
                    "extra_preview": "solo_1_abc",
                },
                {
                    "stage": "component_value_sent",
                    "ts": 2000.0,
                    "token_preview": "ABCD|0|9.0",
                    "widget_key": "solo_countdown_wake_solo_persistent",
                },
            ],
            "timer_armed_timestamps": [],
        },
        "client_stages": [],
    }
    reg = {"last": [], "logical": [], "current": "solo_1_abc"}
    fexp, freg = filter_observations_by_run_identity(exp, reg, identity)
    arms = analyze_timer_arms_identity(fexp, freg, identity)
    assert arms["logical_timer_arms"] == 1
    assert arms["raw_timer_arms"] == 1


def test_merge_ledger_rows_unions_by_event_sequence():
    from run_solo_rv_binding_ladder_auth import merge_ledger_rows

    a = [{"event_sequence": 1, "event": "a", "ts": 1.0}]
    b = [{"event_sequence": 2, "event": "b", "ts": 2.0}, {"event_sequence": 1, "event": "a2", "ts": 1.1}]
    merged = merge_ledger_rows(a, b)
    assert len(merged) == 2
    assert merged[1]["event"] == "b"
