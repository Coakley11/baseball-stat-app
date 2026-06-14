"""Tests for draft-aware question_id fingerprinting and blob metadata."""

from __future__ import annotations

import unittest
from unittest.mock import patch


from suite_analytical_question import _store_question_context_blob, question_id


class TestQuestionIdFingerprint(unittest.TestCase):
    def test_draft_pick_changes_question_id(self) -> None:
        q = "Who is the best player available?"
        page = "Draft Room Simulator"
        base = {"workflow": "Fantasy draft", "player": "the best player"}
        id_pick1 = question_id(
            q,
            source_app="baseball",
            source_page=page,
            context={
                **base,
                "current_pick": 1,
                "send_pipeline_diagnostics": {"session_pick_count": 0, "session_projection_available_count": 0},
            },
        )
        id_pick8 = question_id(
            q,
            source_app="baseball",
            source_page=page,
            context={
                **base,
                "current_pick": 8,
                "send_pipeline_diagnostics": {"session_pick_count": 7, "session_projection_available_count": 51},
            },
        )
        self.assertNotEqual(id_pick1, id_pick8)

    def test_source_page_included_in_question_id(self) -> None:
        q = "Who is the best player available?"
        ctx = {"workflow": "Fantasy draft", "current_pick": 8}
        id_room = question_id(q, source_app="baseball", source_page="Draft Room Simulator", context=ctx)
        id_assistant = question_id(
            q, source_app="baseball", source_page="Draft Assistant Simulator", context=ctx
        )
        self.assertNotEqual(id_room, id_assistant)

    @patch("suite_account.remember_saved_item")
    def test_blob_store_returns_post_save_diagnostics(self, remember_mock) -> None:
        remember_mock.return_value = {"write_mode": "upsert"}
        ctx = {
            "current_pick": 8,
            "available_players": [{"player": "Kyle Tucker"}] * 51,
            "draft_snapshot": {"current_pick": 8, "available_players": [{"player": "Kyle Tucker"}] * 51},
            "best_available": [{"player": "Kyle Tucker"}] * 6,
        }
        meta = _store_question_context_blob(
            {
                "question_id": "testqid123",
                "question": "Who is the best player available?",
                "source_app": "baseball",
                "source_page": "Draft Room Simulator",
                "context": ctx,
                "source_state": {},
            }
        )
        self.assertTrue(meta.get("blob_updated"))
        self.assertEqual(meta.get("blob_payload_available_players_count_after_save"), 51)
        self.assertEqual(meta.get("blob_payload_current_pick_after_save"), 8)
        self.assertEqual(meta.get("question_id"), "testqid123")
        self.assertTrue(meta.get("blob_payload_hash"))


if __name__ == "__main__":
    unittest.main()
