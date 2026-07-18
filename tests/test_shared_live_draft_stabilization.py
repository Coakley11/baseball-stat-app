"""Shared Live Draft stabilization: snapshot, queue prune, chat key, single queue."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_actions import _prune_drafted_from_queue, draft_action_context
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue
from live_draft_chat import canonical_chat_scope
from shared_live_draft_snapshot import (
    build_shared_live_draft_snapshot,
    drafted_player_tokens,
    is_player_drafted_in_room,
)


def _shared_room(*, picks: int = 0, status: str = "in_progress") -> dict:
    teams = ["Team A", "Team B"]
    pick_order = []
    for round_n in range(1, 5):
        order = teams if round_n % 2 == 1 else list(reversed(teams))
        for t in order:
            pick_order.append({"Pick": len(pick_order) + 1, "Round": round_n, "Team": t})
    board = []
    players = [
        ("Manny Machado", "machama01"),
        ("Juan Soto", "sotoju01"),
        ("Aaron Judge", "judgeaa01"),
        ("Mookie Betts", "bettsmo01"),
        ("Freddie Freeman", "freemfr01"),
    ]
    for i in range(picks):
        name, pid = players[i]
        board.append(
            {
                "Pick": i + 1,
                "fullName": name,
                "playerID": pid,
                "Fantasy Team": teams[i % 2],
                "Team": teams[i % 2],
            }
        )
    return {
        "draft_room_id": "SNAP1",
        "status": status,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": board,
        "drafted_player_ids": [p[1] for p in players[:picks]],
        "current_pick_index": picks,
        "config": {"timer_seconds": 30, "num_teams": 2, "picks_per_team": 4},
        "timer_deadline": 9_999_999_999.0,
        "timer_started_at": 9_999_999_969.0,
    }


class SharedSnapshotTests(unittest.TestCase):
    def test_snapshot_current_pick_matches_board_length(self) -> None:
        session = {
            "live_draft_room": _shared_room(picks=5),
            "active_shared_draft_room_code": "SNAP01",
            "auth_user_id": "daniel",
        }
        snap = build_shared_live_draft_snapshot(session)
        self.assertEqual(snap["completed_picks"], 5)
        self.assertEqual(snap["current_pick_index"], 5)
        self.assertEqual(snap["current_pick"], 6)
        self.assertEqual(snap["on_clock_team"], "Team B")
        self.assertEqual(snap["chat_room_key"], "SNAP01")
        self.assertGreater(int(snap["seconds_remaining"] or 0), 0)

    def test_draft_action_context_uses_snapshot_pick(self) -> None:
        session = {
            "live_draft_room": _shared_room(picks=5),
            "active_shared_draft_room_code": "SNAP01",
            "auth_user_id": "daniel",
            "draft_room_participant_team": "Team B",
        }
        try:
            from draft_room_state import ACTIVE_DRAFT_SOURCE_LIVE

            source = ACTIVE_DRAFT_SOURCE_LIVE
        except ImportError:
            source = "live"
        with patch("draft_room_state.resolve_active_draft_source", return_value=source):
            ctx = draft_action_context(session)
        self.assertEqual(ctx.get("current_pick"), 6)
        self.assertNotEqual(ctx.get("current_pick"), 1)


class QueueDraftedPruneTests(unittest.TestCase):
    def test_drafted_player_removed_not_labeled(self) -> None:
        session = {
            "live_draft_room": _shared_room(picks=1),
            "active_shared_draft_room_code": "Q1",
            DRAFT_QUEUE_KEY: ["Manny Machado", "Juan Soto"],
        }
        kept = _prune_drafted_from_queue(session)
        self.assertNotIn("Manny Machado", kept)
        self.assertIn("Juan Soto", kept)
        self.assertTrue(is_player_drafted_in_room(session, "Manny Machado"))
        self.assertTrue(is_player_drafted_in_room(session, "machama01"))
        self.assertFalse(is_player_drafted_in_room(session, "Juan Soto"))

    def test_team_b_pick_clears_team_a_queue(self) -> None:
        session = {
            "live_draft_room": _shared_room(picks=0),
            "active_shared_draft_room_code": "Q2",
            DRAFT_QUEUE_KEY: ["Juan Soto", "Aaron Judge"],
        }
        # Team B drafts Juan Soto
        room = session["live_draft_room"]
        room["draft_board"] = [
            {
                "Pick": 1,
                "fullName": "Juan Soto",
                "playerID": "sotoju01",
                "Fantasy Team": "Team B",
                "Team": "Team B",
            }
        ]
        room["drafted_player_ids"] = ["sotoju01"]
        room["current_pick_index"] = 1
        kept = _prune_drafted_from_queue(session)
        self.assertNotIn("Juan Soto", kept)
        self.assertIn("Aaron Judge", kept)
        tokens = drafted_player_tokens(session)
        self.assertIn("juan soto", tokens)


class ChatScopeTests(unittest.TestCase):
    def test_chat_scope_is_room_code_only(self) -> None:
        session = {
            "active_shared_draft_room_code": "CHAT99",
            "shared_league_id": "league-should-not-matter",
            "live_draft_room": {"draft_room_id": "different-id"},
        }
        self.assertEqual(canonical_chat_scope(session), "room:CHAT99")


class SidebarQueueGateTests(unittest.TestCase):
    def test_live_draft_page_skips_duplicate_sidebar_queue(self) -> None:
        # Mirrors the gate in streamlit_app.render_persistent_workflow_sidebar
        page = "Live Draft Room"
        live = {"status": "in_progress", "draft_room_id": "X"}
        skip = page == "Live Draft Room" and str(live.get("status") or "") in (
            "in_progress",
            "paused",
            "waiting",
            "not_started",
            "ready",
        )
        self.assertTrue(skip)


if __name__ == "__main__":
    unittest.main()
