"""Tests for AMI hardening pass runner."""

from __future__ import annotations

import unittest

from ami_hardening_pass import QUESTION_FAMILIES, run_hardening_pass


class TestAmiHardeningPass(unittest.TestCase):
    def test_families_defined(self) -> None:
        self.assertGreaterEqual(len(QUESTION_FAMILIES), 14)
        pages = {c.page for c in QUESTION_FAMILIES}
        self.assertIn("Draft Assistant Simulator", pages)
        self.assertIn("Trend Value", pages)
        self.assertIn("Valuation", pages)
        self.assertIn("Comparison Tool", pages)
        self.assertIn("Historical Explorer", pages)

    def test_hardening_pass_all_green(self) -> None:
        report = run_hardening_pass()
        self.assertEqual(
            report["summary"]["failed"],
            0,
            report["summary"],
        )
        self.assertTrue(report["summary"]["ready_for_manual_acceptance"])


if __name__ == "__main__":
    unittest.main()
