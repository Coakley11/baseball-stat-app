"""Tests for shared draft room strict JSON serialization."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from draft_room_json_sanitize import (
    SharedRoomJsonSerializeError,
    prepare_supabase_json_body,
    sanitize_shared_room_json,
    validate_strict_json,
)
from draft_room_shared_state import sanitize_shared_room_document, shared_room_document
from draft_room_supabase_store import SupabaseSharedRoomStore, document_to_row


def _live_room_with_dirty_values() -> dict:
    pool = pd.DataFrame(
        [
            {
                "playerID": np.int64(99),
                "fullName": "Aaron Judge",
                "Expected Fantasy Value": np.float64(float("nan")),
                "updated_at": pd.Timestamp("2024-06-01T12:00:00Z"),
            },
        ]
    )
    return {
        "draft_room_id": "ROOM1",
        "status": "in_progress",
        "current_pick_index": np.int64(0),
        "config": {
            "num_teams": np.int32(2),
            "your_team": "Team 1",
            "started_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        },
        "teams": ("Team 1", "Team 2"),
        "rosters": {"Team 1": [], "Team 2": {1, 2}},
        "draft_board": [
            {
                "Pick": np.int64(1),
                "Round": 1,
                "Team": "Team 1",
                "Player": "",
                "picked_at": datetime(2024, 6, 1, 12, 5, tzinfo=timezone.utc),
            }
        ],
        "drafted_player_ids": set(),
        "pool": pool,
        "timer_started_at": np.float64(1717243200.5),
    }


class SharedRoomJsonSanitizeTests(unittest.TestCase):
    def test_numpy_scalar_values(self) -> None:
        out = sanitize_shared_room_json({"n": np.int64(7), "x": np.float64(1.5)})
        self.assertEqual(out["n"], 7)
        self.assertEqual(out["x"], 1.5)

    def test_pandas_nan_becomes_none(self) -> None:
        out = sanitize_shared_room_json({"ops": float("nan"), "arr": [np.nan]})
        self.assertIsNone(out["ops"])
        self.assertIsNone(out["arr"][0])

    def test_datetime_and_timestamp_to_iso(self) -> None:
        ts = pd.Timestamp("2024-06-01T12:00:00Z")
        dt = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        out = sanitize_shared_room_json({"ts": ts, "dt": dt})
        self.assertEqual(out["ts"], ts.isoformat())
        self.assertEqual(out["dt"], dt.isoformat())

    def test_sets_and_tuples_become_lists(self) -> None:
        out = sanitize_shared_room_json({"teams": ("A", "B"), "ids": {1, 2}})
        self.assertEqual(out["teams"], ["A", "B"])
        self.assertEqual(sorted(out["ids"]), [1, 2])

    def test_nested_player_records(self) -> None:
        out = sanitize_shared_room_json(
            {
                "pool_records": [
                    {
                        "playerID": np.int64(1),
                        "rating": np.float64(float("inf")),
                        "tags": frozenset({"a", "b"}),
                    }
                ]
            }
        )
        self.assertEqual(out["pool_records"][0]["playerID"], 1)
        self.assertIsNone(out["pool_records"][0]["rating"])
        self.assertEqual(sorted(out["pool_records"][0]["tags"]), ["a", "b"])

    def test_prepare_supabase_json_body_is_strict_json(self) -> None:
        row = prepare_supabase_json_body(
            {
                "room_code": "ABC123",
                "revision": np.int64(1),
                "shared_room_json": {"room": {"timer": np.float64(1.0)}},
            }
        )
        json.dumps(row, allow_nan=False)

    def test_validate_strict_json_reports_path(self) -> None:
        class _Bad:
            pass

        with self.assertRaises(SharedRoomJsonSerializeError) as ctx:
            validate_strict_json({"room": {"bad": _Bad()}}, path="$")
        self.assertIn("room.bad", str(ctx.exception.path))


class SharedRoomDocumentSanitizeTests(unittest.TestCase):
    def test_sanitize_shared_room_document_converts_live_room_blob(self) -> None:
        doc = shared_room_document(
            room_code="ABC123",
            host_participant_id="host",
            live_room=_live_room_with_dirty_values(),
        )
        cleaned = sanitize_shared_room_document(doc)
        json.dumps(cleaned, allow_nan=False)
        room = cleaned["room"]
        self.assertIn("pool_records", room)
        self.assertNotIn("pool", room)
        self.assertIsInstance(room["teams"], list)
        self.assertIsInstance(room["draft_board"][0]["Pick"], int)
        self.assertIsNone(room["pool_records"][0]["Expected Fantasy Value"])

    def test_document_to_row_post_body_serializable(self) -> None:
        doc = shared_room_document(
            room_code="ABC123",
            host_participant_id="host",
            live_room=_live_room_with_dirty_values(),
        )
        row = document_to_row(doc, created=True)
        json.dumps(row, allow_nan=False)


class SupabaseSharedRoomSaveSerializationTests(unittest.TestCase):
    def test_save_post_uses_json_safe_payload(self) -> None:
        store = SupabaseSharedRoomStore()
        doc = shared_room_document(
            room_code="ABC123",
            host_participant_id="host",
            live_room=_live_room_with_dirty_values(),
        )
        captured: dict = {}

        def _capture_request(method, path, **kwargs):
            captured["method"] = method
            captured["json_body"] = kwargs.get("json_body")
            if method == "GET" or (method == "PATCH" and kwargs.get("params", {}).get("revision")):
                return []
            return [document_to_row(doc, created=True)]

        with unittest.mock.patch("draft_room_supabase_store._request", side_effect=_capture_request):
            saved = store.save(doc)

        self.assertEqual(captured["method"], "POST")
        json.dumps(captured["json_body"], allow_nan=False)
        self.assertEqual(saved["room_code"], "ABC123")


if __name__ == "__main__":
    unittest.main()
