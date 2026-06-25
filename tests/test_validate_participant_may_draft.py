"""validate_participant_may_draft must not import streamlit_app or block stale-complete drafts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_room_membership import validate_participant_may_draft


def _ariel_pick_two_room(*, status: str = "complete") -> dict:
    pick_order = [
        {"Pick": i, "Round": (i - 1) // 2 + 1, "Team": "Daniel" if i % 2 == 1 else "Ariel"}
        for i in range(1, 9)
    ]
    return {
        "status": status,
        "current_pick_index": 1,
        "teams": ["Daniel", "Ariel"],
        "pick_order": pick_order,
        "draft_board": [{"playerID": "p0", "fullName": "Aaron Judge"}],
        "config": {"num_teams": 2},
    }


class ValidateParticipantMayDraftTests(unittest.TestCase):
    def _session(self) -> dict:
        return {
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_team": "Ariel",
            "room_your_team": "Ariel",
        }

    @patch("draft_room_context.is_multiplayer_draft_active", return_value=True)
    @patch("draft_room_context.active_participant_team", return_value="Ariel")
    def test_allows_ariel_on_clock_with_stale_saved_complete(
        self,
        _team: object,
        _mp: object,
    ) -> None:
        session = self._session()
        room = _ariel_pick_two_room(status="complete")
        ok, msg = validate_participant_may_draft(session, room, player_name="Bobby Witt")
        self.assertTrue(ok, msg)
        diag = session.get("_draft_pick_commit_diag") or {}
        self.assertTrue(diag.get("validate_participant_may_draft_result"))
        self.assertEqual(diag.get("validation_participant_team"), "Ariel")
        self.assertEqual(diag.get("validation_on_clock_team"), "Ariel")
        self.assertTrue(diag.get("validation_is_my_turn"))
        self.assertEqual(diag.get("validation_computed_status"), "in_progress")
        self.assertEqual(diag.get("validation_board_size"), 1)
        self.assertEqual(diag.get("validation_total_picks"), 8)

    @patch("draft_room_context.is_multiplayer_draft_active", return_value=True)
    @patch("draft_room_context.active_participant_team", return_value="Ariel")
    @patch("draft_actions._import_baseball_app", side_effect=RuntimeError("streamlit import blocked"))
    def test_does_not_use_streamlit_app_for_slot(
        self,
        _import: object,
        _team: object,
        _mp: object,
    ) -> None:
        session = self._session()
        room = _ariel_pick_two_room(status="in_progress")
        ok, msg = validate_participant_may_draft(session, room)
        self.assertTrue(ok, msg)

    @patch("draft_room_context.is_multiplayer_draft_active", return_value=True)
    @patch("draft_room_context.active_participant_team", return_value="Daniel")
    def test_rejects_wrong_team_with_reason(
        self,
        _team: object,
        _mp: object,
    ) -> None:
        session = self._session()
        room = _ariel_pick_two_room(status="in_progress")
        ok, msg = validate_participant_may_draft(session, room)
        self.assertFalse(ok)
        self.assertIn("Not your pick", msg)
        diag = session.get("_draft_pick_commit_diag") or {}
        self.assertFalse(diag.get("validate_participant_may_draft_result"))
        self.assertEqual(diag.get("validate_participant_may_draft_reason"), msg)


if __name__ == "__main__":
    unittest.main()
