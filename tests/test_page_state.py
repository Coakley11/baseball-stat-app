"""Sidebar page-state save/restore (page_state.py)."""

import page_state as pg


def _norm(page: str) -> str:
    return page


def test_ml_display_filters_saved_and_restored_on_sidebar_return():
    session = {
        "page_filter_state": {},
        "_page_state_last_active": "ML Predictions",
        "ml_position_filter": "1B",
        "ml_sort_by": "Predicted HR",
        "ml_projection_insight_player": "Aaron Judge",
        "ml_predictions_have_run": True,
    }
    pg.save_page_state(session, "ML Predictions", session["page_filter_state"])
    session["ml_position_filter"] = "All positions"
    session["ml_sort_by"] = "Predicted OPS"
    session["ml_projection_insight_player"] = ""
    session["_page_state_last_active"] = "Trend Value"

    pg.handle_sidebar_page_state(session, "ML Predictions", _norm, None)

    assert session["ml_position_filter"] == "1B"
    assert session["ml_sort_by"] == "Predicted HR"
    assert session["ml_projection_insight_player"] == "Aaron Judge"


def test_sidebar_restore_skipped_when_contextual_transfer_targets_page():
    session = {
        "page_filter_state": {
            "ML Predictions": {"ml_position_filter": "C"},
        },
        "_page_state_last_active": "Trend Value",
        "ml_position_filter": "OF",
    }
    pending = {"target": "ML Predictions"}
    pg.handle_sidebar_page_state(session, "ML Predictions", _norm, pending)
    assert session["ml_position_filter"] == "OF"


def test_trend_position_filter_round_trip():
    session = {
        "page_filter_state": {},
        "_page_state_last_active": "Trend Value",
        "trend_position_filter": "SS",
        "trend_lag": 5,
    }
    pg.save_page_state(session, "Trend Value", session["page_filter_state"])
    session["trend_position_filter"] = "All positions"
    session["_page_state_last_active"] = "Valuation"
    pg.handle_sidebar_page_state(session, "Trend Value", _norm, None)
    assert session["trend_position_filter"] == "SS"
    assert session["trend_lag"] == 5
