"""Tests for Supabase shared draft room health probe."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_room_supabase_errors import SharedRoomSupabaseError
from draft_room_supabase_health import probe_shared_room_supabase_health


class SharedRoomSupabaseHealthTests(unittest.TestCase):
    @patch("draft_room_supabase_store.supabase_shared_room_backend_available", return_value=True)
    def test_table_missing_marks_sql_setup_required(self, _mock_avail: object) -> None:
        with patch("draft_room_supabase_store._request") as mock_request:
            mock_request.side_effect = SharedRoomSupabaseError(
                "GET",
                "baseball_shared_draft_rooms",
                404,
                '{"code":"PGRST205","message":"Could not find the table"}',
            )
            health = probe_shared_room_supabase_health(run_write_probe=False)
        self.assertFalse(health["table_reachable"])
        self.assertTrue(health["sql_setup_required"])
        self.assertEqual(health["status_code"], 404)

    @patch("draft_room_supabase_store.supabase_shared_room_backend_available", return_value=True)
    def test_healthy_insert_and_load(self, _mock_avail: object) -> None:
        saved_row = {
            "room_code": "HEALTH1",
            "shared_room_json": {"room_code": "HEALTH1", "revision": 1, "room": {}},
            "revision": 1,
            "status": "not_started",
        }

        def _side_effect(method, path, **kwargs):
            params = kwargs.get("params") or {}
            if method == "GET" and params.get("room_code"):
                raw = str(params.get("room_code", ""))
                code = raw[3:] if raw.startswith("eq.") else raw
                return [
                    {
                        **saved_row,
                        "room_code": code,
                        "shared_room_json": {**saved_row["shared_room_json"], "room_code": code},
                    }
                ]
            if method == "GET" and params.get("limit") == "1":
                return []
            if method == "POST":
                body = kwargs.get("json_body") or {}
                code = str(body.get("room_code") or "HEALTH1")
                return [
                    {
                        **saved_row,
                        "room_code": code,
                        "shared_room_json": {**saved_row["shared_room_json"], "room_code": code},
                    }
                ]
            if method == "DELETE":
                return None
            return []

        with patch("draft_room_supabase_store._request", side_effect=_side_effect):
            with patch("draft_room_supabase_store.SupabaseSharedRoomStore.exists", return_value=False):
                health = probe_shared_room_supabase_health(run_write_probe=True)
        self.assertTrue(health["table_reachable"])
        self.assertTrue(health["insert_ok"])
        self.assertTrue(health["load_ok"])


if __name__ == "__main__":
    unittest.main()
