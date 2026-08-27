"""Two-client Shared Draft flow: leave/delete authority, picks, refresh, consecutive drafts."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_actions import _prune_drafted_from_queue, draft_player
from draft_room_context import (
    create_and_host_shared_room,
    join_shared_draft_room,
    leave_shared_draft_room,
    poll_shared_draft_room,
    prepare_global_draft_context,
    sync_shared_draft_room,
)
from draft_room_create_verify import is_plausible_share_code
from draft_room_membership import resolve_join_team_assignment
from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_TEAM_KEY,
    MEMBERSHIP_KEY,
    PARTICIPANT_STATE_KEY,
    live_draft_room_share_code,
    load_participant_workflow_into_session,
    restore_persisted_shared_room_membership,
    save_participant_workflow_from_session,
)
from draft_room_shared_state import (
    ACTIVE_SHARED_ROOM_CODE_KEY,
    LEFT_PARTICIPANTS_KEY,
    LIVE_DRAFT_ROOM_KEY,
    LocalFileSharedRoomStore,
    load_shared_room,
    reset_shared_room_store_for_tests,
    shared_document_room_blob,
    shared_room_document_private_leaks,
)
from draft_source_validation import ALLOW_FREE_POOL_KEY
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue
from live_draft_completion import apply_live_draft_completion
from live_draft_pick_commit import persist_applied_pick
from live_draft_setup_mode import SETUP_MODE_SHARED, SETUP_MODE_SOLO, can_start_live_draft, set_live_draft_setup_mode
from live_draft_team_ownership import list_available_shared_room_teams
from live_draft_termination import (
    discard_live_draft_and_start_over,
    handle_shared_document_terminal,
    permanently_delete_live_draft,
    session_may_close_backend_shared_room,
)
from live_draft_timer_logic import live_draft_current_slot, live_draft_reset_timer
from shared_draft_permissions import is_canonical_commissioner
from suite_auth import AUTH_USER_ID_KEY


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Mookie Betts", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Freddie Freeman", "Primary Position": "1B"},
            {"playerID": "p5", "fullName": "Francisco Lindor", "Primary Position": "SS"},
        ]
    )


def _room(*, draft_id: str = "FLOW1", status: str = "not_started") -> dict:
    teams = ["Team A", "Team B"]
    return {
        "draft_room_id": draft_id,
        "status": status,
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "picks_per_team": 2,
            "your_team": "Team A",
            "user_team": "Team A",
            "teams": teams,
            "draft_setup_mode": SETUP_MODE_SHARED,
            "timer_seconds": 60,
            ALLOW_FREE_POOL_KEY: True,
        },
        "teams": teams,
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
            {"Pick": 3, "Round": 2, "Team": "Team B"},
            {"Pick": 4, "Round": 2, "Team": "Team A"},
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": _pool(),
    }


def _host() -> dict:
    return {
        AUTH_USER_ID_KEY: "user:daniel",
        "draft_room_participant_id": "user:daniel",
        "_suite_auth_user_id": "user:daniel",
        ALLOW_FREE_POOL_KEY: True,
        "live_draft_setup_mode": SETUP_MODE_SHARED,
    }


def _guest() -> dict:
    return {
        AUTH_USER_ID_KEY: "user:coakley11",
        "draft_room_participant_id": "user:coakley11",
        "_suite_auth_user_id": "user:coakley11",
        ALLOW_FREE_POOL_KEY: True,
    }


class SharedDraftTwoClientFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        reset_shared_room_store_for_tests(self.store)
        self.host = _host()
        self.guest = _guest()
        self._patches = [
            mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_context.get_shared_room_store", return_value=self.store),
            mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False),
            mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, "")),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        reset_shared_room_store_for_tests(None)
        self._tmpdir.cleanup()

    def _create_and_join(self, *, status: str = "in_progress", draft_id: str = "FLOW1") -> str:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code, _ = create_and_host_shared_room(
            self.host, _room(draft_id=draft_id, status=status), host_team="Team A", store=self.store
        )
        self.assertTrue(is_plausible_share_code(code), code)
        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        prepare_global_draft_context(self.host)
        prepare_global_draft_context(self.guest)
        return code

    def test_lobby_ready_after_six_char_join_and_distinct_claims(self) -> None:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code, _ = create_and_host_shared_room(
            self.host, _room(status="not_started"), host_team="Team A", store=self.store
        )
        self.assertTrue(is_plausible_share_code(code))
        self.assertEqual(len(code), 6)
        self.assertNotEqual(str((self.host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id") or ""), code)
        self.assertTrue(is_canonical_commissioner(self.host, load_shared_room(code)))
        self.assertFalse(can_start_live_draft(self.host)[0])

        ok, msg, doc = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.guest.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team B")
        self.assertFalse(is_canonical_commissioner(self.guest, doc))
        steal, steal_err = resolve_join_team_assignment(load_shared_room(code) or {}, "late-guest", requested_team="Team A")
        self.assertIsNone(steal)
        self.assertIn("already assigned", steal_err.lower())
        ok_start, start_reason = can_start_live_draft(self.host)
        self.assertTrue(ok_start, start_reason)

    def test_guest_leave_releases_team_and_blocks_host_steal(self) -> None:
        code = self._create_and_join()
        leave_shared_draft_room(self.guest)
        self.assertFalse(self.guest.get(ACTIVE_SHARED_ROOM_CODE_KEY))

        stored = load_shared_room(code)
        self.assertIsInstance(stored, dict)
        parts = dict((stored or {}).get("participants") or {})
        self.assertNotIn("user:coakley11", parts)
        self.assertIn("user:coakley11", stored.get(LEFT_PARTICIPANTS_KEY) or {})
        open_teams, _ = list_available_shared_room_teams(stored, "late-guest")
        self.assertIn("Team B", open_teams)
        self.assertNotIn("Team A", open_teams)

        steal, steal_err = resolve_join_team_assignment(stored or {}, "late-guest", requested_team="Team A")
        self.assertIsNone(steal)
        self.assertIn("already assigned", steal_err.lower())

        late = {
            AUTH_USER_ID_KEY: "user:late",
            "draft_room_participant_id": "user:late",
            ALLOW_FREE_POOL_KEY: True,
        }
        ok, msg, _ = join_shared_draft_room(late, code, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(late.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team B")

        # Original guest can reclaim after the late joiner leaves, not steal Team A.
        leave_shared_draft_room(late)
        ok2, msg2, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok2, msg2)
        self.assertEqual(self.guest.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team B")
        blocked, blocked_err = join_shared_draft_room(
            {"draft_room_participant_id": "thief", AUTH_USER_ID_KEY: "thief"},
            code,
            requested_team="Team A",
            store=self.store,
        )[:2]
        self.assertFalse(blocked)
        self.assertIn("already assigned", blocked_err.lower())

    def test_guest_discard_does_not_tombstone_shared_room(self) -> None:
        code = self._create_and_join()
        self.assertFalse(session_may_close_backend_shared_room(self.guest, code))
        self.assertTrue(session_may_close_backend_shared_room(self.host, code))

        result = discard_live_draft_and_start_over(self.guest, st=None)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("operation"), "leave")
        self.assertFalse(result.get("backend_closed", True))
        self.assertIsNone(self.guest.get(LIVE_DRAFT_ROOM_KEY))

        stored = load_shared_room(code)
        self.assertIsInstance(stored, dict)
        self.assertNotEqual(str((stored or {}).get("status") or "").lower(), "deleted")
        self.assertIn("user:daniel", dict((stored or {}).get("participants") or {}))
        self.assertNotIn("user:coakley11", dict((stored or {}).get("participants") or {}))

        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)

    def test_alternating_picks_timer_queue_and_host_refresh(self) -> None:
        code = self._create_and_join()
        add_player_to_draft_queue(self.host, "Aaron Judge")
        add_player_to_draft_queue(self.host, "Freddie Freeman")
        add_player_to_draft_queue(self.guest, "Juan Soto")
        add_player_to_draft_queue(self.guest, "Aaron Judge")
        save_participant_workflow_from_session(self.host, code)
        save_participant_workflow_from_session(self.guest, code)

        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        live_draft_reset_timer(host_room)
        deadline = float(host_room["timer_deadline"])
        persist_applied_pick(self.host, host_room, source="timer_reset")
        poll_shared_draft_room(self.guest, force=True, store=self.store)
        self.assertAlmostEqual(float(self.guest[LIVE_DRAFT_ROOM_KEY]["timer_deadline"]), deadline, delta=1.0)

        result = draft_player(self.host, "Aaron Judge", source="live_queue")
        self.assertTrue(result.get("ok"), result)
        persist_applied_pick(self.host, self.host[LIVE_DRAFT_ROOM_KEY], source="manual_pick")
        changed = poll_shared_draft_room(self.guest, force=True, store=self.store)
        self.assertTrue(changed)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(int(guest_room.get("current_pick_index") or 0), 1)
        self.assertEqual((live_draft_current_slot(guest_room) or {}).get("Team"), "Team B")
        load_participant_workflow_into_session(self.guest, code)
        kept_guest = _prune_drafted_from_queue(self.guest)
        self.assertNotIn("Aaron Judge", kept_guest)
        self.assertIn("Juan Soto", kept_guest)
        load_participant_workflow_into_session(self.host, code)
        self.assertNotIn("Aaron Judge", self.host.get(DRAFT_QUEUE_KEY) or [])
        self.assertIn("Freddie Freeman", self.host.get(DRAFT_QUEUE_KEY) or [])
        self.assertEqual(shared_room_document_private_leaks(load_shared_room(code) or {}), [])

        result2 = draft_player(self.guest, "Juan Soto", source="live_queue")
        self.assertTrue(result2.get("ok"), result2)
        persist_applied_pick(self.guest, self.guest[LIVE_DRAFT_ROOM_KEY], source="manual_pick")
        poll_shared_draft_room(self.host, force=True, store=self.store)
        self.assertEqual(int(self.host[LIVE_DRAFT_ROOM_KEY].get("current_pick_index") or 0), 2)
        board = self.host[LIVE_DRAFT_ROOM_KEY].get("draft_board") or []
        self.assertEqual(len(board), 2)

        refreshed = {
            AUTH_USER_ID_KEY: "user:daniel",
            "draft_room_participant_id": "user:daniel",
            ALLOW_FREE_POOL_KEY: True,
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
            MEMBERSHIP_KEY: copy.deepcopy(self.host.get(MEMBERSHIP_KEY) or {}),
            PARTICIPANT_STATE_KEY: copy.deepcopy(self.host.get(PARTICIPANT_STATE_KEY) or {}),
        }
        save_participant_workflow_from_session(self.host, code)
        restored = restore_persisted_shared_room_membership(refreshed)
        self.assertEqual(restored, code)
        load_participant_workflow_into_session(refreshed, code)
        sync_shared_draft_room(refreshed, force=True, store=self.store)
        self.assertEqual(refreshed.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(str((refreshed.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id") or ""), "FLOW1")
        self.assertEqual(live_draft_room_share_code(refreshed.get(LIVE_DRAFT_ROOM_KEY) or {}), code)
        self.assertEqual(int((refreshed.get(LIVE_DRAFT_ROOM_KEY) or {}).get("current_pick_index") or 0), 2)
        self.assertIn("Freddie Freeman", refreshed.get(DRAFT_QUEUE_KEY) or [])
        self.assertNotIn("Juan Soto", refreshed.get(DRAFT_QUEUE_KEY) or [])

    def test_commissioner_delete_propagates_and_guest_poll_is_terminal(self) -> None:
        code = self._create_and_join()
        result = permanently_delete_live_draft(self.host, st=None)
        self.assertTrue(result.get("ok"), result)
        stored = load_shared_room(code)
        self.assertEqual(str((stored or {}).get("status") or "").lower(), "deleted")
        changed = poll_shared_draft_room(self.guest, force=True, store=self.store)
        self.assertTrue(changed)
        self.assertIsNone(self.guest.get(LIVE_DRAFT_ROOM_KEY))
        self.assertTrue(self.guest.get("_live_draft_exit_deleted_room") or self.guest.get("_live_draft_force_setup_after_delete"))
        ok, msg, _ = join_shared_draft_room(
            {"draft_room_participant_id": "late", AUTH_USER_ID_KEY: "late"},
            code,
            store=self.store,
        )
        self.assertFalse(ok)
        self.assertIn("ended", msg.lower())

    def test_consecutive_draft_b_does_not_inherit_draft_a(self) -> None:
        code_a = self._create_and_join(draft_id="FLOWA")
        permanently_delete_live_draft(self.host, st=None)
        poll_shared_draft_room(self.guest, force=True, store=self.store)

        self.host = _host()
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code_b, _ = create_and_host_shared_room(
            self.host, _room(draft_id="FLOWB", status="in_progress"), host_team="Team A", store=self.store
        )
        self.assertTrue(is_plausible_share_code(code_b))
        self.assertNotEqual(code_a, code_b)
        self.assertEqual(self.host.get(ACTIVE_SHARED_ROOM_CODE_KEY), code_b)
        self.assertEqual(str((self.host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id") or ""), "FLOWB")
        self.assertNotEqual(str((load_shared_room(code_a) or {}).get("status") or "").lower(), "in_progress")

        guest_b = _guest()
        ok, msg, _ = join_shared_draft_room(guest_b, code_b, requested_team="Team B", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(guest_b.get(ACTIVE_SHARED_ROOM_CODE_KEY), code_b)
        self.assertEqual(str((guest_b.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id") or ""), "FLOWB")
        self.assertNotEqual(guest_b.get(ACTIVE_SHARED_ROOM_CODE_KEY), code_a)

        solo = {
            AUTH_USER_ID_KEY: "user:solo",
            "draft_room_participant_id": "user:solo",
            "live_draft_setup_mode": SETUP_MODE_SOLO,
        }
        set_live_draft_setup_mode(solo, SETUP_MODE_SOLO)
        self.assertFalse(solo.get(ACTIVE_SHARED_ROOM_CODE_KEY))
        self.assertNotEqual(code_b, solo.get(ACTIVE_SHARED_ROOM_CODE_KEY))

    def test_completed_draft_stays_for_review_on_both_clients(self) -> None:
        code = self._create_and_join()
        for session, player in (
            (self.host, "Aaron Judge"),
            (self.guest, "Juan Soto"),
            (self.guest, "Mookie Betts"),
            (self.host, "Freddie Freeman"),
        ):
            poll_shared_draft_room(session, force=True, store=self.store)
            result = draft_player(session, player, source="free_pool")
            self.assertTrue(result.get("ok"), result)
            persist_applied_pick(session, session[LIVE_DRAFT_ROOM_KEY], source="manual_pick")

        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        apply_live_draft_completion(host_room, self.host)
        persist_applied_pick(self.host, host_room, source="complete")
        poll_shared_draft_room(self.guest, force=True, store=self.store)
        stored = load_shared_room(code)
        self.assertFalse(handle_shared_document_terminal(self.guest, stored))
        guest_room = self.guest.get(LIVE_DRAFT_ROOM_KEY) or {}
        self.assertEqual(len(guest_room.get("draft_board") or []), 4)
        self.assertEqual(str(guest_room.get("status") or "").lower(), "complete")
        self.assertEqual(self.guest.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertEqual(shared_document_room_blob(stored).get("status") if stored else "", "complete")


if __name__ == "__main__":
    unittest.main()
