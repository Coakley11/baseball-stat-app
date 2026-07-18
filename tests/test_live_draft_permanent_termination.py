"""Live Draft permanent End/Delete lifecycle contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_shared_state import LocalFileSharedRoomStore, load_shared_room, reset_shared_room_store_for_tests
from live_draft_completion import (
    LIFECYCLE_ACTIVE_DRAFT,
    LIFECYCLE_SETUP,
    LIFECYCLE_WAITING_SHARED_LOBBY,
    resolve_live_draft_lifecycle,
)
from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    finalize_shared_room_create,
    get_preferred_next_draft_mode,
    set_live_draft_setup_mode,
)
from live_draft_termination import (
    LAST_DRAFT_BOARD_SNAPSHOT_KEY,
    TERMINATION_TOMBSTONES_KEY,
    clear_last_draft_board_snapshot,
    get_last_draft_board_snapshot,
    is_live_draft_permanently_retired,
    permanently_delete_live_draft,
    permanently_end_live_draft,
    repair_corrupted_live_draft_lifecycle,
    reset_context_for_new_live_draft,
)
from suite_auth import AUTH_EXTERNAL_ID_KEY, AUTH_USER_ID_KEY


def _sample_room(*, status: str = "in_progress", picks: int = 3) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Francisco Lindor", "Primary Position": "SS"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Shohei Ohtani", "Primary Position": "DH"},
            {"playerID": "p4", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    board = []
    names = ["Francisco Lindor", "Juan Soto", "Shohei Ohtani"]
    for i in range(min(picks, 3)):
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
        "draft_room_id": "LIFE1",
        "status": status,
        "current_pick_index": picks,
        "config": {
            "num_teams": 2,
            "num_rounds": 4,
            "your_team": "Team A",
            "teams": ["Team A", "Team B"],
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 30,
            "league_name": "Lifecycle Test",
            "total_picks": 8,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Team A" if i % 2 == 0 else "Team B"}
            for i in range(8)
        ],
        "draft_board": board,
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [f"p{i+1}" for i in range(picks)],
        "pool": pool,
    }


def _daniel() -> dict:
    return {
        AUTH_USER_ID_KEY: "uuid-daniel",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
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


class PermanentEndLifecycleTests(unittest.TestCase):
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

    def test_end_partial_shared_closes_for_both_and_preserves_snapshot(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room(picks=3)
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        guest = _coakley()
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)

        result = permanently_end_live_draft(host, st=None, reason="test_end")
        self.assertTrue(result["ok"])
        self.assertIsNone(host.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(host), LIFECYCLE_SETUP)
        self.assertTrue(is_live_draft_permanently_retired(host, room_code=code, draft_id="LIFE1"))
        self.assertIn(TERMINATION_TOMBSTONES_KEY, host)
        snap = get_last_draft_board_snapshot(host)
        self.assertIsNotNone(snap)
        self.assertEqual(int(snap["pick_count"]), 3)
        self.assertTrue(snap.get("not_a_live_room"))
        # Preferred mode remains Shared.
        self.assertEqual(get_preferred_next_draft_mode(host), SETUP_MODE_SHARED)
        # Backend room no longer joinable.
        doc = load_shared_room(code, store=self.store)
        self.assertIn(str(doc.get("status") or "").lower(), {"ended", "closed", "deleted"})
        # Guest cannot restore after tombstone + terminal sync.
        guest["active_shared_draft_room_code"] = code
        from live_draft_termination import handle_shared_document_terminal

        self.assertTrue(handle_shared_document_terminal(guest, doc))
        self.assertIsNone(guest.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(guest), LIFECYCLE_SETUP)

    def test_delete_removes_snapshot(self) -> None:
        host = _daniel()
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room(picks=2)
        code, err = finalize_shared_room_create(host, room, host_team="Team A", store=self.store)
        self.assertFalse(err, err)
        host["live_draft_room"] = room
        permanently_end_live_draft(host, st=None)
        self.assertIsNotNone(get_last_draft_board_snapshot(host))
        # Simulate leftover room pointer then delete.
        host["live_draft_room"] = dict(room)
        host["active_shared_draft_room_code"] = code
        permanently_delete_live_draft(host, st=None)
        self.assertIsNone(get_last_draft_board_snapshot(host))
        self.assertIsNone(host.get("live_draft_room"))
        self.assertTrue(is_live_draft_permanently_retired(host, room_code=code, draft_id="LIFE1"))

    def test_new_draft_resets_to_pick_1(self) -> None:
        host = _daniel()
        host[LAST_DRAFT_BOARD_SNAPSHOT_KEY] = {
            "kind": "last_draft_board_snapshot",
            "not_a_live_room": True,
            "pick_count": 3,
            "total_picks": 8,
            "picks": [{"fullName": "A"}, {"fullName": "B"}, {"fullName": "C"}],
        }
        host["draft_queue"] = ["Juan Soto", "Aaron Judge"]
        host["draft_room_table"] = {"picks": [1, 2, 3]}
        reset_context_for_new_live_draft(host)
        self.assertIsNone(get_last_draft_board_snapshot(host))
        self.assertEqual(host.get("draft_queue") or [], [])

    def test_lifecycle_exclusivity(self) -> None:
        session = _daniel()
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)
        session["live_draft_room"] = _sample_room(status="waiting", picks=0)
        session["active_shared_draft_room_code"] = "ABC123"
        # Without shared mode resolution, waiting + code → lobby or active.
        life = resolve_live_draft_lifecycle(session)
        self.assertIn(life, (LIFECYCLE_WAITING_SHARED_LOBBY, LIFECYCLE_ACTIVE_DRAFT, LIFECYCLE_SETUP))
        permanently_end_live_draft(session, st=None)
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)

    def test_repair_clears_terminal_runtime(self) -> None:
        session = _daniel()
        session["live_draft_room"] = _sample_room(status="ended", picks=2)
        session["active_shared_draft_room_code"] = "DEAD01"
        session["show_live_draft"] = True
        session["draft_started"] = True
        out = repair_corrupted_live_draft_lifecycle(session)
        self.assertTrue(out["ok"])
        self.assertIsNone(session.get("live_draft_room"))
        self.assertNotIn("show_live_draft", session)
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)

    def test_tombstones_survive_session_list_clear(self) -> None:
        session = _daniel()
        session["live_draft_room"] = _sample_room(picks=1)
        session["active_shared_draft_room_code"] = "KEEP99"
        permanently_end_live_draft(session, st=None)
        # Simulate reboot losing legacy lists but keeping durable blob (workspace hydrate).
        session.pop("_live_draft_ended_room_codes", None)
        session.pop("_live_draft_ended_draft_ids", None)
        blob = session.get(TERMINATION_TOMBSTONES_KEY)
        self.assertIsInstance(blob, dict)
        self.assertIn("KEEP99", blob.get("room_codes") or [])
        self.assertTrue(is_live_draft_permanently_retired(session, room_code="KEEP99", draft_id="LIFE1"))


if __name__ == "__main__":
    unittest.main()
