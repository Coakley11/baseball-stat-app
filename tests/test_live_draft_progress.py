"""Tests for live draft progress analysis and stale shared-room repair."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_actions import can_draft_player, draft_action_context
from draft_room_context import create_and_host_shared_room, prepare_global_draft_context
from draft_room_participant_state import ACTIVE_PARTICIPANT_ID_KEY
from draft_room_shared_state import LocalFileSharedRoomStore, publish_shared_room_runtime
from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    analyze_live_draft_progress,
    apply_cloud_live_draft_state_if_allowed,
    repair_stale_live_draft_progress,
)


def _sample_live_room(*, status: str = "in_progress", pick_index: int = 0) -> dict:
    pool = pd.DataFrame(
        [{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": status,
        "current_pick_index": pick_index,
        "config": {"num_teams": 2, "your_team": "Team 1"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class LiveDraftProgressTests(unittest.TestCase):
    def test_not_started_is_not_complete(self) -> None:
        progress = analyze_live_draft_progress(_sample_live_room(status="not_started"))
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(progress["draft_complete_reason"], "not_started")
        self.assertIsNone(progress["current_pick"])
        self.assertIsNone(progress["on_clock_team"])

    def test_repair_stale_complete_status_with_picks_remaining(self) -> None:
        room = _sample_live_room(status="complete", pick_index=99)
        repaired = repair_stale_live_draft_progress(room)
        self.assertIn(repaired["status"], ("in_progress", "not_started"))
        self.assertLess(int(repaired["current_pick_index"]), len(repaired["pick_order"]))

    def test_draft_action_context_not_started_not_marked_complete(self) -> None:
        session = {
            "live_draft_room": _sample_live_room(status="not_started"),
            "active_shared_draft_room_code": "ABC123",
            "draft_room_participant_team": "Team 1",
            "room_your_team": "Team 1",
        }
        try:
            from draft_room_state import set_canonical_draft_meta

            set_canonical_draft_meta(session, mode="live_draft_room", source="test", pick_count=0)
        except ImportError:
            pass
        # not_started lobby is not the effective live source — no Pick 1 / on-clock.
        progress = analyze_live_draft_progress(session["live_draft_room"])
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(progress["draft_complete_reason"], "not_started")
        self.assertIsNone(progress["current_pick"])
        self.assertIsNone(progress["on_clock_team"])
        ctx = draft_action_context(session)
        self.assertNotEqual(ctx.get("active_draft_source"), "live")
        self.assertFalse(bool(ctx.get("live_draft_active")))

    @patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_fresh_shared_room_is_not_complete(self, _mock_auth: object) -> None:
        tmp = tempfile.TemporaryDirectory()
        store = LocalFileSharedRoomStore(root=Path(tmp.name))
        session = {ACTIVE_PARTICIPANT_ID_KEY: "host-user"}
        code, doc = create_and_host_shared_room(session, _sample_live_room(), store=store)
        self.assertTrue(code)
        prepare_global_draft_context(session)
        room = session[LIVE_DRAFT_ROOM_KEY]
        progress = analyze_live_draft_progress(room)
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(int(progress["current_pick_index"]), 0)
        self.assertEqual(progress["total_picks"], 2)
        tmp.cleanup()

    def test_cloud_live_draft_restore_skipped_when_multiplayer_active(self) -> None:
        session = {"active_shared_draft_room_code": "ABC123"}
        cloud = {
            "live_draft_state": {
                "draft_room_id": "STALE",
                "status": "complete",
                "current_pick_index": 99,
                "pick_order": [],
            }
        }
        self.assertFalse(apply_cloud_live_draft_state_if_allowed(session, cloud))

    def test_publish_repairs_stale_complete_document(self) -> None:
        session: dict = {}
        document = {
            "room_code": "ABC123",
            "draft_room_id": "MULTI1",
            "status": "in_progress",
            "revision": 1,
            "room": {
                "draft_room_id": "MULTI1",
                "status": "complete",
                "current_pick_index": 99,
                "teams": ["Team 1", "Team 2"],
                "pick_order": [
                    {"Pick": 1, "Round": 1, "Team": "Team 1"},
                    {"Pick": 2, "Round": 1, "Team": "Team 2"},
                ],
                "draft_board": [],
                "rosters": {"Team 1": [], "Team 2": []},
                "drafted_player_ids": [],
                "pool_records": [],
                "pool_columns": [],
            },
        }
        runtime = publish_shared_room_runtime(session, document, reason="shared_room_create")
        self.assertIsInstance(runtime, dict)
        progress = analyze_live_draft_progress(runtime)
        self.assertFalse(progress["draft_complete"])


if __name__ == "__main__":
    unittest.main()
