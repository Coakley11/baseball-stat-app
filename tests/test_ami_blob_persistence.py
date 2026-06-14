"""Tests for question_id blob persistence on duplicate sends."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_analytical_question import submit_analytical_question


class TestAmiBlobPersistence(unittest.TestCase):
    @patch("suite_account.remember_saved_item")
    def test_duplicate_send_still_updates_blob(self, remember_mock) -> None:
        session: dict = {
            "_ami_last_send": {
                "question_id": "abc123",
                "submitted_at": "2099-01-01T00:00:00+00:00",
            }
        }
        rich_ctx = {
            "workflow": "Fantasy draft",
            "current_pick": 8,
            "available_players": [{"player": "Kyle Tucker", "Primary Position": "OF"}],
            "draft_snapshot": {
                "current_pick": 8,
                "available_players": [{"player": "Kyle Tucker", "Primary Position": "OF"}],
            },
            "send_pipeline_diagnostics": {"ctx_available_players_count": 1},
        }
        with patch("suite_analytical_question._recent_duplicate_send", return_value=True):
            with patch("suite_analytical_question.build_applied_math_resume_url", return_value="http://test"):
                with patch("suite_analytical_question._upsert_applied_intelligence_resume"):
                    result = submit_analytical_question(
                        source_app="baseball",
                        source_page="Draft Assistant Simulator",
                        question="Who is the best player available?",
                        context=rich_ctx,
                        session_state=session,
                    )
        self.assertTrue(result.get("duplicate"))
        self.assertTrue(session.get("_ami_last_send", {}).get("blob_updated"))
        self.assertGreaterEqual(remember_mock.call_count, 1)
        saved_payload = remember_mock.call_args.kwargs.get("payload") or remember_mock.call_args[1].get("payload")
        if saved_payload is None and remember_mock.call_args[0]:
            saved_payload = remember_mock.call_args[0][3] if len(remember_mock.call_args[0]) > 3 else None
        if saved_payload is None:
            saved_payload = remember_mock.call_args.kwargs.get("payload")
        blob_ctx = (saved_payload or {}).get("context") or {}
        self.assertEqual(len(blob_ctx.get("available_players") or []), 1)


if __name__ == "__main__":
    unittest.main()
