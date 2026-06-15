"""Tests for AMI answer quality audit runner."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAMILIES = (
    "Draft Assistant",
    "Draft Market",
    "Player Evaluation",
    "Sleepers",
    "Trend",
    "Valuation",
    "Comparison",
    "Historical Explorer",
)


class TestAnswerQualityAudit(unittest.TestCase):
    def test_quality_audit_runs(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "ami_answer_quality_audit.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertIn("Answer quality audit:", proc.stdout, proc.stdout + proc.stderr)

    def test_quality_cases_cover_families(self) -> None:
        from ami_answer_quality_audit import QUALITY_CASES

        families = {c.family for c in QUALITY_CASES if c.family}
        for fam in FAMILIES:
            self.assertIn(fam, families, f"Missing quality family: {fam}")
        self.assertGreaterEqual(len(QUALITY_CASES), 25, "Expected expanded question-family coverage")

    def test_user_example_questions_present(self) -> None:
        from ami_answer_quality_audit import QUALITY_CASES

        questions = {c.question.lower() for c in QUALITY_CASES}
        must_include = (
            "should i prioritize steals right now?",
            "who is likely to be the next catcher picked in this draft?",
            "why is jose ramirez the best player to draft for me right now?",
            "is this trend meaningful or just noise?",
            "why does barry bonds keep showing up with these filters?",
        )
        for q in must_include:
            self.assertIn(q, questions, f"Missing example question: {q}")


if __name__ == "__main__":
    unittest.main()
