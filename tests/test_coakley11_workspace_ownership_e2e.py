"""End-to-end: Coakley11 must never render or load Daniel's workspace."""

from __future__ import annotations

import unittest
from unittest import mock

from baseball_account_sidebar import prepare_baseball_auth_session, render_baseball_account_sidebar
from suite_auth import (
    AUTH_EXTERNAL_ID_KEY,
    AUTH_JUST_LOGGED_IN_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    account_scoped_workspace_target,
    enforce_workspace_ownership,
    hard_clamp_owned_workspace_before_scoped_load,
)
from suite_identity_guard import build_mp_identity_snapshot
from suite_workspace import get_active_workspace_id, scoped_cloud_app_id, workspace_label
from suite_workspace_registry import is_admin_user


class _FakeSt:
    def __init__(self, session: dict) -> None:
        self.session_state = session
        self.sidebar = mock.MagicMock()
        self.sidebar.expander.return_value.__enter__ = mock.MagicMock(return_value=self)
        self.sidebar.expander.return_value.__exit__ = mock.MagicMock(return_value=False)
        self.caption = mock.MagicMock()
        self.warning = mock.MagicMock()
        self.markdown = mock.MagicMock()


def _coakley(*, active: str = "daniel") -> dict:
    return {
        AUTH_USER_EMAIL_KEY: "coakley11@aol.com",
        AUTH_EXTERNAL_ID_KEY: "coakley11",
        AUTH_USER_ID_KEY: "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "_suite_auth_session": True,
        "_suite_auth_access_token": "tok",
        "_suite_active_workspace_id": active,
        "_suite_owned_workspace_id": "coakley11",
        "draft_room_participant_id": "961df5e9-cdde-48d7-80dd-95a8ba3f46e5",
        "draft_room_participant_team": "Team B",
    }


class Coakley11WorkspaceOwnershipE2ETests(unittest.TestCase):
    def test_page_init_clamps_daniel_and_scopes_cloud_key(self) -> None:
        session = _coakley(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True), mock.patch(
            "suite_auth.restore_auth_session"
        ):
            # Real page-init order: auth prepare → hard clamp → sidebar label.
            prepare_baseball_auth_session(st)
            hard_clamp_owned_workspace_before_scoped_load(session)
            self.assertTrue(is_admin_user(session_state=session))
            self.assertEqual(account_scoped_workspace_target(session), "coakley11")
            self.assertEqual(get_active_workspace_id(st), "coakley11")
            self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
            self.assertEqual(scoped_cloud_app_id("baseball", get_active_workspace_id(st)), "baseball__coakley11")
            self.assertNotEqual(workspace_label(get_active_workspace_id(st)), "Daniel")

            captions: list[str] = []

            def _cap(text: str, *args: object, **kwargs: object) -> None:
                captions.append(str(text))

            st.caption = _cap
            with mock.patch(
                "baseball_account_sidebar.account_sidebar_should_render", return_value=True
            ), mock.patch(
                "baseball_account_sidebar.real_account_status",
                return_value={
                    "auth_enabled": True,
                    "signed_in": True,
                    "email": "coakley11@aol.com",
                    "auth_user_id": session[AUTH_USER_ID_KEY],
                    "message": "ok",
                },
            ), mock.patch(
                "baseball_account_sidebar._dev_auth_details_visible", return_value=False
            ), mock.patch("suite_auth.render_auth_panel"):
                render_baseball_account_sidebar(st)
            joined = " ".join(captions)
            self.assertNotIn("Workspace: **Daniel**", joined)
            self.assertIn("Coakley11", joined)

    def test_admin_status_does_not_bypass_ownership(self) -> None:
        session = _coakley(active="daniel")
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            self.assertTrue(is_admin_user(session_state=session))
            enforce_workspace_ownership(session)
            self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
            trace = session.get("_suite_workspace_ownership_trace") or {}
            self.assertEqual(trace.get("cloud_key"), "baseball__coakley11")

    def test_join_room_does_not_change_owned_or_active_workspace(self) -> None:
        import inspect

        from draft_room_context import join_shared_draft_room

        src = inspect.getsource(join_shared_draft_room)
        for forbidden in ("_suite_active_workspace_id", "set_active_workspace_id", "_suite_owned_workspace_id"):
            self.assertNotIn(forbidden, src)

        session = _coakley(active="coakley11")
        session["active_shared_draft_room_code"] = "HOST01"
        session["draft_room_participant_team"] = "Team B"
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
        self.assertEqual(session["_suite_owned_workspace_id"], "coakley11")

    def test_refresh_and_sign_in_preserve_coakley11(self) -> None:
        session = _coakley(active="coakley11")
        session[AUTH_JUST_LOGGED_IN_KEY] = True
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            session["_suite_active_workspace_id"] = "daniel"
            enforce_workspace_ownership(session)
            self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
            session["_suite_active_workspace_id"] = "daniel"
            hard_clamp_owned_workspace_before_scoped_load(session)
            self.assertEqual(session["_suite_active_workspace_id"], "coakley11")

    def test_prepare_baseball_workspace_clamps_before_scoped_load(self) -> None:
        from baseball_persistent_state import prepare_baseball_workspace

        session = _coakley(active="daniel")
        st = _FakeSt(session)
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True), mock.patch(
            "baseball_persistent_state.sync_workspace_protocol", return_value=True
        ) as sync_mock, mock.patch(
            "workflow_persist_guard.ensure_session_workflow_hydrated", return_value={}
        ), mock.patch(
            "suite_auth.restore_auth_session"
        ):
            prepare_baseball_workspace(st)
        self.assertEqual(session["_suite_active_workspace_id"], "coakley11")
        # Sync must see the clamped workspace (force-sync after clamp).
        self.assertTrue(session.get("_suite_workspace_force_sync") or sync_mock.called)
        self.assertEqual(
            scoped_cloud_app_id("baseball", session["_suite_active_workspace_id"]),
            "baseball__coakley11",
        )

    def test_diagnostics_expose_owned_active_and_scope(self) -> None:
        session = _coakley(active="coakley11")
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=True
        ), mock.patch("suite_workspace.persist_active_workspace_id", return_value=True):
            hard_clamp_owned_workspace_before_scoped_load(session)
        snap = build_mp_identity_snapshot(session, room={"host_team": "Daniel"})
        self.assertEqual(snap["signed_in_account"], "coakley11")
        self.assertEqual(snap["workspace_id"], "coakley11")
        self.assertEqual(snap["owned_workspace_id"], "coakley11")
        self.assertEqual(snap["claimed_team"], "Team B")
        self.assertEqual(snap["cloud_data_scope"], "baseball__coakley11")
        self.assertNotEqual(snap["display_workspace_name"], "Daniel")


if __name__ == "__main__":
    unittest.main()
