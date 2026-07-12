"""Regression tests for trade category OPS formatting and aggregation."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from fantasy_trade_category_values import (
    RATE_CATEGORIES,
    aggregate_trade_package_value,
    find_roster_column,
    format_trade_category_value,
    package_ops_value,
    player_ops_value,
)


class TradeCategoryFormattingTests(unittest.TestCase):
    def test_ops_renders_as_decimal_not_zero(self) -> None:
        self.assertEqual(format_trade_category_value("OPS", 0.850), ".850")

    def test_ops_change_renders_signed_decimal(self) -> None:
        self.assertEqual(format_trade_category_value("OPS", -0.025, is_change=True), "-.025")

    def test_obp_and_slg_use_decimal_formatting(self) -> None:
        self.assertEqual(format_trade_category_value("OBP", 0.341), ".341")
        self.assertEqual(format_trade_category_value("SLG", 0.512), ".512")

    def test_counting_stats_remain_integers(self) -> None:
        self.assertEqual(format_trade_category_value("HR", 21), "21")
        self.assertEqual(format_trade_category_value("RBI", 68), "68")
        self.assertEqual(format_trade_category_value("R", 55), "55")
        self.assertEqual(format_trade_category_value("SB", 12), "12")
        self.assertEqual(format_trade_category_value("HR", -6, is_change=True), "-6")

    def test_missing_ops_renders_dash_not_zero(self) -> None:
        self.assertEqual(format_trade_category_value("OPS", np.nan), "—")
        self.assertEqual(format_trade_category_value("OPS", None), "—")

    def test_ops_derived_from_obp_and_slg(self) -> None:
        row = pd.Series({"OBP": 0.350, "SLG": 0.500})
        self.assertAlmostEqual(player_ops_value(row), 0.850)

    def test_ops_column_alias_resolution(self) -> None:
        df = pd.DataFrame([{"On-Base Plus Slugging": 0.897}])
        self.assertEqual(find_roster_column(df, ("OPS", "On-Base Plus Slugging")), "On-Base Plus Slugging")

    def test_multi_player_ops_not_naively_summed(self) -> None:
        df = pd.DataFrame(
            [
                {"Player": "A", "OPS": 0.900, "OBP": 0.360, "SLG": 0.540},
                {"Player": "B", "OPS": 0.800, "OBP": 0.320, "SLG": 0.480},
            ]
        )
        naive_sum = float(pd.to_numeric(df["OPS"], errors="coerce").sum())
        aggregate = package_ops_value(df)
        self.assertAlmostEqual(aggregate, 0.340 + 0.510)
        self.assertNotAlmostEqual(aggregate, naive_sum)

    def test_multi_player_ops_unavailable_without_components(self) -> None:
        df = pd.DataFrame([{"Player": "A", "OPS": 0.900}, {"Player": "B", "OPS": 0.800}])
        self.assertTrue(pd.isna(package_ops_value(df)))

    def test_aggregate_trade_package_value_ops_single_player(self) -> None:
        df = pd.DataFrame([{"OPS": 0.850}])
        self.assertAlmostEqual(aggregate_trade_package_value(df, "OPS"), 0.850)

    def test_rate_categories_include_ops_family(self) -> None:
        self.assertEqual(RATE_CATEGORIES, {"BA", "AVG", "OBP", "SLG", "OPS"})


if __name__ == "__main__":
    unittest.main()
