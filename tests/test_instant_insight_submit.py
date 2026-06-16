"""Tests for instant Baseball Insight on AMI submit."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestInstantInsightSubmit(unittest.TestCase):
    @patch("suite_analytical_question._store_question_context_blob")
    @patch("suite_activity_client.record_activity")
    def test_baseball_submit_defers_blob_when_requested(
        self, record_mock, blob_mock
    ) -> None:
        from suite_analytical_question import submit_analytical_question

        session: dict = {}
        submit_analytical_question(
            source_app="baseball",
            source_page="Live Draft Room",
            question="Who should I draft next?",
            context={"current_pick": 8, "available_players": [{"player": "A"}]},
            session_state=session,
            defer_blob_save=True,
        )
        record_mock.assert_called_once()
        blob_mock.assert_not_called()
        self.assertIn("_ami_pending_blob_save", session)

    def test_build_return_insight_uses_why_text(self) -> None:
        from types import SimpleNamespace

        from applied_math_return_insight import build_return_insight_payload

        result = SimpleNamespace(
            short_answer="Draft Jose Ramirez now.",
            why="He closes your 3B gap before the tier drops.",
            math_idea="draft value",
            variables="rank_edge",
            assumptions=[],
            confidence_pct=82,
            computed={},
            live_metrics={},
        )
        insight = build_return_insight_payload(
            question="Who should I draft?",
            source_app="baseball",
            source_page="Live Draft Room",
            result=result,
        )
        self.assertIn("3B gap", insight.math_summary)

    def test_build_submit_fallback_insight(self) -> None:
        from applied_math_return_insight import build_submit_fallback_insight

        insight = build_submit_fallback_insight(
            question="Would Nathan Lukes make a good pick?",
            source_app="baseball",
            source_page="Fantasy Sleepers & Busts",
            question_id="abc123",
            full_analysis_url="https://example.com/resume",
            reason="ami_repo_not_found",
        )
        self.assertIn("full analysis", insight.conclusion.lower())
        self.assertTrue(insight.full_analysis_url)

    @patch("suite_analytical_question._recent_duplicate_send", return_value=True)
    @patch("suite_analytical_question._store_question_context_blob")
    @patch("suite_activity_client.record_activity")
    def test_baseball_duplicate_still_records_activity(
        self, record_mock, blob_mock, dup_mock
    ) -> None:
        from suite_analytical_question import submit_analytical_question

        session: dict = {}
        blob_mock.return_value = {"blob_updated": True}
        submit_analytical_question(
            source_app="baseball",
            source_page="Fantasy Sleepers & Busts",
            question="Would Nathan Lukes make a good pick?",
            context={},
            session_state=session,
        )
        record_mock.assert_called_once()

    def test_build_return_insight_scrubs_fallback_for_draft_coach(self) -> None:
        from types import SimpleNamespace

        from applied_math_return_insight import build_return_insight_payload

        result = SimpleNamespace(
            short_answer="**Draft grade: B+** through pick 8.",
            why="No exact solver matched, but we can still model the closest problem.",
            math_idea="Probability reasonableness — compare quoted p to an implied edge band.",
            variables="",
            assumptions=[],
            confidence_pct=82,
            computed={"draft_mode": "draft_review"},
            live_metrics={},
        )
        insight = build_return_insight_payload(
            question="How would you rate my picks?",
            source_app="baseball",
            source_page="Draft Assistant Simulator",
            result=result,
            route=SimpleNamespace(problem_type="Draft review", model_rationale="fallback"),
        )
        self.assertNotIn("no exact solver", insight.math_summary.lower())
        self.assertNotIn("probability reasonableness", (insight.method or "").lower())
        self.assertEqual(insight.method, "Draft review")


if __name__ == "__main__":
    unittest.main()
