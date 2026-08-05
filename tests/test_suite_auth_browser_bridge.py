"""Trusted browser suite_sid → Supabase token bridge and hydration ordering."""

from __future__ import annotations

import unittest
from unittest import mock

from baseball_persistent_state import prepare_baseball_workspace
from live_draft_setup_ui import start_button_disabled
from live_draft_state import live_draft_restore_allowed
from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    ensure_authenticated_session_hydrated,
    is_authenticated,
    restore_auth_session,
)
from suite_auth_browser import (
    BROWSER_LOAD_REASON_KEY,
    SESSION_STATE_SID_KEY,
    load_browser_auth_tokens,
    save_browser_auth_tokens,
    sync_suite_sid_from_query,
)


def _tokens() -> dict:
    return {"access_token": "access-test", "refresh_token": "refresh-test"}


class SuiteAuthBrowserBridgeTests(unittest.TestCase):
    def test_sync_suite_sid_from_query_binds_session(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-abc"}
        st.session_state = {}
        sid = sync_suite_sid_from_query(st)
        self.assertEqual(sid, "sid-abc")
        self.assertEqual(st.session_state[SESSION_STATE_SID_KEY], "sid-abc")

    def test_load_tokens_missing_record(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "missing-sid"}
        st.session_state = {}
        with mock.patch("suite_storage_supabase.load_browser_auth_session", return_value=None):
            self.assertIsNone(load_browser_auth_tokens(st))
        self.assertEqual(st.session_state[BROWSER_LOAD_REASON_KEY], "token_record_missing")

    def test_load_tokens_matching_sid_hydrates(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "good-sid"}
        st.session_state = {}
        with mock.patch(
            "suite_storage_supabase.load_browser_auth_session",
            return_value=_tokens(),
        ):
            out = load_browser_auth_tokens(st)
        self.assertEqual(out, _tokens())
        self.assertEqual(st.session_state[BROWSER_LOAD_REASON_KEY], "ok")

    def test_save_emits_bridge_persist_checkpoint(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-save"}
        st.session_state = {AUTH_USER_ID_KEY: "uuid-1"}
        with mock.patch("suite_storage_supabase.save_browser_auth_session"), mock.patch(
            "suite_storage_supabase.load_browser_auth_session",
            return_value=_tokens(),
        ), mock.patch(
            "live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint"
        ) as emit:
            save_browser_auth_tokens(st, _tokens(), auth_user_id="uuid-1")
            self.assertTrue(emit.called)
            _args, kwargs = emit.call_args
            checkpoint = kwargs.get("checkpoint") if kwargs else None
            if checkpoint is None and len(_args) > 1:
                checkpoint = _args[1]
            self.assertEqual(checkpoint, "save_browser_auth_tokens")
            extra = kwargs.get("extra") or {}
            self.assertTrue(extra.get("persistence_succeeded"))
            self.assertTrue(extra.get("bridge_record_complete"))

    def test_save_uses_session_user_id_when_param_empty(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-save"}
        st.session_state = {SESSION_STATE_SID_KEY: "sid-save", AUTH_USER_ID_KEY: "uuid-1"}
        with mock.patch("suite_storage_supabase.save_browser_auth_session") as save, mock.patch(
            "suite_storage_supabase.load_browser_auth_session",
            return_value=_tokens(),
        ), mock.patch("live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint"):
            save_browser_auth_tokens(st, _tokens(), auth_user_id="")
            save.assert_called_once()
            self.assertEqual(save.call_args.kwargs["user_id"], "uuid-1")

    def test_restore_calls_apply_authenticated_user_on_valid_tokens(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-restore"}
        st.session_state = session
        user = mock.Mock(id="uuid-1", email="a@example.com")
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens", return_value=_tokens()
        ), mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth._apply_authenticated_user"
        ) as apply_user, mock.patch(
            "suite_auth._user_from_auth_response", return_value=user
        ), mock.patch(
            "suite_auth._tokens_from_auth_response", return_value=_tokens()
        ), mock.patch(
            "suite_auth.enforce_workspace_ownership"
        ), mock.patch(
            "suite_auth._sync_auth_account_identity"
        ), mock.patch(
            "draft_archive_visibility.sanitize_workflow_library_for_account"
        ), mock.patch(
            "suite_auth_browser.save_browser_auth_tokens"
        ):
            auth_api.return_value.set_session.return_value = mock.Mock(user=user)
            self.assertTrue(restore_auth_session(session, st=st))
            apply_user.assert_called_once()

    def test_query_param_alone_does_not_authenticate(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "fake"}
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens", return_value=None
        ):
            self.assertFalse(restore_auth_session(session, st=st))
        self.assertFalse(session.get(AUTH_SESSION_KEY))

    def test_incomplete_token_record_rejected(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "partial"}
        st.session_state = {}
        with mock.patch(
            "suite_storage_supabase.load_browser_auth_session",
            return_value={"access_token": "only-access"},
        ):
            self.assertIsNone(load_browser_auth_tokens(st))
        self.assertEqual(st.session_state[BROWSER_LOAD_REASON_KEY], "token_record_incomplete")

    def test_start_disabled_until_auth_complete(self) -> None:
        session = {AUTH_SESSION_KEY: False}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            disabled, _msg = start_button_disabled(session)
        self.assertTrue(disabled)

    def test_start_enabled_when_auth_complete(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-1",
            AUTH_TOKENS_KEY: _tokens(),
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            disabled, _msg = start_button_disabled(session)
        self.assertFalse(disabled)

    def test_warm_prepare_rehydrates_when_auth_missing(self) -> None:
        st = mock.Mock()
        ss: dict = {
            "_suite_auth_user_id": "",
            "_suite_active_workspace_id": "daniel",
            "_suite_cloud_session_revision": "rev1",
            "_ws_synced": True,
            "_baseball_warm_startup_fp": "fp1",
        }
        st.session_state = ss
        with mock.patch("suite_user_persistence._workspace_synced_key", return_value="_ws_synced"), mock.patch(
            "baseball_persistent_state.warm_startup_fingerprint", return_value="fp1"
        ), mock.patch("baseball_persistent_state.sync_workspace_protocol", return_value=True), mock.patch(
            "suite_auth.is_auth_enabled", return_value=True
        ), mock.patch("suite_auth.auth_session_complete", return_value=False), mock.patch(
            "suite_auth.restore_auth_session", return_value=True
        ) as restore, mock.patch(
            "suite_auth.ensure_authenticated_session_hydrated", return_value=True
        ) as ensure:
            prepare_baseball_workspace(st)
            restore.assert_called()
            ensure.assert_called()

    def test_disk_apply_preserves_protected_auth(self) -> None:
        from suite_identity_guard import enforce_identity_after_state_apply, snapshot_protected_browser_identity

        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-1",
            AUTH_TOKENS_KEY: _tokens(),
            "_suite_auth_user_email": "a@example.com",
            "_suite_active_workspace_id": "daniel",
        }
        snap = snapshot_protected_browser_identity(session)
        session.pop(AUTH_SESSION_KEY, None)
        enforce_identity_after_state_apply(session, snapshot=snap, reason="test")
        self.assertTrue(session.get(AUTH_SESSION_KEY))

    def test_restore_allowed_after_hydration(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-1",
            AUTH_TOKENS_KEY: _tokens(),
            "_live_draft_restore_blocked_reason": "auth_required",
        }
        blob = {
            "draft_room_id": "room-1",
            "status": "in_progress",
            "draft_board": [],
            "owner_auth_user_id": "uuid-1",
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "live_draft_state._current_auth_user_id", return_value="uuid-1"
        ):
            allowed, reason = live_draft_restore_allowed(session, blob)
        self.assertTrue(allowed)
        self.assertNotEqual(reason, "auth_required")

    def test_signed_out_restore_blocked(self) -> None:
        session: dict = {"_live_draft_restore_blocked_reason": "auth_required"}
        blob = {"draft_room_id": "r1", "status": "in_progress", "draft_board": []}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            allowed, reason = live_draft_restore_allowed(session, blob)
        self.assertFalse(allowed)
        self.assertEqual(reason, "auth_required")

    def test_snapshot_acceptance_requires_genuine_hydration(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "uuid-1",
            AUTH_TOKENS_KEY: _tokens(),
        }
        with mock.patch("live_draft_auth_snapshot_stage1_diag.is_auth_enabled", return_value=True):
            from live_draft_auth_snapshot_stage1_diag import record_auth_snapshot_capture

            record_auth_snapshot_capture(session, st=mock.Mock())
        from suite_auth import AUTH_START_RERUN_SNAPSHOT_KEY

        self.assertIn(AUTH_START_RERUN_SNAPSHOT_KEY, session)
        self.assertTrue(auth_session_complete(session))
        self.assertTrue(is_authenticated(session))
        self.assertTrue(ensure_authenticated_session_hydrated(session))


if __name__ == "__main__":
    unittest.main()
