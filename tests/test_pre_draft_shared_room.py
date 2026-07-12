"""Pre-draft shared draft room — create, join code, lobby, and start gates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import join_shared_draft_room, resolve_shared_room_code
from draft_room_create_verify import is_plausible_share_code, load_shared_room_with_diagnostics
from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, LIVE_DRAFT_ROOM_KEY, LocalFileSharedRoomStore
from draft_ui import on_prepare_shared_draft_room
from live_draft_setup_mode import (
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    can_start_live_draft,
    finalize_shared_room_create,
    set_live_draft_setup_mode,
    shared_room_code,
)
from live_draft_team_ownership import ROOM_NOT_FOUND_MSG, distinct_claimed_owner_count, lookup_open_teams_for_code
from suite_auth import AUTH_USER_ID_KEY


def _sample_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )


def apptest_build_not_started_room(team_names: list[str], *, host_team: str) -> dict:
    teams = [str(t).strip() for t in team_names if str(t).strip()]
    pick_order = [{"Pick": i + 1, "Round": 1, "Team": teams[i % len(teams)]} for i in range(len(teams))]
    return {
        "draft_room_id": "PREDRAFT1",
        "status": "not_started",
        "current_pick_index": 0,
        "config": {
            "num_teams": len(teams),
            "your_team": host_team,
            "user_team": host_team,
            "teams": teams,
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": _sample_pool(),
    }


def _sample_room(**overrides) -> dict:
    room = apptest_build_not_started_room(["Daniel", "Team 2"], host_team="Daniel")
    room.update(overrides)
    return room


class PrepareSharedCallbackTests(unittest.TestCase):
    def test_on_click_sets_pending_and_mode_before_handler(self) -> None:
        import streamlit as st

        session: dict = {"live_draft_setup_mode": SETUP_MODE_SHARED}
        with mock.patch.object(st, "session_state", session):
            on_prepare_shared_draft_room()
        self.assertTrue(session.get("_start_live_draft_pending"))
        self.assertEqual(session.get("_start_live_draft_mode"), "prepare_shared")
        diag = session.get("_draft_room_create_diag") or {}
        self.assertGreaterEqual(int(diag.get("create_button_callback_count") or 0), 1)
        self.assertTrue(diag.get("room_create_attempted"))


class PreDraftSharedRoomCreateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._save_patch = mock.patch("baseball_persistent_state.force_save_baseball_state")
        self._patch.start()
        self._save_patch.start()

    def tearDown(self) -> None:
        self._save_patch.stop()
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_daniel_creates_two_team_room_with_join_code(self, _auth: object) -> None:
        session = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        room = _sample_room()
        code, err = finalize_shared_room_create(session, room, host_team="Daniel", store=self.store)
        self.assertFalse(err, err)
        self.assertEqual(len(code), 6)
        self.assertTrue(is_plausible_share_code(code))
        self.assertEqual(shared_room_code(session), code)
        self.assertEqual(str(room.get("status")), "not_started")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_room_persists_before_display(self, _auth: object) -> None:
        session = {"draft_room_participant_id": "daniel-user"}
        set_live_draft_setup_mode(session, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(session, room, host_team="Daniel", store=self.store)
        load = load_shared_room_with_diagnostics(self.store, code)
        self.assertTrue(load.get("found"))
        doc = load.get("document")
        assert isinstance(doc, dict)
        self.assertEqual(str(doc.get("room_code")).upper(), code)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_readback_by_code_returns_same_room(self, _auth: object) -> None:
        session = {"draft_room_participant_id": "daniel-user"}
        room = _sample_room()
        code, _ = finalize_shared_room_create(session, room, host_team="Daniel", store=self.store)
        load = self.store.load(code)
        assert isinstance(load, dict)
        self.assertEqual(str(load.get("draft_room_id")), "PREDRAFT1")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_coakley_joins_and_claims_team_2(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        guest = {"draft_room_participant_id": "coakley-user", AUTH_USER_ID_KEY: "coakley-user"}
        ok, msg, _ = join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        self.assertTrue(ok, msg)
        self.assertEqual(resolve_shared_room_code(guest), code)
        self.assertEqual(str(guest.get("draft_room_participant_team") or guest.get("room_your_team") or ""), "Team 2")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_daniel_keeps_team_ownership(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        guest = {"draft_room_participant_id": "coakley-user", AUTH_USER_ID_KEY: "coakley-user"}
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        self.assertEqual(str(host.get("room_your_team") or ""), "Daniel")
        doc = self.store.load(code)
        assert isinstance(doc, dict)
        participants = dict(doc.get("participants") or {})
        host_meta = participants.get("daniel-user") or {}
        self.assertEqual(str(host_meta.get("assigned_team")), "Daniel")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_two_distinct_owners_enable_start(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        guest = {"draft_room_participant_id": "coakley-user", AUTH_USER_ID_KEY: "coakley-user"}
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        host["live_draft_room"] = host.get(LIVE_DRAFT_ROOM_KEY) or room
        self.assertEqual(distinct_claimed_owner_count(host, host["live_draft_room"]), 2)
        ok, reason = can_start_live_draft(host)
        self.assertTrue(ok, reason)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_start_blocked_with_one_owner(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        host["live_draft_room"] = room
        ok, reason = can_start_live_draft(host)
        self.assertFalse(ok)
        self.assertIn("participant", reason.lower())

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_invalid_code_rejected(self, _auth: object) -> None:
        _teams, err = lookup_open_teams_for_code("ZZZZZZ", store=self.store)
        self.assertEqual(_teams, [])
        self.assertEqual(err, ROOM_NOT_FOUND_MSG)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_refresh_preserves_room_and_ownership(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        guest = {"draft_room_participant_id": "coakley-user", AUTH_USER_ID_KEY: "coakley-user"}
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        reloaded = {
            "draft_room_participant_id": "daniel-user",
            AUTH_USER_ID_KEY: "daniel-user",
            ACTIVE_SHARED_ROOM_CODE_KEY: code,
        }
        load = self.store.load(code)
        assert isinstance(load, dict)
        self.assertEqual(str(load.get("room_code")).upper(), code)
        self.assertEqual(shared_room_code({**reloaded, LIVE_DRAFT_ROOM_KEY: room}), code)

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_solo_mode_unaffected(self, _auth: object) -> None:
        session = {"live_draft_setup_mode": SETUP_MODE_SOLO}
        ok, _ = can_start_live_draft(session)
        self.assertTrue(ok)
        self.assertEqual(shared_room_code(session), "")

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_both_sessions_share_room_id(self, _auth: object) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = _sample_room()
        code, _ = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        guest = {"draft_room_participant_id": "coakley-user", AUTH_USER_ID_KEY: "coakley-user"}
        join_shared_draft_room(guest, code, requested_team="Team 2", store=self.store)
        host_room = host.get(LIVE_DRAFT_ROOM_KEY) or {}
        guest_room = guest.get(LIVE_DRAFT_ROOM_KEY) or {}
        self.assertEqual(host_room.get("draft_room_id"), guest_room.get("draft_room_id"))


class PreDraftSharedRoomAppTestLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError as exc:
            raise unittest.SkipTest(f"streamlit.testing.v1.AppTest unavailable: {exc}") from exc
        cls.AppTest = AppTest

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._patch.start()
        self._auth.start()

    def tearDown(self) -> None:
        self._auth.stop()
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_create_shared_draft_room_shows_join_code(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "pre_draft_shared_room_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["live_draft_team_name_0"] = "Daniel"
        at.session_state["live_draft_team_name_1"] = "Team 2"
        at.session_state["room_your_team"] = "Daniel"
        at.run()
        btn = at.button(key="live_draft_prepare_shared_btn")
        self.assertIsNotNone(btn, "Create Shared Draft Room button not found")
        btn.click().run()
        blob = "\n".join(str(m.value) for m in at.markdown)
        success_blob = "\n".join(str(m.value) for m in at.success)
        combined = blob + "\n" + success_blob
        self.assertIn("JOIN_CODE_VISIBLE:", combined, combined)
        code = ""
        for line in combined.splitlines():
            if "JOIN_CODE_VISIBLE:" in line or "LOBBY_JOIN_CODE:" in line:
                code = line.split(":")[-1].strip().strip("*").strip("`")
        if not code and "active_shared_draft_room_code" in at.session_state:
            code = str(at.session_state["active_shared_draft_room_code"] or "").upper()
        self.assertEqual(len(code), 6, combined)
        self.assertIn(code, combined)


if __name__ == "__main__":
    unittest.main()
