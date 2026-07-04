"""Player action list helpers, eligibility, and trade context discovery."""

import pandas as pd

import player_actions as pa
from player_trade_context import (
    TRADE_ACTION_ACQUIRE,
    TRADE_ACTION_TRADE_AWAY,
    collect_player_roster_contexts,
    complete_trade_acquire_flow,
    player_has_roster_context,
    split_trade_acquire_contexts,
    start_trade_acquire_flow,
)


def _yearly_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "playerID": ["ruthb01", "judgea01", "bonds01"],
            "fullName": ["Babe Ruth", "Aaron Judge", "Barry Bonds"],
            "yearID": [1935, 2025, 2007],
        }
    )


def test_dedupe_append_name():
    assert pa.dedupe_append_name(["A", "B"], "C") == ["A", "B", "C"]
    assert pa.dedupe_append_name(["A", "B"], "B") == ["A", "B"]
    assert pa.dedupe_append_name([], "X", cap=2) == ["X"]


def test_merge_chart_labels():
    assert pa.merge_chart_labels(["a", "b"], "c") == ["a", "b", "c"]
    assert pa.merge_chart_labels(["a", "b"], "a") == ["b", "a"]
    assert pa.merge_chart_labels(["a", "b", "c"], "d", max_labels=3) == ["b", "c", "d"]


def test_is_active_current_player_recent_and_historical():
    yearly = _yearly_sample()
    assert pa.is_active_current_player({"playerID": "judgea01"}, yearly) is True
    assert pa.is_active_current_player({"fullName": "Babe Ruth"}, yearly) is False
    assert pa.is_active_current_player({"fullName": "Barry Bonds"}, yearly) is False


def test_collect_player_roster_contexts_live_simulator_and_archive():
    session = {
        "room_your_team": "Daniel",
        "live_draft_room": {
            "config": {"league_name": "Mock League", "your_team": "Daniel"},
            "draft_board": [
                {"Player": "Aaron Judge", "Team": "Rivals"},
                {"Player": "Mike Trout", "Team": "Daniel"},
                {"Player": "Mookie Betts", "Team": "Rivals"},
            ],
        },
        "draft_room_table": pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Rivals"],
                "Player": ["Mike Trout", "Mookie Betts"],
            }
        ),
        "draft_archive_teams": [
            {
                "draft_id": "arch1",
                "draft_name": "Saved Team",
                "draft_type": "simulator",
                "team_name": "Daniel",
                "players": [{"Player": "Mookie Betts"}],
            }
        ],
    }

    judge_contexts = collect_player_roster_contexts(session, "Aaron Judge")
    assert len(judge_contexts) == 1
    assert judge_contexts[0]["is_user_team"] is False

    trout_contexts = collect_player_roster_contexts(session, "Mike Trout")
    trade, acquire = split_trade_acquire_contexts(trout_contexts)
    assert trade
    assert not acquire

    betts_contexts = collect_player_roster_contexts(session, "Mookie Betts")
    assert len(betts_contexts) == 2
    trade, acquire = split_trade_acquire_contexts(betts_contexts)
    assert trade and acquire

    assert player_has_roster_context(session, "Aaron Judge") is True
    assert player_has_roster_context(session, "Babe Ruth") is False


def test_start_trade_acquire_flow_auto_acquire_and_mode_prompt():
    session = {
        "room_your_team": "Daniel",
        "live_draft_room": {
            "config": {"league_name": "Mock League", "your_team": "Daniel"},
            "draft_board": [{"Player": "Aaron Judge", "Team": "Rivals"}],
        },
        "pending_trade_acquire_players": [],
        "pending_trade_away_players": [],
    }
    msg = start_trade_acquire_flow(session, player_name="Aaron Judge", key_prefix="test")
    assert msg is not None
    assert "acquire target" in msg
    assert session["pending_trade_acquire_players"] == ["Aaron Judge"]

    session = {
        "room_your_team": "Daniel",
        "live_draft_room": {
            "config": {"league_name": "Mock League", "your_team": "Daniel"},
            "draft_board": [{"Player": "Mookie Betts", "Team": "Rivals"}],
        },
        "draft_room_table": pd.DataFrame(columns=["Round", "Pick", "Team", "Player"]),
        "draft_archive_teams": [
            {
                "draft_id": "arch1",
                "draft_name": "Saved Team",
                "draft_type": "simulator",
                "team_name": "Daniel",
                "players": [{"Player": "Mookie Betts"}],
            }
        ],
        "pending_trade_acquire_players": [],
        "pending_trade_away_players": [],
    }
    msg = start_trade_acquire_flow(session, player_name="Mookie Betts", key_prefix="ctx")
    assert msg is None
    assert session["_player_trade_acquire_flow"]["step"] == "choose_mode"

    msg = complete_trade_acquire_flow(session, mode=TRADE_ACTION_ACQUIRE)
    assert "acquire target" in msg
    assert session["pending_trade_acquire_players"] == ["Mookie Betts"]

    session = {
        "room_your_team": "Daniel",
        "live_draft_room": {
            "config": {"league_name": "Mock League", "your_team": "Daniel"},
            "draft_board": [{"Player": "Mike Trout", "Team": "Daniel"}],
        },
        "draft_room_table": pd.DataFrame(columns=["Round", "Pick", "Team", "Player"]),
        "pending_trade_acquire_players": [],
        "pending_trade_away_players": [],
    }
    msg = start_trade_acquire_flow(session, player_name="Mike Trout", key_prefix="trade")
    assert msg is not None
    assert "trade candidate" in msg
    assert session["pending_trade_away_players"] == ["Mike Trout"]


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
