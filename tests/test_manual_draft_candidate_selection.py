"""Manual draft candidate selection must match visible dropdown value."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_ui import (
    PENDING_MANUAL_PICK_KEY,
    manual_draft_candidate_widget_key,
    queue_manual_draft_pick,
)


class ManualDraftCandidateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = {
            "current_pick_index": 1,
            "draft_board": [{"fullName": "Aaron Judge"}],
            "pick_order": [{"Pick": i} for i in range(1, 9)],
            "pool": pd.DataFrame(
                [
                    {"playerID": "judgeaa01", "fullName": "Aaron Judge"},
                    {"playerID": "wittbo02", "fullName": "Bobby Witt"},
                ]
            ),
        }
        self.session: dict = {"live_draft_room": self.room}

    def test_widget_key_scoped_to_pick_index(self) -> None:
        self.assertEqual(manual_draft_candidate_widget_key(self.room), "live_draft_manual_candidate_i1")
        self.room["current_pick_index"] = 2
        self.assertEqual(manual_draft_candidate_widget_key(self.room), "live_draft_manual_candidate_i2")

    def test_queue_reads_widget_key_not_legacy_snapshot(self) -> None:
        wkey = manual_draft_candidate_widget_key(self.room)
        self.session[wkey] = "Bobby Witt"
        self.session["_live_draft_manual_candidate_snapshot"] = {
            "name": "Aaron Judge",
            "id": "judgeaa01",
            "widget_key": wkey,
        }
        ok = queue_manual_draft_pick(self.session, widget_key=wkey, pool_source="free_pool")
        self.assertTrue(ok)
        pending = self.session[PENDING_MANUAL_PICK_KEY]
        self.assertEqual(pending["player_name"], "Bobby Witt")
        self.assertEqual(pending["selected_player_id"], "wittbo02")
        diag = self.session.get("_draft_pick_commit_diag") or {}
        self.assertEqual(diag.get("queued_manual_pick_player_name"), "Bobby Witt")
        self.assertEqual(diag.get("queued_manual_pick_player_id"), "wittbo02")
        self.assertTrue(diag.get("queue_manual_draft_pick_entered"))

    def test_queue_empty_selection_sets_error(self) -> None:
        wkey = manual_draft_candidate_widget_key(self.room)
        ok = queue_manual_draft_pick(self.session, widget_key=wkey)
        self.assertFalse(ok)
        self.assertNotIn(PENDING_MANUAL_PICK_KEY, self.session)
        self.assertIn("Select a player first", str(self.session.get("_live_draft_pick_flash_error") or ""))


class ManualDraftPanelVisibleCandidateTests(unittest.TestCase):
    @patch("draft_ui.can_draft_player", return_value=(True, ""))
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=True)
    @patch("draft_actions.draft_action_context")
    @patch("live_draft_state.live_draft_get_available")
    def test_panel_records_visible_candidate_from_selectbox_return(
        self,
        mock_get_available: MagicMock,
        mock_ctx: MagicMock,
        _free: MagicMock,
        _can: MagicMock,
    ) -> None:
        from draft_ui import render_live_manual_draft_panel

        pool = pd.DataFrame(
            [
                {"playerID": "judgeaa01", "fullName": "Aaron Judge", "Expected Fantasy Value": 2.0},
                {"playerID": "wittbo02", "fullName": "Bobby Witt", "Expected Fantasy Value": 1.0},
            ]
        )
        room = {
            "status": "in_progress",
            "current_pick_index": 1,
            "config": {"your_team": "Team 1"},
            "teams": ["Team 1", "Team 2"],
            "pick_order": [{"Pick": 1, "Team": "Team 1"}, {"Pick": 2, "Team": "Team 1"}],
            "draft_board": [{"fullName": "X"}],
            "pool": pool,
        }
        mock_get_available.return_value = pool
        mock_ctx.return_value = {
            "draft_status": "in_progress",
            "is_your_pick": True,
            "your_team": "Team 1",
            "on_clock_team": "Team 1",
            "current_pick": 2,
            "draft_complete": False,
        }
        st = MagicMock()
        st.selectbox.return_value = "Bobby Witt"
        session: dict = {"room_your_team": "Team 1", "draft_queue": []}
        wkey = manual_draft_candidate_widget_key(room)
        session[wkey] = "Bobby Witt"
        render_live_manual_draft_panel(st, session, room, multiplayer=False)
        diag = session.get("_live_draft_ui_diag") or {}
        self.assertEqual(diag.get("visible_draft_candidate_name"), "Bobby Witt")
        self.assertEqual(diag.get("visible_draft_candidate_id"), "wittbo02")
        self.assertEqual(diag.get("draft_candidate_widget_key"), wkey)
        commit_diag = session.get("_draft_pick_commit_diag") or {}
        self.assertEqual(commit_diag.get("visible_draft_candidate_name"), "Bobby Witt")


if __name__ == "__main__":
    unittest.main()
