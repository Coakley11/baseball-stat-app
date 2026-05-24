"""Unit tests for contextual page transfer rules (stdlib + pandas only)."""

import pandas as pd

import page_transfers as pg


def test_valuation_accepts_transferred_players():
    assert pg.target_accepts_transferred_players("Valuation")
    assert pg.target_allows_top3_players("Valuation")


def test_comparison_and_trend_accept_players():
    assert pg.target_accepts_transferred_players("Comparison Tool")
    assert pg.target_accepts_transferred_players("Trend Value")


def test_top3_checkbox_for_valuation_from_hist_and_ml():
    df = pd.DataFrame({"fullName": ["A", "B", "C"], "OPS": [1.0, 0.9, 0.8]})
    assert pg.should_show_top3_checkbox("hist_to_valuation", "Valuation", df, "fullName")
    assert pg.should_show_top3_checkbox("hist_to_compare", "Comparison Tool", df, "fullName")
    assert not pg.should_show_top3_checkbox("hist_to_leaders", "Leaderboards", df, "fullName")


def test_compare_to_valuation_does_not_auto_send_players():
    session = {"compare_players": ["Player A (2020-2024)", "Player B (2019-2023)"]}
    payload = pg.build_transfer(session, "compare_to_valuation", {"send_top_3_players": True})
    assert payload["transfer_players"]["mode"] == "none"
    assert not payload["transfer_players"]["names"]
    assert not payload["transfer_players"]["labels"]


def test_compare_to_trend_sends_selected_players():
    session = {"compare_players": ["Player A (2020-2024)"]}
    payload = pg.build_transfer(session, "compare_to_trend", {})
    assert payload["transfer_players"]["mode"] == "compare_selected"
    assert payload["transfer_players"]["labels"] == ["Player A (2020-2024)"]


def test_fantasy_filter_to_raw_of_includes_outfield_codes():
    assert pg.fantasy_filter_to_raw_positions("OF") == ["OF", "LF", "CF", "RF"]
    assert pg.fantasy_filter_to_raw_positions("1B") == ["1B"]
    assert pg.fantasy_filter_to_raw_positions("All positions") == []


def test_raw_positions_to_fantasy_filter_of_family():
    assert pg.raw_positions_to_fantasy_filter(["LF", "CF"]) == "OF"
    assert pg.raw_positions_to_fantasy_filter(["1B"]) == "1B"
    assert pg.raw_positions_to_fantasy_filter(["DH"]) == "DH/UTIL"


def test_trend_to_valuation_transfers_position_via_target_page():
    session = {
        "trend_lag": 5,
        "trend_position_filter": "OF",
        "_lahman_max_year": 2024,
    }
    payload = pg.build_transfer(
        session,
        "trend_to_valuation",
        {"target_page": "Valuation", "dataset_max_year": 2024},
    )
    assert payload["transfer_filters"]["value_position_filter"] == "OF"
    assert payload["transfer_filters"]["value_lag"] == 5


def test_valuation_to_hist_transfers_position_multiselect():
    session = {
        "value_lag": 3,
        "value_position_filter": "1B",
        "_lahman_max_year": 2024,
    }
    payload = pg.build_transfer(
        session,
        "valuation_to_hist",
        {"target_page": "Historical Explorer", "dataset_max_year": 2024},
    )
    assert payload["transfer_filters"]["historical_position_filter"] == ["1B"]
    assert payload["transfer_filters"]["hist_pos"] == ["1B"]
    assert payload["transfer_filters"]["historical_year_range_filter"] == (2022, 2024)


def test_valuation_to_trend_transfers_catcher():
    session = {"value_lag": 4, "value_position_filter": "C"}
    payload = pg.build_transfer(
        session,
        "valuation_to_trend",
        {"target_page": "Trend Value"},
    )
    assert payload["transfer_filters"]["trend_position_filter"] == "C"


def test_hist_to_trend_infers_position_from_hist_pos():
    session = {
        "historical_year_range_filter": (2020, 2024),
        "historical_position_filter": ["SS"],
    }
    payload = pg.build_transfer(
        session,
        "hist_to_trend",
        {"target_page": "Trend Value"},
    )
    assert payload["transfer_filters"]["trend_position_filter"] == "SS"
    assert payload["transfer_filters"]["trend_lag"] == 5


