"""Sleepers / bust-risk AMI send routing."""

from __future__ import annotations

import unittest

from baseball_ami_pages import (
    build_sleepers_send_diagnostics,
    detect_sleepers_send_intent,
    finalize_sleepers_context_for_send,
)


class TestSleepersSendIntent(unittest.TestCase):
    def test_market_bust_risks_question(self) -> None:
        q = "Are there any players in Market Bust Risks that I should consider drafting?"
        self.assertEqual(detect_sleepers_send_intent(q), "bust_risk_review")

    def test_sleeper_ranking_intent(self) -> None:
        q = "Which sleeper has the best combination of upside and safety?"
        self.assertEqual(detect_sleepers_send_intent(q), "sleeper_ranking")

    def test_named_sleeper_question(self) -> None:
        q = "Should I draft Nathan Lukes in this draft since he is a top sleeper?"
        self.assertEqual(detect_sleepers_send_intent(q), "sleeper_take")

    def test_bust_take_with_named_player(self) -> None:
        q = "Should I draft Eric Wagaman despite bust risk?"
        self.assertEqual(detect_sleepers_send_intent(q), "bust_take")


class TestFinalizeSleepersContext(unittest.TestCase):
    def test_bust_review_clears_stale_sleeper_focus(self) -> None:
        session = {
            "_ami_sleepers_snapshot": {
                "sleeper_candidates": [{"player": "Nathan Lukes", "adp": 326}],
                "bust_risks": [{"player": "Eric Wagaman", "adp": 180}],
            }
        }
        ctx = {
            "question_player": "Nathan Lukes",
            "sleeper_focus": {"player": "Nathan Lukes", "adp": 326},
            "routing_hint": "sleeper_take",
            "intent": "sleeper_analysis",
        }
        question = "Are there any players in Market Bust Risks that I should consider drafting?"
        finalize_sleepers_context_for_send(ctx, session, question=question)

        self.assertEqual(ctx.get("routing_hint"), "bust_risk_review")
        self.assertEqual(ctx.get("intent"), "bust_risk_analysis")
        self.assertEqual(ctx.get("market_section"), "Market Bust Risks")
        self.assertNotIn("sleeper_focus", ctx)
        self.assertNotIn("question_player", ctx)
        bust_rows = ctx.get("bust_risks") or []
        self.assertEqual(len(bust_rows), 1)
        self.assertEqual(bust_rows[0].get("player"), "Eric Wagaman")

    def test_named_sleeper_keeps_focus(self) -> None:
        session = {
            "_ami_sleepers_snapshot": {
                "sleeper_candidates": [{"player": "Nathan Lukes", "adp": 326, "fantasy_edge": 226}],
            }
        }
        ctx: dict = {}
        question = "Should I draft Nathan Lukes in this draft since he is a top sleeper?"
        finalize_sleepers_context_for_send(ctx, session, question=question)

        self.assertEqual(ctx.get("question_player"), "Nathan Lukes")
        self.assertEqual(ctx.get("routing_hint"), "sleeper_take")
        focus = ctx.get("sleeper_focus") or {}
        self.assertEqual(focus.get("player"), "Nathan Lukes")

    def test_sleepers_send_diagnostics(self) -> None:
        ctx = {
            "routing_hint": "bust_risk_review",
            "market_section": "Market Bust Risks",
            "bust_risks": [{"player": "Eric Wagaman"}],
        }
        diag = build_sleepers_send_diagnostics(
            ctx,
            question="Are there any players in Market Bust Risks that I should consider drafting?",
        )
        self.assertEqual(diag.get("sleepers_send_intent"), "bust_risk_review")
        self.assertEqual(diag.get("bust_risk_count"), 1)
        self.assertFalse(diag.get("sleeper_focus_present"))

    def test_bust_routing_on_draft_page(self) -> None:
        from suite_analytical_question import build_submit_context

        session = {
            "_ami_sleepers_snapshot": {
                "bust_risks": [{"player": "Eric Wagaman", "adp": 180}],
            },
            "_ami_draft_snapshot": {"current_pick": 8, "draft_round": 4},
        }
        ctx = build_submit_context(
            "baseball",
            "Draft Assistant Simulator",
            session,
            question="Are there any players in Market Bust Risks that I should consider drafting?",
        )
        self.assertEqual(ctx.get("routing_hint"), "bust_risk_review")
        self.assertEqual(ctx.get("intent"), "bust_risk_analysis")
        self.assertNotIn("sleeper_focus", ctx)
        self.assertGreaterEqual(len(ctx.get("bust_risks") or []), 1)

    def test_finalize_sleeper_ranking_routing(self) -> None:
        session = {
            "_ami_sleepers_snapshot": {
                "sleeper_candidates": [
                    {"player": "Nathan Lukes", "Fantasy Edge": 226, "Expert Std Dev": 12.5, "ADP": 326},
                    {"player": "Isaac Collins", "Fantasy Edge": 180, "Expert Std Dev": 28.0, "ADP": 280},
                ],
            }
        }
        ctx: dict = {}
        question = "Which sleeper has the best combination of upside and safety?"
        finalize_sleepers_context_for_send(ctx, session, question=question)
        self.assertEqual(ctx.get("routing_hint"), "sleeper_ranking")
        self.assertEqual(ctx.get("intent"), "sleeper_ranking_analysis")
        self.assertNotIn("sleeper_focus", ctx)
        self.assertGreaterEqual(len(ctx.get("sleeper_candidates") or []), 2)


if __name__ == "__main__":
    unittest.main()
