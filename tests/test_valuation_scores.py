"""Valuation scores on hand-computed players: formula, ordering, scaling, weights, missing data."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from valuation_scores import add_valuation_scores

ROOT = Path(__file__).resolve().parents[1]
COUNTS = ["R", "H", "2B", "3B", "HR", "RBI", "SB"]
RATES = ["BA", "OBP", "SLG", "OPS"]
TRENDS = [f"{s}_trend" for s in ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"]]


def _player(**values) -> dict:
    row = {c: 0.0 for c in COUNTS + RATES + TRENDS}
    row.update(values)
    return row


def _frame(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


class ValuationFormulaTests(unittest.TestCase):
    def test_perf_score_by_hand(self):
        # 100 R·0.10 + 40 HR·0.25 + 90 RBI·0.20 + .300 BA·100·0.05 + .900 OPS·100·0.10
        df = add_valuation_scores(_frame(_player(R=100, HR=40, RBI=90, BA=0.300, OPS=0.900)), 1.0, 1.0)
        self.assertAlmostEqual(df.loc[0, "Perf_Score"], 10 + 10 + 18 + 1.5 + 9.0)

    def test_trend_score_by_hand(self):
        # +5 HR/season·2 + +0.010 OPS/season·100 − 3 SB/season·1
        df = add_valuation_scores(_frame(_player(HR_trend=5, OPS_trend=0.010, SB_trend=-3)), 1.0, 1.0)
        self.assertAlmostEqual(df.loc[0, "Trend_Score"], 10 + 1 - 3)

    def test_order_follows_the_blend_and_scales_to_0_1(self):
        df = add_valuation_scores(
            _frame(
                _player(HR=40),                # perf 10, trend 0   → 10
                _player(HR=20, HR_trend=4),    # perf 5,  trend 8   → 13
                _player(HR=10),                # perf 2.5           → 2.5
            ),
            1.0,
            1.0,
        )
        self.assertEqual(list(df["Valuation_Raw"]), [10.0, 13.0, 2.5])
        self.assertEqual(df["Valuation_Score"].round(6).tolist(), [round(7.5 / 10.5, 6), 1.0, 0.0])

    def test_weights_change_the_order(self):
        rows = (_player(HR=40), _player(HR=20, HR_trend=4))
        current_only = add_valuation_scores(_frame(*rows), 1.0, 0.0)
        self.assertGreater(current_only.loc[0, "Valuation_Score"], current_only.loc[1, "Valuation_Score"])
        trend_heavy = add_valuation_scores(_frame(*rows), 1.0, 3.0)
        self.assertLess(trend_heavy.loc[0, "Valuation_Score"], trend_heavy.loc[1, "Valuation_Score"])

    def test_missing_trend_and_rates_count_as_zero(self):
        df = add_valuation_scores(_frame(_player(HR=40, HR_trend=np.nan, BA=np.nan), _player()), 1.0, 1.0)
        self.assertAlmostEqual(df.loc[0, "Trend_Score"], 0.0)
        self.assertAlmostEqual(df.loc[0, "Perf_Score"], 10.0)

    def test_all_equal_scores_zero(self):
        df = add_valuation_scores(_frame(_player(HR=10), _player(HR=10)), 1.0, 1.0)
        self.assertEqual(df["Valuation_Score"].tolist(), [0.0, 0.0])


class WiringTests(unittest.TestCase):
    def test_valuation_page_uses_the_shared_scores(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("add_valuation_scores(valuation_df, w_current, w_trend)", src)
        self.assertNotIn('valuation_df["Perf_Score"] = (', src)


if __name__ == "__main__":
    unittest.main()
