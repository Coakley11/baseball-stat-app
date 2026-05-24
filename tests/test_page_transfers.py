"""Unit tests for contextual page transfer rules (stdlib + pandas only)."""

import pandas as pd

import page_transfers as pg


def test_valuation_does_not_accept_transferred_players():
    assert not pg.target_accepts_transferred_players("Valuation")
    assert not pg.target_allows_top3_players("Valuation")


def test_comparison_and_trend_accept_players():
    assert pg.target_accepts_transferred_players("Comparison Tool")
    assert pg.target_accepts_transferred_players("Trend Value")


def test_top3_checkbox_hidden_for_valuation_target():
    df = pd.DataFrame({"fullName": ["A", "B", "C"], "OPS": [1.0, 0.9, 0.8]})
    assert not pg.should_show_top3_checkbox("hist_to_valuation", "Valuation", df, "fullName")
    assert pg.should_show_top3_checkbox("hist_to_compare", "Comparison Tool", df, "fullName")


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