def test_sanitize_trend_position_filter_string():
    assert pg._sanitize_value("trend_position_filter", "OF") == "OF"
    assert pg._sanitize_value("trend_position_filter", "All positions") is None
    assert pg._sanitize_value("trend_position_filter", ["OF"]) is None


def test_valuation_top3_checkbox_label():
    assert "valuation" in pg.top3_checkbox_label("Valuation").lower()


def test_valuation_top3_checkbox_targets():
    df = pd.DataFrame({
        "fullName": ["A", "B", "C"],
        "Valuation Score": [0.8, 1.0, 0.6],
    })
    assert pg.should_show_top3_checkbox("valuation_to_compare", "Comparison Tool", df, "fullName")
    assert pg.should_show_top3_checkbox("valuation_to_trend", "Trend Value", df, "fullName")
    assert not pg.should_show_top3_checkbox("valuation_to_hist", "Historical Explorer", df, "fullName")
    assert not pg.should_show_top3_checkbox("valuation_to_leaders", "Leaderboards", df, "fullName")


def _valuation_xfer_extra(df, *, send_top3: bool, target_page: str):
    return {
        "send_top_3_players": send_top3,
        "target_page": target_page,
        "transfer_results_df": df,
        "transfer_name_col": "fullName",
        "rank_stat": "Valuation Score",
        "default_rank_stat": "Valuation Score",
    }


def test_valuation_to_compare_sends_top3_in_table_order():
    df = pd.DataFrame({
        "fullName": ["Alice", "Bob", "Carol", "Dave"],
        "Valuation Score": [0.9, 1.0, 0.5, 0.3],
    })
    session = {"value_lag": 3, "value_position_filter": "OF"}
    payload = pg.build_transfer(
        session,
        "valuation_to_compare",
        _valuation_xfer_extra(df, send_top3=True, target_page="Comparison Tool"),
    )
    assert payload["transfer_players"]["mode"] == "top_3"
    assert payload["transfer_players"]["names"] == ["Alice", "Bob", "Carol"]


def test_valuation_to_trend_sends_top3_1b_filtered_order():
    df = pd.DataFrame({
        "fullName": ["First", "Second", "Third", "Fourth"],
        "Valuation Score": [0.4, 1.0, 0.7, 0.2],
    })
    session = {"value_lag": 5, "value_position_filter": "1B"}
    payload = pg.build_transfer(
        session,
        "valuation_to_trend",
        _valuation_xfer_extra(df, send_top3=True, target_page="Trend Value"),
    )
    assert payload["transfer_players"]["mode"] == "top_3"
    assert payload["transfer_players"]["names"] == ["First", "Second", "Third"]
    assert payload["transfer_filters"]["trend_position_filter"] == "1B"
    assert payload["transfer_filters"]["trend_lag"] == 5


def test_valuation_top3_off_sends_no_players():
    df = pd.DataFrame({"fullName": ["A", "B", "C"], "Valuation Score": [1.0, 0.5, 0.2]})
    payload = pg.build_transfer(
        {"value_lag": 3},
        "valuation_to_compare",
        _valuation_xfer_extra(df, send_top3=False, target_page="Comparison Tool"),
    )
    assert payload["transfer_players"]["mode"] == "none"
    assert not payload["transfer_players"]["names"]


def test_valuation_top3_caption():
    cap = pg.top3_transfer_caption("Valuation", ["Player A", "Player B", "Player C"])
    assert cap == "Sending top 3 valuation players: Player A, Player B, Player C"


def test_ml_to_trend_transfers_position_and_window():
    session = {"ml_lookback": 4, "ml_min_games": 120, "ml_position_filter": "OF"}
    payload = pg.build_transfer(
        session,
        "ml_to_trend",
        {"target_page": "Trend Value", "transfer_position": "OF", "ml_lookback": 4, "ml_min_games": 120},
    )
    assert payload["transfer_filters"]["trend_position_filter"] == "OF"
    assert payload["transfer_filters"]["trend_lag"] == 4
    assert payload["transfer_filters"]["trend_min_g"] == 120


