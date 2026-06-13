"""End-to-end Baseball AMI acceptance tests (context + analyst stub)."""

from __future__ import annotations

import unittest

from ami_acceptance_harness import (
    audit_page_context,
    build_realistic_draft_assistant_session,
    build_realistic_live_draft_session,
    build_realistic_sleepers_session,
    build_realistic_trend_valuation_session,
    run_acceptance_check,
    run_full_acceptance_suite,
)


class TestAmiAcceptanceSuite(unittest.TestCase):
    def test_full_suite_passes(self) -> None:
        report = run_full_acceptance_suite()
        self.assertEqual(report["summary"]["failed"], 0, report["summary"])
        self.assertGreaterEqual(report["summary"]["passed"], 8)

    def test_draft_assistant_context_complete(self) -> None:
        session = build_realistic_draft_assistant_session()
        ctx = session["_acceptance_ctx"]
        audit = audit_page_context(ctx, "Draft Assistant Simulator")
        missing = [a.key for a in audit if not a.present]
        self.assertEqual(missing, [], f"Missing: {missing}")

    def test_draft_assistant_does_not_recommend_drafted_player(self) -> None:
        session = build_realistic_draft_assistant_session()
        ctx = session["_acceptance_ctx"]
        result = run_acceptance_check(
            "T1_board_awareness",
            "Draft Assistant Simulator",
            "Who should I draft next?",
            ctx,
        )
        self.assertTrue(result.passed, result.failures)
        self.assertIn("Cal Raleigh", result.stub_response)
        self.assertNotIn("Aaron Judge", result.stub_response.split("Alternatives")[0])

    def test_live_draft_has_drafted_players(self) -> None:
        session = build_realistic_live_draft_session()
        ctx = session["_acceptance_ctx"]
        result = run_acceptance_check(
            "T1_board_awareness",
            "Live Draft Room",
            "I'm on the clock. Who should I take?",
            ctx,
        )
        self.assertTrue(result.passed, result.failures)
        self.assertTrue(ctx.get("drafted_players") or ctx.get("canonical_drafted_players"))

    def test_sleepers_excludes_drafted(self) -> None:
        session = build_realistic_sleepers_session()
        ctx = session["_acceptance_ctx"]
        result = run_acceptance_check(
            "T5_sleepers",
            "Fantasy Sleepers & Busts",
            "Should I take this sleeper?",
            ctx,
        )
        self.assertTrue(result.passed, result.failures)
        self.assertIn("Junior Caminero", result.stub_response)

    def test_trend_valuation_draft_status(self) -> None:
        session = build_realistic_trend_valuation_session()
        trend = run_acceptance_check(
            "T6_valuation_trend",
            "Trend Value",
            "Is this player undervalued?",
            session["_trend_ctx"],
        )
        val = run_acceptance_check(
            "T6_valuation_trend",
            "Valuation",
            "How risky is this pick?",
            session["_valuation_ctx"],
        )
        self.assertTrue(trend.passed, trend.failures)
        self.assertTrue(val.passed, val.failures)

    def test_analyst_frame_present(self) -> None:
        ctx = build_realistic_draft_assistant_session()["_acceptance_ctx"]
        self.assertIn("ami_answer_template", ctx)
        self.assertIn("ami_quality_rule", ctx)
        self.assertGreaterEqual(len(ctx.get("ami_answer_template", [])), 6)


if __name__ == "__main__":
    unittest.main()
