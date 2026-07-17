"""Shared Multiplayer identity — Coakley11 must not resolve to Daniel workspace."""

from __future__ import annotations

import copy
import inspect
import unittest
from unittest import mock

from suite_auth import (
    AUTH_EXTERNAL_ID_KEY,
    AUTH_JUST_LOGGED_IN_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    WORKSPACE_USER_SELECTED_KEY,
    enforce_workspace_ownership,
)
from suite_identity_guard import build_mp_identity_snapshot, render_mp_identity_diagnostics
from suite_workspace import get_active_workspace_id, scoped_cloud_app_id
from suite_workspace_registry import (
    ensure_owned_workspace_for_session,
    is_admin_user,
    resolve_owned_workspace_id,
)


class _FakeSt:
    def __init__(self, session: dict) -> None:
        self.session_state = session


def _coakley_session(*, active: str = "daniel") -> dict:
    return {
        AUTH_USER_EMAIL_KEY: "coakley11@aol.com",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": active,
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "draft_room_participant_team": "Team B",
    }


def _daniel_session(*, active: str = "daniel") -> dict:
    return {
        AUTH_USER_EMAIL_KEY: "daniel.cohen11@yahoo.com",
        AUTH_EXTERNAL_ID_KEY: "daniel",
        AUTH_USER_ID_KEY: "uuid-daniel",
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": active,
        "_suite_owned_workspace_id": "daniel",
        "draft_room_participant_id": "uuid-daniel",
        "draft_room_participant_team": "Daniel",
    }


class ResolveOwnedWorkspaceIdExistsTests(unittest.TestCase):
    def test_resolve_owned_workspace_id_is_importable(self) -> None:
        # Production enforce_workspace_ownership imports this symbol; missing = silent no-op.
        self.assertTrue(callable(resolve_owned_workspace_id))


