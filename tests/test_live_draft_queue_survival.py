"""Queue survival — multi-pass wipe detection + empty-overwrite guards."""

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
        self.assertTrue(bool(session.get("_live_draft_queue_blob_restore_skipped")))

    def test_empty_blob_refused_even_after_dirty_cleared(self) -> None:
        """Later pass: dirty flag cleared but session queue still populated."""
        from baseball_persistent_state import apply_baseball_disk_state
        from draft_state import DRAFT_QUEUE_KEY, clear_draft_local_edit

        st = MagicMock()
        session: dict[str, Any] = {
            "active_page": "Live Draft Room",
            DRAFT_QUEUE_KEY: ["Juan Soto", "Aaron Judge"],
            "draft_state": {
                "queue": ["Juan Soto", "Aaron Judge"],
                "watchlist_focus": [],
                "watchlist_favorites": [],
            },
        }
        st.session_state = session
        clear_draft_local_edit(session)
        apply_baseball_disk_state(
            st,
            {
                "active_page": "Live Draft Room",
                "draft_queue": [],
                "draft_state": {"queue": [], "watchlist_focus": [], "watchlist_favorites": []},
            },
        )
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Juan Soto", "Aaron Judge"])
        self.assertEqual(
            session.get("_live_draft_queue_blob_restore_skipped"),
            "refuse_empty_blob_over_session",
        )

    def test_write_canonical_blocks_empty_overwrite(self) -> None:
        from draft_state import DRAFT_QUEUE_KEY, mark_draft_local_edit, write_canonical_draft_state
        from live_draft_queue_survival import begin_queue_action

        session: dict[str, Any] = {
            DRAFT_QUEUE_KEY: ["Juan Soto"],
            "draft_state": {"queue": ["Juan Soto"], "watchlist_focus": [], "watchlist_favorites": []},
        }
        mark_draft_local_edit(session)
        begin_queue_action(session, name="Juan Soto")
        write_canonical_draft_state(session, queue=[], reason="reconcile_on_load", local_edit=False)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Juan Soto"])
        self.assertTrue(bool(session.get("_live_draft_queue_empty_write_blocked")))

    def test_survival_points_detect_clear(self) -> None:
        from live_draft_queue_survival import begin_queue_script_pass, note_queue_survival

        session: dict[str, Any] = {
            "draft_queue": ["Francisco Lindor"],
            "draft_state": {"queue": ["Francisco Lindor"]},
        }
        begin_queue_script_pass(session)
        note_queue_survival(session, "A", detail="after add")
        session["draft_queue"] = []
        session["draft_state"] = {"queue": []}
        note_queue_survival(session, "B", detail="wiped")
        cleared = session.get("_live_draft_queue_cleared_at")
        self.assertIsInstance(cleared, dict)
        self.assertEqual(cleared.get("point"), "B")
        self.assertEqual(cleared.get("previous_queue"), ["Francisco Lindor"])
        self.assertTrue(str(cleared.get("pass_id") or "").startswith("pass_"))


if __name__ == "__main__":
    unittest.main()
