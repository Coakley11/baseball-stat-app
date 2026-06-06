"""Smoke tests for suite activity trace imports on Baseball."""

from __future__ import annotations

import importlib


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
