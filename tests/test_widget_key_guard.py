"""Regression: widget-backed session keys must not be snapshotted or restored."""

from __future__ import annotations

import unittest

import page_state as pg


class WidgetKeyGuardTests(unittest.TestCase):
    def test_standings_refresh_button_not_snapshotted(self) -> None:
        session = {
            "page_filter_state": {},
            "_page_state_last_active": "Fantasy Standings Tracker",
            "standings_stats_source": "MLB API Auto-Fetch",
            "standings_api_season": 2026,
            "standings_refresh_mlb_stats": True,
            "standings_refresh_mlb_stats_btn": True,
            "_standings_refresh_mlb_stats_requested": True,
        }
        pg.save_page_state(session, "Fantasy Standings Tracker", session["page_filter_state"])
        snap = session["page_filter_state"].get("Fantasy Standings Tracker") or {}
        self.assertNotIn("standings_refresh_mlb_stats", snap)
        self.assertNotIn("standings_refresh_mlb_stats_btn", snap)
        self.assertNotIn("_standings_refresh_mlb_stats_requested", snap)
        self.assertEqual(snap.get("standings_stats_source"), "MLB API Auto-Fetch")

    def test_standings_refresh_legacy_key_not_restored(self) -> None:
        session: dict = {}
        store = {
            "Fantasy Standings Tracker": {
                "standings_stats_source": "MLB API Auto-Fetch",
                "standings_refresh_mlb_stats": True,
            }
        }
        pg.restore_page_state(session, "Fantasy Standings Tracker", store)
        self.assertNotIn("standings_refresh_mlb_stats", session)
        self.assertEqual(session.get("standings_stats_source"), "MLB API Auto-Fetch")

    def test_league_rank_strength_weakness_direction(self) -> None:
        from fantasy_actionable_recommendations import (
            format_category_rank_line,
            format_category_weakness_line,
            league_strength_categories,
            league_weakness_categories,
            plain_lineup_archetype,
        )

        ranks = {"HR": 1, "RBI": 2, "SB": 4, "AVG": 3}
        strengths = league_strength_categories(ranks, n_teams=4)
        weaknesses = league_weakness_categories(ranks, n_teams=4)
        self.assertEqual(strengths[0], "HR")
        self.assertEqual(weaknesses[0], "SB")
        self.assertIn("#1st of 4", format_category_rank_line("HR", 1, n_teams=4))
        self.assertIn("#4th of 4", format_category_weakness_line("SB", 4, n_teams=4))
        archetype = plain_lineup_archetype(
            {},
            rate_label="AVG",
            strong_cats=strengths,
            weak_cats=weaknesses,
        )
        self.assertIn("primary risk", archetype.lower())
        self.assertNotIn("clear strength", archetype.lower())


if __name__ == "__main__":
    unittest.main()
