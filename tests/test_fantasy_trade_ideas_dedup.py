"""Trade idea deduplication regression tests."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_trade_ideas import deduplicate_trade_ideas, trade_idea_signature


class TradeIdeaDeduplicationTests(unittest.TestCase):
    def test_exact_duplicate_appears_once(self) -> None:
        ideas = pd.DataFrame(
            [
                {
                    "Give": "José Ramírez",
                    "Receive": "Aaron Judge",
                    "Other Team": "Team 2",
                    "Overall Score": 80,
                    "Trade Fit Score": 20,
                    "Fairness Score": 90,
                },
                {
                    "Give": "José Ramírez",
                    "Receive": "Aaron Judge",
                    "Other Team": "Team 2",
                    "Overall Score": 75,
                    "Trade Fit Score": 18,
                    "Fairness Score": 88,
                },
            ]
        )
        out, stats = deduplicate_trade_ideas(ideas, league_id="league:test", my_team="Daniel")
        self.assertEqual(len(out), 1)
        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(float(out.iloc[0]["Overall Score"]), 80.0)

    def test_multi_player_order_insensitive_signature(self) -> None:
        sig_a = trade_idea_signature(
            league_id="league:test",
            my_team="Daniel",
            opposing_team="Team 2",
            give_value="Player A, Player B",
            receive_value="Player C, Player D",
        )
        sig_b = trade_idea_signature(
            league_id="league:test",
            my_team="Daniel",
            opposing_team="Team 2",
            give_value="Player B, Player A",
            receive_value="Player D, Player C",
        )
        self.assertEqual(sig_a, sig_b)

    def test_dedup_keeps_stronger_scoring_row(self) -> None:
        ideas = pd.DataFrame(
            [
                {
                    "Give": "A, B",
                    "Receive": "C",
                    "Other Team": "Team 2",
                    "Overall Score": 60,
                    "Why It Helps": "weaker",
                },
                {
                    "Give": "B, A",
                    "Receive": "C",
                    "Other Team": "Team 2",
                    "Overall Score": 95,
                    "Why It Helps": "stronger",
                },
            ]
        )
        out, stats = deduplicate_trade_ideas(ideas, league_id="league:test", my_team="Daniel")
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out.iloc[0]["Why It Helps"]), "stronger")
        self.assertEqual(stats["unique_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
