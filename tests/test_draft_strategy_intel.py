"""Unit tests for draft_strategy_intel."""

import unittest

from draft_strategy_intel import draft_strategy_line


class TestDraftStrategyLine(unittest.TestCase):
    def _base_row(self):
        return {
            "Primary Position": "SS",
            "Availability Probability": 0.5,
            "Market Rank": 80.0,
            "Fantasy Edge": 5.0,
            "proj_SB": 8.0,
            "proj_BA": 0.26,
            "Risk Penalty": 0.03,
            "Breakout Probability": 0.4,
        }

    def test_neutral_fallback(self):
        s = draft_strategy_line(
            self._base_row(),
            draft_format="5x5 Roto",
            current_pick=50,
            position_dropoff_by_pos={"SS": 0.01},
            median_scarcity_dropoff=0.05,
            remaining_high_sb_count=40,
            category_needs=[],
            roster_means={},
            pool_means={},
        )
        self.assertIn("Neutral", s)

    def test_low_availability_urgency(self):
        row = self._base_row()
        row["Availability Probability"] = 0.25
        s = draft_strategy_line(
            row,
            draft_format="5x5 Roto",
            current_pick=50,
            position_dropoff_by_pos={"SS": 0.02},
            median_scarcity_dropoff=0.04,
            remaining_high_sb_count=30,
            category_needs=[],
            roster_means={},
            pool_means={},
        )
        self.assertIn("next pick", s.lower())

    def test_scarcity_cliff(self):
        row = self._base_row()
        row["proj_SB"] = 5.0
        s = draft_strategy_line(
            row,
            draft_format="5x5 Roto",
            current_pick=50,
            position_dropoff_by_pos={"SS": 0.12},
            median_scarcity_dropoff=0.05,
            remaining_high_sb_count=30,
            category_needs=[],
            roster_means={},
            pool_means={},
        )
        self.assertIn("scarcity", s.lower())

    def test_fantasy_edge_value(self):
        row = self._base_row()
        row["Fantasy Edge"] = 25.0
        s = draft_strategy_line(
            row,
            draft_format="5x5 Roto",
            current_pick=50,
            position_dropoff_by_pos={"SS": 0.02},
            median_scarcity_dropoff=0.05,
            remaining_high_sb_count=30,
            category_needs=[],
            roster_means={},
            pool_means={},
        )
        self.assertIn("edge", s.lower())

    def test_caps_three_fragments(self):
        row = self._base_row()
        row["Availability Probability"] = 0.25
        row["Fantasy Edge"] = 30.0
        row["proj_SB"] = 20.0
        row["Breakout Probability"] = 0.6
        row["Risk Penalty"] = 0.05
        s = draft_strategy_line(
            row,
            draft_format="5x5 Roto",
            current_pick=50,
            position_dropoff_by_pos={"SS": 0.15},
            median_scarcity_dropoff=0.05,
            remaining_high_sb_count=8,
            category_needs=["SB", "BA"],
            roster_means={"proj_BA": 0.24},
            pool_means={"proj_BA": 0.26, "proj_SB": 10.0},
        )
        parts = [p.strip() for p in s.split(" · ")]
        self.assertLessEqual(len(parts), 3)


if __name__ == "__main__":
    unittest.main()
