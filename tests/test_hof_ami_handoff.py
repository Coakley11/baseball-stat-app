"""HOF case AMI full-analysis handoff tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_analytical_question import (
    analytical_question_continue_copy,
    build_question_payload,
    submit_analytical_question,
)


class HofAmiHandoffTests(unittest.TestCase):
    def test_hof_continue_copy_uses_player_title(self) -> None:
        payload = build_question_payload(
            source_app="baseball",
            source_page="Career Totals",
            question="Hall of Fame statistical case for Albert Pujols",
            context={
                "player": "Albert Pujols",
                "hof_case_packet": {
                    "mode": "hall_of_fame_case",
                    "target_player": "Albert Pujols",
                    "hof_case_summary": "Hall of Fame statistical case for Albert Pujols · cohort 12/40 HOF (30%)",
                },
                "routing_hint": "hof_case_analysis",
            },
            quant_area="hall_of_fame_case",
        )
        title, subtitle, button = analytical_question_continue_copy(payload)
        self.assertIn("Albert Pujols", title)
        self.assertIn("Open full Hall of Fame analysis", title)
        self.assertIn("cohort 12/40 HOF", subtitle)
        self.assertNotIn("Do NOT present", subtitle)
        self.assertIn("Open analysis", button)

    def test_hof_submit_upserts_applied_intelligence_resume(self) -> None:
        upserts: list = []
        activities: list = []
        with patch("suite_analytical_question._upsert_applied_intelligence_resume", side_effect=lambda p, **k: upserts.append((p, k))):
            with patch("suite_analytical_question._store_question_context_blob"):
                with patch("suite_activity_client.record_activity", side_effect=lambda *a, **k: activities.append((a, k))):
                    result = submit_analytical_question(
                        source_app="baseball",
                        source_page="Career Totals",
                        question="Hall of Fame statistical case for Albert Pujols",
                        context={
                            "player": "Albert Pujols",
                            "hof_case_packet": {
                                "mode": "hall_of_fame_case",
                                "target_player": "Albert Pujols",
                            },
                            "routing_hint": "hof_case_analysis",
                        },
                        quant_area="hall_of_fame_case",
                    )
        self.assertTrue(upserts)
        self.assertTrue(str(result.get("action_url") or "").strip())
        self.assertIn("suite_ai_question_id", str(result.get("action_url") or ""))
        self.assertTrue(activities)
        event_type = activities[0][0][1]
        self.assertEqual(event_type, "hof_case_analysis_submitted")


if __name__ == "__main__":
    unittest.main()
