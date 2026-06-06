"""Smoke tests for suite activity trace imports on Baseball."""

from __future__ import annotations

import importlib
from unittest.mock import patch


def test_activity_time_import_and_utc_now_iso():
    mod = importlib.import_module("activity_time")
    ts = mod.utc_now_iso()
    assert isinstance(ts, str)
    assert ts.endswith("Z")
    assert "T" in ts


def test_baseball_activity_trace_import():
    mod = importlib.import_module("baseball_activity")
    trace = mod.last_activity_trace()
    assert isinstance(trace, dict)


def test_baseball_event_trace_row_helper():
    mod = importlib.import_module("baseball_event_trace")
    row = mod.last_activity_event_row()
    assert row is None or isinstance(row, dict)


@patch("suite_activity_client.record_activity")
def test_log_trend_comparison_viewed(mock_record):
    ba = importlib.import_module("baseball_activity")
    ba.log_trend_comparison_viewed(
        "Juan Soto",
        "Anthony Volpe",
        players=["Juan Soto", "Anthony Volpe"],
        trend_stat="OPS",
        chart_mode="Actual Values",
    )
    trace = ba.last_activity_trace()
    assert trace["event_type"] == "trend_comparison_viewed"
    assert trace["resume_key"] == "trendcompare:Juan Soto:Anthony Volpe"
    assert trace["players"] == "Juan Soto vs Anthony Volpe"
    mock_record.assert_called_once()
    args = mock_record.call_args
    assert args[0][0] == "baseball"
    assert args[0][1] == "trend_comparison_viewed"
    assert args[1]["resume_key"] == "trendcompare:Juan Soto:Anthony Volpe"
