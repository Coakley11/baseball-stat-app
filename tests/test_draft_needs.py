"""Tests for shared draft position/category needs."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_needs import (
    display_position_needs_label,
    filter_bench_gaps,
    infer_draft_team_needs,
    infer_hitter_category_needs,
    infer_position_needs,
)


def _slot_config() -> dict:
    return {
        "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 0, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 2},
    }


class DraftNeedsTests(unittest.TestCase):
    def test_open_slots_exclude_bench(self) -> None:
        cfg = _slot_config()
        roster = pd.DataFrame(
            [
                {"Primary Position": "C", "Expected Fantasy Value": 0.9},
                {"Primary Position": "1B", "Expected Fantasy Value": 0.85},
            ]
        )
        needs = infer_position_needs(roster, cfg)
        self.assertIn("2B", needs)
        self.assertIn("SS", needs)
        self.assertNotIn("BN", needs)

    def test_filled_slots_return_empty_for_scoring(self) -> None:
        cfg = {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 0, "OF": 0, "DH": 0, "P": 0, "BN": 1}}
        roster = pd.DataFrame(
            [
                {"Primary Position": "C", "Expected Fantasy Value": 0.9},
                {"Primary Position": "1B", "Expected Fantasy Value": 0.85},
            ]
        )
        needs = infer_position_needs(roster, cfg)
        self.assertEqual(needs, [])
        self.assertEqual(display_position_needs_label(needs), "All Positions")

    def test_draft_complete_clears_needs(self) -> None:
        roster = pd.DataFrame([{"Primary Position": "C", "proj_HR": 5}])
        pool = pd.DataFrame([{"Primary Position": "OF", "proj_HR": 30}])
        pos, cats = infer_draft_team_needs(
            roster,
            pool,
            config=_slot_config(),
            draft_complete=True,
        )
        self.assertEqual(pos, [])
        self.assertEqual(cats, [])

    def test_category_needs_from_projected_totals(self) -> None:
        roster = pd.DataFrame(
            [
                {"Primary Position": "OF", "proj_HR": 8, "proj_RBI": 30, "proj_SB": 2, "proj_BA": 0.220},
                {"Primary Position": "1B", "proj_HR": 10, "proj_RBI": 35, "proj_SB": 1, "proj_BA": 0.215},
            ]
        )
        pool = pd.DataFrame(
            [
                {"Primary Position": "OF", "proj_HR": 25, "proj_RBI": 80, "proj_SB": 12, "proj_BA": 0.265},
            ]
            * 20
        )
        needs = infer_hitter_category_needs(roster, pool, fantasy_format="5x5 Roto")
        self.assertIn("AVG", needs)
        self.assertNotIn("ERA", needs)
        self.assertNotIn("WHIP", needs)

    def test_filter_bench_gaps(self) -> None:
        self.assertEqual(filter_bench_gaps(["C", "BN", "BN"]), ["C"])


if __name__ == "__main__":
    unittest.main()
