"""Player action list helpers, eligibility, and trade context discovery."""

import pandas as pd

import player_actions as pa
from fantasy_league_context import (
    TRADE_MODE_ACQUIRE,
    TRADE_MODE_TRADE_AWAY,
    activate_league_context,
    create_league_context_from_live_room,
    get_active_league_context,
    workflow_target_player_names,
)
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


def _league_room() -> dict:
    return {
        "config": {"league_name": "Mock League", "fantasy_format": "5x5 Roto", "your_team": "Daniel"},
        "rosters": {
            "Daniel": [{"fullName": "Mike Trout", "Primary Position": "OF"}],
            "Rivals": [{"fullName": "Aaron Judge", "Primary Position": "OF"}],
        },
        "draft_board": [
            {"Fantasy Team": "Rivals", "fullName": "Aaron Judge", "Pick": 1},
            {"Fantasy Team": "Daniel", "fullName": "Mike Trout", "Pick": 2},
        ],
    }


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
    assert len(judge_contexts) >= 1
    assert any(not c.get("is_user_team") for c in judge_contexts)

    trout_contexts = collect_player_roster_contexts(session, "Mike Trout")
    trade, acquire = split_trade_acquire_contexts(trout_contexts)
    assert trade
    assert not acquire

    betts_contexts = collect_player_roster_contexts(session, "Mookie Betts")
    assert len(betts_contexts) >= 2
    trade, acquire = split_trade_acquire_contexts(betts_contexts)
    assert trade and acquire

    assert player_has_roster_context(session, "Aaron Judge") is True
    assert player_has_roster_context(session, "Babe Ruth") is False


def _seed_context(session: dict, room: dict, context_id: str, *, display_name: str = "") -> None:
    create_league_context_from_live_room(
        session,
        room,
        my_team_name="Daniel",
        league_context_id=context_id,
        display_name=display_name or context_id,
    )
    activate_league_context(session, context_id)


def test_start_trade_acquire_flow_auto_acquire_persists_to_context():
    session: dict = {}
    room = _league_room()
    _seed_context(session, room, "live:acquire_test")
    session["live_draft_room"] = room
    msg = start_trade_acquire_flow(session, player_name="Aaron Judge", key_prefix="test")
    assert msg is not None
    assert "acquire target" in msg
    assert "Opening Fantasy Lineup Assistant" in msg
    assert session["_navigate_to_page"] == "Fantasy Lineup Assistant"
    ctx = get_active_league_context(session)
    assert ctx is not None
    assert workflow_target_player_names(ctx, TRADE_MODE_ACQUIRE) == ["Aaron Judge"]


def test_start_trade_acquire_flow_mode_prompt_and_complete():
    session: dict = {}
    _seed_context(session, _league_room(), "live:ctx_a", display_name="League A")
    _seed_context(
        session,
        {
            "config": {"league_name": "League B", "fantasy_format": "5x5 Roto", "your_team": "Daniel"},
            "rosters": {
                "Daniel": [{"fullName": "Mike Trout"}],
                "East": [{"fullName": "Mookie Betts"}],
            },
            "draft_board": [
                {"Fantasy Team": "Daniel", "fullName": "Mike Trout", "Pick": 1},
                {"Fantasy Team": "East", "fullName": "Mookie Betts", "Pick": 2},
            ],
        },
        "live:ctx_b",
        display_name="League B",
    )
    session["live_draft_room"] = {
        "config": {"league_name": "Mock League", "your_team": "Daniel"},
        "draft_board": [{"Player": "Mookie Betts", "Team": "Rivals"}],
    }
    session["draft_room_table"] = pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])
    msg = start_trade_acquire_flow(session, player_name="Mookie Betts", key_prefix="ctx")
    assert msg is None
    assert session["_player_trade_acquire_flow"]["step"] == "choose_context"
    candidates = session["_player_trade_acquire_flow"]["candidates"]
    ctx_id = str(candidates[0].get("context_id"))
    msg = complete_trade_acquire_flow(session, mode=TRADE_ACTION_ACQUIRE, context_id=ctx_id)
    assert "acquire target" in msg
    active = get_active_league_context(session)
    assert active is not None
    assert "Mookie Betts" in workflow_target_player_names(active, TRADE_MODE_ACQUIRE)


def test_start_trade_acquire_flow_trade_away_persists():
    session: dict = {}
    room = _league_room()
    _seed_context(session, room, "live:trade_away")
    session["live_draft_room"] = room
    session["draft_room_table"] = pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])
    msg = start_trade_acquire_flow(session, player_name="Mike Trout", key_prefix="trade")
    assert msg is not None
    assert "trade candidate" in msg
    ctx = get_active_league_context(session)
    assert ctx is not None
    assert workflow_target_player_names(ctx, TRADE_MODE_TRADE_AWAY) == ["Mike Trout"]


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
