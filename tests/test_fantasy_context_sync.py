"""Active League Context vs research-page sync semantics."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_context_source import DRAFT_ASSISTANT_PAGE, USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    active_league_context_badge_text,
    research_league_sync_enabled,
    research_sync_badge_text,
)
from fantasy_waiver_wire import filter_unrostered_players, waiver_filter_enabled


def _session_with_rosters(*, sync: bool) -> dict:
    return {
        FANTASY_RESEARCH_SYNC_KEY: sync,
        "fantasy_league_context_state": {
            "active_league_context_id": "ctx1",
            "contexts": {
                "ctx1": {
                    "league_context_id": "ctx1",
                    "display_name": "Home League",
                    "my_team_name": "Daniel",
                    "league_rosters": {
                        "Daniel": {
                            "team_name": "Daniel",
                            "is_user_team": True,
                            "players": [{"player_name": "Aaron Judge", "player_key": "aaron judge"}],
                        },
                        "Rivals": {
                            "team_name": "Rivals",
                            "players": [{"player_name": "Juan Soto", "player_key": "juan soto"}],
                        },
                    },
                }
            },
        },
    }


class FantasyContextSyncTests(unittest.TestCase):
    def test_research_sync_off_skips_roster_filter(self) -> None:
        session = _session_with_rosters(sync=False)
        players = pd.DataFrame({"Player": ["Aaron Judge", "Juan Soto", "Mike Trout"]})
        self.assertFalse(research_league_sync_enabled(session))
        self.assertFalse(waiver_filter_enabled(session))
        filtered = filter_unrostered_players(session, players)
        pd.testing.assert_frame_equal(filtered, players)

    def test_research_sync_on_filters_rostered_players(self) -> None:
        session = _session_with_rosters(sync=True)
        players = pd.DataFrame({"Player": ["Aaron Judge", "Juan Soto", "Mike Trout"]})
        self.assertTrue(research_league_sync_enabled(session))
        filtered = filter_unrostered_players(session, players)
        self.assertEqual(filtered["Player"].tolist(), ["Mike Trout"])

    def test_trend_value_skips_filter_without_research_sync_even_with_active_league(self) -> None:
        session = _session_with_rosters(sync=False)
        players = pd.DataFrame({"fullName": ["Aaron Judge", "Juan Soto", "Mike Trout"]})
        filtered = filter_unrostered_players(session, players, name_col="fullName", page_name="Trend Value")
        pd.testing.assert_frame_equal(filtered, players)

    def test_live_draft_filters_das_without_research_sync(self) -> None:
        session = _session_with_rosters(sync=False)
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = True
        session["live_draft_room"] = {
            "draft_room_id": "room1",
            "status": "in_progress",
            "config": {"user_team": "Daniel"},
            "draft_board": [
                {"Team": "Daniel", "Player": "Aaron Judge"},
                {"Team": "Rivals", "Player": "Juan Soto"},
            ],
        }
        session["draft_room_table"] = pd.DataFrame(
            {
                "Round": [1, 1],
                "Pick": [1, 2],
                "Team": ["Daniel", "Rivals"],
                "Player": ["Aaron Judge", "Juan Soto"],
            }
        )
        players = pd.DataFrame({"fullName": ["Aaron Judge", "Juan Soto", "Mike Trout"]})
        filtered = filter_unrostered_players(
            session, players, name_col="fullName", page_name=DRAFT_ASSISTANT_PAGE
        )
        self.assertEqual(filtered["fullName"].tolist(), ["Mike Trout"])

    def test_simulator_board_filters_das_without_research_sync(self) -> None:
        session = {
            FANTASY_RESEARCH_SYNC_KEY: False,
            "draft_room_table": pd.DataFrame(
                {
                    "Round": [1, 1],
                    "Pick": [1, 2],
                    "Team": ["Daniel", "Rivals"],
                    "Player": ["Aaron Judge", "Juan Soto"],
                }
            ),
            "room_your_team": "Daniel",
        }
        players = pd.DataFrame({"fullName": ["Aaron Judge", "Juan Soto", "Mike Trout"]})
        filtered = filter_unrostered_players(
            session, players, name_col="fullName", page_name=DRAFT_ASSISTANT_PAGE
        )
        self.assertEqual(filtered["fullName"].tolist(), ["Mike Trout"])

    def test_active_league_badge_independent_of_sync(self) -> None:
        session = {
            FANTASY_RESEARCH_SYNC_KEY: False,
            "fantasy_league_context_state": {
                "active_league_context_id": "ctx1",
                "contexts": {
                    "ctx1": {
                        "league_context_id": "ctx1",
                        "display_name": "2026 Main League",
                        "my_team_name": "Daniel",
                        "league_rosters": {
                            "Daniel": {
                                "team_name": "Daniel",
                                "players": [{"player_name": "Aaron Judge", "player_key": "aaron judge"}],
                            }
                        },
                    }
                },
            },
        }
        badge = active_league_context_badge_text(session)
        self.assertIn("2026 Main League", badge)
        self.assertIn("Saved Draft Library Active Draft", badge)
        self.assertEqual(
            research_sync_badge_text(session),
            "Research mode: **General MLB** (off) · Fantasy Context Source: **Saved Draft Library Active Draft** · **2026 Main League** · Team: **Daniel**",
        )


if __name__ == "__main__":
    unittest.main()
