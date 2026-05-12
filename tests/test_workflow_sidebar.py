"""Unit tests for workflow_sidebar pure helpers (stdlib only)."""
import unittest

import workflow_sidebar as ws


class TestNormalizeDedupeQueue(unittest.TestCase):
    def test_order_and_dedupe(self):
        self.assertEqual(ws.normalize_dedupe_queue(["a", " b ", "a", "", "c"]), ["a", "b", "c"])

    def test_non_list(self):
        self.assertEqual(ws.normalize_dedupe_queue(None), [])


class TestMergeMru(unittest.TestCase):
    def test_bump(self):
        self.assertEqual(ws.merge_mru(["x", "y"], "x", 10), ["y", "x"])

    def test_cap(self):
        self.assertEqual(ws.merge_mru(["a", "b", "c"], "d", 3), ["b", "c", "d"])


class TestMergeComparisonPairs(unittest.TestCase):
    def test_dedupe_unordered(self):
        a = ws.merge_comparison_pairs([], "M A", "M B", 8)
        b = ws.merge_comparison_pairs(a, "M B", "M A", 8)
        self.assertEqual(len(b), 1)

    def test_cap(self):
        pairs = []
        for i in range(10):
            pairs = ws.merge_comparison_pairs(pairs, f"P{i}a", f"P{i}b", 3)
        self.assertEqual(len(pairs), 3)


class TestToggleFavorite(unittest.TestCase):
    def test_toggle(self):
        self.assertEqual(ws.toggle_favorite([], "A", 5), ["A"])
        self.assertEqual(ws.toggle_favorite(["A", "B"], "A", 5), ["B"])


if __name__ == "__main__":
    unittest.main()
