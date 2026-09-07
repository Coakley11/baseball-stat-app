"""Durable Pause must not be clobbered by stale in_progress peer writes."""

from __future__ import annotations

import unittest

from draft_room_shared_state import (
    ALLOW_UNPAUSE_COMMIT_KEY,
    mark_shared_unpause_commit_allowed,
    preserve_paused_against_stale_in_progress,
)


class PreservePausedAgainstStaleWriteTests(unittest.TestCase):
    def test_stale_in_progress_keeps_paused(self) -> None:
        current = {
            "status": "paused",
            "revision": 12,
            "room": {"status": "paused", "paused_remaining_seconds": 44},
        }
        live = {
            "status": "in_progress",
            "paused_remaining_seconds": None,
            "timer_deadline": 999.0,
            "draft_board": [],
        }
        out = preserve_paused_against_stale_in_progress({}, current, live)
        self.assertEqual(out.get("status"), "paused")
        self.assertEqual(int(out.get("paused_remaining_seconds") or 0), 44)
        self.assertIsNone(out.get("timer_deadline"))

    def test_explicit_unpause_allowed(self) -> None:
        current = {"status": "paused", "room": {"paused_remaining_seconds": 30}}
        live = {"status": "in_progress", "timer_deadline": 123.0}
        session = {}
        mark_shared_unpause_commit_allowed(session)
        out = preserve_paused_against_stale_in_progress(session, current, live)
        self.assertEqual(out.get("status"), "in_progress")
        self.assertNotIn(ALLOW_UNPAUSE_COMMIT_KEY, session)

    def test_in_progress_to_paused_unchanged(self) -> None:
        current = {"status": "in_progress", "room": {}}
        live = {"status": "paused", "paused_remaining_seconds": 20}
        out = preserve_paused_against_stale_in_progress({}, current, live)
        self.assertIs(out, live)


if __name__ == "__main__":
    unittest.main()
