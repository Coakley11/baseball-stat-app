"""Regression tests for DataFrame coercion and safe length helpers."""
from __future__ import annotations

import json
import unittest

import numpy as np
import pandas as pd

from dataframe_utils import (
    coerce_dataframe,
    ensure_lab_team_rank_column,
    has_dataframe_column,
    is_dataframe_empty,
    safe_collection_len,
    safe_sort_dataframe,
    sanitize_for_json,
)


class TestCoerceDataframe(unittest.TestCase):
    def test_none(self) -> None:
        df = coerce_dataframe(None)
        self.assertTrue(df.empty)

    def test_list(self) -> None:
        df = coerce_dataframe([{"a": 1}, {"a": 2}])
        self.assertEqual(len(df), 2)

    def test_dict(self) -> None:
        df = coerce_dataframe({"a": 1, "b": 2})
        self.assertEqual(len(df), 1)

    def test_empty_dataframe(self) -> None:
        df = coerce_dataframe(pd.DataFrame())
        self.assertTrue(df.empty)

    def test_populated_dataframe(self) -> None:
        df = coerce_dataframe(pd.DataFrame({"x": [1, 2]}))
        self.assertEqual(len(df), 2)


class TestIsDataframeEmpty(unittest.TestCase):
    def test_none(self) -> None:
        self.assertTrue(is_dataframe_empty(None))

    def test_empty_df(self) -> None:
        self.assertTrue(is_dataframe_empty(pd.DataFrame()))

    def test_populated_df(self) -> None:
        self.assertFalse(is_dataframe_empty(pd.DataFrame({"x": [1]})))

    def test_list(self) -> None:
        self.assertTrue(is_dataframe_empty([]))
        self.assertFalse(is_dataframe_empty([1]))


class TestSafeCollectionLen(unittest.TestCase):
    def test_none(self) -> None:
        self.assertEqual(safe_collection_len(None), 0)

    def test_empty_dataframe_no_crash(self) -> None:
        self.assertEqual(safe_collection_len(pd.DataFrame()), 0)

    def test_populated_dataframe(self) -> None:
        self.assertEqual(safe_collection_len(pd.DataFrame({"x": [1, 2, 3]})), 3)

    def test_list(self) -> None:
        self.assertEqual(safe_collection_len([1, 2]), 2)

    def test_or_pattern_would_crash_on_dataframe(self) -> None:
        df = pd.DataFrame({"pick": [1, 2]})
        self.assertEqual(safe_collection_len(df), 2)


class TestSanitizeForJson(unittest.TestCase):
    def test_nan_float_becomes_none(self) -> None:
        out = sanitize_for_json({"ops": float("nan")})
        self.assertIsNone(out["ops"])
        json.dumps(out)

    def test_inf_becomes_none(self) -> None:
        out = sanitize_for_json({"x": float("inf"), "y": float("-inf")})
        self.assertIsNone(out["x"])
        self.assertIsNone(out["y"])
        json.dumps(out)

    def test_dataframe_with_nan(self) -> None:
        df = pd.DataFrame({"HR": [1.0, float("nan")]})
        out = sanitize_for_json({"rows": df})
        self.assertEqual(out["rows"][0]["HR"], 1.0)
        self.assertIsNone(out["rows"][1]["HR"])
        json.dumps(out)

    def test_numpy_scalar(self) -> None:
        out = sanitize_for_json({"n": np.int64(5)})
        self.assertEqual(out["n"], 5)


class TestSafeSortDataframe(unittest.TestCase):
    def test_empty_summary(self) -> None:
        self.assertTrue(safe_sort_dataframe(None, "Projected Team Rank").empty)

    def test_missing_rank_column(self) -> None:
        df = pd.DataFrame({"Fantasy Team": ["Team A"], "Total Projected Fantasy Value": [100.0]})
        self.assertTrue(safe_sort_dataframe(df, "Projected Team Rank").empty)
        self.assertFalse(has_dataframe_column(df, "Projected Team Rank"))

    def test_populated_with_rank_column(self) -> None:
        df = pd.DataFrame(
            {
                "Fantasy Team": ["Team B", "Team A"],
                "Total Projected Fantasy Value": [90.0, 120.0],
                "Projected Team Rank": [2, 1],
            }
        )
        sorted_df = safe_sort_dataframe(df, "Projected Team Rank")
        self.assertEqual(sorted_df.iloc[0]["Fantasy Team"], "Team A")

    def test_ensure_lab_team_rank_column(self) -> None:
        df = pd.DataFrame(
            {
                "Fantasy Team": ["Team B", "Team A"],
                "Total Projected Fantasy Value": [90.0, 120.0],
            }
        )
        out = ensure_lab_team_rank_column(df)
        self.assertIn("Projected Team Rank", out.columns)
        self.assertEqual(out.sort_values("Projected Team Rank").iloc[0]["Fantasy Team"], "Team A")


if __name__ == "__main__":
    unittest.main()
