"""Regression: shared multiplayer join roles, auto Team B, End/Delete, resume lobby."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_room_context import create_and_host_shared_room, join_shared_draft_room
from draft_room_membership import is_room_host, resolve_join_team_assignment
from draft_room_participant_state import MEMBERSHIP_KEY, resolve_participant_id
from draft_room_shared_state import LocalFileSharedRoomStore, load_shared_room
from live_draft_completion import LIFECYCLE_SETUP, resolve_live_draft_lifecycle
from live_draft_resume_lobby import (
    all_required_participants_rejoined,
    continue_draft_from_resume_lobby,
    resume_lobby_rows,
)
from live_draft_resumable_slot import continue_saved_draft, save_and_continue_later
from live_draft_team_ownership import list_available_shared_room_teams, session_identity_aliases
from live_draft_termination import discard_live_draft_and_start_over
from shared_draft_permissions import is_canonical_commissioner, participant_may_auto_pick


def _two_team_room(*, status: str = "waiting") -> dict:
    return {
        "draft_room_id": "DRAFTAB",
        "status": status,
        "teams": ["Team A", "Team B"],
        "config": {"num_teams": 2, "picks_per_team": 2, "timer_seconds": 60, "your_team": "Team A"},
        "pick_order": [
            {"Pick": 1, "Team": "Team A"},
            {"Pick": 2, "Team": "Team B"},
            {"Pick": 3, "Team": "Team A"},
            {"Pick": 4, "Team": "Team B"},
        ],
        "draft_board": [],
        "current_pick_index": 0,
        "pool": [],
    }


class SharedJoinRolesAndDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch(
            "draft_room_shared_state.get_shared_room_store", return_value=self.store
        )
        self._patch.start()
        self.daniel = {
            "draft_room_participant_id": "daniel-pid",
            "auth_user_id": "daniel-auth",
            "_suite_auth_user_id": "daniel-auth",
        }
        self.coakley = {
            "draft_room_participant_id": "coakley-pid",
            "auth_user_id": "coakley-auth",
            "_suite_auth_user_id": "coakley-auth",
        }

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_guest_auto_assigned_team_b_not_commissioner(self, *_mocks: object) -> None:
        room = _two_team_room()
        code, doc = create_and_host_shared_room(self.daniel, room, host_team="Team A", store=self.store)
        self.assertTrue(code)
        self.assertEqual(doc.get("commissioner_participant_id") or doc.get("host_participant_id"), "daniel-pid")
        self.assertTrue(is_canonical_commissioner(self.daniel, doc))
        self.assertTrue(is_room_host(self.daniel, doc))

        # Stale membership pollution must not grant Team A / commissioner to guest.
        self.coakley[MEMBERSHIP_KEY] = {
            code: {
                "daniel-pid": {"participant_id": "daniel-pid", "assigned_team": "Team A"},
                "coakley-pid": {"participant_id": "coakley-pid", "assigned_team": "Team A"},
            }
        }
        aliases = session_identity_aliases(self.coakley)
        self.assertNotIn("daniel-pid", aliases)

        team, err = resolve_join_team_assignment(
            load_shared_room(code) or doc,
            "coakley-pid",
            requested_team=None,
            current_identity_aliases=aliases,
        )
        self.assertEqual(err, "")
        self.assertEqual(team, "Team B")

        ok, msg, joined_doc = join_shared_draft_room(
            self.coakley, code, requested_team=None, store=self.store
        )
        self.assertTrue(ok, msg)
        self.assertEqual(self.coakley.get("draft_room_participant_team"), "Team B")
        self.assertFalse(is_canonical_commissioner(self.coakley, joined_doc))
        self.assertFalse(is_room_host(self.coakley, joined_doc))
        self.assertTrue(is_canonical_commissioner(self.daniel, joined_doc))

        open_teams, _diag = list_available_shared_room_teams(joined_doc, "other-pid")
        self.assertNotIn("Team A", open_teams)
        self.assertNotIn("Team B", open_teams)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_multiple_open_teams_require_selection(self, *_mocks: object) -> None:
        room = {
            **_two_team_room(),
            "teams": ["Team A", "Team B", "Team C"],
            "config": {"num_teams": 3, "picks_per_team": 1, "timer_seconds": 60},
        }
        code, doc = create_and_host_shared_room(self.daniel, room, host_team="Team A", store=self.store)
        team, err = resolve_join_team_assignment(doc, "coakley-pid", requested_team=None)
        self.assertIsNone(team)
        self.assertIn("Choose a team", err)
        team2, err2 = resolve_join_team_assignment(doc, "coakley-pid", requested_team="Team A")
        self.assertIsNone(team2)
        self.assertIn("already assigned", err2.lower())
        team3, err3 = resolve_join_team_assignment(doc, "coakley-pid", requested_team="Team C")
        self.assertEqual(team3, "Team C")
        self.assertEqual(err3, "")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_reattach_same_team_and_end_delete(self, *_mocks: object) -> None:
        room = _two_team_room(status="in_progress")
        code, _ = create_and_host_shared_room(self.daniel, room, host_team="Team A", store=self.store)
        ok, msg, _ = join_shared_draft_room(self.coakley, code, store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(self.coakley.get("draft_room_participant_team"), "Team B")

        # Reattach
        ok2, msg2, _ = join_shared_draft_room(self.coakley, code, store=self.store)
        self.assertTrue(ok2, msg2)
        self.assertEqual(self.coakley.get("draft_room_participant_team"), "Team B")

        self.daniel["live_draft_room"] = dict(self.daniel.get("live_draft_room") or room)
        self.daniel["live_draft_room"]["status"] = "in_progress"
        self.daniel["active_shared_draft_room_code"] = code
        self.assertTrue(is_canonical_commissioner(self.daniel, load_shared_room(code)))

        result = discard_live_draft_and_start_over(self.daniel, st=None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(self.daniel.get("_live_draft_deleting"), "done")
        self.assertIsNone(self.daniel.get("live_draft_room"))
        self.assertEqual(resolve_live_draft_lifecycle(self.daniel), LIFECYCLE_SETUP)

        # Lifecycle stays setup even if a stale room pointer is injected.
        self.daniel["live_draft_room"] = dict(room)
        self.assertEqual(resolve_live_draft_lifecycle(self.daniel), LIFECYCLE_SETUP)
        self.assertIsNone(self.daniel.get("live_draft_room"))

        ended = load_shared_room(code)
        self.assertIsInstance(ended, dict)
        self.assertEqual(str(ended.get("status") or "").lower(), "deleted")
        ok3, msg3, _ = join_shared_draft_room(
            {"draft_room_participant_id": "late-guest"}, code, store=self.store
        )
        self.assertFalse(ok3)
        self.assertIn("ended", msg3.lower())

        # Guest session also settles to setup when tombstone / missing membership.
        self.coakley.pop("live_draft_room", None)
        self.coakley.pop("active_shared_draft_room_code", None)
        self.assertEqual(resolve_live_draft_lifecycle(self.coakley), LIFECYCLE_SETUP)

    def test_solo_host_may_auto_pick_any_on_clock_team(self) -> None:
        room = _two_team_room(status="in_progress")
        room["config"] = dict(room.get("config") or {})
        room["config"]["draft_setup_mode"] = "solo"
        room["current_pick_index"] = 1
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        self.assertTrue(participant_may_auto_pick(session, room, on_clock_team="Team B"))
        self.assertTrue(participant_may_auto_pick(session, room, on_clock_team="Team A"))

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_auto_pick_permissions(self, *_mocks: object) -> None:
        room = _two_team_room(status="in_progress")
        room["current_pick_index"] = 1  # Team B on clock
        code, doc = create_and_host_shared_room(self.daniel, room, host_team="Team A", store=self.store)
        join_shared_draft_room(self.coakley, code, store=self.store)
        live = dict(room)
        live["status"] = "in_progress"
        live["current_pick_index"] = 1
        self.coakley["draft_room_participant_team"] = "Team B"
        self.daniel["draft_room_participant_team"] = "Team A"
        self.assertTrue(participant_may_auto_pick(self.coakley, live, document=doc, on_clock_team="Team B"))
        self.assertFalse(participant_may_auto_pick(self.coakley, live, document=doc, on_clock_team="Team A"))
        self.assertTrue(participant_may_auto_pick(self.daniel, live, document=doc, on_clock_team="Team A"))
        self.assertTrue(participant_may_auto_pick(self.daniel, live, document=doc, on_clock_team="Team B"))

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    @mock.patch("draft_room_membership.ensure_authenticated_for_shared_room", return_value=(True, ""))
    def test_save_continue_resume_lobby_gate(self, *_mocks: object) -> None:
        room = _two_team_room(status="in_progress")
        room["draft_board"] = [{"Pick": 1, "Team": "Team A", "Player": "P1"}]
        room["current_pick_index"] = 1
        code, doc = create_and_host_shared_room(self.daniel, room, host_team="Team A", store=self.store)
        join_shared_draft_room(self.coakley, code, store=self.store)
        self.daniel["live_draft_room"] = dict(self.daniel.get("live_draft_room") or room)
        self.daniel["live_draft_room"]["status"] = "in_progress"
        self.daniel["live_draft_room"]["current_pick_index"] = 1
        self.daniel["live_draft_room"]["draft_board"] = list(room["draft_board"])
        self.daniel["active_shared_draft_room_code"] = code

        saved = save_and_continue_later(self.daniel, st=None, replace_existing=True)
        self.assertTrue(saved.get("ok"), saved)
        self.assertEqual(resolve_live_draft_lifecycle(self.daniel), LIFECYCLE_SETUP)

        parked = load_shared_room(code)
        self.assertEqual(str((parked or {}).get("status") or "").lower(), "saved_for_later")

        cont = continue_saved_draft(self.daniel, st=None)
        self.assertTrue(cont.get("ok"), cont)
        self.assertTrue(cont.get("resume_lobby") or self.daniel.get("_live_draft_resume_lobby"))
        self.assertEqual(str(self.daniel["live_draft_room"].get("status")), "paused")

        doc2 = load_shared_room(code)
        rows = resume_lobby_rows(self.daniel, doc2)
        self.assertGreaterEqual(len(rows), 1)
        ready, ready_n, total_n = all_required_participants_rejoined(self.daniel, doc2)
        # Coakley has not rejoined this browser session.
        self.assertGreaterEqual(total_n, 2)
        self.assertFalse(ready)
        blocked = continue_draft_from_resume_lobby(self.daniel, st=None, document=doc2)
        self.assertFalse(blocked.get("ok"))

        # Simulate Coakley rejoin into lobby.
        join_shared_draft_room(self.coakley, code, store=self.store)
        doc3 = load_shared_room(code)
        # Daniel also marks rejoined via continue_saved_draft session.
        if isinstance(doc3, dict):
            from live_draft_resume_lobby import mark_resume_rejoined
            from draft_room_shared_state import bump_revision

            doc3 = mark_resume_rejoined(doc3, participant_id="daniel-pid")
            doc3 = mark_resume_rejoined(doc3, participant_id="coakley-pid")
            self.store.save(bump_revision(doc3))
            doc3 = load_shared_room(code)
        ready2, _, _ = all_required_participants_rejoined(self.daniel, doc3)
        self.assertTrue(ready2)
        resumed = continue_draft_from_resume_lobby(self.daniel, st=None, document=doc3)
        self.assertTrue(resumed.get("ok"), resumed)
        self.assertEqual(int(self.daniel["live_draft_room"].get("current_pick_index") or 0), 1)
        self.assertFalse(self.daniel.get("_live_draft_resume_lobby"))


class AliasPollutionTests(unittest.TestCase):
    def test_session_aliases_exclude_sibling_membership_pids(self) -> None:
        session = {
            "draft_room_participant_id": "guest-1",
            MEMBERSHIP_KEY: {
                "ABC123": {
                    "host-1": {"participant_id": "host-1", "assigned_team": "Team A"},
                    "guest-1": {"participant_id": "guest-1", "assigned_team": "Team B"},
                }
            },
        }
        aliases = session_identity_aliases(session)
        self.assertIn("guest-1", aliases)
        self.assertNotIn("host-1", aliases)


if __name__ == "__main__":
    unittest.main()
