"""Tests for recommendation_player_diagnostics."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_roster_slots import exclude_pitchers_when_no_pitcher_slots, freeze_slot_instances_on_config
from recommendation_player_diagnostics import (
    diagnose_recommendation_player,
    format_recommendation_diagnostic_line,
)


class PitcherHardExcludeTests(unittest.TestCase):
    def test_excludes_pitcher_only_rows_without_p_slots(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "3B": 0, "DH": 0, "P": 0, "BN": 0}}
        )
        pool = pd.DataFrame(
            [
                {"fullName": "Free Pitcher", "Primary Position": "P", "W": 4, "K": 40},
                {"fullName": "Free Catcher", "Primary Position": "C", "HR": 8},
            ]
        )
        out = exclude_pitchers_when_no_pitcher_slots(pool, config=cfg, fantasy_format="5x5 Roto")
        names = set(out["fullName"].astype(str))
        self.assertIn("Free Catcher", names)
        self.assertNotIn("Free Pitcher", names)

    def test_keeps_ohtani_hitter_row_without_p_slots(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "3B": 0, "DH": 1, "P": 0, "BN": 0}}
        )
        pool = pd.DataFrame(
            [
                {
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "DH",
                    "Eligible Positions": "DH/UTIL/P",
                    "AB": 420,
                    "HR": 44,
                    "W": 6,
                    "ERA": 2.80,
                    "Expected Fantasy Value": 0.99,
                },
            ]
        )
        out = exclude_pitchers_when_no_pitcher_slots(pool, config=cfg, fantasy_format="5x5 Roto")
        self.assertEqual(list(out["fullName"]), ["Shohei Ohtani"])

    def test_excludes_pitchers_when_format_has_no_pitching_even_with_p_slots(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "3B": 0, "DH": 0, "P": 2, "BN": 0}}
        )
        pool = pd.DataFrame([{"fullName": "Ace", "Primary Position": "P", "W": 10}])
        out = exclude_pitchers_when_no_pitcher_slots(pool, config=cfg, fantasy_format="5x5 Roto")
        self.assertTrue(out.empty)


class RecommendationDiagnosticTests(unittest.TestCase):
    def test_ohtani_excluded_reason_is_pitcher_not_silent(self) -> None:
        cfg = freeze_slot_instances_on_config(
            {"slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "3B": 0, "DH": 0, "P": 0, "BN": 0}}
        )
        source = pd.DataFrame(
            [
                {
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "P",
                    "W": 6,
                    "Expected Fantasy Value": 0.99,
                    "Draft Fit Score": 1.5,
                }
            ]
        )
        diag = diagnose_recommendation_player(
            "Shohei Ohtani",
            source_pool=source,
            available_pool=pd.DataFrame(),
            recs=pd.DataFrame(),
            config=cfg,
            fantasy_format="5x5 Roto",
        )
        self.assertEqual(diag["available"], "no")
        self.assertIn("pitcher excluded", str(diag["reason_excluded"]))
        line = format_recommendation_diagnostic_line(diag)
        self.assertIn("Shohei Ohtani", line)
        self.assertIn("Available:", line)

    def test_available_ohtani_shows_in_table_reason(self) -> None:
        available = pd.DataFrame(
            [
                {
                    "fullName": "Shohei Ohtani",
                    "Primary Position": "DH",
                    "Eligible Positions": "DH/UTIL/P",
                    "AB": 420,
                    "Expected Fantasy Value": 0.99,
                    "Draft Fit Score": 1.8,
                    "playerID": "ohtani",
                }
            ]
        )
        recs = available.copy()
        diag = diagnose_recommendation_player(
            "Shohei Ohtani",
            source_pool=available,
            available_pool=available,
            recs=recs,
            fantasy_format="5x5 Roto",
        )
        self.assertEqual(diag["available"], "yes")
        self.assertEqual(diag["reason_excluded"], "in recommendation table")


if __name__ == "__main__":
    unittest.main()
