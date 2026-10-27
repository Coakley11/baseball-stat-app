"""Signed-out visitors and signed-in accounts never act as, or read, another account (2026-10-26).

Before: with sign-in on, a signed-out visitor resolved to the deployment's ``suite_user_id``
(the owner): the owner's account id, the owner's workspace ("daniel"), and the owner's legacy
``user_id IS NULL`` rows. An email containing "daniel" or "ariel" resolved to those profiles.
Every Supabase request in these tests is patched to fail, so nothing reaches the network.
"""

from __future__ import annotations

import unittest
from unittest import mock

import streamlit

import suite_auth
import suite_storage_supabase as sss
import suite_user

OWNER_ROW, OTHER_ROW = "uuid-owner", "uuid-other"


def _signed_in(email: str, uid: str, profile: str) -> dict:
    """A signed-in session as _apply_authenticated_user leaves it (profile bound at sign-in;
    the binding itself is tested in test_account_identity_binding)."""
    return {
        suite_auth.AUTH_SESSION_KEY: True,
        suite_auth.AUTH_USER_ID_KEY: uid,
        suite_auth.AUTH_USER_EMAIL_KEY: email,
        suite_auth.AUTH_EXTERNAL_ID_KEY: profile,
    }


class _Base(unittest.TestCase):
    """Sign-in on, a cloud config present, the owner configured as suite_user_id."""

    def setUp(self) -> None:
        self.session: dict = {}
        patches = [
            mock.patch.object(streamlit, "session_state", self.session),
            mock.patch("suite_auth.is_auth_enabled", return_value=True),
            mock.patch.dict("os.environ", {"SUITE_USER_ID": "daniel", "SUITE_USER_EMAIL": "daniel.cohen11@yahoo.com"}),
            mock.patch("suite_user.get_cloud_config", return_value=object()),
            mock.patch("suite_storage_supabase._request", side_effect=AssertionError("network request sent")),
            mock.patch(
                "suite_storage_supabase.ensure_user_row",
                side_effect=lambda ext, **_: {"daniel": OWNER_ROW}.get(str(ext), f"uuid-{ext}"),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        suite_user.reset_account_cache()
        self.addCleanup(suite_user.reset_account_cache)


class SignedOutGuestTests(_Base):
    def test_guest_has_no_account_and_is_not_the_owner(self) -> None:
        self.assertTrue(suite_auth.is_anonymous_guest())
        self.assertEqual(suite_user.get_account_user_id(), "")
        ext = suite_user.get_external_user_id()
        self.assertTrue(ext.startswith("guest_"), ext)
        self.assertEqual(suite_user.get_user_email(), "")

    def test_guest_workspace_is_private_even_if_session_says_daniel(self) -> None:
        from suite_workspace import SESSION_KEY, get_active_workspace_id

        self.session[SESSION_KEY] = "daniel"
        ws = get_active_workspace_id()
        self.assertTrue(ws.startswith("guest_"), ws)
        self.assertEqual(suite_auth.allowed_workspaces_for_session(self.session), (ws,))
        other_guest: dict = {}
        with mock.patch.object(streamlit, "session_state", other_guest):
            self.assertNotEqual(get_active_workspace_id(), ws)

    def test_account_scoped_storage_is_refused_without_a_request(self) -> None:
        calls = (
            lambda: sss.load_current_state_for_app("baseball"),
            lambda: sss.save_current_state("baseball", page="Home", summary="x", metrics={"a": 1}),
            lambda: sss.load_events(),
            lambda: sss.load_active_resume_items(),
            lambda: sss.load_saved_items(app="baseball"),
            lambda: sss.save_user_settings("baseball", {"a": 1}),
            lambda: sss.record_activity("baseball", "page_view", page="Home"),
        )
        for call in calls:
            with self.assertRaises(sss.AnonymousAccountAccessBlocked):
                call()

    def test_cloud_session_blob_is_neither_read_nor_written(self) -> None:
        import suite_cloud_state as scs

        with mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True), \
                mock.patch("suite_cloud_state._import_storage", return_value=(sss, "suite_storage_supabase")), \
                mock.patch("suite_cloud_state.cloud_read_failure", return_value=None):
            self.assertFalse(scs.save_cloud_full_session("baseball", {"draft_archive_teams": [{"draft_id": "g"}]}))
            state, _ = scs.load_cloud_full_session("baseball")
            self.assertEqual(state, {})

    def test_guest_never_reads_or_writes_saved_workspaces_on_disk(self) -> None:
        import suite_user_persistence as sup

        with mock.patch("suite_user_persistence._read_json", side_effect=AssertionError("read a saved workspace")), \
                mock.patch("suite_user_persistence._write_json", side_effect=AssertionError("wrote a workspace")):
            self.assertEqual(sup._load_raw("baseball", "daniel"), ({}, None, None))
            self.assertFalse(sup.save_user_state("baseball", {"x": 1}, workspace_id="daniel"))
            self.assertFalse(sup.reset_user_state("baseball", workspace_id="daniel"))

            class _St:
                session_state = self.session

            self.assertFalse(sup.force_autosave(_St(), "baseball", build_state=lambda _s: {"x": 1}, reason="draft_edit"))
            self.assertIsNone(sup.autosave_if_changed(_St(), "baseball", build_state=lambda _s: {"x": 1}))

    def test_draft_save_asks_to_sign_in(self) -> None:
        import pandas as pd

        from draft_archive_ui import _persist_archive, _persist_failure_message
        from fantasy_league_context import save_simulator_league_context

        board = pd.DataFrame([{"Team": "A", "Player": "P1", "Pick": 1}, {"Team": "B", "Player": "P2", "Pick": 2}])
        entry, _ = save_simulator_league_context(self.session, board, my_team_name="A", defer_activation=True, save_only=True)

        class _St:
            session_state = self.session

        self.assertFalse(_persist_archive(self.session, _St(), reason="simulator_league_context_saved", entry=entry))
        self.assertIn("sign in to save drafts", _persist_failure_message(self.session))

    def test_guest_cannot_accept_a_league_invite_or_use_shared_leagues(self) -> None:
        from fantasy_league_invites import join_shared_league_from_invite
        from fantasy_shared_league_store import load_shared_league, push_league_context_to_shared

        ok = join_shared_league_from_invite(self.session, invite_id="inv", league_id="lg", team_name="Team A")
        self.assertIn("Sign in", str(ok[2]))
        self.assertIsNone(load_shared_league("lg"))
        self.assertIsNone(push_league_context_to_shared(self.session, {"league_id": "lg", "league_context_id": "c"}))

    def test_no_session_to_check_is_treated_as_a_guest(self) -> None:
        class _NoSession:
            def get(self, *_a, **_k):
                raise RuntimeError("no script run context")

        with mock.patch.object(streamlit, "session_state", _NoSession()):
            self.assertTrue(suite_auth.is_anonymous_guest())
            self.assertEqual(suite_user.get_account_user_id(), "")
            with self.assertRaises(sss.AnonymousAccountAccessBlocked):
                sss.load_events()


class SignedInIsolationTests(_Base):
    def test_two_accounts_get_their_own_ids_and_rows(self) -> None:
        owner = _signed_in("daniel.cohen11@yahoo.com", "auth-owner", "daniel")
        other = _signed_in("pat@example.com", "auth-pat", "pat")
        seen = []
        for session in (owner, other, owner, other):
            with mock.patch.object(streamlit, "session_state", session):
                seen.append(suite_user.get_account_user_id())
        self.assertEqual(seen, [OWNER_ROW, "uuid-pat", OWNER_ROW, "uuid-pat"])

    def test_only_the_owner_workspace_reads_legacy_rows(self) -> None:
        for session, ws, expect_null in (
            (_signed_in("daniel.cohen11@yahoo.com", "auth-owner", "daniel"), "daniel", True),
            (_signed_in("pat@example.com", "auth-pat", "pat"), "pat", False),
        ):
            with mock.patch.object(streamlit, "session_state", session), \
                    mock.patch("suite_workspace.get_active_workspace_id", return_value=ws):
                params: dict = {}
                sss._apply_user_scope_params(params)
                if expect_null:
                    self.assertIn("user_id.is.null", params.get("or", ""))
                else:
                    self.assertEqual(params, {"user_id": "eq.uuid-pat"})

    def test_unresolved_account_is_refused_not_given_the_owners_rows(self) -> None:
        session = _signed_in("pat@example.com", "auth-pat", "pat")
        with mock.patch.object(streamlit, "session_state", session), \
                mock.patch("suite_storage_supabase.ensure_user_row", side_effect=RuntimeError("offline")):
            suite_user.reset_account_cache()
            self.assertTrue(suite_user.get_account_user_id().startswith("local:"))
            with self.assertRaises(sss.AnonymousAccountAccessBlocked):
                sss.load_current_state_for_app("baseball")

    def test_email_lookalikes_do_not_reach_preset_profiles(self) -> None:
        infer = suite_auth._infer_external_id_from_email
        for email in ("daniel.cohen11@gmail.com", "coakley11@example.com", "daniel.smith@example.com", "mydaniel@x.com", "ariel.k@x.com", "daniel@x.com",
                      "ariel@x.com", "guest@x.com", "test_user@x.com"):
            self.assertNotIn(infer(email), ("daniel", "ariel", "guest", "test_user", "coakley11"), email)
        self.assertNotEqual(suite_auth.resolve_auth_external_id({suite_auth.AUTH_USER_ID_KEY: "abc"}), "daniel")

    def test_configured_profile_email_maps_exactly(self) -> None:
        with mock.patch("suite_auth._configured_profile_emails", return_value={"kid@family.example": "ariel"}):
            self.assertEqual(suite_auth._infer_external_id_from_email("Kid@Family.example"), "ariel")
            self.assertNotEqual(suite_auth._infer_external_id_from_email("kid2@family.example"), "ariel")

    def test_signed_in_email_is_the_accounts_own_not_the_owners(self) -> None:
        with mock.patch.object(streamlit, "session_state", _signed_in("pat@example.com", "auth-pat", "pat")):
            self.assertEqual(suite_user.get_user_email(), "pat@example.com")


class NoSignInLocalInstallTests(unittest.TestCase):
    """Sign-in off (the owner's single-user install): unchanged, the configured account."""

    def test_local_install_uses_the_configured_account(self) -> None:
        with mock.patch("suite_auth.is_auth_enabled", return_value=False), \
                mock.patch.dict("os.environ", {"SUITE_USER_ID": "daniel"}), \
                mock.patch("suite_user.get_cloud_config", return_value=None):
            suite_user.reset_account_cache()
            self.assertFalse(suite_auth.is_anonymous_guest())
            self.assertEqual(suite_user.get_account_user_id(), "local:daniel")
            params: dict = {}
            sss._apply_user_scope_params(params)
            self.assertEqual(params, {"user_id": "is.null"})
        suite_user.reset_account_cache()


if __name__ == "__main__":
    unittest.main()
