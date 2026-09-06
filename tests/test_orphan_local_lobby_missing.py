"""Orphan not_started local lobby must clear when the shared file is missing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LocalFileSharedRoomStore,
    reset_shared_room_store_for_tests,
)
from shared_room_membership_gate import assert_or_repair_before_shared_render, repair_stale_shared_room_session


class OrphanLocalLobbyMissingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_shared_state.get_local_shared_room_store", return_value=self.store),
            mock.patch("draft_room_shared_state.shared_room_backend_name", return_value="local_file"),
            mock.patch(
                "shared_room_membership_gate.load_authoritative_shared_document",
                return_value=None,
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_not_started_orphan_lobby_clears(self) -> None:
        session = {
            "auth_user_id": "daniel",
            "draft_room_participant_id": "daniel",
            ACTIVE_SHARED_ROOM_CODE_KEY: "DNIEWF",
            "draft_room_participant_team": "Team A",
            "live_draft_room": {
                "draft_room_id": "PREDRAFT1",
                "status": "not_started",
                "current_pick_index": 0,
            },
        }
        ok, reason = assert_or_repair_before_shared_render(session)
        self.assertFalse(ok)
        self.assertEqual(reason, "orphan_local_lobby_missing")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)
        self.assertFalse(isinstance(session.get("live_draft_room"), dict))

    def test_in_progress_soft_miss_still_kept(self) -> None:
        session = {
            "auth_user_id": "daniel",
            "draft_room_participant_id": "daniel",
            ACTIVE_SHARED_ROOM_CODE_KEY: "LIVE99",
            "draft_room_participant_team": "Team A",
            "live_draft_room": {
                "draft_room_id": "DRLIVE",
                "status": "in_progress",
                "current_pick_index": 1,
            },
        }
        ok, reason = assert_or_repair_before_shared_render(session)
        self.assertTrue(ok, reason)
        self.assertIn("soft_miss", reason)
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "LIVE99")

    def test_repair_stale_clears_orphan_not_started(self) -> None:
        session = {
            "auth_user_id": "daniel",
            "draft_room_participant_id": "daniel",
            ACTIVE_SHARED_ROOM_CODE_KEY: "GONE01",
            "draft_room_participant_team": "Team A",
            "live_draft_room": {"draft_room_id": "X", "status": "not_started"},
        }
        diag = repair_stale_shared_room_session(session)
        self.assertTrue(diag.get("repaired"))
        self.assertEqual(diag.get("prior_room_code"), "GONE01")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)

    def test_orphan_clear_removes_page_filter_and_membership_maps(self) -> None:
        """Nested page_filter live_draft_room must not rehydrate an orphan lobby."""
        from live_draft_state import LIVE_DRAFT_PAGE_BLOCK, LIVE_DRAFT_ROOM_KEY, prepare_live_draft_state

        session = {
            "auth_user_id": "guest",
            "draft_room_participant_id": "workspace:guest",
            ACTIVE_SHARED_ROOM_CODE_KEY: "2PMUNM",
            "draft_room_participant_team": "Team A",
            "draft_room_participant_membership": {
                "2PMUNM": {"workspace:guest": {"participant_id": "workspace:guest", "assigned_team": "Team A"}}
            },
            "draft_room_participant_state": {"2PMUNM": {"joined_at": "2026-09-06T02:20:17+00:00"}},
            "page_filter_state": {
                LIVE_DRAFT_PAGE_BLOCK: {
                    LIVE_DRAFT_ROOM_KEY: {
                        "draft_room_id": "JOIN01",
                        "status": "not_started",
                        "current_pick_index": 0,
                        "config": {"share_code": "2PMUNM", "room_code": "2PMUNM"},
                    }
                }
            },
            "live_draft_room": {
                "draft_room_id": "JOIN01",
                "status": "not_started",
                "current_pick_index": 0,
                "config": {"share_code": "2PMUNM", "room_code": "2PMUNM"},
            },
        }
        ok, reason = assert_or_repair_before_shared_render(session)
        self.assertFalse(ok)
        self.assertEqual(reason, "orphan_local_lobby_missing")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)
        self.assertNotIn("draft_room_participant_membership", session)
        pf = session.get("page_filter_state") or {}
        block = pf.get(LIVE_DRAFT_PAGE_BLOCK) or {}
        self.assertNotIn(LIVE_DRAFT_ROOM_KEY, block)
        # Prepare must not resurrect the orphan from page_filter.
        prepared = prepare_live_draft_state(session)
        self.assertFalse(isinstance(prepared, dict) and prepared.get("draft_room_id") == "JOIN01")
        self.assertNotIn(ACTIVE_SHARED_ROOM_CODE_KEY, session)


if __name__ == "__main__":
    unittest.main()
