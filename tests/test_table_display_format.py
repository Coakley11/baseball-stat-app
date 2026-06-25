"""Regression tests for safe table Styler formatting."""

from __future__ import annotations

import unittest

import pandas as pd

from table_display_format import filter_styler_format_map, safe_format_stat_value


class SafeFormatStatValueTests(unittest.TestCase):
    def test_blank_returns_empty(self) -> None:
        self.assertEqual(safe_format_stat_value(None), "")
        self.assertEqual(safe_format_stat_value(""), "")

    def test_rate_four_decimals(self) -> None:
        self.assertEqual(safe_format_stat_value(0.2714, kind="rate"), ".2714")

    def test_count_one_decimal(self) -> None:
        self.assertEqual(safe_format_stat_value(12.34, kind="count"), "12.3")


class FilterStylerFormatMapTests(unittest.TestCase):
    def test_skips_string_columns(self) -> None:
        df = pd.DataFrame({"Projected AVG": [".2714", ".2500"], "Projected HR": [10.0, 12.0]})
        fmt = {"Projected AVG": "{:.4f}", "Projected HR": "{:.1f}"}
        out = filter_styler_format_map(df, fmt)
        self.assertNotIn("Projected AVG", out)
        self.assertIn("Projected HR", out)

    def test_preformatted_team_analysis_does_not_crash_styler(self) -> None:
        df = pd.DataFrame(
            {
                "Fantasy Team": ["Ariel", "Daniel"],
                "Projected AVG": [".2714", ".2500"],
                "Projected OPS": [".7826", ".8012"],
                "Total Projected Fantasy Value": [120.5, 115.2],
            }
        )
        fmt = filter_styler_format_map(
            df,
            {
                "Projected AVG": "{:.4f}",
                "Projected OPS": "{:.4f}",
                "Total Projected Fantasy Value": "{:.1f}",
            },
        )
        styled = df.style.format(fmt)
        html = styled.to_html()
        self.assertIn("Ariel", html)


if __name__ == "__main__":
    unittest.main()
