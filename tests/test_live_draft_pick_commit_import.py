"""Regression: live draft helpers must not import streamlit_app."""

from __future__ import annotations

import importlib
import sys
import unittest
from unittest.mock import patch


class PickCommitImportTests(unittest.TestCase):
    def test_import_live_draft_pick_commit_does_not_load_streamlit_app(self) -> None:
        for name in list(sys.modules):
            if name in ("streamlit_app", "Streamlit_app"):
                del sys.modules[name]
        import live_draft_pick_commit  # noqa: F401

        self.assertNotIn("streamlit_app", sys.modules)
        self.assertNotIn("Streamlit_app", sys.modules)

    def test_run_autopick_selection_does_not_load_streamlit_app(self) -> None:
        for name in list(sys.modules):
            if name in ("streamlit_app", "Streamlit_app"):
                del sys.modules[name]
        import live_draft_pick_commit as commit

        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
            "config": {"your_team": "Team A"},
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {"Team A": []},
            "pool": None,
        }
        with patch("live_draft_autopick.live_draft_auto_pick", return_value=(False, "pool empty")):
            commit.run_autopick_selection(room)
        self.assertNotIn("streamlit_app", sys.modules)
        self.assertNotIn("Streamlit_app", sys.modules)


class FalseCompleteTests(unittest.TestCase):
    def test_false_complete_reopened(self) -> None:
        from live_draft_safe_mode import is_draft_truly_complete, reconcile_live_draft_room

        room = {
            "status": "complete",
            "current_pick_index": 6,
            "teams": ["A", "B"],
            "pick_order": [{"Pick": i + 1, "Team": "A" if i % 2 == 0 else "B"} for i in range(6)],
            "draft_board": [{"playerID": f"p{i}"} for i in range(4)],
            "config": {"picks_per_team": 3},
        }
        session: dict = {"live_draft_room": room}
        result = reconcile_live_draft_room(session, room)
        self.assertTrue(result.false_complete_detected)
        self.assertEqual(result.computed_draft_status, "in_progress")
        self.assertFalse(is_draft_truly_complete(result.room))


if __name__ == "__main__":
    unittest.main()
