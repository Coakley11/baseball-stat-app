"""Regression: scatterplot size encoding must not crash on boolean/object columns."""

from __future__ import annotations

import unittest

import pandas as pd

from scatter_encoding import (
    build_scatter_size_encoding,
    filter_size_by_columns,
    is_quantitative_size_column,
    prepare_scatter_size_column,
    scatter_numeric_size_values,
    scatter_size_domain,
)


class _FakeAlt:
    class Scale:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Legend:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Size:
        def __init__(self, field, **kwargs):
            self.field = field
            self.kwargs = kwargs


class ScatterSizeEncodingTests(unittest.TestCase):
    def test_boolean_series_quantile_safe(self) -> None:
        s = pd.Series([True, False, True, False])
        vals = scatter_numeric_size_values(s)
        self.assertIsNotNone(vals)
        domain = scatter_size_domain(pd.DataFrame({"isHallOfFamer": s}), "isHallOfFamer")
        self.assertIsNotNone(domain)

    def test_is_hall_of_famer_not_quantitative_size(self) -> None:
        s = pd.Series([True, False, True])
        self.assertFalse(is_quantitative_size_column(s))

    def test_filter_size_by_excludes_is_hall_of_famer(self) -> None:
        df = pd.DataFrame({"HR": [10, 20], "SB": [5, 8], "isHallOfFamer": [True, False]})
        numeric = ["HR", "SB", "isHallOfFamer"]
        opts = filter_size_by_columns(df, numeric)
        self.assertIn("HR", opts)
        self.assertIn("SB", opts)
        self.assertNotIn("isHallOfFamer", opts)

    def test_object_string_column_returns_none(self) -> None:
        df = pd.DataFrame({"size_col": ["a", "b", "c"]})
        enc, out = build_scatter_size_encoding(df, "size_col", alt_module=_FakeAlt)
        self.assertIsNone(enc)
        self.assertIs(out, df)

    def test_hr_column_builds_encoding(self) -> None:
        df = pd.DataFrame({"HR": [10, 20, 30, 40]})
        enc, prepared = build_scatter_size_encoding(df, "HR", alt_module=_FakeAlt)
        self.assertIsNotNone(enc)
        self.assertIn("_scatter_size_numeric", prepared.columns)

    def test_single_row_graceful_fallback(self) -> None:
        df = pd.DataFrame({"HR": [42]})
        enc, _ = build_scatter_size_encoding(df, "HR", alt_module=_FakeAlt)
        self.assertIsNone(enc)

    def test_empty_chart_df(self) -> None:
        df = pd.DataFrame({"HR": pd.Series([], dtype=float)})
        _, num_col = prepare_scatter_size_column(df, "HR")
        self.assertIsNone(num_col)

    def test_career_like_hof_boolean_column_no_crash(self) -> None:
        df = pd.DataFrame(
            {
                "HR": [20, 30, 40],
                "SB": [5, 10, 15],
                "isHallOfFamer": [True, False, False],
            }
        )
        enc, prepared = build_scatter_size_encoding(df, "isHallOfFamer", alt_module=_FakeAlt)
        self.assertIsNone(enc)
        self.assertIs(prepared, df)

    def test_historical_like_mixed_numeric_hr(self) -> None:
        df = pd.DataFrame({"HR": [1, 2, 3, 4, 5], "SB": [0, 1, 2, 3, 4]})
        enc, _ = build_scatter_size_encoding(df, "HR", alt_module=_FakeAlt)
        self.assertIsNotNone(enc)


if __name__ == "__main__":
    unittest.main()
