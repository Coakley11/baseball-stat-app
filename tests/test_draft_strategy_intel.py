"""Unit tests for draft_strategy_intel (contextual, numeric strategy lines)."""

import unittest

from draft_strategy_intel import draft_strategy_line


def _row(**kwargs):
    base = {
        "Primary Position": "OF",
        "Availability Probability": 0.55,
        "Market Rank": 100.0,
        "Fantasy Edge": 8.0,
        "Model Rank": 92.0,
        "proj_SB": 12.0,
        "proj_HR": 22.0,
        "proj_BA": 0.265,
        "proj_RBI": 75.0,
        "proj_R": 80.0,
        "proj_OPS": 0.78,
        "Risk Penalty": 0.03,
        "Breakout Probability": 0.35,
    }
    base.update(kwargs)
    return base


class TestDraftStrategyLine(unittest.TestCase):
    def _ctx(self, **kwargs):
        defaults = dict(
            draft_format="5x5 Roto",
            current_pick=40,
            position_meta_by_pos={
                "OF": {"dropoff": 0.08, "available": 45},
                "SS": {"dropoff": 0.02, "available": 12},
            },
            median_scarcity_dropoff=0.04,
            remaining_high_sb_count=25,
            remaining_high_hr_count=35,
            category_needs=["SB"],
            roster_means={"proj_SB": 6.0, "proj_HR": 20.0, "proj_BA": 0.252, "proj_RBI": 70.0, "proj_R": 75.0},
            pool_means={"proj_SB": 11.0, "proj_HR": 21.0, "proj_BA": 0.258, "proj_RBI": 72.0, "proj_R": 76.0},
            needed_positions=[],
            current_position_counts={"OF": 2},
            target_position_counts={"OF": 3, "SS": 1, "C": 1, "1B": 1, "2B": 1, "3B": 1, "DH": 1},
        )
        defaults.update(kwargs)
        return defaults

    def test_roster_shortage_includes_numbers(self):
        s = draft_strategy_line(_row(proj_SB=24.0), **self._ctx())
        self.assertIn("stolen bases", s.lower())
        self.assertIn("mean", s.lower())

    def test_positional_need_counts(self):
        r = _row(proj_SB=8.0)
        r["Primary Position"] = "SS"
        s = draft_strategy_line(
            r,
            **self._ctx(needed_positions=["SS"], current_position_counts={"SS": 0}),
        )
        self.assertIn("SS", s)
        self.assertIn("0/1", s)

    def test_dropoff_sentence_when_wide(self):
        r = _row()
        r["Primary Position"] = "OF"
        s = draft_strategy_line(
            r,
            **self._ctx(
                position_meta_by_pos={"OF": {"dropoff": 0.09, "available": 40}},
                median_scarcity_dropoff=0.03,
                needed_positions=[],
            ),
        )
        self.assertTrue("0.09" in s)

    def test_fallback_when_no_roster_signal(self):
        r = _row()
        r["Fantasy Edge"] = 5.0
        r["Model Rank"] = 95.0
        s = draft_strategy_line(
            r,
            **self._ctx(
                roster_means={},
                pool_means={},
                category_needs=[],
                remaining_high_sb_count=80,
                remaining_high_hr_count=80,
                position_meta_by_pos={"OF": {"dropoff": 0.01, "available": 45}},
                median_scarcity_dropoff=0.05,
            ),
        )
        self.assertIn("No extra strategy", s)

    def test_max_two_sentence_units(self):
        r = _row(proj_SB=30.0)
        r["Availability Probability"] = 0.25
        s = draft_strategy_line(
            r,
            **self._ctx(
                needed_positions=["OF"],
                current_position_counts={"OF": 1},
                roster_means={"proj_SB": 4.0, "proj_HR": 19.0, "proj_BA": 0.25, "proj_RBI": 68.0, "proj_R": 70.0},
            ),
        )
        self.assertLessEqual(s.count("."), 4)


if __name__ == "__main__":
    unittest.main()
