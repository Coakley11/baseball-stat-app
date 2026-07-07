"""Active-team resolver: Active League > Simulator priority and fallback."""

from __future__ import annotations

import unittest

import pandas as pd

from active_team_context import (
    SOURCE_LEAGUE,
    SOURCE_NONE,
    SOURCE_SIMULATOR,
    apply_category_need_boost,
    apply_position_need_boost,
    player_helps_positions,
    recalculate_pool_ranks,
    resolve_active_team_context,
)


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fullName": ["Aaron Judge", "Juan Soto", "Mike Trout", "Bobby Witt Jr."],
            "proj_HR": [50, 40, 35, 30],
            "proj_RBI": [120, 100, 90, 95],
            "proj_SB": [5, 8, 3, 40],
            "proj_BA": [0.290, 0.300, 0.280, 0.310],
        }
    )


def _league_session(*, team: str = "Daniel") -> dict:
    return {
        "fantasy_league_context_state": {
            "active_league_context_id": "ctx1",
            "contexts": {
                "ctx1": {
                    "league_context_id": "ctx1",
                    "display_name": "Home League",
                    "my_team_name": team,
                    "fantasy_format": "5x5 Roto",
                    "league_rosters": {
                        team: {
                            "team_name": team,
                            "is_user_team": True,
                            "players": [
                                {"player_name": "Aaron Judge", "player_key": "aaron judge"}
                            ],
                        },
                        "Rivals": {
                            "team_name": "Rivals",
                            "players": [
                                {"player_name": "Juan Soto", "player_key": "juan soto"}
                            ],
                        },
                    },
                }
            },
        },
    }


def _simulator_session() -> dict:
    return {
        "live_draft_room": {
            "status": "in_progress",
            "config": {"your_team": "Sim Team", "user_team": "Sim Team"},
            "teams": ["Sim Team", "Opponent"],
            "rosters": {
                "Sim Team": [{"Player": "Aaron Judge", "Primary Position": "OF"}],
                "Opponent": [{"Player": "Juan Soto", "Primary Position": "OF"}],
            },
            "draft_board": [
                {"fullName": "Aaron Judge"},
                {"fullName": "Juan Soto"},
            ],
        },
    }


class ActiveTeamContextTests(unittest.TestCase):
    def test_active_league_supplies_team_and_unavailable_players(self) -> None:
        ctx = resolve_active_team_context(_league_session(), pool_df=_pool())
        self.assertEqual(ctx.source, SOURCE_LEAGUE)
        self.assertEqual(ctx.active_team, "Daniel")
        self.assertTrue(ctx.is_unavailable("Aaron Judge"))
        self.assertTrue(ctx.is_unavailable("Juan Soto"))
        self.assertFalse(ctx.is_unavailable("Mike Trout"))

    def test_available_pool_recalculates_on_remaining_players(self) -> None:
        ctx = resolve_active_team_context(_league_session(), pool_df=_pool())
        remaining = ctx.available_pool(_pool())
        names = remaining["fullName"].tolist()
        self.assertNotIn("Aaron Judge", names)
        self.assertNotIn("Juan Soto", names)
        self.assertIn("Mike Trout", names)
        self.assertIn("Bobby Witt Jr.", names)

    def test_active_league_overrides_simulator(self) -> None:
        session = _league_session()
        session.update(_simulator_session())
        ctx = resolve_active_team_context(session, pool_df=_pool())
        self.assertEqual(ctx.source, SOURCE_LEAGUE)
        self.assertEqual(ctx.active_team, "Daniel")

    def test_simulator_used_when_no_active_league(self) -> None:
        ctx = resolve_active_team_context(_simulator_session(), pool_df=_pool())
        self.assertEqual(ctx.source, SOURCE_SIMULATOR)
        self.assertEqual(ctx.active_team, "Sim Team")
        self.assertTrue(ctx.is_unavailable("Aaron Judge"))
        self.assertTrue(ctx.is_unavailable("Juan Soto"))

    def test_no_context_returns_empty_and_leaves_pool_untouched(self) -> None:
        ctx = resolve_active_team_context({}, pool_df=_pool())
        self.assertEqual(ctx.source, SOURCE_NONE)
        self.assertFalse(ctx.has_active_team)
        pd.testing.assert_frame_equal(ctx.available_pool(_pool()), _pool())


class PositionBoostTests(unittest.TestCase):
    def test_player_helps_positions_alias_matching(self) -> None:
        self.assertTrue(player_helps_positions("LF", {"OF"}))
        self.assertTrue(player_helps_positions(["1B", "OF"], {"1B"}))
        self.assertFalse(player_helps_positions("SS", {"1B", "2B"}))
        self.assertFalse(player_helps_positions("", {"1B"}))

    def test_boost_raises_needed_positions_only(self) -> None:
        df = pd.DataFrame(
            {
                "Player": ["A", "B", "C"],
                "Primary Position": ["1B", "SS", "OF"],
                "Score": [10.0, 10.0, 10.0],
            }
        )
        boosted = apply_position_need_boost(df, ["1B", "OF"], score_col="Score", boost=0.2)
        vals = dict(zip(boosted["Player"], boosted["Score"]))
        self.assertAlmostEqual(vals["A"], 12.0)
        self.assertAlmostEqual(vals["B"], 10.0)
        self.assertAlmostEqual(vals["C"], 12.0)
        self.assertEqual(boosted.loc[boosted["Player"] == "B", "Position Need Boost"].iloc[0], False)

    def test_boost_is_noop_without_needs(self) -> None:
        df = pd.DataFrame({"Player": ["A"], "Primary Position": ["1B"], "Score": [10.0]})
        boosted = apply_position_need_boost(df, [], score_col="Score")
        self.assertAlmostEqual(boosted["Score"].iloc[0], 10.0)

    def test_recalculate_pool_ranks_is_dense(self) -> None:
        df = pd.DataFrame(
            {
                "fullName": ["A", "C"],
                "Blended Projection Score": [9.0, 7.0],
                "Model Rank": [1, 3],
                "Market Rank": [2, 5],
            }
        )
        out = recalculate_pool_ranks(df)
        self.assertEqual(out["Model Rank"].tolist(), [1, 2])
        self.assertEqual(out["Fantasy Edge"].tolist(), [1.0, 3.0])

    def test_category_boost_favors_power_when_hr_weak(self) -> None:
        df = pd.DataFrame(
            {
                "Player": ["Slugger", "Speedster"],
                "HR": [35, 8],
                "Score": [10.0, 10.0],
            }
        )
        boosted = apply_category_need_boost(df, ["HR", "RBI"], score_col="Score", boost=0.15)
        vals = dict(zip(boosted["Player"], boosted["Score"]))
        self.assertGreater(vals["Slugger"], vals["Speedster"])


if __name__ == "__main__":
    unittest.main()
