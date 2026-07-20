"""Tests for Supabase shared draft room backend (PR 4)."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from draft_room_shared_state import sanitize_shared_room_document, shared_room_document
from draft_room_supabase_store import (
    SupabaseSharedRoomStore,
    document_to_row,
    row_to_document,
)


def _sample_document(*, revision: int = 1) -> dict:
    return shared_room_document(
        room_code="ABC123",
        host_participant_id="host-user",
        live_room={
            "draft_room_id": "ROOM1",
            "status": "in_progress",
            "config": {"num_teams": 2},
            "teams": ["Team 1", "Team 2"],
            "rosters": {"Team 1": [], "Team 2": []},
            "draft_board": [],
            "pool_records": [],
            "pool_columns": [],
        },
        revision=revision,
    )


class SharedRoomSanitizeTests(unittest.TestCase):
    def test_strips_private_participant_fields(self) -> None:
        doc = _sample_document()
        doc["queue"] = ["Aaron Judge"]
        doc["notes"] = "secret"
        doc["participants"] = {
            "u1": {
                "assigned_team": "Team 1",
                "display_name": "Host",
                "joined_at": "2026-01-01T00:00:00+00:00",
                "workflow": {"queue": ["Aaron Judge"]},
            }
        }
        cleaned = sanitize_shared_room_document(doc)
        self.assertNotIn("queue", cleaned)
        self.assertNotIn("notes", cleaned)
        self.assertNotIn("workflow", cleaned["participants"]["u1"])


class SupabaseSharedRoomStoreTests(unittest.TestCase):
    def test_row_round_trip(self) -> None:
        doc = _sample_document(revision=3)
        row = document_to_row(doc)
        self.assertEqual(row["room_code"], "ABC123")
        self.assertEqual(row["revision"], 3)
        back = row_to_document(row)
        self.assertIsNotNone(back)
        assert back is not None
        self.assertEqual(back["room_code"], "ABC123")
        self.assertEqual(back["revision"], 3)

    def test_save_if_revision_conflict_returns_current(self) -> None:
        store = SupabaseSharedRoomStore()
        doc = _sample_document(revision=2)
        current_row = document_to_row(_sample_document(revision=2))

        with patch("draft_room_supabase_store._request") as mock_request:
            mock_request.side_effect = [
                [{"room_code": "ABC123", "revision": 2, "status": "", "updated_at": ""}],  # head
                [current_row],  # full load on conflict
            ]
            ok, saved = store.save_if_revision(doc, expected_revision=1)
        self.assertFalse(ok)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["revision"], 2)

    def test_save_if_revision_success(self) -> None:
        store = SupabaseSharedRoomStore()
        doc = _sample_document(revision=1)
        doc["chat"] = {"messages": [], "chat_revision": 1}

        with patch("draft_room_supabase_store._request") as mock_request:
            mock_request.side_effect = [
                [{"room_code": "ABC123", "revision": 1, "status": "", "updated_at": ""}],  # head
                [],  # PATCH return=minimal
            ]
            ok, saved = store.save_if_revision(doc, expected_revision=1)
        self.assertTrue(ok)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(mock_request.call_args_list[1].kwargs.get("prefer"), "return=minimal")

    def test_exists_and_load(self) -> None:
        store = SupabaseSharedRoomStore()
        row = document_to_row(_sample_document())
        with patch("draft_room_supabase_store._request") as mock_request:
            mock_request.return_value = [{"room_code": "ABC123"}]
            self.assertTrue(store.exists("ABC123"))
            mock_request.return_value = [row]
            loaded = store.load("ABC123")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["room_code"], "ABC123")


    def test_backend_factory_prefers_local_when_forced(self) -> None:
        import os
        from draft_room_shared_state import get_local_shared_room_store, reset_shared_room_store_for_tests, shared_room_backend_name

        with patch.dict(os.environ, {"BASEBALL_SHARED_DRAFT_ROOM_BACKEND": "local"}, clear=False):
            reset_shared_room_store_for_tests(None)
            self.assertEqual(shared_room_backend_name(), "local_file")
            from draft_room_shared_state import get_shared_room_store

            store = get_shared_room_store()
            self.assertIsInstance(store, type(get_local_shared_room_store()))
        reset_shared_room_store_for_tests(None)


if __name__ == "__main__":
    unittest.main()
