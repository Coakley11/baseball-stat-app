"""Active League Context vs research-page sync semantics."""

from __future__ import annotations

import unittest

import pandas as pd

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
        self.assertIn("Active", badge)
        self.assertEqual(research_sync_badge_text(session), "Research mode: **General MLB** (sync off)")


if __name__ == "__main__":
    unittest.main()
