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

    def test_blend_uses_percentiles_by_hand(self):
        df = add_valuation_scores(
            _frame(
                _player(HR=40),                # perf 10   → pct 1     ; trend 0 (tie) → pct 0.5
                _player(HR=20, HR_trend=4),    # perf 5    → pct 2/3   ; trend 8       → pct 1
                _player(HR=10),                # perf 2.5  → pct 1/3   ; trend 0 (tie) → pct 0.5
            ),
            1.0,
            1.0,
        )
        raw = [(1 + 0.5) / 2, (2 / 3 + 1) / 2, (1 / 3 + 0.5) / 2]
        self.assertEqual(df["Valuation_Raw"].round(9).tolist(), [round(r, 9) for r in raw])
        lo, hi = raw[2], raw[1]
        self.assertEqual(df["Valuation_Score"].round(9).tolist(), [round((raw[0] - lo) / (hi - lo), 9), 1.0, 0.0])

    def test_one_to_one_means_equal_influence_regardless_of_raw_scale(self):
        # Trend swings 100× wider than production; at 1:1 the best producer and the best trend tie.
        df = add_valuation_scores(
            _frame(_player(HR=40, HR_trend=-100), _player(HR=4, HR_trend=100), _player(HR=20)),
            1.0,
            1.0,
        )
        self.assertAlmostEqual(df.loc[0, "Valuation_Raw"], df.loc[1, "Valuation_Raw"])

    def test_weights_change_the_order(self):
        rows = (_player(HR=40), _player(HR=20, HR_trend=4), _player(HR=10, HR_trend=-2))
        current_only = add_valuation_scores(_frame(*rows), 1.0, 0.0)
        self.assertEqual(current_only["Valuation_Score"].idxmax(), 0)
        trend_only = add_valuation_scores(_frame(*rows), 0.0, 1.0)
        self.assertEqual(trend_only["Valuation_Score"].idxmax(), 1)

    def test_zero_total_weight_scores_zero(self):
        df = add_valuation_scores(_frame(_player(HR=40), _player(HR=10)), 0.0, 0.0)
        self.assertEqual(df["Valuation_Score"].tolist(), [0.0, 0.0])

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
