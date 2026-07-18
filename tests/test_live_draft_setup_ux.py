"""Shared multiplayer draft setup UX — lobby, team claim, setup visibility."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room
from draft_room_membership import resolve_join_team_assignment
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LocalFileSharedRoomStore
from live_draft_setup_mode import (
    SETUP_MODE_SHARED,
    is_shared_lobby,
    setup_is_read_only,
    should_hide_legacy_shared_panel,
    should_show_full_draft_setup,
    finalize_shared_room_create,
    set_live_draft_setup_mode,
)
from live_draft_team_ownership import open_teams_for_join, team_claim_rows


def _sample_room(**overrides) -> dict:
    pool = pd.DataFrame([{"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"}])
    room = {
        "draft_room_id": "UX1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {"num_teams": 3, "your_team": "Danny", "teams": ["Danny", "Amiel", "Team 3"]},
        "teams": ["Danny", "Amiel", "Team 3"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Danny"},
            {"Pick": 2, "Round": 1, "Team": "Amiel"},
            {"Pick": 3, "Round": 1, "Team": "Team 3"},
        ],
        "draft_board": [],
        "rosters": {"Danny": [], "Amiel": [], "Team 3": []},
        "drafted_player_ids": [],
        "pool": pool,
    }
    room.update(overrides)
    return room


def _shared_doc(room: dict, **overrides) -> dict:
    doc = {
        "schema_version": 1,
        "room_code": "ABC123",
        "draft_room_id": room["draft_room_id"],
        "revision": 1,
        "status": "open",
        "host_participant_id": "host-user",
        "host_user_id": "host-user",
        "participants": {
            "host-user": {
                "assigned_team": "Danny",
                "display_name": "Danny",
                "joined_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "room": room,
    }
    doc.update(overrides)
    return doc


class SetupVisibilityTests(unittest.TestCase):
    def test_full_setup_only_before_room_exists(self) -> None:
        self.assertTrue(should_show_full_draft_setup({}))
        self.assertFalse(should_show_full_draft_setup({}, room=_sample_room()))

    def test_shared_lobby_detected(self) -> None:
        session = {"live_draft_setup_mode": SETUP_MODE_SHARED}
        room = _sample_room(status="not_started")
        self.assertTrue(is_shared_lobby(session, room))

    def test_setup_read_only_after_first_pick(self) -> None:
        room = _sample_room(
            status="in_progress",
            draft_board=[{"Pick": 1, "Team": "Danny", "Player": "Aaron Judge"}],
        )
        self.assertTrue(setup_is_read_only(room))

    def test_legacy_panel_hidden_when_room_code_exists(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            "live_draft_room": _sample_room(),
        }
        self.assertTrue(should_hide_legacy_shared_panel(session))


class TeamClaimTests(unittest.TestCase):
    def test_join_auto_assigns_when_exactly_one_open(self) -> None:
        doc = _shared_doc(_sample_room())
        # Danny claimed; Amiel + Team 3 open → requires selection
        team, err = resolve_join_team_assignment(doc, "guest-user", requested_team=None)
        self.assertIsNone(team)
        self.assertIn("Choose a team", err)

    def test_join_auto_assigns_sole_open_team(self) -> None:
        room = _sample_room()
        room["teams"] = ["Danny", "Amiel"]
        room["config"] = {**dict(room.get("config") or {}), "num_teams": 2}
        doc = _shared_doc(room)
        team, err = resolve_join_team_assignment(doc, "guest-user", requested_team=None)
        self.assertEqual(team, "Amiel")
        self.assertEqual(err, "")

    def test_join_accepts_requested_open_team(self) -> None:
        doc = _shared_doc(_sample_room())
        team, err = resolve_join_team_assignment(doc, "guest-user", requested_team="Amiel")
        self.assertEqual(team, "Amiel")
        self.assertEqual(err, "")

    def test_open_teams_excludes_host_claim(self) -> None:
        doc = _shared_doc(_sample_room())
        open_teams = open_teams_for_join(doc)
        self.assertIn("Amiel", open_teams)
        self.assertIn("Team 3", open_teams)
        self.assertNotIn("Danny", open_teams)

    def test_team_claim_rows_show_host_and_open(self) -> None:
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123"}
        room = _sample_room()
        doc = _shared_doc(room)
        rows = team_claim_rows(session, room, document=doc)
        by_team = {r["team"]: r for r in rows}
        self.assertTrue(by_team["Danny"]["claimed"])
        self.assertTrue(by_team["Danny"]["is_host"])
        self.assertFalse(by_team["Amiel"]["claimed"])


class GuestJoinIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_guest_joins_with_explicit_team(self, _auth: object) -> None:
        session = {"draft_room_participant_id": "host-user", "live_draft_setup_mode": SETUP_MODE_SHARED}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(session, room, host_team="Danny", store=self.store)
        guest = {"draft_room_participant_id": "guest-user"}
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Amiel", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(str(guest.get("draft_room_participant_team") or ""), "Amiel")


class ReadyCardRenderTests(unittest.TestCase):
    @mock.patch("live_draft_setup_ui._is_room_host", return_value=True)
    @mock.patch("live_draft_setup_ui.start_button_disabled", return_value=(False, ""))
    @mock.patch("live_draft_setup_ui.count_joined_teams", return_value=(1, 3))
    @mock.patch("live_draft_setup_ui.shared_room_code", return_value="ABC123")
    @mock.patch("live_draft_setup_ui.is_shared_multiplayer_intent", return_value=True)
    def test_host_sees_start_live_draft_button(
        self,
        _intent: object,
        _code: object,
        _count: object,
        _disabled: object,
        _host: object,
    ) -> None:
        from live_draft_setup_ui import render_shared_draft_ready_card

        st = mock.MagicMock()
        session = {"live_draft_setup_mode": SETUP_MODE_SHARED}
        room = _sample_room(status="not_started")
        render_shared_draft_ready_card(st, session, room, on_start=lambda: None)
        start_calls = [
            c for c in st.button.call_args_list if c.args and "Start Live Draft" in str(c.args[0])
        ]
        self.assertEqual(len(start_calls), 1, st.button.call_args_list)
        self.assertEqual(start_calls[0].kwargs.get("type"), "primary")
        # Canonical Copy lives on the waiting-room header, not the ready card.
        self.assertFalse(
            any(c.args and c.args[0] == "Copy room code" for c in st.button.call_args_list),
            st.button.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
