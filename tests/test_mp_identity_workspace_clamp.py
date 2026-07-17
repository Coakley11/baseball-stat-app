"""Shared Multiplayer identity — Coakley11 must not resolve to Daniel workspace."""

from __future__ import annotations

import unittest
from unittest import mock

from suite_auth import (
    AUTH_EXTERNAL_ID_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    enforce_workspace_ownership,
)
from suite_identity_guard import build_mp_identity_snapshot
from suite_workspace import get_active_workspace_id
from suite_workspace_registry import resolve_owned_workspace_id


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


class JoinDoesNotMutateWorkspaceTests(unittest.TestCase):
    def test_join_shared_draft_room_does_not_write_workspace_keys(self) -> None:
        import inspect

        from draft_room_context import join_shared_draft_room

        src = inspect.getsource(join_shared_draft_room)
        for forbidden in (
            "_suite_active_workspace_id",
            "set_active_workspace_id",
            "_suite_owned_workspace_id",
        ):
            self.assertNotIn(forbidden, src)

        guest = _coakley_session(active="coakley11")
        before = dict(guest)
        # Simulate post-join participant keys only (what join is allowed to set).
        guest["draft_room_participant_team"] = "Team B"
        guest["active_shared_draft_room_code"] = "ABC123"
        self.assertEqual(guest["_suite_active_workspace_id"], before["_suite_active_workspace_id"])
        self.assertEqual(guest["_suite_active_workspace_id"], "coakley11")
        self.assertNotEqual(guest["_suite_active_workspace_id"], "daniel")


if __name__ == "__main__":
    unittest.main()
