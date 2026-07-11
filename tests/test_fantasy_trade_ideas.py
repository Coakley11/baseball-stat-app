"""Regression tests for Fantasy Lineup Assistant trade idea generator."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_ASSISTANT_TAB_KEY,
    derive_category_needs,
    filter_trade_suggestions_by_requested_players,
    generate_trade_ideas,
    resolve_lineup_assistant_tab,
    suggest_trade_targets_for_team,
)


def _sample_rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Power Guy", "HR": 25, "RBI": 70, "R": 60, "SB": 3, "BA": 0.240, "OPS": 0.800},
            {"Team": "Daniel", "Player": "Contact Guy", "HR": 8, "RBI": 45, "R": 55, "SB": 12, "BA": 0.310, "OPS": 0.760},
            {"Team": "C. Oakley", "Player": "Oak Power", "HR": 22, "RBI": 68, "R": 58, "SB": 4, "BA": 0.255, "OPS": 0.820},
            {"Team": "C. Oakley", "Player": "Oak Contact", "HR": 6, "RBI": 40, "R": 50, "SB": 15, "BA": 0.320, "OPS": 0.780},
            {"Team": "Team 3", "Player": "Third Basher", "HR": 20, "RBI": 62, "R": 52, "SB": 6, "BA": 0.265, "OPS": 0.790},
        ]
    )


class FantasyTradeIdeasTests(unittest.TestCase):
    def test_derive_category_needs_falls_back_to_roster_analysis_without_standings(self) -> None:
        rosters = _sample_rosters()
        needs = derive_category_needs(None, "Daniel", rosters, summarize_team_category_needs_fn=lambda *_: {})
        self.assertTrue(isinstance(needs, dict))

    def test_generate_trade_ideas_searches_all_opposing_teams(self) -> None:
        rosters = _sample_rosters()

        def _needs(_standings, team_name: str) -> dict[str, bool]:
            return {"BA": True} if team_name == "Daniel" else {}

        ideas, diag = generate_trade_ideas(
            "Daniel",
            rosters,
            None,
            summarize_team_category_needs_fn=_needs,
            league_context_id="league-test",
        )
        self.assertGreaterEqual(len(diag["opposing_teams_searched"]), 2)
        self.assertNotIn("Daniel", diag["opposing_teams_searched"])
        if not ideas.empty:
            self.assertNotIn(set(ideas["Other Team"].astype(str)), {"Daniel"})

    @patch("fantasy_trade_ideas.derive_category_needs", return_value={})
    def test_generate_trade_ideas_without_needs_reports_failure_reason(self, _mock_needs) -> None:
        rosters = _sample_rosters()
        ideas, diag = generate_trade_ideas(
            "Daniel",
            rosters,
            pd.DataFrame(),
            summarize_team_category_needs_fn=lambda *_: {},
            league_context_id="league-test",
        )
        self.assertTrue(ideas.empty)
        self.assertEqual(diag["failure_reason"], "no_category_needs_detected")

    def test_generate_trade_ideas_with_needs_returns_suggestions(self) -> None:
        rosters = _sample_rosters()

        def _needs(_standings, team_name: str) -> dict[str, bool]:
            return {"BA": True} if team_name == "Daniel" else {}

        ideas, diag = generate_trade_ideas(
            "Daniel",
            rosters,
            None,
            summarize_team_category_needs_fn=_needs,
            league_context_id="league-test",
        )
        self.assertGreater(diag["candidate_count_before_filters"], 0)
        self.assertGreaterEqual(diag["final_idea_count"], 1)
        self.assertFalse(ideas.empty)
        self.assertIn("Give", ideas.columns)
        self.assertIn("Receive", ideas.columns)
        self.assertIn("Other Team", ideas.columns)
        self.assertIn("Value Explanation", ideas.columns)

    def test_filter_trade_suggestions_by_requested_players(self) -> None:
        suggestions = pd.DataFrame(
            [
                {"Give": "Power Guy", "Receive": "Oak Contact", "Other Team": "C. Oakley"},
                {"Give": "Contact Guy", "Receive": "Oak Power", "Other Team": "C. Oakley"},
            ]
        )
        filtered = filter_trade_suggestions_by_requested_players(
            suggestions,
            forced_give=["Power Guy"],
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["Give"], "Power Guy")

    def test_suggest_trade_targets_for_team_excludes_own_team(self) -> None:
        rosters = _sample_rosters()
        out = suggest_trade_targets_for_team("Daniel", "Daniel", rosters, {"BA": True})
        self.assertTrue(out.empty)

    def test_resolve_lineup_assistant_tab_opens_trade_analyzer_on_handoff(self) -> None:
        session: dict = {"_lineup_focus_trade_center": True}
        tab = resolve_lineup_assistant_tab(session)
        self.assertEqual(tab, "Trade Center")
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_KEY], "Trade Center")


if __name__ == "__main__":
    unittest.main()
