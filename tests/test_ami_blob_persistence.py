"""Tests for question_id blob persistence on duplicate sends."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_analytical_question import submit_analytical_question


class TestAmiBlobPersistence(unittest.TestCase):
    @patch("suite_activity_client.record_activity")
    @patch("suite_account.remember_saved_item")
    def test_submit_passes_ami_continue_url_to_activity(self, remember_mock, record_mock) -> None:
        session: dict = {}
        with patch("suite_analytical_question._upsert_applied_intelligence_resume"):
            result = submit_analytical_question(
                source_app="baseball",
                source_page="Draft Assistant Simulator",
                question="Who should I draft next?",
                context={"current_pick": 8, "available_players": [{"player": "A"}] * 51},
                session_state=session,
            )
        self.assertIn("applied-mathematical-intelligence", str(result.get("action_url") or ""))
        self.assertIn("suite_ai_question_id", str(result.get("action_url") or ""))
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        self.assertIn("suite_ai_question_id", str(kwargs.get("action_url") or ""))
        self.assertIn("applied-mathematical-intelligence", str(kwargs.get("action_url") or ""))
        metrics = kwargs.get("metrics") or {}
        self.assertEqual(metrics.get("target_app"), "applied_intelligence")
        self.assertIn("suite_ai_question_id", str(metrics.get("continue_action_url") or ""))
        self.assertNotIn("saved_item_type", metrics)
        self.assertTrue(str(metrics.get("resume_key") or "").startswith("ai:question:"))

    def test_analytical_question_skips_save_current_state(self) -> None:
        from suite_storage_supabase import record_activity as cloud_record_activity

        timing: dict = {}
        with patch("suite_storage_supabase._defer_append_event") as defer_mock, patch(
            "suite_storage_supabase.save_current_state"
        ) as save_state_mock, patch("suite_storage_supabase.upsert_resume_item"):
            cloud_record_activity(
                "baseball",
                "analytical_question",
                page="Draft Assistant Simulator",
                metrics={"question_id": "q1"},
                summary="Asked Applied Math: test",
                resume_key="ai:question:q1",
                resume_title="Continue",
                resume_subtitle="test",
                action_url="http://example.com",
                timing_out=timing,
            )
        self.assertTrue(timing.get("append_event_deferred"))
        save_state_mock.assert_not_called()
        defer_mock.assert_called_once()

    @patch("suite_activity_client.record_activity")
    @patch("suite_account.remember_saved_item")
    def test_activity_recorded_before_blob_save(self, remember_mock, record_mock) -> None:
        order: list[str] = []

        def _record(*_args, **_kwargs):
            order.append("activity")

        def _blob(*_args, **_kwargs):
            order.append("blob")
            return {"ok": True}

        record_mock.side_effect = _record
        remember_mock.side_effect = _blob
        with patch("suite_analytical_question._upsert_applied_intelligence_resume"):
            submit_analytical_question(
                source_app="baseball",
                source_page="Draft Assistant Simulator",
                question="Who should I draft next?",
                context={"current_pick": 8, "available_players": [{"player": "A"}]},
                session_state={},
            )
        self.assertEqual(order[:2], ["activity", "blob"])
        remember_apps = [call.args[0] for call in remember_mock.call_args_list]
        self.assertEqual(remember_apps, ["applied_intelligence"])

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
