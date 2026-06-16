"""Comparison Tool AMI send routing and context promotion."""

from __future__ import annotations

import unittest

from applied_math_context import extract_comparison_players_from_question
from baseball_ami_pages import (
    build_comparison_send_diagnostics,
    detect_comparison_send_intent,
    finalize_comparison_context_for_send,
)


class TestComparisonPlayerExtraction(unittest.TestCase):
    """Regression: parser must strip trailing question fragments from the second player."""

    def test_strips_trailing_draft_pick_phrase(self) -> None:
        a, b = extract_comparison_players_from_question(
            "Is Juan Soto vs Aaron Judge the better draft pick?"
        )
        self.assertEqual(a, "Juan Soto")
        self.assertEqual(b, "Aaron Judge")

    def test_strips_trailing_long_term_value_phrase(self) -> None:
        a, b = extract_comparison_players_from_question(
            "Mookie Betts vs Ronald Acuna the better long-term value?"
        )
        self.assertEqual(a, "Mookie Betts")
        self.assertEqual(b, "Ronald Acuna")

    def test_plain_versus_question_unchanged(self) -> None:
        a, b = extract_comparison_players_from_question("Kyle Tucker vs Corbin Carroll")
        self.assertEqual(a, "Kyle Tucker")
        self.assertEqual(b, "Corbin Carroll")


class TestComparisonSendIntent(unittest.TestCase):
    def test_head_to_head_vs_question(self) -> None:
        q = "Is Juan Soto vs Aaron Judge the better draft pick?"
        self.assertEqual(detect_comparison_send_intent(q), "comparison_draft_pick")

    def test_long_term_value_question(self) -> None:
        q = "Who has better long-term value, Mookie Betts or Ronald Acuna?"
        self.assertEqual(detect_comparison_send_intent(q), "comparison_long_term")


class TestFinalizeComparisonContext(unittest.TestCase):
    def test_promotes_players_chart_and_routing(self) -> None:
        session = {
            "sig_player_a_clean": "Juan Soto",
            "sig_player_b_clean": "Aaron Judge",
            "compare_stat": "OPS",
            "comparison_state": {
                "players": ["Juan Soto", "Aaron Judge"],
                "player_a": "Juan Soto",
                "player_b": "Aaron Judge",
                "chart": {"compare_x_axis_mode": "Season Year"},
            },
            "_ami_comparison_context": {
                "comparison_stats": ["OPS"],
                "comparison_differences": [{"player": "Juan Soto", "Slope": 0.02}],
            },
        }
        ctx: dict = {}
        question = "Is Juan Soto vs Aaron Judge the better draft pick?"
        finalize_comparison_context_for_send(ctx, session, question=question)

        self.assertEqual(ctx.get("player_a"), "Juan Soto")
        self.assertEqual(ctx.get("player_b"), "Aaron Judge")
        self.assertEqual(ctx.get("routing_hint"), "comparison_draft_pick")
        self.assertEqual(ctx.get("intent"), "comparison_analysis")
        self.assertEqual(ctx.get("metrics"), ["OPS"])
        self.assertEqual(len(ctx.get("comparison_differences") or []), 1)
        self.assertEqual((ctx.get("comparison_chart") or {}).get("compare_x_axis_mode"), "Season Year")

        diag = build_comparison_send_diagnostics(ctx, question=question)
        self.assertEqual(diag.get("comparison_send_intent"), "comparison_draft_pick")
        self.assertTrue(diag.get("player_a_present"))
        self.assertTrue(diag.get("player_b_present"))


if __name__ == "__main__":
    unittest.main()
