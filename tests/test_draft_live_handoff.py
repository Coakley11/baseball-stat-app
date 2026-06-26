"""Tests for Live Draft Room → canonical board → Draft Assistant handoff."""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import pandas as pd

from draft_room_state import (
    ACTIVE_DRAFT_MODE_LIVE,
    CANONICAL_DRAFT_META_KEY,
    DRAFT_ROOM_TABLE_KEY,
    draft_handoff_diagnostics,
    ensure_live_draft_synced_to_canonical_board,
    get_canonical_draft_board,
    live_draft_handoff_pick_count,
    should_resolve_live_draft_source,
    sync_live_draft_room_to_canonical_board,
    table_pick_count,
)
from live_draft_navigation import BROWSING_AWAY_KEY, FORCE_SYNC_ON_RETURN_KEY, on_browse_other_pages
from live_draft_state import LIVE_DRAFT_ROOM_KEY


def _live_room(*, status: str = "in_progress", picks: int = 2) -> dict:
    teams = ["Team A", "Team B"]
    pick_order = [
        {"Round": 1, "Pick": 1, "Team": "Team A"},
        {"Round": 1, "Pick": 2, "Team": "Team B"},
        {"Round": 2, "Pick": 3, "Team": "Team B"},
        {"Round": 2, "Pick": 4, "Team": "Team A"},
    ]
    draft_board = []
    names = ["Aaron Judge", "Bobby Witt Jr.", "Mike Trout", "Mookie Betts"]
    for i in range(picks):
        slot = pick_order[i]
        draft_board.append(
            {
                "Pick": slot["Pick"],
                "fullName": names[i],
                "Fantasy Team": slot["Team"],
            }
        )
    return {
        "status": status,
        "teams": teams,
        "config": {"picks_per_team": 2, "your_team": "Team A"},
        "pick_order": pick_order,
        "draft_board": draft_board,
    }


class TestDraftLiveHandoff(unittest.TestCase):
    def test_live_draft_handoff_pick_count(self) -> None:
        room = _live_room(picks=2)
        self.assertEqual(live_draft_handoff_pick_count(room), 2)
        self.assertEqual(live_draft_handoff_pick_count({}), 0)

    def test_pick_commit_sync_updates_canonical_board(self) -> None:
        session: dict = {DRAFT_ROOM_TABLE_KEY: pd.DataFrame()}
        room = _live_room(picks=2)
        out = sync_live_draft_room_to_canonical_board(session, room)
        self.assertEqual(table_pick_count(out), 2)
        meta = session.get(CANONICAL_DRAFT_META_KEY) or {}
        self.assertEqual(meta.get("active_mode"), ACTIVE_DRAFT_MODE_LIVE)

    def test_get_canonical_syncs_from_live_room_without_prior_board(self) -> None:
        session: dict = {LIVE_DRAFT_ROOM_KEY: _live_room(picks=3)}
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 3)
        self.assertIn("Aaron Judge", board["Player"].astype(str).tolist())

    def test_completed_live_draft_populates_assistant_context(self) -> None:
        session: dict = {
            LIVE_DRAFT_ROOM_KEY: _live_room(status="complete", picks=4),
            "room_your_team": "Team A",
        }
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 4)
        roster = board[board["Team"].astype(str) == "Team A"]["Player"].astype(str).tolist()
        self.assertIn("Aaron Judge", roster)
        self.assertIn("Mookie Betts", roster)

    def test_should_resolve_live_source_for_completed_draft_with_picks(self) -> None:
        session: dict = {LIVE_DRAFT_ROOM_KEY: _live_room(status="complete", picks=4)}
        self.assertTrue(should_resolve_live_draft_source(session))

    def test_ensure_sync_diagnostics(self) -> None:
        session: dict = {LIVE_DRAFT_ROOM_KEY: _live_room(picks=2)}
        diag = ensure_live_draft_synced_to_canonical_board(session, reason="test")
        self.assertTrue(diag.get("ok"))
        self.assertEqual(diag.get("live_draft_pick_count"), 2)
        self.assertEqual(diag.get("canonical_pick_count_after"), 2)
        self.assertEqual(diag.get("assistant_roster_source"), "live_draft_room")

    def test_draft_handoff_diagnostics_after_sync(self) -> None:
        session: dict = {
            LIVE_DRAFT_ROOM_KEY: _live_room(picks=2),
            "room_your_team": "Team A",
        }
        get_canonical_draft_board(session)
        diag = draft_handoff_diagnostics(session)
        self.assertTrue(diag.get("live_draft_room_exists"))
        self.assertEqual(diag.get("live_draft_pick_count"), 2)
        self.assertGreaterEqual(diag.get("canonical_draft_board_pick_count", 0), 2)
        self.assertEqual(diag.get("draft_assistant_roster_count"), 1)

    def test_leave_browse_does_not_clear_live_room(self) -> None:
        room = _live_room(picks=2)
        session: dict = {LIVE_DRAFT_ROOM_KEY: copy.deepcopy(room), "active_page": "Live Draft Room"}
        on_browse_other_pages(session, target_page="Draft Assistant Simulator")
        self.assertTrue(session.get(BROWSING_AWAY_KEY))
        self.assertEqual(live_draft_handoff_pick_count(session.get(LIVE_DRAFT_ROOM_KEY)), 2)

    def test_refresh_style_empty_board_still_syncs_from_live(self) -> None:
        """Fresh session with only persisted live room — canonical board should hydrate."""
        session: dict = {LIVE_DRAFT_ROOM_KEY: _live_room(status="complete", picks=4)}
        self.assertEqual(table_pick_count(session.get(DRAFT_ROOM_TABLE_KEY)), 0)
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 4)

    def test_no_live_draft_leaves_empty_default(self) -> None:
        session: dict = {}
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 0)
        diag = draft_handoff_diagnostics(session)
        self.assertFalse(diag.get("live_draft_room_exists"))
        self.assertEqual(diag.get("assistant_roster_source"), "empty")

    def test_shared_poll_sync_updates_canonical_board(self) -> None:
        session: dict = {LIVE_DRAFT_ROOM_KEY: _live_room(picks=1)}
        room_after_poll = _live_room(picks=2)
        with mock.patch("draft_room_context.is_multiplayer_draft_active", return_value=True):
            with mock.patch("draft_room_context.poll_shared_draft_room") as poll:
                def _apply_poll(sess: dict) -> None:
                    sess[LIVE_DRAFT_ROOM_KEY] = copy.deepcopy(room_after_poll)

                poll.side_effect = _apply_poll
                from live_draft_navigation import apply_force_sync_on_return

                session[FORCE_SYNC_ON_RETURN_KEY] = True
                apply_force_sync_on_return(session)
        board = get_canonical_draft_board(session)
        self.assertEqual(table_pick_count(board), 2)


if __name__ == "__main__":
    unittest.main()
