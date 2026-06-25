"""Tests for team projected totals display formatting."""

from __future__ import annotations

import unittest

import pandas as pd


class TeamProjectedTotalsFormatTests(unittest.TestCase):
    def test_avg_ops_use_four_decimal_dot_style(self) -> None:
        from streamlit_app import format_team_projected_totals_table

        df = pd.DataFrame(
            {
                "Fantasy Team": ["Team A"],
                "Projected AVG": [0.2714],
                "Projected OPS": [0.7826],
            }
        )
        out = format_team_projected_totals_table(df)
        self.assertEqual(out.iloc[0]["Projected AVG"], ".2714")
        self.assertEqual(out.iloc[0]["Projected OPS"], ".7826")

    def test_counting_stats_use_one_decimal(self) -> None:
        from streamlit_app import format_team_projected_totals_table

        df = pd.DataFrame(
            {
                "Fantasy Team": ["Team A"],
                "Projected HR": [242.34],
                "Projected RBI": [891.67],
                "Projected R": [902.44],
                "Projected SB": [118.52],
                "Projected W": [82.14],
                "Projected SV": [61.83],
                "Projected K": [1432.58],
                "Projected ERA": [3.74],
            }
        )
        out = format_team_projected_totals_table(df)
        self.assertEqual(out.iloc[0]["Projected HR"], "242.3")
        self.assertEqual(out.iloc[0]["Projected RBI"], "891.7")
        self.assertEqual(out.iloc[0]["Projected R"], "902.4")
        self.assertEqual(out.iloc[0]["Projected SB"], "118.5")
        self.assertEqual(out.iloc[0]["Projected W"], "82.1")
        self.assertEqual(out.iloc[0]["Projected SV"], "61.8")
        self.assertEqual(out.iloc[0]["Projected K"], "1432.6")
        self.assertEqual(out.iloc[0]["Projected ERA"], "3.7")

    def test_avg_ops_not_percent(self) -> None:
        from streamlit_app import format_team_projected_totals_table

        df = pd.DataFrame({"Projected AVG": [0.2714], "Projected OPS": [0.7826]})
        out = format_team_projected_totals_table(df)
        self.assertNotIn("%", str(out.iloc[0]["Projected AVG"]))
        self.assertNotIn("%", str(out.iloc[0]["Projected OPS"]))


if __name__ == "__main__":
    unittest.main()
