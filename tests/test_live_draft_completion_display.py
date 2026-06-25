"""Live draft completion must derive from board size only — never stale saved status."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_ui import render_live_manual_draft_panel
from live_draft_safe_mode import is_draft_truly_complete, live_draft_is_in_progress
from live_draft_state import analyze_live_draft_progress


def _room_at_pick_two(*, status: str = "complete") -> dict:
    pool = pd.DataFrame([{"playerID": "p1", "fullName": "Juan Soto", "Expected Fantasy Value": 1.0}])
    pick_order = [
        {"Pick": i, "Round": (i - 1) // 2 + 1, "Team": f"Team {((i - 1) % 2) + 1}"}
        for i in range(1, 9)
    ]
    return {
        "status": status,
        "current_pick_index": 1,
        "config": {"your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": pick_order,
        "draft_board": [{"playerID": "p0", "fullName": "Aaron Judge"}],
        "pool": pool,
    }


class LiveDraftDerivedCompletionTests(unittest.TestCase):
    def test_pick_two_with_stale_complete_status_is_not_complete(self) -> None:
        room = _room_at_pick_two(status="complete")
        self.assertFalse(is_draft_truly_complete(room))
        self.assertTrue(live_draft_is_in_progress(room))
        progress = analyze_live_draft_progress(room)
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(progress["draft_status"], "in_progress")

    @patch("draft_ui.can_draft_player", return_value=(True, ""))
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=True)
    @patch("draft_actions.draft_action_context")
    @patch("live_draft_state.live_draft_get_available")
    def test_manual_panel_does_not_show_complete_at_pick_two(
        self,
        mock_get_available: MagicMock,
        mock_ctx: MagicMock,
        _free: MagicMock,
        _can: MagicMock,
    ) -> None:
        room = _room_at_pick_two(status="complete")
        mock_get_available.return_value = room["pool"]
        mock_ctx.return_value = {
            "draft_status": "in_progress",
            "is_your_pick": True,
            "your_team": "Team 1",
            "on_clock_team": "Team 1",
            "current_pick": 2,
            "draft_complete": False,
        }
        st = MagicMock()
        session: dict = {"room_your_team": "Team 1", "draft_queue": []}
        render_live_manual_draft_panel(st, session, room, multiplayer=False)
        for call in st.info.call_args_list:
            self.assertNotIn("Draft is complete.", str(call))
        st.button.assert_called()


if __name__ == "__main__":
    unittest.main()
