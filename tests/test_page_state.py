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


def test_draft_room_import_uploader_not_snapshotted_or_restored():
    session = {
        "page_filter_state": {},
        "_page_state_last_active": "Draft Room Simulator",
        "room_your_team": "Daniel",
        "draft_room_import_uploader": {"fake": "uploaded_bytes"},
        "draft_room_import_last_processed_hash": "abc123",
    }
    pg.save_page_state(session, "Draft Room Simulator", session["page_filter_state"])
    snap = session["page_filter_state"].get("Draft Room Simulator") or {}
    assert "draft_room_import_uploader" not in snap
    assert "draft_room_import_last_processed_hash" not in snap
    assert snap.get("room_your_team") is None
    session.pop("draft_room_import_uploader", None)
    session.pop("draft_room_import_last_processed_hash", None)
    session["page_filter_state"]["Draft Room Simulator"] = {
        **(session["page_filter_state"].get("Draft Room Simulator") or {}),
        "room_your_team": "Team 2",
    }
    pg.restore_page_state(session, "Draft Room Simulator", session["page_filter_state"])
    assert "draft_room_import_uploader" not in session
    assert session.get("draft_room_import_last_processed_hash") is None
    assert session.get("room_your_team") == "Daniel"


def test_live_draft_confirm_button_not_snapshotted():
    session = {
        "page_filter_state": {},
        "_page_state_last_active": "Live Draft Room",
        "live_draft_timer": "90 seconds",
        "live_draft_confirm_sim_start": True,
        "_simulator_to_live_show_confirm": True,
    }
    pg.save_page_state(session, "Live Draft Room", session["page_filter_state"])
    snap = session["page_filter_state"].get("Live Draft Room") or {}
    assert "live_draft_confirm_sim_start" not in snap
    assert "live_draft_confirm_sim_cancel" not in snap
    assert snap.get("live_draft_timer") == "90 seconds"
    session["live_draft_confirm_sim_start"] = False
    session.pop("_simulator_to_live_show_confirm", None)
    pg.restore_page_state(session, "Live Draft Room", session["page_filter_state"])
    assert session.get("live_draft_confirm_sim_start") is not True
    assert session.get("_simulator_to_live_show_confirm") is None


def test_start_live_draft_pending_not_snapshotted():
    session = {
        "page_filter_state": {},
        "_page_state_last_active": "Live Draft Room",
        "_start_live_draft_pending": True,
        "_start_live_draft_mode": "simulator",
    }
    pg.save_page_state(session, "Live Draft Room", session["page_filter_state"])
    snap = session["page_filter_state"].get("Live Draft Room") or {}
    assert "_start_live_draft_pending" not in snap
    assert "_start_live_draft_mode" not in snap
