"""Tests for AMI answer quality audit runner."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestAnswerQualityAudit(unittest.TestCase):
    def test_quality_audit_all_pass(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "ami_answer_quality_audit.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_quality_cases_cover_user_families(self) -> None:
        from ami_answer_quality_audit import QUALITY_CASES

        ids = {c.case_id for c in QUALITY_CASES}
        expected = {
            "next_catcher",
            "position_run",
            "make_it_back",
            "wait_on_player",
            "olson_vs_schwarber",
            "jose_ramirez",
            "team_needs",
            "hitter_vs_pitcher",
            "best_values",
            "sleepers",
            "trend_interpretation",
            "historical_filters",
            "comparison_power",
            "comparison_why",
        }
        self.assertTrue(expected.issubset(ids), f"Missing quality cases: {expected - ids}")


if __name__ == "__main__":
    unittest.main()
