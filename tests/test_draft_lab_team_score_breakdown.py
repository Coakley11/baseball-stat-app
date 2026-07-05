"""Tests for Draft Lab Team Score breakdown helper."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_lab_analysis import build_draft_lab_team_score_breakdown


class DraftLabTeamScoreBreakdownTests(unittest.TestCase):
    def test_breakdown_sums_player_grades(self) -> None:
        board = pd.DataFrame(
            [
                {"Fantasy Team": "Team A", "fullName": "Aaron Judge", "Expected Fantasy Value": 0.82, "Pick": 1},
                {"Fantasy Team": "Team A", "fullName": "Freddie Freeman", "Expected Fantasy Value": 0.74, "Pick": 2},
                {"Fantasy Team": "Team B", "fullName": "Jose Ramirez", "Expected Fantasy Value": 0.71, "Pick": 3},
            ]
        )
        total, breakdown = build_draft_lab_team_score_breakdown(board, "Team A")
        self.assertAlmostEqual(total, 156.0, places=2)
        self.assertEqual(len(breakdown), 2)
        self.assertEqual(breakdown.iloc[0]["Player"], "Aaron Judge")
        self.assertAlmostEqual(float(breakdown.iloc[0]["Player Grade"]), 82.0, places=2)
