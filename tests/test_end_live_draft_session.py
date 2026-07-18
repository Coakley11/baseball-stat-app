"""End Live Draft session clears runtime without wiping archives/shared leagues."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_archive_state import DRAFT_ARCHIVE_KEY, list_draft_archives
from live_draft_completion import SESSION_ENDED_NOTICE_KEY, end_live_draft_session
from live_draft_navigation import get_draft_return_context
from live_draft_state import LIVE_DRAFT_ROOM_KEY, LIVE_DRAFT_STATE_KEY, prepare_live_draft_state


class EndLiveDraftSessionTests(unittest.TestCase):
    def test_end_clears_runtime_and_preserves_archives(self) -> None:
        session = {
            LIVE_DRAFT_ROOM_KEY: {
                "status": "complete",
                "draft_room_id": "room-end-1",
                "config": {"league_name": "Fresh 10-Pick Live Test", "user_team": "Team 1"},
                "teams": ["Team 1", "Team 2"],
                "draft_board": [{"Pick": 1, "Team": "Team 1", "Player": "Aaron Judge"}],
                "live_draft_completion_record": {
                    "draft_status": "complete",
                    "final_board_locked": True,
                },
            },
            LIVE_DRAFT_STATE_KEY: {"status": "complete", "draft_room_id": "room-end-1"},
            "active_shared_draft_room_code": "",
            DRAFT_ARCHIVE_KEY: [
                {
                    "draft_id": "archive-keep-1",
                    "draft_name": "Fresh 10-Pick Live Test",
                    "team_name": "Team 1",
                }
            ],
            "league_contexts": {
                "ctx-keep-1": {
                    "league_context_id": "ctx-keep-1",
                    "league_name": "Fresh 10-Pick Live Test",
                    "league_id": "league-keep-1",
                }
            },
        }
        with patch("live_draft_state.commit_live_draft_room", return_value={"saved": True}):
            result = end_live_draft_session(session, st=None, reason="test_end")
        self.assertTrue(result.get("ok"))
        self.assertIsNone(session.get(LIVE_DRAFT_ROOM_KEY))
        self.assertFalse(session.get(LIVE_DRAFT_STATE_KEY))
        self.assertEqual(len(list_draft_archives(session)), 1)
        self.assertIn("ctx-keep-1", session.get("league_contexts") or {})
        notice = session.get(SESSION_ENDED_NOTICE_KEY) or {}
        self.assertIn("Ended the Live Draft session", str(notice.get("message") or ""))
        self.assertFalse(session.get("_start_live_draft_pending"))
        self.assertNotIn("live_draft_my_team", session)
        room = prepare_live_draft_state(session)
        self.assertIsNone(room)
        ctx = get_draft_return_context(session)
        # Temporary last-board snapshot is allowed; Resume Live Draft is not.
        if ctx is not None:
            self.assertEqual(ctx.get("kind"), "last_board_snapshot")
            self.assertTrue(ctx.get("not_a_live_room"))
        self.assertNotEqual(str((ctx or {}).get("title") or ""), "Return to Live Draft")


if __name__ == "__main__":
    unittest.main()
