"""Pending manual pick queue — survives rerun before commit."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from draft_ui import (
    MANUAL_PICK_SELECTBOX_KEY,
    PENDING_MANUAL_PICK_KEY,
    process_pending_manual_draft_pick,
    queue_manual_draft_pick,
)


class PendingManualDraftPickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session: dict = {
            MANUAL_PICK_SELECTBOX_KEY: "Aaron Judge",
            "live_draft_room": {
                "status": "in_progress",
                "draft_board": [],
                "current_pick_index": 0,
                "pick_order": [{"team": "Team A"}, {"team": "Team B"}],
                "teams": ["Team A", "Team B"],
                "config": {"your_team": "Team A"},
            },
        }
        self.st = MagicMock()

    @patch("draft_actions._live_player_available", return_value=(True, ""))
    @patch("live_draft_state.live_draft_get_available", return_value=None)
    def test_queue_sets_pending_and_diagnostics(self, _avail: MagicMock, _live: MagicMock) -> None:
        queue_manual_draft_pick(self.session, pool_source="free_pool", candidate_source="test")
        pending = self.session.get(PENDING_MANUAL_PICK_KEY)
        self.assertIsInstance(pending, dict)
        self.assertEqual(pending.get("player_name"), "Aaron Judge")
        diag = self.session.get("_draft_pick_commit_diag") or {}
        self.assertTrue(diag.get("draft_button_clicked"))

    @patch("draft_ui.draft_player", return_value={"ok": True, "message": "Drafted Aaron Judge."})
    def test_process_pending_commits_before_restore(self, mock_draft: MagicMock) -> None:
        self.session[PENDING_MANUAL_PICK_KEY] = {
            "player_name": "Aaron Judge",
            "pool_source": "free_pool",
            "candidate_source": "test",
            "player_still_available_at_click": True,
        }
        result = process_pending_manual_draft_pick(self.st, self.session)
        self.assertTrue(result.get("processed"))
        self.assertTrue(result.get("ok"))
        mock_draft.assert_called_once()
        self.assertNotIn(PENDING_MANUAL_PICK_KEY, self.session)
        self.assertNotIn("_live_draft_manual_pick_in_flight", self.session)

    def test_process_pending_noop_when_empty(self) -> None:
        result = process_pending_manual_draft_pick(self.st, self.session)
        self.assertFalse(result.get("processed"))


if __name__ == "__main__":
    unittest.main()
