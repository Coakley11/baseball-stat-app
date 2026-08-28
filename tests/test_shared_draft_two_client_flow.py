"""Two-client Shared Draft flow: leave/delete authority, picks, refresh, consecutive drafts."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_actions import _prune_drafted_from_queue
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
    SHARED_ROOM_META_KEY,
    LocalFileSharedRoomStore,
    load_shared_room,
    publish_shared_room_runtime,
    reset_shared_room_store_for_tests,
    shared_document_room_blob,
    shared_room_document_private_leaks,
)
from draft_source_validation import ALLOW_FREE_POOL_KEY
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue
from live_draft_completion import apply_live_draft_completion
from live_draft_pick_commit import persist_applied_pick
from live_draft_pick_engine import live_draft_make_pick
from live_draft_resume_lobby import all_required_participants_rejoined, continue_draft_from_resume_lobby
from live_draft_resumable_slot import continue_saved_draft, save_and_continue_later
from live_draft_setup_mode import (
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    set_live_draft_setup_mode,
    start_prepared_shared_room,
)
from live_draft_team_ownership import list_available_shared_room_teams
from live_draft_termination import (
    discard_live_draft_and_start_over,
    handle_shared_document_terminal,
    permanently_delete_live_draft,
    session_may_close_backend_shared_room,
)
from live_draft_timer_logic import (
    ensure_live_draft_timer_for_pick,
    live_draft_current_slot,
    live_draft_reset_timer,
    live_draft_seconds_remaining,
)
from shared_draft_local_pool import (
    DRAFT_ROOM_PLAYER_POOL_CODE_KEY,
    DRAFT_ROOM_PLAYER_POOL_KEY,
    ensure_local_shared_player_pool,
)
from shared_draft_permissions import is_canonical_commissioner
from shared_room_membership_gate import can_render_shared_live_draft
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
        self._ensure_pool(self.host)
        self._ensure_pool(self.guest)
        return code

    def _ensure_pool(self, session: dict) -> None:
        room = session.get(LIVE_DRAFT_ROOM_KEY)
        if not isinstance(room, dict):
            return
        pool = room.get("pool")
        if pool is None or (hasattr(pool, "empty") and bool(pool.empty)):
            room["pool"] = _pool()

    def _make_pick(self, session: dict, player_name: str) -> None:
        self._ensure_pool(session)
        room = session[LIVE_DRAFT_ROOM_KEY]
        row = next(
            r
            for r in room["pool"].to_dict("records")
            if str(r.get("fullName") or "") == player_name
        )
        ok, msg = live_draft_make_pick(room, row, verdict="flow pick")
        self.assertTrue(ok, msg)
        commit = persist_applied_pick(session, room, source="manual_pick")
        self.assertTrue(commit.ok, commit.message)

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
        ok_guest, guest_reason = can_start_live_draft(self.guest)
        self.assertFalse(ok_guest)
        self.assertIn("commissioner", guest_reason.lower())

    def test_stale_host_save_after_guest_leave_does_not_resurrect_seat(self) -> None:
        code = self._create_and_join()
        stale_host_doc = copy.deepcopy(load_shared_room(code) or {})
        self.assertIn("user:coakley11", dict(stale_host_doc.get("participants") or {}))

        leave_shared_draft_room(self.guest)
        after_leave = load_shared_room(code)
        self.assertIsInstance(after_leave, dict)
        self.assertNotIn("user:coakley11", dict((after_leave or {}).get("participants") or {}))
        self.assertIn("user:coakley11", (after_leave or {}).get(LEFT_PARTICIPANTS_KEY) or {})

        # Stale host still lists the guest and has no leave ledger — the real race.
        self.assertIn("user:coakley11", dict(stale_host_doc.get("participants") or {}))
        self.assertNotIn("user:coakley11", stale_host_doc.get(LEFT_PARTICIPANTS_KEY) or {})
        self.store.save(stale_host_doc)

        stored = load_shared_room(code)
        self.assertIsInstance(stored, dict)
        self.assertNotIn("user:coakley11", dict((stored or {}).get("participants") or {}))
        self.assertNotIn("user:coakley11", dict((stored or {}).get("joined_participants") or {}))
        claims = (stored or {}).get("team_claims") or {}
        claim_owners = []
        for raw in claims.values():
            if isinstance(raw, dict):
                claim_owners.append(str(raw.get("participant_id") or raw.get("user_id") or ""))
            else:
                claim_owners.append(str(raw or ""))
        self.assertNotIn("user:coakley11", claim_owners)
        self.assertIn("user:coakley11", (stored or {}).get(LEFT_PARTICIPANTS_KEY) or {})
        open_teams, _ = list_available_shared_room_teams(stored, "late-guest")
        self.assertIn("Team B", open_teams)
        self.assertNotIn("Team A", open_teams)

        # Rejoin uses register → clear_shared_room_participant_left, not a stale save.
        # Leave cleared runtime ids; a returning guest still has the same account identity.
        self.guest[AUTH_USER_ID_KEY] = "user:coakley11"
        self.guest["draft_room_participant_id"] = "user:coakley11"
        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.guest.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team B")
        after_rejoin = load_shared_room(code)
        self.assertIn("user:coakley11", dict((after_rejoin or {}).get("participants") or {}))
        self.assertNotIn("user:coakley11", (after_rejoin or {}).get(LEFT_PARTICIPANTS_KEY) or {})

    def test_stale_prior_rejoin_marker_cannot_beat_later_leave(self) -> None:
        from draft_room_shared_state import REJOINED_PARTICIPANTS_KEY

        code = self._create_and_join()
        leave_shared_draft_room(self.guest)
        self.guest[AUTH_USER_ID_KEY] = "user:coakley11"
        self.guest["draft_room_participant_id"] = "user:coakley11"
        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        after_rejoin = load_shared_room(code)
        self.assertIn("user:coakley11", dict((after_rejoin or {}).get("participants") or {}))
        self.assertIn("user:coakley11", (after_rejoin or {}).get(REJOINED_PARTICIPANTS_KEY) or {})
        stale_prior_rejoin = copy.deepcopy(after_rejoin or {})

        leave_shared_draft_room(self.guest)
        after_second_leave = load_shared_room(code)
        self.assertNotIn("user:coakley11", dict((after_second_leave or {}).get("participants") or {}))
        self.assertIn("user:coakley11", (after_second_leave or {}).get(LEFT_PARTICIPANTS_KEY) or {})
        self.assertNotIn("user:coakley11", (after_second_leave or {}).get(REJOINED_PARTICIPANTS_KEY) or {})

        # Replay the captured prior-rejoin document (has guest + older rejoin marker).
        self.assertIn("user:coakley11", dict(stale_prior_rejoin.get("participants") or {}))
        self.assertIn("user:coakley11", stale_prior_rejoin.get(REJOINED_PARTICIPANTS_KEY) or {})
        self.store.save(stale_prior_rejoin)

        stored = load_shared_room(code)
        self.assertNotIn("user:coakley11", dict((stored or {}).get("participants") or {}))
        self.assertNotIn("user:coakley11", dict((stored or {}).get("joined_participants") or {}))
        self.assertIn("user:coakley11", (stored or {}).get(LEFT_PARTICIPANTS_KEY) or {})
        open_teams, _ = list_available_shared_room_teams(stored, "late-guest")
        self.assertIn("Team B", open_teams)

        # A genuinely later registration rejoin still succeeds.
        self.guest[AUTH_USER_ID_KEY] = "user:coakley11"
        self.guest["draft_room_participant_id"] = "user:coakley11"
        ok2, msg2, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok2, msg2)
        self.assertEqual(self.guest.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team B")
        after_later_rejoin = load_shared_room(code)
        self.assertIn("user:coakley11", dict((after_later_rejoin or {}).get("participants") or {}))
        self.assertNotIn("user:coakley11", (after_later_rejoin or {}).get(LEFT_PARTICIPANTS_KEY) or {})

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
        self.assertTrue(
            any(tok in blocked_err.lower() for tok in ("already assigned", "already claimed")),
            blocked_err,
        )

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

        self._make_pick(self.host, "Aaron Judge")
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
        kept_host = _prune_drafted_from_queue(self.host)
        self.assertNotIn("Aaron Judge", kept_host)
        self.assertIn("Freddie Freeman", kept_host)
        self.assertEqual(shared_room_document_private_leaks(load_shared_room(code) or {}), [])

        self._make_pick(self.guest, "Juan Soto")
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
            self._make_pick(session, player)

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

    def test_completed_draft_refresh_restores_review_for_both_clients(self) -> None:
        code = self._create_and_join()
        for session, player in (
            (self.host, "Aaron Judge"),
            (self.guest, "Juan Soto"),
            (self.guest, "Mookie Betts"),
            (self.host, "Freddie Freeman"),
        ):
            poll_shared_draft_room(session, force=True, store=self.store)
            self._make_pick(session, player)

        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        apply_live_draft_completion(host_room, self.host)
        persist_applied_pick(self.host, host_room, source="complete")
        poll_shared_draft_room(self.guest, force=True, store=self.store)
        save_participant_workflow_from_session(self.host, code)
        save_participant_workflow_from_session(self.guest, code)

        for session, uid in ((self.host, "user:daniel"), (self.guest, "user:coakley11")):
            refreshed = {
                AUTH_USER_ID_KEY: uid,
                "draft_room_participant_id": uid,
                ALLOW_FREE_POOL_KEY: True,
                ACTIVE_SHARED_ROOM_CODE_KEY: code,
                MEMBERSHIP_KEY: copy.deepcopy(session.get(MEMBERSHIP_KEY) or {}),
                PARTICIPANT_STATE_KEY: copy.deepcopy(session.get(PARTICIPANT_STATE_KEY) or {}),
            }
            restored = restore_persisted_shared_room_membership(refreshed)
            self.assertEqual(restored, code, refreshed.get("_live_draft_restore_blocked_reason"))
            prepare_global_draft_context(refreshed)
            room = refreshed.get(LIVE_DRAFT_ROOM_KEY) or {}
            self.assertEqual(str(room.get("status") or "").lower(), "complete")
            self.assertEqual(len(room.get("draft_board") or []), 4)
            self.assertEqual(refreshed.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
            ok, reason = can_render_shared_live_draft(refreshed, require_team_claim=False)
            self.assertTrue(ok, reason)

        late_ok, late_msg, _ = join_shared_draft_room(
            {"draft_room_participant_id": "late", AUTH_USER_ID_KEY: "late"},
            code,
            store=self.store,
        )
        self.assertFalse(late_ok)
        self.assertTrue(
            any(tok in late_msg.lower() for tok in ("finished", "complete", "joinable")),
            late_msg,
        )

    def test_guest_cannot_start_shared_draft(self) -> None:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code, _ = create_and_host_shared_room(
            self.host, _room(status="not_started"), host_team="Team A", store=self.store
        )
        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        prepare_global_draft_context(self.host)
        prepare_global_draft_context(self.guest)

        ok_host, host_reason = can_start_live_draft(self.host)
        self.assertTrue(ok_host, host_reason)
        ok_guest, guest_reason = can_start_live_draft(self.guest)
        self.assertFalse(ok_guest)
        self.assertIn("commissioner", guest_reason.lower())

        blocked = start_prepared_shared_room(self.guest, None)
        self.assertTrue(blocked.get("handled"))
        self.assertFalse(blocked.get("ok"))
        self.assertIn("commissioner", str(blocked.get("error") or "").lower())
        self.assertEqual(str((self.guest.get(LIVE_DRAFT_ROOM_KEY) or {}).get("status") or ""), "not_started")
        self.assertEqual(str((load_shared_room(code) or {}).get("status") or "").lower(), "not_started")

        with mock.patch("live_draft_state.commit_live_draft_room"):
            started = start_prepared_shared_room(self.host, None)
        self.assertTrue(started.get("ok"), started)
        self.assertEqual(str((self.host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("status") or ""), "in_progress")
        stored = load_shared_room(code)
        self.assertEqual(str((stored or {}).get("status") or "").lower(), "in_progress")
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        self.assertIsNone(host_room.get("timer_deadline"))
        self.assertIsNone(host_room.get("timer_started_at"))
        stored_blob = shared_document_room_blob(stored) or {}
        self.assertIsNone(stored_blob.get("timer_deadline"))
        self.assertIsNone(stored_blob.get("timer_started_at"))

        # Simulate a Start-armed 30s clock that already expired during a slow first paint.
        host_room["timer_started_at"] = __import__("time").time() - 45
        host_room["timer_deadline"] = __import__("time").time() - 15
        host_room["timer_handled_index"] = -1
        self.assertEqual(live_draft_seconds_remaining(host_room), 0)
        self.assertFalse(ensure_live_draft_timer_for_pick(host_room))
        self.assertTrue(ensure_live_draft_timer_for_pick(host_room, live_board_ready=True))
        remaining = live_draft_seconds_remaining(host_room)
        self.assertGreaterEqual(remaining, 58)
        self.assertLessEqual(remaining, 60)

    def test_start_and_publish_keep_create_time_session_pool(self) -> None:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        empty = _room(status="not_started")
        empty["pool"] = pd.DataFrame()
        code, _ = create_and_host_shared_room(
            self.host, empty, host_team="Team A", store=self.store
        )
        self.host["draft_room_player_pool"] = _pool()
        self.host[LIVE_DRAFT_ROOM_KEY]["status"] = "not_started"
        self.host[LIVE_DRAFT_ROOM_KEY]["pool"] = pd.DataFrame()
        with mock.patch("live_draft_state.commit_live_draft_room"):
            started = start_prepared_shared_room(self.host, None)
        self.assertTrue(started.get("ok"), started)
        host_pool = self.host[LIVE_DRAFT_ROOM_KEY].get("pool")
        self.assertIsNotNone(host_pool)
        self.assertFalse(getattr(host_pool, "empty", True))
        self.assertGreaterEqual(len(host_pool), 4)

        stored = load_shared_room(code)
        self.host[LIVE_DRAFT_ROOM_KEY]["pool"] = pd.DataFrame()
        published = publish_shared_room_runtime(self.host, stored, reason="shared_room_pick")
        self.assertIsInstance(published, dict)
        kept = published.get("pool")
        self.assertFalse(getattr(kept, "empty", True))
        self.assertGreaterEqual(len(kept), 4)

    def test_create_stashes_pool_so_start_survives_persist_wipe(self) -> None:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code, _ = create_and_host_shared_room(
            self.host, _room(status="not_started"), host_team="Team A", store=self.store
        )
        self.assertTrue(is_plausible_share_code(code), code)
        stashed = self.host.get(DRAFT_ROOM_PLAYER_POOL_KEY)
        self.assertFalse(getattr(stashed, "empty", True))
        self.assertEqual(str(self.host.get(DRAFT_ROOM_PLAYER_POOL_CODE_KEY) or ""), code)
        stored = load_shared_room(code)
        stored_blob = shared_document_room_blob(stored) or {}
        self.assertTrue(getattr(pd.DataFrame(stored_blob.get("pool_records") or []), "empty", True))
        self.assertNotIn("pool", stored_blob)

        self.host[LIVE_DRAFT_ROOM_KEY]["pool"] = pd.DataFrame()
        with mock.patch("live_draft_state.commit_live_draft_room"):
            started = start_prepared_shared_room(self.host, None)
        self.assertTrue(started.get("ok"), started)
        recovered = self.host[LIVE_DRAFT_ROOM_KEY].get("pool")
        self.assertFalse(getattr(recovered, "empty", True))
        self.assertGreaterEqual(len(recovered), 4)

    def test_guest_join_rebuilds_local_pool_when_document_stripped(self) -> None:
        set_live_draft_setup_mode(self.host, SETUP_MODE_SHARED)
        code, _ = create_and_host_shared_room(
            self.host, _room(status="not_started"), host_team="Team A", store=self.store
        )
        stored = load_shared_room(code)
        stored_blob = shared_document_room_blob(stored) or {}
        self.assertNotIn("pool_records", stored_blob)
        self.assertNotIn("pool", stored_blob)

        rebuilt = _pool()
        with mock.patch(
            "shared_draft_local_pool.rebuild_shared_room_player_pool",
            return_value=rebuilt,
        ) as builder:
            ok, msg, _ = join_shared_draft_room(
                self.guest, code, requested_team="Team B", store=self.store
            )
        self.assertTrue(ok, msg)
        builder.assert_called()
        guest_pool = (self.guest.get(LIVE_DRAFT_ROOM_KEY) or {}).get("pool")
        self.assertFalse(getattr(guest_pool, "empty", True))
        self.assertGreaterEqual(len(guest_pool), 4)
        self.assertIn("Aaron Judge", list(guest_pool["fullName"]))
        after_join = shared_document_room_blob(load_shared_room(code)) or {}
        self.assertNotIn("pool_records", after_join)
        self.assertNotIn("pool", after_join)

    def test_later_leave_room_does_not_reuse_prior_room_pool_stash(self) -> None:
        first = _pool()
        self.host[DRAFT_ROOM_PLAYER_POOL_KEY] = first
        self.host[DRAFT_ROOM_PLAYER_POOL_CODE_KEY] = "AAAA11"
        self.host[ACTIVE_SHARED_ROOM_CODE_KEY] = "BBBB22"
        empty = _room(status="not_started")
        empty["pool"] = pd.DataFrame()
        empty["room_code"] = "BBBB22"
        rebuilt = _pool()
        rebuilt.loc[0, "fullName"] = "Juan Soto"
        attached = ensure_local_shared_player_pool(
            self.host, empty, builder=lambda _session, _room: rebuilt
        )
        self.assertFalse(getattr(attached, "empty", True))
        self.assertEqual(str(attached.iloc[0]["fullName"]), "Juan Soto")
        self.assertEqual(str(self.host.get(DRAFT_ROOM_PLAYER_POOL_CODE_KEY) or ""), "BBBB22")

    def test_unchanged_revision_still_syncs_timer_deadline(self) -> None:
        code = self._create_and_join()
        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        live_draft_reset_timer(host_room)
        persist_applied_pick(self.host, host_room, source="timer_reset")
        poll_shared_draft_room(self.guest, force=True, store=self.store)
        first = float(self.guest[LIVE_DRAFT_ROOM_KEY]["timer_deadline"])
        local_rev = int((self.guest.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)

        stored = load_shared_room(code)
        self.assertIsInstance(stored, dict)
        blob = dict(shared_document_room_blob(stored) or {})
        drifted = first + 17.0
        blob["timer_deadline"] = drifted
        stored["room"] = blob
        self.store.save(stored)
        self.assertEqual(int((load_shared_room(code) or {}).get("revision") or 0), local_rev)

        self.guest.pop("_shared_draft_sync_run", None)
        changed = sync_shared_draft_room(self.guest, force=False, store=self.store)
        self.assertTrue(changed)
        self.assertAlmostEqual(
            float(self.guest[LIVE_DRAFT_ROOM_KEY]["timer_deadline"]), drifted, delta=0.2
        )

    def test_save_continue_two_client_rejoin_without_injected_markers(self) -> None:
        code = self._create_and_join()
        self._make_pick(self.host, "Aaron Judge")
        poll_shared_draft_room(self.guest, force=True, store=self.store)
        save_participant_workflow_from_session(self.host, code)
        save_participant_workflow_from_session(self.guest, code)
        guest_membership = copy.deepcopy(self.guest.get(MEMBERSHIP_KEY) or {})
        guest_pstate = copy.deepcopy(self.guest.get(PARTICIPANT_STATE_KEY) or {})

        saved = save_and_continue_later(self.host, st=None, replace_existing=True)
        self.assertTrue(saved.get("ok"), saved)
        parked = load_shared_room(code)
        self.assertEqual(str((parked or {}).get("status") or "").lower(), "saved_for_later")

        parked_refresh = {
            AUTH_USER_ID_KEY: "user:coakley11",
            "draft_room_participant_id": "user:coakley11",
            ALLOW_FREE_POOL_KEY: True,
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
            MEMBERSHIP_KEY: guest_membership,
            PARTICIPANT_STATE_KEY: guest_pstate,
        }
        restored = restore_persisted_shared_room_membership(parked_refresh)
        self.assertEqual(restored, "")
        self.assertIn("saved_for_later", str(parked_refresh.get("_live_draft_restore_blocked_reason") or ""))

        cont = continue_saved_draft(self.host, st=None)
        self.assertTrue(cont.get("ok"), cont)
        self.assertTrue(cont.get("resume_lobby") or self.host.get("_live_draft_resume_lobby"))

        ok, msg, _ = join_shared_draft_room(
            self.guest, code, requested_team="Team B", store=self.store
        )
        self.assertTrue(ok, msg)
        doc = load_shared_room(code)
        ready, ready_n, total_n = all_required_participants_rejoined(self.host, doc)
        self.assertTrue(
            ready,
            (ready_n, total_n, (doc or {}).get("resume_rejoined"), (doc or {}).get("resume_reserved_teams")),
        )
        resumed = continue_draft_from_resume_lobby(self.host, st=None, document=doc)
        self.assertTrue(resumed.get("ok"), resumed)
        self.assertEqual(int((self.host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("current_pick_index") or 0), 1)
        self.assertFalse(self.host.get("_live_draft_resume_lobby"))

    def test_host_leave_mid_draft_is_leave_only(self) -> None:
        code = self._create_and_join()
        leave_shared_draft_room(self.host)
        stored = load_shared_room(code)
        self.assertIsInstance(stored, dict)
        self.assertEqual(str((stored or {}).get("status") or "").lower(), "in_progress")
        self.assertNotIn("user:daniel", dict((stored or {}).get("participants") or {}))
        self.assertIn("user:coakley11", dict((stored or {}).get("participants") or {}))
        self.assertFalse(session_may_close_backend_shared_room(self.guest, code))

        deleted = permanently_delete_live_draft(self.guest, st=None)
        self.assertTrue(deleted.get("ok"), deleted)
        self.assertEqual(deleted.get("operation"), "leave")
        after_guest = load_shared_room(code)
        self.assertEqual(str((after_guest or {}).get("status") or "").lower(), "in_progress")
        self.assertNotEqual(str((after_guest or {}).get("status") or "").lower(), "deleted")

        self.host = _host()
        ok, msg, _ = join_shared_draft_room(
            self.host, code, requested_team="Team A", store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.host.get(ACTIVE_PARTICIPANT_TEAM_KEY), "Team A")
        self.assertTrue(is_canonical_commissioner(self.host, load_shared_room(code)))


if __name__ == "__main__":
    unittest.main()
