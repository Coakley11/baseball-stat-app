"""Recent AMI Questions must exclude Hall of Fame statistical cases."""

from __future__ import annotations

import unittest

from suite_analytical_question import (
    filter_resume_items_for_recent_ami,
    load_recent_ami_questions,
    should_exclude_from_recent_ami_questions,
)


class RecentAmiFilterTests(unittest.TestCase):
    def test_excludes_hof_case_by_metrics(self) -> None:
        self.assertTrue(
            should_exclude_from_recent_ami_questions(
                event="hof_case_analysis_submitted",
                metrics={
                    "exclude_from_recent_ami": True,
                    "activity_kind": "hof_case",
                    "app_context_type": "baseball_hof_case",
                    "quant_area": "hall_of_fame_case",
                },
            )
        )

    def test_includes_regular_analytical_question(self) -> None:
        self.assertFalse(
            should_exclude_from_recent_ami_questions(
                event="analytical_question",
                metrics={
                    "question": "Who should I draft next?",
                    "quant_area": "draft_assistant",
                },
            )
        )

    def test_filter_resume_items_drops_hof_rows(self) -> None:
        rows = filter_resume_items_for_recent_ami(
            [
                {"item_key": "ai:question:abc", "title": "Who should I draft next?"},
                {"item_key": "hof:ami:xyz", "title": "Open full Hall of Fame analysis — Mike Trout"},
                {"item_key": "bb:hof_case:trout", "title": "Review Hall of Fame case — Mike Trout"},
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("draft", rows[0]["title"].lower())

    def test_load_recent_ami_questions_filters_hof(self) -> None:
        events = [
            {
                "event": "analytical_question",
                "metrics": {"question": "Should I take this sleeper?", "quant_area": "sleepers"},
            },
            {
                "event": "hof_case_analysis_submitted",
                "metrics": {"exclude_from_recent_ami": True, "activity_kind": "hof_case"},
            },
            {
                "event": "analytical_question",
                "metrics": {"question": "Who should I draft?", "quant_area": "draft_assistant"},
            },
        ]

        import unittest.mock as mock

        with mock.patch("suite_storage_supabase.load_events", return_value=events):
            rows = load_recent_ami_questions(limit=5)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.get("event") == "analytical_question" for r in rows))


if __name__ == "__main__":
    unittest.main()
