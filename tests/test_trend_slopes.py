"""Trend slopes: hand-checked method, and the vectorized pass equals the original per-player fit."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from trend_slopes import reference_slope, trend_slopes

ROOT = Path(__file__).resolve().parents[1]
STATS = ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]


def _season_window(first_year: int) -> pd.DataFrame:
    batting = pd.read_csv(ROOT / "Batting.csv", low_memory=False)
    cols = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF"]
    for c in cols:
        batting[c] = pd.to_numeric(batting[c], errors="coerce").fillna(0)
    y = batting[batting["yearID"] >= first_year].groupby(["playerID", "yearID"], as_index=False)[cols].sum()
    ab = y["AB"].replace(0, np.nan)
    obp_den = (y["AB"] + y["BB"] + y["HBP"] + y["SF"]).replace(0, np.nan)
    y["BA"] = y["H"] / ab
    y["OBP"] = (y["H"] + y["BB"] + y["HBP"]) / obp_den
    y["SLG"] = ((y["H"] - y["2B"] - y["3B"] - y["HR"]) + 2 * y["2B"] + 3 * y["3B"] + 4 * y["HR"]) / ab
    y["OPS"] = y["OBP"] + y["SLG"]
    return y


class HandCheckedTrendTests(unittest.TestCase):
    def setUp(self):
        self.seasons = pd.DataFrame(
            [
                ("A", 2023, 10, 0.250), ("A", 2024, 20, 0.260), ("A", 2025, 30, 0.270),
                ("B", 2023, 30, 0.300), ("B", 2025, 10, 0.280),
                ("C", 2025, 40, 0.310),
                ("D", 2023, 5, np.nan), ("D", 2024, 15, 0.200), ("D", 2025, 25, 0.300),
                ("E", 2023, 12, 0.250), ("E", 2024, 8, 0.250), ("E", 2025, 10, 0.250),
            ],
            columns=["playerID", "yearID", "HR", "BA"],
        )
        self.out = trend_slopes(self.seasons, ["HR", "BA"]).set_index("playerID")

    def test_steady_rise_is_the_change_per_season(self):
        self.assertAlmostEqual(self.out.loc["A", "HR_trend"], 10.0)
        self.assertAlmostEqual(self.out.loc["A", "BA_trend"], 0.010)

    def test_gap_year_keeps_real_spacing_and_decline_is_negative(self):
        self.assertAlmostEqual(self.out.loc["B", "HR_trend"], -10.0)  # (10 − 30) over two seasons

    def test_one_season_has_no_trend(self):
        self.assertTrue(np.isnan(self.out.loc["C", "HR_trend"]))

    def test_missing_season_value_is_left_out(self):
        self.assertAlmostEqual(self.out.loc["D", "BA_trend"], 0.100)  # 2024 → 2025 only
        self.assertAlmostEqual(self.out.loc["D", "HR_trend"], 10.0)

    def test_least_squares_not_end_to_end(self):
        self.assertAlmostEqual(self.out.loc["E", "HR_trend"], -1.0)  # not (10 − 12) / 2
        self.assertAlmostEqual(self.out.loc["E", "BA_trend"], 0.0)

    def test_every_player_gets_a_row(self):
        self.assertEqual(sorted(self.out.index), ["A", "B", "C", "D", "E"])


class EquivalenceTests(unittest.TestCase):
    def test_matches_the_per_player_fit_on_real_seasons(self):
        window = _season_window(2023)
        sample_ids = sorted(window["playerID"].unique())[::7]
        sample = window[window["playerID"].isin(sample_ids)]
        new = trend_slopes(sample, STATS).set_index("playerID")
        for pid, group in sample.groupby("playerID"):
            for stat in STATS:
                ref = reference_slope(group, stat)
                got = new.loc[pid, f"{stat}_trend"]
                if np.isnan(ref):
                    self.assertTrue(np.isnan(got), (pid, stat))
                else:
                    self.assertAlmostEqual(got, ref, places=8, msg=(pid, stat))


class WiringTests(unittest.TestCase):
    def test_trend_table_uses_the_vectorized_pass(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        body = src[src.index("def compute_player_trend_table"):src.index("def get_latest_player_context")]
        self.assertIn("trend_slopes(", body)
        self.assertNotIn(".apply(", body)


if __name__ == "__main__":
    unittest.main()
