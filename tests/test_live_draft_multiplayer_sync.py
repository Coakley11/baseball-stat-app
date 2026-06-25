"""Tests for canonical timer_deadline sync and pick notice deduplication."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from draft_commit_diagnostics import (
    LIVE_DRAFT_SUCCESS_SHOWN_KEY,
    render_live_draft_pick_notice,
    set_live_draft_pick_notice,
)
from live_draft_state import room_from_persist_dict, room_to_persist_dict
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining


class TimerDeadlineSyncTests(unittest.TestCase):
    def test_reset_timer_sets_shared_deadline(self) -> None:
        room = {"status": "in_progress", "config": {"timer_seconds": 90}, "timer_handled_index": -1}
        before = time.time()
        live_draft_reset_timer(room)
        self.assertIsNotNone(room.get("timer_deadline"))
        self.assertGreaterEqual(float(room["timer_deadline"]), before + 89)
        self.assertLessEqual(float(room["timer_deadline"]), before + 91)

    def test_seconds_remaining_uses_deadline_not_local_start(self) -> None:
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "timer_deadline": time.time() + 42,
            "timer_started_at": time.time() - 999,
        }
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 40)
        self.assertLessEqual(remaining, 43)

    def test_deadline_roundtrips_through_persist(self) -> None:
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 60},
            "current_pick_index": 1,
            "timer_handled_index": -1,
        }
        live_draft_reset_timer(room)
        blob = room_to_persist_dict(room)
        self.assertIn("timer_deadline", blob)
        self.assertIsNone(blob.get("timer_started_at"))
        restored = room_from_persist_dict(blob)
        assert restored is not None
        self.assertIsNotNone(restored.get("timer_deadline"))
        self.assertGreater(live_draft_seconds_remaining(restored), 0)


class PickNoticeDedupTests(unittest.TestCase):
    def test_success_notice_renders_once(self) -> None:
        session: dict = {}
        set_live_draft_pick_notice(session, "success", "Drafted Julio Rodriguez.", pick_key="2:julior01")
        st = mock.MagicMock()
        render_live_draft_pick_notice(st, session)
        st.success.assert_called_once_with("Drafted Julio Rodriguez.")
        set_live_draft_pick_notice(session, "success", "Drafted Julio Rodriguez.", pick_key="2:julior01")
        render_live_draft_pick_notice(st, session)
        st.success.assert_called_once()


if __name__ == "__main__":
    unittest.main()
