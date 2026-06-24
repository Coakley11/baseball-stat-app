"""Tests for shared draft room Supabase error mapping."""

from __future__ import annotations

import unittest

from draft_room_supabase_errors import (
    SharedRoomSupabaseError,
    friendly_supabase_message,
    shared_room_supabase_error_from_runtime,
)


class SharedRoomSupabaseErrorTests(unittest.TestCase):
    def test_parse_runtime_error(self) -> None:
        exc = RuntimeError(
            'Supabase POST baseball_shared_draft_rooms failed (404): '
            '{"code":"PGRST205","message":"Could not find the table"}'
        )
        parsed = shared_room_supabase_error_from_runtime(exc)
        self.assertEqual(parsed.status_code, 404)
        self.assertEqual(parsed.method, "POST")
        self.assertIn("PGRST205", parsed.detail)
        self.assertIn("sql/baseball_shared_draft_rooms.sql", parsed.user_message)

    def test_friendly_rls_message(self) -> None:
        msg = friendly_supabase_message(403, "permission denied for table baseball_shared_draft_rooms")
        self.assertIn("denied access", msg.lower())

    def test_to_diag_dict(self) -> None:
        err = SharedRoomSupabaseError("POST", "baseball_shared_draft_rooms", 400, '{"hint":"bad"}')
        diag = err.to_diag_dict()
        self.assertEqual(diag["status_code"], 400)
        self.assertIsInstance(diag["parsed_detail"], dict)


if __name__ == "__main__":
    unittest.main()
