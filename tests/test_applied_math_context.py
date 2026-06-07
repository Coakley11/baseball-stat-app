"""Tests for Baseball Applied Math context extractors."""

from __future__ import annotations

import unittest

from applied_math_context import (
    apply_source_state_to_session,
    build_baseball_applied_math_context,
    build_source_state,
    record_trend_intel,
)


class TestBaseballSourceState(unittest.TestCase):
    def test_build_source_state_captures_full_comparison_labels(self) -> None:
        session = {
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Aaron Judge (NYY)",
            "compare_players": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            "compare_stat": "OPS",
            "compare_year_range": [2019, 2024],
        }
        ss = build_source_state("Comparison Tool", session)
        self.assertEqual(ss["source_page"], "Comparison Tool")
        self.assertEqual(ss["entity_params"]["player_a_label"], "Juan Soto (NYY)")
        self.assertEqual(ss["widget_params"]["sig_player_a_clean"], "Juan Soto (NYY)")
        self.assertEqual(ss["filter_params"]["compare_stat"], "OPS")

    def test_apply_source_state_sets_pending_keys(self) -> None:
        session: dict = {}
        source = build_source_state(
            "Comparison Tool",
            {
                "sig_player_a_clean": "Juan Soto (NYY)",
                "sig_player_b_clean": "Aaron Judge (NYY)",
                "compare_players": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            },
        )
        apply_source_state_to_session(session, source)
        self.assertEqual(session["pending_sig_player_a"], "Juan Soto (NYY)")
        self.assertEqual(session["pending_compare_players"], ["Juan Soto (NYY)", "Aaron Judge (NYY)"])
        self.assertEqual(session["_navigate_to_page"], "Comparison Tool")


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
