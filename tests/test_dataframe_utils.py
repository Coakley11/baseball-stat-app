"""Regression tests for DataFrame coercion and safe length helpers."""
from __future__ import annotations

import unittest

import pandas as pd

import json

import numpy as np

from dataframe_utils import coerce_dataframe, is_dataframe_empty, safe_collection_len, sanitize_for_json


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
        # ``df or []`` raises ValueError on DataFrame — safe_collection_len must not.
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


if __name__ == "__main__":
    unittest.main()
