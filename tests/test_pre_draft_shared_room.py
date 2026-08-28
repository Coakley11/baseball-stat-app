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
from draft_ui import on_join_shared_draft_from_setup, on_prepare_shared_draft_room
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

    def test_join_on_click_sets_pending_before_handler(self) -> None:
        import streamlit as st

        session: dict = {
            "live_draft_join_code_input": "abc123",
            "live_draft_join_team_pick": "",
        }
        with mock.patch.object(st, "session_state", session):
            on_join_shared_draft_from_setup(
                requested_code="abc123",
                requested_team="Team 2",
                selectbox_return_value="Team 2",
            )
        self.assertTrue(session.get("_join_shared_draft_from_setup"))
        self.assertEqual(session.get("_join_requested_code"), "ABC123")
        self.assertEqual(session.get("_join_requested_team"), "Team 2")
        self.assertGreaterEqual(int(session.get("_join_button_callback_count") or 0), 1)
        join_diag = session.get("_draft_room_join_diag") or {}
        self.assertTrue(join_diag.get("join_attempted"))
        self.assertEqual(join_diag.get("join_code"), "ABC123")
        self.assertEqual(join_diag.get("selectbox_return_value"), "Team 2")
        self.assertEqual(join_diag.get("session_team_widget_value"), "")


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
        self.assertTrue(
            any(tok in reason.lower() for tok in ("participant", "manager", "claim", "join", "two distinct")),
            reason,
        )

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
        self._patch_ctx = mock.patch("draft_room_context.get_shared_room_store", return_value=self.store)
        self._auth = mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
        self._save_patch = mock.patch("baseball_persistent_state.force_save_baseball_state")
        self._patch.start()
        self._patch_ctx.start()
        self._auth.start()
        self._save_mock = self._save_patch.start()

    def tearDown(self) -> None:
        self._save_patch.stop()
        self._auth.stop()
        self._patch_ctx.stop()
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

    def _seed_host_room(self, *, guest_team: str = "Team 2") -> tuple[str, dict]:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = apptest_build_not_started_room(["Daniel", guest_team], host_team="Daniel")
        code, err = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        self.assertFalse(err, err)
        assert code
        return code, host

    def test_seeded_room_exposes_team_2_in_join_lookup(self) -> None:
        code, _host = self._seed_host_room()
        teams, err = lookup_open_teams_for_code(code, store=self.store)
        self.assertEqual(err, "")
        self.assertEqual(teams, ["Team 2"])

    def test_guest_join_one_click_shows_success_and_same_room(self) -> None:
        code, host = self._seed_host_room()
        fixture = Path(__file__).resolve().parent / "fixtures" / "pre_draft_guest_join_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["draft_room_participant_id"] = "coakley-user"
        at.session_state[AUTH_USER_ID_KEY] = "coakley-user"
        at.session_state["live_draft_join_code_input"] = code
        at.run()
        team_pick = at.selectbox(key="live_draft_join_team_pick")
        self.assertIsNotNone(team_pick, "Team 2 should appear after valid code entry")
        team_pick.set_value("Team 2").run()
        at.button(key="live_draft_join_from_setup_btn").click().run()
        blob = "\n".join(
            str(m.value)
            for group in (at.markdown, at.success, at.error)
            for m in group
        )
        self.assertIn("Joined room", blob, blob)
        self.assertIn(code, blob, blob)
        self.assertEqual(str(at.session_state["active_shared_draft_room_code"] or "").upper(), code)
        self.assertIn("GUEST_TEAM:Team 2", blob, blob)
        host_room_id = (host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id")
        guest_room_id = (at.session_state["live_draft_room"] or {}).get("draft_room_id")
        self.assertEqual(host_room_id, guest_room_id)

    def test_guest_join_single_option_team_b_without_manual_toggle(self) -> None:
        """Reproduce live HS75UK case: one open team visible, widget session key still blank."""
        code, host = self._seed_host_room(guest_team="Team B")
        fixture = Path(__file__).resolve().parent / "fixtures" / "pre_draft_guest_join_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["draft_room_participant_id"] = "coakley-user"
        at.session_state[AUTH_USER_ID_KEY] = "coakley-user"
        at.session_state["live_draft_join_code_input"] = code
        at.run()
        team_pick = at.selectbox(key="live_draft_join_team_pick")
        self.assertIsNotNone(team_pick, "Team B selectbox should render for valid code")
        self.assertEqual(list(team_pick.options), ["Team B"])
        at.button(key="live_draft_join_from_setup_btn").click().run()
        blob = "\n".join(
            str(m.value)
            for group in (at.markdown, at.success, at.error)
            for m in group
        )
        self.assertIn("Joined room", blob, blob)
        self.assertIn(code, blob, blob)
        self.assertIn("GUEST_TEAM:Team B", blob, blob)
        self.assertEqual(str(at.session_state["active_shared_draft_room_code"] or "").upper(), code)
        host_room_id = (host.get(LIVE_DRAFT_ROOM_KEY) or {}).get("draft_room_id")
        guest_room_id = (at.session_state["live_draft_room"] or {}).get("draft_room_id")
        self.assertEqual(host_room_id, guest_room_id)
        join_diag = dict(at.session_state["_draft_room_join_diag"]) if "_draft_room_join_diag" in at.session_state else {}
        self.assertEqual(str(join_diag.get("selectbox_return_value") or ""), "Team B")
        self.assertTrue(join_diag.get("room_lookup_attempted"))
        self.assertTrue(join_diag.get("claim_attempted"))
        self.assertTrue(join_diag.get("claim_ok"))

    def test_join_processor_rejects_multiple_open_teams_without_capture(self) -> None:
        import streamlit as st

        from live_draft_setup_ui import render_guest_join_from_setup

        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = apptest_build_not_started_room(["Daniel", "Team B", "Team C"], host_team="Daniel")
        code, err = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        self.assertFalse(err, err)
        assert code
        session: dict = {
            "draft_room_participant_id": "coakley-user",
            AUTH_USER_ID_KEY: "coakley-user",
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": code,
            "_join_requested_team": "",
            "_join_selectbox_return_value": "",
            "_join_session_team_widget_value": "",
        }
        with mock.patch.object(st, "session_state", session):
            joined = render_guest_join_from_setup(st, session)
        self.assertFalse(joined)
        self.assertEqual(session.get("_draft_join_error"), "Choose a team before joining.")
        join_diag = session.get("_draft_room_join_diag") or {}
        self.assertFalse(join_diag.get("claim_attempted"))
        self.assertTrue(join_diag.get("room_lookup_attempted"))

    def test_guest_join_multiple_open_teams_with_explicit_selection(self) -> None:
        host = {"draft_room_participant_id": "daniel-user", AUTH_USER_ID_KEY: "daniel-user"}
        set_live_draft_setup_mode(host, SETUP_MODE_SHARED)
        room = apptest_build_not_started_room(["Daniel", "Team B", "Team C"], host_team="Daniel")
        code, err = finalize_shared_room_create(host, room, host_team="Daniel", store=self.store)
        self.assertFalse(err, err)
        assert code
        fixture = Path(__file__).resolve().parent / "fixtures" / "pre_draft_guest_join_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["draft_room_participant_id"] = "coakley-user"
        at.session_state[AUTH_USER_ID_KEY] = "coakley-user"
        at.session_state["live_draft_join_code_input"] = code
        at.run()
        at.selectbox(key="live_draft_join_team_pick").set_value("Team C").run()
        at.button(key="live_draft_join_from_setup_btn").click().run()
        blob = "\n".join(str(m.value) for group in (at.markdown, at.success) for m in group)
        self.assertIn("Joined room", blob, blob)
        self.assertIn("GUEST_TEAM:Team C", blob, blob)

    def test_guest_join_invalid_code_shows_error(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "pre_draft_guest_join_apptest.py"
        at = self.AppTest.from_file(str(fixture), default_timeout=120)
        at.session_state["draft_room_participant_id"] = "coakley-user"
        at.session_state[AUTH_USER_ID_KEY] = "coakley-user"
        at.run()
        at.text_input(key="live_draft_join_code_input").set_value("ZZZZZZ").run()
        at.session_state["live_draft_join_team_pick"] = "Team 2"
        at.button(key="live_draft_join_from_setup_btn").click().run()
        blob = "\n".join(str(m.value) for m in at.error)
        self.assertIn(ROOM_NOT_FOUND_MSG, blob, blob)

    def test_join_handler_surfaces_already_claimed_error(self) -> None:
        import streamlit as st

        from draft_room_membership import ERR_TEAM_ALREADY_ASSIGNED
        from live_draft_setup_ui import render_guest_join_from_setup

        code, _host = self._seed_host_room()
        session: dict = {
            "draft_room_participant_id": "other-user",
            AUTH_USER_ID_KEY: "other-user",
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": code,
            "_join_requested_team": "Team 2",
            "live_draft_join_code_input": code,
            "live_draft_join_team_pick": "Team 2",
        }
        with mock.patch(
            "draft_room_context.join_shared_draft_room",
            return_value=(False, ERR_TEAM_ALREADY_ASSIGNED, None),
        ):
            with mock.patch.object(st, "session_state", session):
                joined = render_guest_join_from_setup(st, session)
        self.assertFalse(joined)
        self.assertEqual(session.get("_draft_join_error"), "Team is already claimed")
        join_diag = session.get("_draft_room_join_diag") or {}
        self.assertTrue(join_diag.get("claim_attempted"))

    def test_join_processor_single_team_fallback_when_capture_blank(self) -> None:
        import streamlit as st

        from live_draft_setup_ui import render_guest_join_from_setup

        code, _host = self._seed_host_room(guest_team="Team B")
        session: dict = {
            "draft_room_participant_id": "coakley-user",
            AUTH_USER_ID_KEY: "coakley-user",
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": code,
            "_join_requested_team": "",
            "_join_selectbox_return_value": "",
            "_join_session_team_widget_value": "",
        }
        with mock.patch.object(st, "session_state", session):
            joined = render_guest_join_from_setup(st, session)
        self.assertTrue(joined)
        self.assertEqual(str(session.get("_draft_join_flash") or ""), f"Joined room {code} as Team B.")
        join_diag = session.get("_draft_room_join_diag") or {}
        self.assertTrue(join_diag.get("team_fallback_used"))
        self.assertTrue(join_diag.get("room_lookup_attempted"))
        self.assertTrue(join_diag.get("claim_attempted"))
        self.assertTrue(join_diag.get("claim_ok"))

    def test_setup_join_force_saves_workspace_membership(self) -> None:
        import streamlit as st

        from live_draft_setup_ui import render_guest_join_from_setup

        code, _host = self._seed_host_room(guest_team="Team B")
        session: dict = {
            "draft_room_participant_id": "coakley-user",
            AUTH_USER_ID_KEY: "coakley-user",
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": code,
            "_join_requested_team": "Team B",
            "live_draft_join_code_input": code,
            "live_draft_join_team_pick": "Team B",
        }
        with mock.patch.object(st, "session_state", session):
            joined = render_guest_join_from_setup(st, session)
        self.assertTrue(joined)
        self.assertTrue(
            any(call.kwargs.get("reason") == "shared_draft_join" for call in self._save_mock.call_args_list),
            self._save_mock.call_args_list,
        )
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), code)
        self.assertTrue(session.get("draft_room_participant_membership"))


if __name__ == "__main__":
    unittest.main()
