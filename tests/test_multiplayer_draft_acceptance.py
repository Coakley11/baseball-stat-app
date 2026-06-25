"""End-to-end acceptance tests for multiplayer draft room reliability."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from draft_actions import draft_player
from draft_room_context import (
    commit_shared_room_state,
    create_and_host_shared_room,
    join_shared_draft_room,
    prepare_global_draft_context,
)
from draft_room_diagnostics import get_shared_room_diagnostics
from draft_room_membership import (
    ERR_HOST_ONLY_RESET,
    close_shared_draft_room,
    reset_live_draft_with_membership_guard,
)
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    ACTIVE_PARTICIPANT_TEAM_KEY,
    restore_persisted_shared_room_membership,
)
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore, bump_revision
from draft_source_validation import ALLOW_FREE_POOL_KEY, allowed_draft_player_names
from live_draft_state import LIVE_DRAFT_ROOM_KEY
from suite_auth import AUTH_USER_ID_KEY


def _import_live_helpers():
    try:
        from streamlit_app import live_draft_get_available, live_draft_make_pick
    except ImportError:
        from Streamlit_app import live_draft_get_available, live_draft_make_pick  # type: ignore[no-redef]
    return live_draft_get_available, live_draft_make_pick


def _sample_live_room() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    return {
        "draft_room_id": "MULTI1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", ALLOW_FREE_POOL_KEY: True},
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


class MultiplayerDraftAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host_session: dict = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-host-uuid",
            AUTH_USER_ID_KEY: "auth-host-uuid",
            ALLOW_FREE_POOL_KEY: True,
            "draft_queue": ["Aaron Judge", "Juan Soto"],
        }
        self.guest_session: dict = {
            ACTIVE_PARTICIPANT_ID_KEY: "auth-guest-uuid",
            AUTH_USER_ID_KEY: "auth-guest-uuid",
        }
        self._store_patch = patch(
            "draft_room_shared_state.get_shared_room_store",
            return_value=self.store,
        )
        self._backend_patch = patch(
            "draft_room_shared_state.shared_room_backend_name",
            return_value="local",
        )
        self._auth_patch = patch(
            "draft_room_membership.shared_room_requires_auth",
            return_value=False,
        )
        self._store_patch.start()
        self._backend_patch.start()
        self._auth_patch.start()

    def tearDown(self) -> None:
        self._auth_patch.stop()
        self._backend_patch.stop()
        self._store_patch.stop()
        self._tmpdir.cleanup()

    def _bootstrap_host_room(self) -> str:
        code, _ = create_and_host_shared_room(
            self.host_session,
            _sample_live_room(),
            store=self.store,
        )
        self.host_session[ALLOW_FREE_POOL_KEY] = True
        room = self.host_session[LIVE_DRAFT_ROOM_KEY]
        if isinstance(room, dict):
            cfg = dict(room.get("config") or {})
            cfg[ALLOW_FREE_POOL_KEY] = True
            cfg["your_team"] = "Team 1"
            room["config"] = cfg
        prepare_global_draft_context(self.host_session)
        return code

    def test_diagnostics_snapshot(self) -> None:
        code = self._bootstrap_host_room()
        diag = get_shared_room_diagnostics(self.host_session)
        self.assertTrue(diag["active"])
        self.assertEqual(diag["room_code"], code)
        self.assertEqual(diag["assigned_team"], "Team 1")
        self.assertEqual(diag["participant_id"], "auth-host-uuid")
        self.assertEqual(diag["backend"], "local")
        self.assertIsNotNone(diag["revision"])
        self.assertIsNotNone(diag["last_sync_time"])

    def test_simultaneous_pick_first_commit_wins(self) -> None:
        self._bootstrap_host_room()
        stale_tab = copy.deepcopy(self.host_session)

        result = draft_player(self.host_session, "Aaron Judge", source="live_queue")
        self.assertTrue(result["ok"], result.get("message"))

        result2 = draft_player(stale_tab, "Juan Soto", source="live_queue")
        self.assertFalse(result2["ok"])
        self.assertIn(
            result2["error"],
            ("shared_commit_failed", "not_allowed", "validation_failed", "membership_guard", "live_make_pick_failed"),
        )

        refreshed = stale_tab[LIVE_DRAFT_ROOM_KEY]
        self.assertIn("p1", refreshed.get("drafted_player_ids") or [])
        self.assertNotIn("p2", refreshed.get("drafted_player_ids") or [])

    def test_drafted_player_removed_from_pool_and_candidates(self) -> None:
        self._bootstrap_host_room()
        live_draft_get_available, live_draft_make_pick = _import_live_helpers()
        room = self.host_session[LIVE_DRAFT_ROOM_KEY]
        pool_row = room["pool"].iloc[0].to_dict()
        ok, _ = live_draft_make_pick(room, pool_row)
        self.assertTrue(ok)
        ok, commit_msg, _ = commit_shared_room_state(
            self.host_session,
            room,
            player_name="Aaron Judge",
            pick_already_applied=True,
            store=self.store,
        )
        self.assertTrue(ok, commit_msg)
        prepare_global_draft_context(self.host_session)

        available = live_draft_get_available(self.host_session[LIVE_DRAFT_ROOM_KEY])
        names = available["fullName"].astype(str).tolist()
        self.assertNotIn("Aaron Judge", names)

        from draft_room_state import get_all_drafted_player_names

        drafted = get_all_drafted_player_names(self.host_session)
        self.assertIn("Aaron Judge", drafted)

        candidates = allowed_draft_player_names(
            self.host_session,
            available_names=names,
        )
        self.assertNotIn("Aaron Judge", candidates)

    def test_membership_persists_after_clearing_active_code(self) -> None:
        code = self._bootstrap_host_room()
        join_shared_draft_room(self.guest_session, code, requested_team="Team 2", store=self.store)
        team_before = self.guest_session.get(ACTIVE_PARTICIPANT_TEAM_KEY)

        self.guest_session.pop(ACTIVE_SHARED_ROOM_CODE_KEY, None)
        self.guest_session.pop(ACTIVE_PARTICIPANT_TEAM_KEY, None)
        self.guest_session.pop(LIVE_DRAFT_ROOM_KEY, None)

        restored = restore_persisted_shared_room_membership(self.guest_session)
        self.assertEqual(restored, code)
        self.assertEqual(self.guest_session.get(ACTIVE_PARTICIPANT_TEAM_KEY), team_before)

        prepare_global_draft_context(self.guest_session)
        self.assertEqual(self.guest_session.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(self.guest_session.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team 2")
        self.assertIsInstance(self.guest_session.get(LIVE_DRAFT_ROOM_KEY), dict)

    def test_guest_cannot_reset_or_close_room(self) -> None:
        code = self._bootstrap_host_room()
        join_shared_draft_room(self.guest_session, code, requested_team="Team 2", store=self.store)
        self.guest_session[ACTIVE_SHARED_ROOM_CODE_KEY] = code

        ok_close, msg_close = close_shared_draft_room(self.guest_session, store=self.store)
        self.assertFalse(ok_close)
        self.assertEqual(msg_close, ERR_HOST_ONLY_RESET)

        ok_reset, msg_reset = reset_live_draft_with_membership_guard(self.guest_session)
        self.assertFalse(ok_reset)
        self.assertEqual(msg_reset, ERR_HOST_ONLY_RESET)

    def test_commit_conflict_refreshes_stale_revision(self) -> None:
        code = self._bootstrap_host_room()
        doc = self.store.load(code)
        self.assertIsNotNone(doc)
        stale_rev = int(doc.get("revision") or 0)

        room = copy.deepcopy(self.host_session[LIVE_DRAFT_ROOM_KEY])
        live_draft_get_available, live_draft_make_pick = _import_live_helpers()
        row = room["pool"].iloc[0].to_dict()
        live_draft_make_pick(room, row)
        self.store.save_if_revision(bump_revision(doc, live_room=room), expected_revision=stale_rev)

        loser = copy.deepcopy(self.host_session)
        loser_room = copy.deepcopy(loser[LIVE_DRAFT_ROOM_KEY])
        loser_row = loser_room["pool"].iloc[1].to_dict()
        live_draft_make_pick(loser_room, loser_row)
        ok, msg, _saved = commit_shared_room_state(
            loser,
            loser_room,
            expected_revision=stale_rev,
            store=self.store,
        )
        self.assertFalse(ok)
        self.assertIn("Board refreshed", msg)
        self.assertIn("p1", (loser[LIVE_DRAFT_ROOM_KEY].get("drafted_player_ids") or []))


if __name__ == "__main__":
    unittest.main()
