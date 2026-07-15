"""Queue survival — blob restore must not wipe a dirty Add-to-Queue mutation."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock


class QueueSurvivalTests(unittest.TestCase):
    def test_dirty_add_survives_apply_baseball_disk_state(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state
        from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue, is_draft_locally_dirty

        st = MagicMock()
        session: dict[str, Any] = {"active_page": "Live Draft Room"}
        st.session_state = session
        add_player_to_draft_queue(session, "Francisco Lindor")
        self.assertTrue(is_draft_locally_dirty(session))
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Francisco Lindor"])

        stale = {
            "active_page": "Live Draft Room",
            "draft_queue": [],
            "draft_state": {"queue": [], "watchlist_focus": [], "watchlist_favorites": []},
            "page_filter_state": {
                "Draft Workflow": {
                    "draft_queue": [],
                    "draft_state": {"queue": [], "watchlist_focus": [], "watchlist_favorites": []},
                }
            },
        }
        apply_baseball_disk_state(st, stale)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Francisco Lindor"])
        self.assertEqual(session["draft_state"]["queue"], ["Francisco Lindor"])
        self.assertEqual(session.get("_live_draft_queue_blob_restore_skipped"), "local_dirty_or_pending")

    def test_survival_points_detect_clear(self) -> None:
        from live_draft_queue_survival import note_queue_survival

        session: dict[str, Any] = {"draft_queue": ["Francisco Lindor"], "draft_state": {"queue": ["Francisco Lindor"]}}
        note_queue_survival(session, "A", detail="after add")
        session["draft_queue"] = []
        session["draft_state"] = {"queue": []}
        note_queue_survival(session, "B", detail="wiped")
        cleared = session.get("_live_draft_queue_cleared_at")
        self.assertIsInstance(cleared, dict)
        self.assertEqual(cleared.get("point"), "B")
        self.assertEqual(cleared.get("previous_queue"), ["Francisco Lindor"])


if __name__ == "__main__":
    unittest.main()
