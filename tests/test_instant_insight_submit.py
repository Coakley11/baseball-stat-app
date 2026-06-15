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


if __name__ == "__main__":
    unittest.main()