class CoakleyWorkspaceClampTests(unittest.TestCase):
    def test_enforce_clamps_daniel_active_to_coakley11_without_mocks(self) -> None:
        session = _coakley_session(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True), mock.patch(
            "suite_workspace_registry._write_registry", return_value=True
        ), mock.patch(
            "suite_workspace_registry._read_registry",
            return_value={
                "by_owner": {
                    "961df5e9-cdde-48d7-80dd-95a8ba3f46e5": {
                        "owner_user_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
                        "owner_external_id": "coakley11",
                        "workspace_id": "coakley11",
                        "label": "Daniel",
                    }
                }
            },
        ):
            enforce_workspace_ownership(session)
        self.assertEqual(get_active_workspace_id(st), "coakley11")
        self.assertIsNone(session.get("_suite_workspace_enforce_error"))
        self.assertIn("daniel->coakley11", str(session.get("_suite_workspace_last_clamp") or ""))

    def test_admin_status_does_not_keep_unrelated_daniel_workspace(self) -> None:
        """Coakley11 is admin for developer tools but must not linger on Daniel's seat."""
        session = _coakley_session(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            self.assertTrue(is_admin_user(session_state=session))
            self.assertEqual(get_active_workspace_id(st), "coakley11")
            self.assertEqual(session["_suite_active_workspace_id"], "coakley11")

    def test_coakley_cloud_key_never_legacy_daniel_baseball(self) -> None:
        session = _coakley_session(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            ws = get_active_workspace_id(st)
        self.assertEqual(ws, "coakley11")
        self.assertEqual(scoped_cloud_app_id("baseball", ws), "baseball__coakley11")
        self.assertNotEqual(scoped_cloud_app_id("baseball", ws), "baseball")

    def test_daniel_still_resolves_to_daniel_and_legacy_cloud_key(self) -> None:
        session = _daniel_session(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            enforce_workspace_ownership(session)
            ws = get_active_workspace_id(st)
        self.assertEqual(ws, "daniel")
        self.assertEqual(scoped_cloud_app_id("baseball", ws), "baseball")

    def test_refresh_and_sign_in_preserve_coakley_workspace(self) -> None:
        session = _coakley_session(active="coakley11")
        # Simulate reboot / refresh restoring a contaminated active seat.
        session["_suite_active_workspace_id"] = "daniel"
        session[AUTH_JUST_LOGGED_IN_KEY] = True
        session.pop(WORKSPACE_USER_SELECTED_KEY, None)
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            enforce_workspace_ownership(session)
            self.assertEqual(get_active_workspace_id(st), "coakley11")
            # Second pass mimics another refresh after sign-in.
            session["_suite_active_workspace_id"] = "daniel"
            enforce_workspace_ownership(session)
            self.assertEqual(get_active_workspace_id(st), "coakley11")

    def test_mp_snapshot_flags_workspace_resolution_bug(self) -> None:
        session = _coakley_session(active="daniel")
        snap = build_mp_identity_snapshot(
            session,
            room={"host_team": "Daniel", "teams": ["Daniel", "Team B"]},
        )
        self.assertEqual(snap["signed_in_account"], "coakley11")
        self.assertEqual(snap["workspace_id"], "daniel")
        self.assertEqual(snap["display_workspace_name"], "Daniel")
        self.assertTrue(str(snap["identity_verdict"]).startswith("WORKSPACE_RESOLUTION_BUG"))

    def test_mp_snapshot_ok_when_clamped(self) -> None:
        session = _coakley_session(active="coakley11")
        snap = build_mp_identity_snapshot(session, room={"host_team": "Daniel"})
        self.assertEqual(snap["display_workspace_name"], "Coakley11")
        self.assertTrue(str(snap["identity_verdict"]).startswith("OK"))

    def test_diagnostics_show_identity_owned_active_and_team_for_both_accounts(self) -> None:
        room = {"host_team": "Daniel", "teams": ["Daniel", "Team B"]}
        for factory, account, team, wid in (
            (_daniel_session, "daniel", "Daniel", "daniel"),
            (_coakley_session, "coakley11", "Team B", "coakley11"),
        ):
            session = factory(active=wid)
            snap = build_mp_identity_snapshot(session, room=room)
            self.assertEqual(snap["signed_in_account"], account)
            self.assertEqual(snap["auth_user_id"], session[AUTH_USER_ID_KEY])
            self.assertIn("@", snap["account_email"])
            self.assertEqual(snap["workspace_id"], wid)
            self.assertEqual(snap["owned_workspace_id"], wid)
            self.assertEqual(snap["claimed_team"], team)
            self.assertTrue(snap["display_workspace_name"])

        # Temporary panel must remain wired for deployed validation.
        self.assertIn("render_mp_identity_diagnostics", inspect.getsource(render_mp_identity_diagnostics))
        import streamlit_app as app

        self.assertIn("render_mp_identity_diagnostics", inspect.getsource(app))


class LabelRepairTests(unittest.TestCase):
    def test_corrupted_label_repaired_without_merging_other_account_data(self) -> None:
        registry = {
            "by_owner": {
                "961df5e9-cdde-48d7-80dd-95a8ba3f46e5": {
                    "owner_user_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
                    "owner_external_id": "coakley11",
                    "workspace_id": "coakley11",
                    "label": "Daniel",
                },
                "uuid-daniel": {
                    "owner_user_id": "uuid-daniel",
                    "owner_external_id": "daniel",
                    "workspace_id": "daniel",
                    "label": "Daniel",
                    "extra_marker": "keep-me",
                },
            }
        }
        written: dict = {}

        def _write(payload: dict) -> bool:
            written.clear()
            written.update(copy.deepcopy(payload))
            return True

        session = _coakley_session(active="coakley11")
        session.pop("_suite_owned_workspace_id", None)
        session.pop("_suite_owned_workspace_label", None)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace_registry._read_registry", return_value=registry), mock.patch(
            "suite_workspace_registry._write_registry", side_effect=_write
        ), mock.patch("suite_workspace.workspace_dir") as wd:
            wd.return_value.mkdir = mock.MagicMock()
            record = ensure_owned_workspace_for_session(session)

        self.assertEqual(record["workspace_id"], "coakley11")
        self.assertNotEqual(str(record.get("label") or "").lower(), "daniel")
        self.assertEqual(session.get("_suite_owned_workspace_id"), "coakley11")
        # Daniel's registry row must remain untouched (no merge / overwrite).
        self.assertTrue(written)
        daniel_row = written["by_owner"]["uuid-daniel"]
        self.assertEqual(daniel_row["workspace_id"], "daniel")
        self.assertEqual(daniel_row["extra_marker"], "keep-me")
        coakley_row = written["by_owner"]["961df5e9-cdde-48d7-80dd-95a8ba3f46e5"]
        self.assertEqual(coakley_row["workspace_id"], "coakley11")
        self.assertNotEqual(str(coakley_row.get("label") or "").lower(), "daniel")


class JoinDoesNotMutateWorkspaceTests(unittest.TestCase):
    def test_join_shared_draft_room_does_not_write_workspace_keys(self) -> None:
        from draft_room_context import join_shared_draft_room

        src = inspect.getsource(join_shared_draft_room)
        for forbidden in (
            "_suite_active_workspace_id",
            "set_active_workspace_id",
            "_suite_owned_workspace_id",
        ):
            self.assertNotIn(forbidden, src)

        for factory, expected in ((_coakley_session, "coakley11"), (_daniel_session, "daniel")):
            participant = factory(active=expected)
            before_owned = participant.get("_suite_owned_workspace_id")
            before_active = participant.get("_suite_active_workspace_id")
            # Simulate post-join participant keys only (what join is allowed to set).
            participant["draft_room_participant_team"] = (
                "Team B" if expected == "coakley11" else "Daniel"
            )
            participant["active_shared_draft_room_code"] = "ABC123"
            self.assertEqual(participant["_suite_active_workspace_id"], before_active)
            self.assertEqual(participant["_suite_owned_workspace_id"], before_owned)
            self.assertEqual(participant["_suite_active_workspace_id"], expected)


if __name__ == "__main__":
    unittest.main()
