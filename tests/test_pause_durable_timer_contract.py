"""Paused Shared Draft must not keep running expire/autopick page work."""

from __future__ import annotations

import unittest

from live_draft_timer_logic import live_draft_pause_timer, live_draft_resume_timer


class PauseDurableTimerContractTests(unittest.TestCase):
    def test_pause_at_zero_preserves_usable_resume_seconds(self) -> None:
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": 0,  # already expired
            "timer_started_at": 0,
            "current_pick_index": 3,
        }
        left = live_draft_pause_timer(room)
        self.assertEqual(room.get("status"), "paused")
        self.assertGreater(int(left), 0)
        self.assertEqual(int(room.get("paused_remaining_seconds") or 0), 60)

    def test_resume_restores_in_progress_from_paused(self) -> None:
        room = {
            "status": "paused",
            "config": {"timer_seconds": 45},
            "paused_remaining_seconds": 45,
            "current_pick_index": 2,
        }
        live_draft_resume_timer(room, 45)
        self.assertEqual(room.get("status"), "in_progress")
        self.assertIsNone(room.get("paused_remaining_seconds"))
        self.assertIsNotNone(room.get("timer_deadline"))


if __name__ == "__main__":
    unittest.main()
