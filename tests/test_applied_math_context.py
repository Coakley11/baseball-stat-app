"""Tests for Baseball Applied Math context extractors."""

from __future__ import annotations

import unittest

from applied_math_context import build_baseball_applied_math_context, record_trend_intel


class TestBaseballAppliedMathContext(unittest.TestCase):
    def test_trend_page_includes_slope_delta_r2(self) -> None:
        session = {
            "single_trend_dashboard_player": "Lorenzo Cain (KC)",
            "single_trend_dashboard_stats": ["HR"],
            "trend_plot_stat": "HR",
            "_ami_trend_summary": {
                "stat": "HR",
                "player": "Lorenzo Cain",
                "latest": 15,
                "delta": 6,
                "slope": 1.2,
                "r2": 0.64,
                "summary": "upward but noisy trend",
            },
        }
        ctx = build_baseball_applied_math_context("Trend Value", session)
        ts = ctx.get("trend_summary")
        self.assertIsInstance(ts, dict)
        self.assertEqual(ts.get("slope"), 1.2)
        self.assertEqual(ts.get("r2"), 0.64)
        self.assertEqual(ts.get("delta"), 6)

    def test_comparison_includes_both_players(self) -> None:
        session = {
            "sig_player_a_clean": "Mike Piazza (NYM)",
            "sig_player_b_clean": "Jeff Bagwell (HOU)",
            "_ami_comparison_context": {"comparison_stats": ["OPS"]},
        }
        ctx = build_baseball_applied_math_context("Comparison Tool", session)
        self.assertEqual(ctx["player_a"], "Mike Piazza")
        self.assertEqual(ctx["player_b"], "Jeff Bagwell")

    def test_record_trend_intel_caches_summary(self) -> None:
        session: dict = {}
        record_trend_intel(
            session,
            player="Lorenzo Cain",
            stat="HR",
            intel_row={"Slope": 1.2, "R²": 0.64, "Net Change": 6, "Trend Direction": "Up"},
            year_start=2018,
            year_end=2022,
        )
        self.assertIn("_ami_trend_summary", session)
        self.assertEqual(session["_ami_trend_summary"]["slope"], 1.2)


if __name__ == "__main__":
    unittest.main()
