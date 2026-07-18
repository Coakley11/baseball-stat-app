"""Save & Continue Later vs End/Delete — single resumable slot."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore, load_shared_room, reset_shared_room_store_for_tests
from live_draft_completion import LIFECYCLE_SETUP, resolve_live_draft_lifecycle
from live_draft_resumable_slot import (
    RESUMABLE_LIVE_DRAFT_SLOT_KEY,
    continue_saved_draft,
    get_resumable_live_draft_slot,
    save_and_continue_later,
    warn_if_starting_replaces_resumable,
)
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    finalize_shared_room_create,
    set_live_draft_setup_mode,
)
from live_draft_termination import discard_live_draft_and_start_over, is_live_draft_permanently_retired
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _room(*, picks: int = 3, status: str = "in_progress") -> dict:
    board = []
    names = ["Francisco Lindor", "Juan Soto", "Shohei Ohtani"]
    for i in range(picks):
        board.append(
            {
                "Pick": i + 1,
                "Round": 1,
                "Team": "Team A" if i % 2 == 0 else "Team B",
                "fullName": names[i],
                "playerID": f"p{i+1}",
            }
        )
    return {
        "draft_room_id": "SAVE1",
        "status": status,
        "current_pick_index": picks,
        "timer_deadline": None,
        "paused_remaining_seconds": 45,
        "config": {
            "num_teams": 2,
            "num_rounds": 10,
            "your_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 60,
            "league_name": "Save Continue Test",
            "total_picks": 20,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Team A" if i % 2 == 0 else "Team B"}
            for i in range(20)
        ],
        "draft_board": board,
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [f"p{i+1}" for i in range(picks)],
        "pool": pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": f"Player {i}", "Primary Position": "OF"} for i in range(1, 6)]
        ),
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
        "draft_queue": ["Aaron Judge", "Mookie Betts"],
    }


def _coakley() -> dict:
    return {
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
    }


class SaveContinueLaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def test_save_continue_preserves_picks_and_pauses(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room(picks=3, status="in_progress")
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        host["draft_queue"] = ["Aaron Judge", "Mookie Betts"]

        result = save_and_continue_later(host, st=None, replace_existing=True)
        self.assertTrue(result["ok"], result)
        self.assertIsNone(host.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(host), LIFECYCLE_SETUP)
        slot = get_resumable_live_draft_slot(host)
        self.assertIsNotNone(slot)
        self.assertEqual(int(slot["summary"]["current_pick"]), 4)
        self.assertEqual(int(slot["summary"]["total_picks"]), 20)
        self.assertEqual(slot["room"]["status"], "saved_for_later")
        self.assertEqual(len(slot["room"]["draft_board"]), 3)
        self.assertEqual(slot["queues"]["draft_queue"], ["Aaron Judge", "Mookie Betts"])
        doc = load_shared_room(code, store=self.store)
        self.assertEqual(str(doc.get("status") or "").lower(), "saved_for_later")

    def test_continue_restores_exact_pick(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room(picks=3)
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        save_and_continue_later(host, st=None, replace_existing=True)
        self.assertIsNone(host.get("live_draft_room"))

        guest = _coakley()
        # Guest gets the same slot via shared room continue (simulate slot copy + code).
        guest[RESUMABLE_LIVE_DRAFT_SLOT_KEY] = dict(host[RESUMABLE_LIVE_DRAFT_SLOT_KEY])
        result = continue_saved_draft(guest, st=None)
        self.assertTrue(result["ok"], result)
        restored = guest.get("live_draft_room")
        self.assertIsInstance(restored, dict)
        self.assertEqual(int(restored.get("current_pick_index") or 0), 3)
        self.assertEqual(len(restored.get("draft_board") or []), 3)
        self.assertEqual(str(restored.get("status") or ""), "paused")
        self.assertEqual(str(guest.get("active_shared_draft_room_code") or "").upper(), code)

    def test_only_one_slot_replace_requires_confirm(self) -> None:
        host = _daniel()
        host["live_draft_room"] = _room(picks=1)
        host["live_draft_room"]["draft_room_id"] = "A"
        first = save_and_continue_later(host, st=None, replace_existing=True)
        self.assertTrue(first["ok"])
        host["live_draft_room"] = _room(picks=2)
        host["live_draft_room"]["draft_room_id"] = "B"
        blocked = save_and_continue_later(host, st=None, replace_existing=False)
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked.get("needs_replace_confirm"))
        self.assertEqual(get_resumable_live_draft_slot(host)["draft_id"], "A")
        replaced = save_and_continue_later(host, st=None, replace_existing=True)
        self.assertTrue(replaced["ok"])
        self.assertEqual(get_resumable_live_draft_slot(host)["draft_id"], "B")

    def test_discard_clears_slot_and_invalidates_room(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _room(picks=2)
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        save_and_continue_later(host, st=None, replace_existing=True)
        self.assertIsNotNone(get_resumable_live_draft_slot(host))
        # Resume then discard.
        continue_saved_draft(host, st=None)
        discard_live_draft_and_start_over(host, st=None)
        self.assertIsNone(get_resumable_live_draft_slot(host))
        self.assertIsNone(host.get("live_draft_room"))
        self.assertTrue(is_live_draft_permanently_retired(host, room_code=code, draft_id="SAVE1"))
        self.assertEqual(resolve_live_draft_lifecycle(host), LIFECYCLE_SETUP)
        doc = load_shared_room(code, store=self.store)
        self.assertIn(str(doc.get("status") or "").lower(), {"deleted", "ended", "closed"})
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertFalse(ok)
        self.assertIn("ended", msg.lower())

    def test_warn_when_starting_with_slot(self) -> None:
        host = _daniel()
        host["live_draft_room"] = _room(picks=1)
        save_and_continue_later(host, st=None, replace_existing=True)
        warn = warn_if_starting_replaces_resumable(host)
        self.assertIsNotNone(warn)
        self.assertIn("resumable draft", warn["message"].lower())


if __name__ == "__main__":
    unittest.main()
