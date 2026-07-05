"""Regression tests for in-season fantasy stats persistence across refresh."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_in_season_state import (
    FANTASY_IN_SEASON_STATE_KEY,
    hydrate_fantasy_in_season_to_session,
    in_season_context_ready,
    sync_fantasy_in_season_state,
)


class FantasyInSeasonPersistenceTests(unittest.TestCase):
    def test_sync_and_hydrate_roundtrip(self) -> None:
        session: dict = {
            "_fantasy_current_hitter_stats": pd.DataFrame(
                [{"Player": "Aaron Judge", "Player Key": "aaron judge", "HR": 20, "RBI": 50}]
            ),
            "_fantasy_current_pitcher_stats": pd.DataFrame(),
            "fantasy_current_roster_stats": pd.DataFrame(
                [{"Team": "Daniel", "Player": "Aaron Judge", "HR": 20, "RBI": 50}]
            ),
            "fantasy_current_standings": pd.DataFrame(
                [{"Team": "Daniel", "Total Roto Points": 120.0}]
            ),
            "_fantasy_standings_stats_loaded_at": "2026-07-05T12:00:00+00:00",
            "_fantasy_standings_stats_source": "MLB API Auto-Fetch",
            "standings_api_season": 2026,
        }
        sync_fantasy_in_season_state(session, reason="test")
        self.assertIn(FANTASY_IN_SEASON_STATE_KEY, session)
        blob = session[FANTASY_IN_SEASON_STATE_KEY]
        self.assertTrue(blob.get("hitter_stats_records"))
        self.assertTrue(blob.get("roster_stats_records"))

        fresh: dict = {}
        self.assertTrue(hydrate_fantasy_in_season_to_session(fresh, dict(blob)))
        self.assertTrue(in_season_context_ready(fresh))
        hitters = fresh.get("_fantasy_current_hitter_stats")
        roster = fresh.get("fantasy_current_roster_stats")
        self.assertIsInstance(hitters, pd.DataFrame)
        self.assertIsInstance(roster, pd.DataFrame)
        self.assertFalse(hitters.empty)
        self.assertFalse(roster.empty)
        self.assertEqual(str(fresh.get("_fantasy_standings_stats_source")), "MLB API Auto-Fetch")

    def test_lineup_and_waiver_context_after_restore(self) -> None:
        session: dict = {}
        blob = {
            "schema_version": 1,
            "hitter_stats_records": [{"Player": "Juan Soto", "HR": 18, "RBI": 55, "R": 60, "SB": 5, "BA": 0.285}],
            "roster_stats_records": [
                {"Team": "Daniel", "Player": "Juan Soto", "HR": 18, "RBI": 55, "R": 60, "SB": 5, "BA": 0.285}
            ],
            "stats_loaded_at": "2026-07-05T12:00:00+00:00",
            "stats_source": "MLB API Auto-Fetch",
        }
        hydrate_fantasy_in_season_to_session(session, blob)
        self.assertTrue(in_season_context_ready(session))
        waiver_hitters = session.get("_fantasy_current_hitter_stats")
        lineup_roster = session.get("fantasy_current_roster_stats")
        self.assertIsInstance(waiver_hitters, pd.DataFrame)
        self.assertIsInstance(lineup_roster, pd.DataFrame)
        self.assertEqual(str(waiver_hitters.iloc[0]["Player"]), "Juan Soto")
        self.assertEqual(str(lineup_roster.iloc[0]["Player"]), "Juan Soto")

    def test_disk_state_roundtrip_via_baseball_persistent_state(self) -> None:
        from unittest.mock import MagicMock

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        st = MagicMock()
        st.session_state = {
            "_fantasy_current_hitter_stats": pd.DataFrame([{"Player": "Mike Trout", "HR": 15}]),
            "fantasy_current_roster_stats": pd.DataFrame([{"Team": "Daniel", "Player": "Mike Trout", "HR": 15}]),
            "_fantasy_standings_stats_loaded_at": "2026-07-05T12:00:00+00:00",
            "_fantasy_standings_stats_source": "MLB API Auto-Fetch",
            "active_page": "Fantasy Standings Tracker",
            "main_sidebar_page": "Fantasy Standings Tracker",
            "page_filter_state": {},
        }
        sync_fantasy_in_season_state(st.session_state, reason="test")
        blob = build_baseball_disk_state(st)
        self.assertIn(FANTASY_IN_SEASON_STATE_KEY, blob)

        st2 = MagicMock()
        st2.session_state = {
            "active_page": "Fantasy Lineup Assistant",
            "main_sidebar_page": "Fantasy Lineup Assistant",
            "page_filter_state": {},
        }
        apply_baseball_disk_state(st2, blob)
        self.assertTrue(in_season_context_ready(st2.session_state))

    def test_cross_device_cloud_restore(self) -> None:
        """Device A saves standings; device B cold session restores waiver + lineup context."""
        from unittest.mock import MagicMock

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        device_a = MagicMock()
        device_a.session_state = {
            "_fantasy_current_hitter_stats": pd.DataFrame(
                [{"Player": "Juan Soto", "HR": 18, "RBI": 55, "R": 60, "SB": 5, "BA": 0.285}]
            ),
            "fantasy_current_roster_stats": pd.DataFrame(
                [{"Team": "Daniel", "Player": "Juan Soto", "HR": 18, "RBI": 55}]
            ),
            "fantasy_current_standings": pd.DataFrame([{"Team": "Daniel", "Total Roto Points": 110.0}]),
            "_fantasy_standings_stats_loaded_at": "2026-07-05T12:00:00+00:00",
            "_fantasy_standings_stats_source": "MLB API Auto-Fetch",
            "use_active_league_context_waiver_filter": True,
            "fantasy_league_context_state": {
                "contexts": {
                    "lc-main": {
                        "league_context_id": "lc-main",
                        "display_name": "2026 Main League",
                        "my_team_name": "Daniel",
                    }
                },
                "active_league_context_id": "lc-main",
            },
            "active_page": "Fantasy Standings Tracker",
            "main_sidebar_page": "Fantasy Standings Tracker",
            "page_filter_state": {},
        }
        sync_fantasy_in_season_state(device_a.session_state, reason="standings_computed")
        cloud_blob = build_baseball_disk_state(device_a)
        self.assertIn(FANTASY_IN_SEASON_STATE_KEY, cloud_blob)
        self.assertTrue(cloud_blob.get("use_active_league_context_waiver_filter"))

        device_b = MagicMock()
        device_b.session_state = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "page_filter_state": {},
        }
        apply_baseball_disk_state(device_b, cloud_blob)
        ss = device_b.session_state
        self.assertTrue(in_season_context_ready(ss))
        self.assertTrue(ss.get("use_active_league_context_waiver_filter"))
        self.assertFalse(ss.get("fantasy_current_roster_stats", pd.DataFrame()).empty)
        self.assertFalse(ss.get("_fantasy_current_hitter_stats", pd.DataFrame()).empty)

        from fantasy_context_ui import fantasy_context_badge_text

        badge = fantasy_context_badge_text(ss)
        self.assertIn("Synced", badge)
        self.assertIn("2026 Main League", badge)

if __name__ == "__main__":
    unittest.main()
