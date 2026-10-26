"""Trend slopes: hand-checked method, and the vectorized pass equals the original per-player fit."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from trend_slopes import RATE_SHRINK_PA, reference_slope, trend_slopes

ROOT = Path(__file__).resolve().parents[1]
STATS = ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]
COUNTING = ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB"]


def _season_window(first_year: int) -> pd.DataFrame:
    batting = pd.read_csv(ROOT / "Batting.csv", low_memory=False)
    cols = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF", "SH"]
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
    def test_counting_stats_match_the_per_player_fit_on_real_seasons(self):
        window = _season_window(2023)
        sample_ids = sorted(window["playerID"].unique())[::7]
        sample = window[window["playerID"].isin(sample_ids)]
        new = trend_slopes(sample, STATS).set_index("playerID")
        for pid, group in sample.groupby("playerID"):
            for stat in COUNTING:
                ref = reference_slope(group, stat)
                got = new.loc[pid, f"{stat}_trend"]
                if np.isnan(ref):
                    self.assertTrue(np.isnan(got), (pid, stat))
                else:
                    self.assertAlmostEqual(got, ref, places=8, msg=(pid, stat))


def _season(pid, year, ab, h, bb=0, doubles=0, triples=0, hr=0):
    return {"playerID": pid, "yearID": year, "AB": ab, "H": h, "BB": bb, "HBP": 0, "SF": 0, "SH": 0,
            "2B": doubles, "3B": triples, "HR": hr, "BA": h / ab if ab else np.nan}


class WeightedRateTrendTests(unittest.TestCase):
    """Rate trends: seasons pulled toward league rate by sample size, then PA-weighted."""

    def setUp(self):
        rows = [
            _season("P", 2024, 600, 180),   # .300 over a full season
            _season("P", 2025, 5, 5),       # 1.000 over 5 PA
            _season("L", 2024, 9400, 2320),  # rest of the league
            _season("L", 2025, 9995, 2495),
        ]
        self.seasons = pd.DataFrame(rows)
        self.out = trend_slopes(self.seasons, ["BA", "H"]).set_index("playerID")

    def test_tiny_season_barely_moves_the_trend_by_hand(self):
        lg24, lg25 = 2500 / 10000, 2500 / 10000
        k = RATE_SHRINK_PA
        s24 = (0.300 * 600 + lg24 * k) / (600 + k)
        s25 = (1.000 * 5 + lg25 * k) / (5 + k)
        self.assertAlmostEqual(self.out.loc["P", "BA_trend"], s25 - s24)  # two seasons: line through both
        self.assertLess(abs(self.out.loc["P", "BA_trend"]), 0.05)  # unweighted it is +0.700

    def test_counting_stats_keep_the_plain_fit(self):
        self.assertAlmostEqual(self.out.loc["P", "H_trend"], 5 - 180)

    def test_full_seasons_keep_most_of_their_change(self):
        rows = [_season("Q", y, 600, h) for y, h in ((2023, 150), (2024, 165), (2025, 180))]
        rows += [_season("L", y, 20000, 5000) for y in (2023, 2024, 2025)]
        out = trend_slopes(pd.DataFrame(rows), ["BA"]).set_index("playerID")
        # Equal PA, so the weighted line is the plain line through the pulled-in seasons.
        league = [(h + 5000) / 20600 for h in (150, 165, 180)]  # league includes Q
        pulled = [(h / 600 * 600 + lg * 200) / 800 for h, lg in zip((150, 165, 180), league)]
        expected = (pulled[2] - pulled[0]) / 2
        self.assertAlmostEqual(out.loc["Q", "BA_trend"], expected)
        self.assertGreater(expected / 0.025, 0.74)  # keeps ~3/4 of the plain +.025 per season

    def test_gap_year_spacing_and_one_season_rules_still_hold(self):
        rows = [_season("G", 2023, 500, 125), _season("G", 2025, 500, 150), _season("S", 2025, 400, 120),
                _season("L", 2023, 9500, 2375), _season("L", 2025, 9100, 2225)]
        out = trend_slopes(pd.DataFrame(rows), ["BA"]).set_index("playerID")
        self.assertGreater(out.loc["G", "BA_trend"], 0)
        self.assertLess(out.loc["G", "BA_trend"], 0.05 / 2 + 1e-9)  # per season, over a two-year gap
        self.assertTrue(np.isnan(out.loc["S", "BA_trend"]))

    def test_without_plate_appearance_columns_rates_use_the_plain_fit(self):
        rows = pd.DataFrame({"playerID": ["A", "A"], "yearID": [2024, 2025], "BA": [0.250, 0.300]})
        out = trend_slopes(rows, ["BA"]).set_index("playerID")
        self.assertAlmostEqual(out.loc["A", "BA_trend"], 0.05)

    def test_real_data_tiny_season_no_longer_leads(self):
        window = _season_window(2023)
        out = trend_slopes(window, ["OPS"]).set_index("playerID")
        self.assertLess(abs(out.loc["garrest01", "OPS_trend"]), 0.1)  # was +1.27 off a 5-AB season
        self.assertGreater(out.loc["judgeaa01", "OPS_trend"], 0.03)  # established improvement survives


class WiringTests(unittest.TestCase):
    def test_trend_table_uses_the_vectorized_pass(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        body = src[src.index("def compute_player_trend_table"):src.index("def get_latest_player_context")]
        self.assertIn("trend_slopes(", body)
        self.assertNotIn(".apply(", body)
        for col in ("AB", "BB", "HBP", "SF", "SH"):
            self.assertIn(f'"{col}"', body)  # plate appearances reach the rate weighting


if __name__ == "__main__":
    unittest.main()
