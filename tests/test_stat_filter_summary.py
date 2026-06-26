"""Tests for Career/Historical stat minimum filter summaries."""

from __future__ import annotations

import unittest

from stat_filter_summary import (
    build_stat_filter_summary_diagnostics,
    build_stat_filter_summary_lines,
    gather_active_stat_min_filters,
    format_stat_min_line,
    render_stat_filter_summary,
)


class StatFilterSummaryTests(unittest.TestCase):
    def test_gather_only_active_nonzero_mins(self) -> None:
        session = {
            "career_H_min": 3000,
            "career_HR_min": 500,
            "career_2B_min": 0,
            "career_OPS_min": 0.0,
            "career_team_filter": ["NYY"],
        }
        active = gather_active_stat_min_filters(session, prefix="career")
        self.assertEqual(active, [("H", 3000.0), ("HR", 500.0)])

    def test_historical_summary_lines(self) -> None:
        session = {
            "hist_HR_min": 40,
            "hist_2B_min": 20,
            "hist_RBI_min": 100,
            "historical_hof_membership_filter": "Hall of Famers Only",
        }
        lines = build_stat_filter_summary_lines(session, prefix="hist")
        self.assertEqual(
            lines,
            [
                "Doubles ≥ 20",
                "Home Runs ≥ 40",
                "RBI ≥ 100",
            ],
        )

    def test_rate_stat_formatting(self) -> None:
        self.assertEqual(format_stat_min_line("OPS", 0.85), "OPS ≥ 0.850")
        self.assertEqual(format_stat_min_line("H", 3000), "Hits ≥ 3,000")

    def test_empty_when_no_active_mins(self) -> None:
        self.assertEqual(build_stat_filter_summary_lines({}, prefix="career"), [])

    def test_diagnostics_track_renderer_state(self) -> None:
        session: dict = {"career_H_min": 3000, "_filter_summary_called_career": True, "_filter_summary_displayed_career": True}
        diag = build_stat_filter_summary_diagnostics(session, mode="career")
        self.assertTrue(diag["renderer_called"])
        self.assertTrue(diag["summary_displayed"])
        self.assertEqual(diag["active_filter_count"], 1)
        self.assertEqual(diag["active_widget_keys"]["career_H_min"], 3000.0)
        self.assertIn("career_HR_min", diag["all_widget_values"])


if __name__ == "__main__":
    unittest.main()
