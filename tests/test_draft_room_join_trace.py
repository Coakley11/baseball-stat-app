"""Tests for shared draft room join tracing and live draft hydration guards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, prepare_global_draft_context
from draft_room_join_trace import JOIN_TRACE_KEY, trace_join_step
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore
from live_draft_state import LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [{"Pick": 1, "Round": 1, "Team": "Team 1", "Player": ""}],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class DraftRoomJoinTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host_session = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        self.guest_session = {ACTIVE_PARTICIPANT_ID_KEY: "guest-user"}

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_join_records_trace_and_activates_multiplayer(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        ok, msg, _ = join_shared_draft_room(self.guest_session, code, store=self.store)
        self.assertTrue(ok, msg)
        trace = self.guest_session.get(JOIN_TRACE_KEY)
        self.assertIsInstance(trace, list)
        steps = [row.get("step") for row in trace if isinstance(row, dict)]
        self.assertIn("join_called", steps)
        self.assertIn("join_success", steps)

        prepare_global_draft_context(self.guest_session)
        self.assertEqual(self.guest_session.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(self.guest_session.get("draft_room_participant_team"), "Team 2")
        self.assertIsInstance(self.guest_session.get(LIVE_DRAFT_ROOM_KEY), dict)

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_prepare_live_draft_state_preserves_shared_room(self, _mock_auth: object) -> None:
        code, _ = create_and_host_shared_room(self.host_session, _sample_live_room(), store=self.store)
        join_shared_draft_room(self.guest_session, code, store=self.store)
        prepare_global_draft_context(self.guest_session)
        shared_room = self.guest_session[LIVE_DRAFT_ROOM_KEY]
        shared_room["current_pick_index"] = 99
        self.guest_session["live_draft_state"] = {
            "draft_room_id": "LOCAL-STALE",
            "status": "in_progress",
            "draft_board": [],
        }
        restored = prepare_live_draft_state(self.guest_session)
        self.assertEqual(int(restored.get("current_pick_index") or 0), 99)

    def test_trace_join_step_appends(self) -> None:
        session: dict = {}
        trace_join_step(session, "join_button_clicked", room_code_entered="ABC123")
        trace = session.get(JOIN_TRACE_KEY)
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["step"], "join_button_clicked")
        self.assertEqual(trace[0]["room_code_entered"], "ABC123")


    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    def test_auth_diagnostics_when_not_signed_in(self, _mock_auth: object) -> None:
        from draft_room_join_trace import get_shared_room_auth_diagnostics

        diag = get_shared_room_auth_diagnostics({})
        self.assertTrue(diag["shared_room_requires_auth"])
        self.assertFalse(diag["join_would_pass"])
        self.assertIn("log in", str(diag["join_block_reason"]).lower())

    @patch("draft_room_membership.shared_room_requires_auth", return_value=True)
    @patch("draft_room_membership.is_auth_session", return_value=True)
    @patch("draft_room_membership.auth_user_id", return_value="uuid-guest-1")
    def test_auth_diagnostics_when_signed_in(self, _uid: object, _sess: object, _req: object) -> None:
        from draft_room_join_trace import get_shared_room_auth_diagnostics

        diag = get_shared_room_auth_diagnostics({"_suite_auth_session": True, "_suite_auth_user_id": "uuid-guest-1"})
        self.assertTrue(diag["join_would_pass"])
        self.assertEqual(diag["auth_user_id"], "uuid-guest-1")


if __name__ == "__main__":
    unittest.main()
