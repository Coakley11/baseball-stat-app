"""Regression tests for persisted compare/historical year range sanitization."""

import unittest

from year_range_state import sanitize_year_range


class TestSanitizeYearRange(unittest.TestCase):
    def setUp(self) -> None:
        self.bounds = (2010, 2024)
        self.default = (2010, 2024)

    def test_stale_wide_range_clamps(self) -> None:
        self.assertEqual(
            sanitize_year_range((1900, 3000), *self.bounds),
            (2010, 2024),
        )

    def test_empty_list_uses_default(self) -> None:
        self.assertEqual(
            sanitize_year_range([], *self.bounds, default=(2015, 2024)),
            (2015, 2024),
        )

    def test_none_uses_default(self) -> None:
        self.assertEqual(
            sanitize_year_range(None, *self.bounds, default=(2012, 2020)),
            (2012, 2020),
        )

    def test_bad_values_use_default(self) -> None:
        self.assertEqual(
            sanitize_year_range(["bad", 2020], *self.bounds, default=self.default),
            self.default,
        )

    def test_reversed_range_uses_default(self) -> None:
        self.assertEqual(
            sanitize_year_range((2024, 2018), *self.bounds, default=self.default),
            self.default,
        )

    def test_single_year_bounds_returns_none(self) -> None:
        self.assertIsNone(sanitize_year_range((2010, 2024), 2020, 2020))

    def test_single_year_invalid_saved_uses_default_none_bounds(self) -> None:
        self.assertIsNone(sanitize_year_range((1900, 3000), 2020, 2020))

    def test_valid_partial_range_kept(self) -> None:
        self.assertEqual(
            sanitize_year_range((2015, 2020), *self.bounds),
            (2015, 2020),
        )

    def test_list_input_accepted(self) -> None:
        self.assertEqual(
            sanitize_year_range([2016, 2019], *self.bounds),
            (2016, 2019),
        )


if __name__ == "__main__":
    unittest.main()
