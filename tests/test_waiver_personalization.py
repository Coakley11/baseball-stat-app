"""Waiver Wire personalization: position-need weighting and personalized adds."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_waiver_wire import (
    compute_position_need_weights,
    recommend_adds_personalized,
)


def _context_with_slots() -> dict:
    return {
        "my_team_name": "Daniel",
        "roster_settings": {
            "roster_slots": {"C": 1, "1B": 1, "2B": 1, "OF": 3},
            "slot_instances": [],
        },
        "league_rosters": {
            "Daniel": {"team_name": "Daniel", "is_user_team": True, "players": []},
        },
    }


class PositionNeedWeightTests(unittest.TestCase):
    def test_missing_position_dominates_filled(self) -> None:
        # Roster already has a 1B and two OF, but no catcher.
        roster = pd.DataFrame(
            {
                "Player": ["Freddie Freeman", "Mookie Betts", "Kyle Tucker"],
                "Primary Position": ["1B", "OF", "OF"],
            }
        )
        weights = compute_position_need_weights(_context_with_slots(), roster)
        self.assertGreater(weights.get("C", 0), weights.get("1B", 0))
        # Catcher is missing → top weight; 1B filled → small weight.
        self.assertAlmostEqual(weights["C"], 1.0)
        self.assertLess(weights["1B"], 0.5)

    def test_thin_position_between_missing_and_filled(self) -> None:
        roster = pd.DataFrame(
            {
                "Player": ["Salvador Perez", "Freddie Freeman", "Mookie Betts"],
                "Primary Position": ["C", "1B", "OF"],
            }
        )
        weights = compute_position_need_weights(_context_with_slots(), roster)
        # OF needs 3, only 1 filled → thin; C and 1B filled → low.
        self.assertGreater(weights["OF"], weights["C"])
        self.assertGreater(weights["OF"], weights["1B"])


class PersonalizedAddTests(unittest.TestCase):
    def test_catcher_dominates_when_none_rostered(self) -> None:
        context = _context_with_slots()
        roster = pd.DataFrame(
            {
                "Player": ["Freddie Freeman", "Mookie Betts", "Kyle Tucker"],
                "Primary Position": ["1B", "OF", "OF"],
            }
        )
        pool = pd.DataFrame(
            {
                "Player": ["Elite OF", "Decent Catcher"],
                "Primary Position": ["OF", "C"],
                "Player Grade": [95.0, 70.0],
                "HR": [40, 18],
                "RBI": [110, 60],
            }
        )
        needs = {"targets": [], "weaknesses": []}
        adds = recommend_adds_personalized(
            pool, needs, context=context, my_roster=roster, limit=5
        )
        # Even though the OF has a much higher grade, the missing catcher should
        # outrank it because catcher is an empty required slot.
        self.assertEqual(adds.iloc[0]["Player"], "Decent Catcher")
        self.assertIn("C", adds.iloc[0]["Why Add"])

    def test_quality_breaks_ties_when_positions_filled(self) -> None:
        context = _context_with_slots()
        # All required slots filled; add should fall back to quality.
        roster = pd.DataFrame(
            {
                "Player": ["C1", "1B1", "2B1", "OF1", "OF2", "OF3"],
                "Primary Position": ["C", "1B", "2B", "OF", "OF", "OF"],
            }
        )
        pool = pd.DataFrame(
            {
                "Player": ["Star OF", "Weak OF"],
                "Primary Position": ["OF", "OF"],
                "Player Grade": [95.0, 40.0],
                "HR": [40, 10],
                "RBI": [110, 30],
            }
        )
        needs = {"targets": [], "weaknesses": []}
        adds = recommend_adds_personalized(
            pool, needs, context=context, my_roster=roster, limit=5
        )
        self.assertEqual(adds.iloc[0]["Player"], "Star OF")

    def test_hr_weakness_boosts_power_hitters(self) -> None:
        context = _context_with_slots()
        roster = pd.DataFrame(
            {
                "Player": ["C1", "1B1", "2B1", "OF1", "OF2", "OF3"],
                "Primary Position": ["C", "1B", "2B", "OF", "OF", "OF"],
                "HR": [5, 8, 4, 12, 10, 9],
            }
        )
        pool = pd.DataFrame(
            {
                "Player": ["Power Bat", "Speed Guy"],
                "Primary Position": ["OF", "OF"],
                "Player Grade": [72.0, 72.0],
                "HR": [28, 6],
                "RBI": [90, 35],
                "SB": [4, 35],
            }
        )
        needs = {
            "targets": ["HR", "RBI"],
            "weaknesses": ["HR", "RBI"],
            "category_ranks": {"HR": 8, "RBI": 7},
            "n_teams": 10,
        }
        adds = recommend_adds_personalized(
            pool, needs, context=context, my_roster=roster, limit=5
        )
        self.assertEqual(adds.iloc[0]["Player"], "Power Bat")
        self.assertIn("HR", adds.iloc[0]["Why Add"])


if __name__ == "__main__":
    unittest.main()
