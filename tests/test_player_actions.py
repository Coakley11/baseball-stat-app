"""Player action list helpers and page-state skip restore."""

import player_actions as pa


def test_dedupe_append_name():
    assert pa.dedupe_append_name(["A", "B"], "C") == ["A", "B", "C"]
    assert pa.dedupe_append_name(["A", "B"], "B") == ["A", "B"]
    assert pa.dedupe_append_name([], "X", cap=2) == ["X"]


def test_merge_chart_labels():
    assert pa.merge_chart_labels(["a", "b"], "c") == ["a", "b", "c"]
    assert pa.merge_chart_labels(["a", "b"], "a") == ["b", "a"]
    assert pa.merge_chart_labels(["a", "b", "c"], "d", max_labels=3) == ["b", "c", "d"]


def test_skip_page_restore_flag():
    import page_state as pg

    session = {
        "page_filter_state": {
            "Trend Value": {"trend_lag": 99},
        },
        "_page_state_last_active": "Historical Explorer",
    }
    session["trend_lag"] = 3
    pg.handle_sidebar_page_state(session, "Trend Value", lambda x: x, None)
    assert session["trend_lag"] == 99

    session2 = {
        "page_filter_state": {"Trend Value": {"trend_lag": 99}},
        "_page_state_last_active": "Historical Explorer",
        "_skip_page_restore_for": "Trend Value",
        "trend_lag": 3,
    }
    pg.handle_sidebar_page_state(session2, "Trend Value", lambda x: x, None)
    assert session2["trend_lag"] == 3
