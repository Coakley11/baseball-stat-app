"""Auth hydration across Start Draft rerun and live draft restore gates."""

from __future__ import annotations

import unittest
from unittest import mock

from live_draft_state import (
    _prepare_live_draft_state_body,
    live_draft_restore_allowed,
    reconcile_live_draft_auth_restore_block,
)
from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_ID_KEY,
    ensure_authenticated_session_hydrated,
    is_authenticated,
)


def _auth_session(*, user_id: str = "uuid-daniel") -> dict:
    return {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: user_id,
        AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        "_suite_auth_external_id": "daniel",
        "_suite_active_workspace_id": "daniel",
    }


class LiveDraftStartAuthHydrationTests(unittest.TestCase):
    def test_ensure_hydrated_no_op_when_session_complete(self) -> None:
        session = _auth_session()
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.restore_auth_session"
        ) as restore:
            self.assertTrue(ensure_authenticated_session_hydrated(session))
            restore.assert_not_called()

    def test_ensure_hydrated_calls_restore_when_incomplete(self) -> None:
        session = {AUTH_SESSION_KEY: True, AUTH_USER_ID_KEY: "uuid-daniel"}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.restore_auth_session", return_value=True
        ) as restore:
            ensure_authenticated_session_hydrated(session, st=mock.Mock())
            restore.assert_called_once()

    def test_prepare_hydrates_before_restore_gate(self) -> None:
        session = {
            "live_draft_state": {
                "draft_room_id": "room-1",
                "status": "in_progress",
                "draft_board": [],
                "owner_auth_user_id": "uuid-daniel",
            },
            "live_draft_room": {
                "draft_room_id": "room-1",
                "status": "in_progress",
                "current_pick_index": 0,
                "draft_board": [],
            },
            "_live_draft_restore_blocked_reason": "auth_required",
        }

        def _hydrate(s: dict, **_: object) -> bool:
            s.update(_auth_session())
            return True

        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.ensure_authenticated_session_hydrated", side_effect=_hydrate
        ), mock.patch(
            "live_draft_state._finish_prepare",
            side_effect=lambda _s, room: room,
        ), mock.patch(
            "live_draft_state.is_runtime_room", return_value=True
        ), mock.patch(
            "live_draft_state.canonical_live_draft",
            return_value=session["live_draft_state"],
        ):
            _prepare_live_draft_state_body(session)
        self.assertTrue(is_authenticated(session))
        self.assertNotEqual(session.get("_live_draft_restore_blocked_reason"), "auth_required")

    def test_reconcile_clears_stale_auth_required_when_allowed(self) -> None:
        session = _auth_session()
        session["_live_draft_restore_blocked_reason"] = "auth_required"
        session["live_draft_state"] = {
            "draft_room_id": "room-1",
            "status": "in_progress",
            "draft_board": [],
            "owner_auth_user_id": "uuid-daniel",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            self.assertTrue(reconcile_live_draft_auth_restore_block(session))
        self.assertNotIn("_live_draft_restore_blocked_reason", session)

    def test_reconcile_leaves_non_auth_block_reason(self) -> None:
        session = _auth_session()
        session["_live_draft_restore_blocked_reason"] = "workspace_mismatch"
        self.assertFalse(reconcile_live_draft_auth_restore_block(session))
        self.assertEqual(session["_live_draft_restore_blocked_reason"], "workspace_mismatch")

    def test_signed_out_stays_blocked(self) -> None:
        session = {
            "live_draft_state": {"draft_room_id": "room-1", "status": "in_progress", "draft_board": []},
            "_live_draft_restore_blocked_reason": "auth_required",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            self.assertFalse(reconcile_live_draft_auth_restore_block(session))
            allowed, reason = live_draft_restore_allowed(session, session["live_draft_state"])
        self.assertFalse(allowed)
        self.assertEqual(reason, "auth_required")

    def test_query_params_alone_do_not_authenticate(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "fake-from-query"}
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens", return_value=None
        ), mock.patch("suite_auth._auth_api") as auth_api:
            auth_api.return_value.set_session.side_effect = AssertionError("must not call supabase without tokens")
            from suite_auth import restore_auth_session

            self.assertFalse(restore_auth_session(session, st=st))
        self.assertFalse(session.get(AUTH_SESSION_KEY))

    def test_ownership_check_still_runs_when_authenticated(self) -> None:
        session = _auth_session(user_id="uuid-coakley")
        blob = {
            "draft_room_id": "room-1",
            "status": "in_progress",
            "draft_board": [],
            "owner_auth_user_id": "uuid-daniel",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "live_draft_state._current_auth_user_id", return_value="uuid-coakley"
        ):
            allowed, reason = live_draft_restore_allowed(session, blob)
        self.assertFalse(allowed)
        self.assertEqual(reason, "auth_user_mismatch")


if __name__ == "__main__":
    unittest.main()