def test_valuation_to_ml_uses_transfer_position():
    session = {"value_lag": 3, "value_position_filter": "1B"}
    payload = pg.build_transfer(session, "valuation_to_ml", {"target_page": "ML Predictions"})
    assert payload["transfer_filters"]["ml_lookback"] == 3
    assert payload["transfer_filters"]["transfer_position"] == "1B"


def test_ml_to_draft_assistant_transfers_window_and_style():
    session = {
        "ml_lookback": 4,
        "ml_min_games": 120,
        "ml_projection_style": "Aggressive",
    }
    payload = pg.build_transfer(
        session,
        "ml_to_draft_assistant",
        {"target_page": "Draft Assistant Simulator", "ml_lookback": 4, "ml_min_games": 120, "ml_projection_style": "Aggressive"},
    )
    assert payload["transfer_filters"]["draft_window"] == 4
    assert payload["transfer_filters"]["fantasy_draft_projection_style"] == "Aggressive"
    assert payload["transfer_filters"]["draft_ml_min_games_signal"] == 120
    assert payload["transfer_filters"]["draft_use_ml_blend"] is True
    assert payload["transfer_players"]["mode"] == "none"


def test_draft_assistant_to_ml_transfers_window():
    session = {
        "draft_window": 5,
        "fantasy_draft_projection_style": "Balanced",
        "draft_ml_min_games_signal": 200,
    }
    payload = pg.build_transfer(session, "draft_assistant_to_ml", {"target_page": "ML Predictions"})
    assert payload["transfer_filters"]["ml_lookback"] == 5
    assert payload["transfer_filters"]["ml_projection_style"] == "Balanced"
    assert payload["transfer_filters"]["ml_min_games"] == 200


def test_ml_to_sleepers_includes_min_ab_and_position():
    session = {"ml_lookback": 3, "ml_min_games": 100, "ml_min_ab": 250, "ml_position_filter": "OF"}
    payload = pg.build_transfer(
        session,
        "ml_to_sleepers",
        {
            "target_page": "Fantasy Sleepers & Busts",
            "transfer_position": "OF",
            "ml_lookback": 3,
            "ml_min_games": 100,
            "ml_min_ab": 250,
        },
    )
    assert payload["transfer_filters"]["fantasy_market_window"] == 3
    assert payload["transfer_filters"]["fantasy_market_min_g"] == 100
    assert payload["transfer_filters"]["fantasy_market_min_ab"] == 250
    assert payload["transfer_filters"]["fantasy_market_positions"] == ["OF", "LF", "CF", "RF"]


def test_ml_top3_checkbox_for_compare_trend_valuation_not_sleepers():
    df = pd.DataFrame({"Player": ["A", "B", "C"], "Predicted HR": [40, 35, 30]})
    assert pg.should_show_top3_checkbox("ml_to_compare", "Comparison Tool", df, "Player")
    assert pg.should_show_top3_checkbox("ml_to_trend", "Trend Value", df, "Player")
    assert pg.should_show_top3_checkbox("ml_to_valuation", "Valuation", df, "Player")
    assert not pg.should_show_top3_checkbox("ml_to_sleepers", "Fantasy Sleepers & Busts", df, "Player")


def test_ml_predictions_registry_lists_all_fantasy_hub_targets():
    entries = pg.CONTEXTUAL_NAV_REGISTRY[("ML Predictions", "after_table")]
    targets = {e["target"] for e in entries}
    expected = {
        "Trend Value",
        "Valuation",
        "Comparison Tool",
        "Fantasy Sleepers & Busts",
        "Draft Assistant Simulator",
        "Draft Simulation Test Mode",
        "Live Draft Room",
        "Draft Room Simulator",
    }
    assert targets == expected


def test_compare_to_ml_maps_year_range_to_lookback():
    session = {"compare_year_range": (2020, 2024)}
    payload = pg.build_transfer(session, "compare_to_ml", {"target_page": "ML Predictions"})
    assert payload["transfer_filters"]["ml_lookback"] == 5
