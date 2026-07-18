"""Continue Saved Draft + Replace and Start New Draft consistency."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore
from live_draft_completion import LIFECYCLE_WAITING_SHARED_LOBBY, resolve_live_draft_lifecycle
from live_draft_resumable_slot import (
    continue_saved_draft,
    get_resumable_live_draft_slot,
    replace_resumable_and_arm_start,
)
from live_draft_setup_mode import SETUP_MODE_SHARED, set_live_draft_setup_mode
from shared_room_membership_gate import assert_or_repair_before_shared_render


def _room() -> dict:
    pool = pd.DataFrame(
        [{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}]
    )
    return {
        "draft_room_id": "RPL001",
        "status": "in_progress",
        "current_pick_index": 2,
        "config": {
            "num_teams": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 60,
            "picks_per_team": 4,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
            {"Pick": 3, "Round": 2, "Team": "Team B"},
            {"Pick": 4, "Round": 2, "Team": "Team A"},
        ],
        "draft_board": [
            {"Pick": 1, "Team": "Team A", "Player": "Aaron Judge", "playerID": "p1"},
            {"Pick": 2, "Team": "Team B", "Player": "Other", "playerID": "p2"},
        ],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": ["p1", "p2"],
        "pool": pool,
        "timer_deadline": None,
        "paused": True,
    }


class ResumeReplaceConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmpdir.cleanup()

    def _park_slot(self, session: dict, code: str, room: dict) -> None:
        from live_draft_resumable_slot import RESUMABLE_LIVE_DRAFT_SLOT_KEY
        from live_draft_resume_lobby import stamp_resume_reserved_on_document
        from draft_room_shared_state import bump_revision

        doc = self.store.load(code)
        self.assertIsInstance(doc, dict)
        doc = stamp_resume_reserved_on_document(doc)
        self.store.save(bump_revision(doc))
        session[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = {
            "kind": "resumable_live_draft_slot",
            "draft_id": room["draft_room_id"],
            "room_id": room["draft_room_id"],
            "room_code": code,
            "mode": SETUP_MODE_SHARED,
            "is_shared": True,
            "participant_team": "Team A",
            "participant_id": "daniel",
            "room": dict(room),
            "queues": {"draft_queue": ["Player X"]},
            "summary": {
                "mode_label": "Shared",
                "num_teams": 2,
                "current_pick": 3,
                "total_picks": 4,
            },
            "saved_at": "2026-07-18T00:00:00+00:00",
        }
        # Mimic park: clear active room pointers.
        session.pop("live_draft_room", None)
        session.pop("active_shared_draft_room_code", None)

    def test_continue_saved_opens_resume_lobby_not_wiped_by_gate(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, doc = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self.assertTrue(code)
        self._park_slot(host, code, room)

        result = continue_saved_draft(host)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(host.get("_live_draft_resume_lobby"))
        self.assertEqual(host.get("active_shared_draft_room_code"), code)
        self.assertIsInstance(host.get("live_draft_room"), dict)
        self.assertEqual(int(host["live_draft_room"].get("current_pick_index") or 0), 2)

        may, reason = assert_or_repair_before_shared_render(host)
        self.assertTrue(may, reason)
        self.assertIsInstance(host.get("live_draft_room"), dict)

        life = resolve_live_draft_lifecycle(host, room=host.get("live_draft_room"))
        self.assertEqual(life, LIFECYCLE_WAITING_SHARED_LOBBY)

    def test_replace_tombstones_and_arms_fresh_create(self) -> None:
        host = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "preferred_next_draft_mode": SETUP_MODE_SHARED,
        }
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room()
        code, _ = create_and_host_shared_room(host, room, host_team="Team A", store=self.store)
        self._park_slot(host, code, room)
        self.assertIsNotNone(get_resumable_live_draft_slot(host))

        rep = replace_resumable_and_arm_start(host)
        self.assertTrue(rep.get("ok"), rep)
        self.assertIsNone(get_resumable_live_draft_slot(host))
        new_code = str(rep.get("new_room_code") or "")
        self.assertTrue(new_code)
        self.assertNotEqual(new_code, code)
        self.assertEqual(host.get("active_shared_draft_room_code"), new_code)
        closed = self.store.load(code)
        self.assertEqual(str((closed or {}).get("status") or "").lower(), "deleted")

    def test_queue_revision_blocks_stale_hydrate(self) -> None:
        from draft_room_participant_state import (
            load_participant_workflow_into_session,
            save_participant_workflow_from_session,
        )

        session = {
            "draft_room_participant_id": "daniel",
            "auth_user_id": "daniel",
            "draft_queue": ["A", "B"],
            "_draft_queue_revision": 15,
            "_draft_queue_persist_dirty": True,
        }
        # Seed older remote workflow revision 14 with resurrected player.
        from draft_room_participant_state import participant_workflow_slot

        slot = participant_workflow_slot(session, "ABC123")
        slot["workflow"] = {
            "queue": ["A", "B", "C"],
            "queue_revision": 14,
            "watchlist_focus": [],
            "watchlist_favorites": [],
        }
        load_participant_workflow_into_session(session, "ABC123")
        self.assertEqual(session.get("draft_queue"), ["A", "B"])
        self.assertTrue(session.get("_live_draft_queue_stale_hydrate_blocked"))

        # Save advances remote to 15; hydrate of same dirty still keeps local.
        save_participant_workflow_from_session(session, "ABC123")
        self.assertEqual(
            int((participant_workflow_slot(session, "ABC123").get("workflow") or {}).get("queue_revision") or 0),
            15,
        )


if __name__ == "__main__":
    unittest.main()
