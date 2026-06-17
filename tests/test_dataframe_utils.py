"""Regression tests for DataFrame coercion and safe length helpers."""
from __future__ import annotations

import unittest

import pandas as pd

from dataframe_utils import coerce_dataframe, is_dataframe_empty, safe_collection_len


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


if __name__ == "__main__":
    unittest.main()
