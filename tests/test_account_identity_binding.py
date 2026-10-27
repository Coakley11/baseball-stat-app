"""Sign-in binds each verified account to its own profile; two accounts never share one (2026-10-27).

Before: the profile id was the email's local part, so john@a.com and john@b.com shared the
"john" account (suite_users row, workspace, saved data); "daniel.cohen11@<any domain>" was the
owner and "coakley11@<any domain>" an admin. Now (suite_auth.resolve_account_profile_id) an
existing profile is kept only for the email recorded on its suite_users row, and a collision gets
a stable id derived from the Supabase user id. The store below stands in for suite_users.
"""

from __future__ import annotations

import unittest
from unittest import mock

import streamlit

import suite_auth
import suite_storage_supabase as sss
import suite_user


class _Users:
    """In-memory suite_users: external_id -> (uuid, email)."""

    def __init__(self, rows: dict[str, str]) -> None:
        self.rows = {ext: (f"uuid-{ext}", email) for ext, email in rows.items()}
        self.created: list[str] = []
        self.offline = False

    def find(self, *, external_id: str = "", email: str = "") -> list[dict[str, str]]:
        if self.offline:
            raise RuntimeError("store unreachable")
        out = []
        for ext, (uid, mail) in self.rows.items():
            if (external_id and ext == external_id) or (email and not external_id and mail.lower() == email.lower()):
                out.append({"id": uid, "external_id": ext, "email": mail})
        return out

    def ensure(self, ext: str, *, email: str = "", display_name: str = "") -> str:
        del display_name
        if ext not in self.rows:
            self.rows[ext] = (f"uuid-{ext}", email)
            self.created.append(ext)
        return self.rows[ext][0]


EXISTING = {
    "daniel": "daniel.cohen11@yahoo.com",
    "ariel": "ariel.k@family.example",
    "coakley11": "coakley11@aol.com",
    "john": "john@a.com",
    "pat": "",  # a legacy row without a recorded email
}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.users = _Users(dict(EXISTING))
        for p in (
            mock.patch("suite_auth.is_auth_enabled", return_value=True),
            mock.patch("suite_storage_supabase.find_user_rows", side_effect=self.users.find),
            mock.patch("suite_storage_supabase.ensure_user_row", side_effect=self.users.ensure),
            mock.patch("suite_storage_supabase._request", side_effect=AssertionError("network request sent")),
            mock.patch("suite_user.get_cloud_config", return_value=object()),
            mock.patch("suite_auth._configured_profile_emails", return_value={}),
        ):
            p.start()
            self.addCleanup(p.stop)
        suite_user.reset_account_cache()
        self.addCleanup(suite_user.reset_account_cache)

    def sign_in(self, email: str, auth_uid: str) -> dict:
        """The session _apply_authenticated_user leaves after a verified sign-in."""
        session: dict = {}
        suite_auth._apply_authenticated_user(
            session, {"id": auth_uid, "email": email}, tokens={"access_token": "a", "refresh_token": "r"}
        )
        return session

    def profile(self, email: str, auth_uid: str) -> str:
        return suite_auth.resolve_auth_external_id(self.sign_in(email, auth_uid))


class ProfileBindingTests(_Base):
    def test_same_local_part_on_two_domains_get_different_accounts(self) -> None:
        a = self.profile("john@a.com", "auth-john-a")
        b = self.profile("john@b.com", "auth-john-b")
        self.assertEqual(a, "john")  # the existing account keeps its profile and data
        self.assertNotEqual(b, "john")
        self.assertTrue(b.startswith("john_"), b)
        self.assertEqual(b, self.profile("john@b.com", "auth-john-b"))  # stable across sign-ins
        self.assertNotEqual(self.users.ensure(a), self.users.ensure(b))

    def test_existing_daniel_and_ariel_keep_their_profiles_without_new_rows(self) -> None:
        self.assertEqual(self.profile("Daniel.Cohen11@yahoo.com", "auth-owner"), "daniel")
        self.assertEqual(self.profile("ariel.k@family.example", "auth-ariel"), "ariel")
        self.assertEqual(self.users.created, [])

    def test_look_alike_addresses_get_no_one_elses_profile_or_admin(self) -> None:
        from suite_workspace_registry import is_admin_user

        for email, uid in (("daniel.cohen11@gmail.com", "auth-x1"), ("coakley11@evil.example", "auth-x2"),
                           ("ariel@x.example", "auth-x3"), ("daniel@x.example", "auth-x4")):
            session = self.sign_in(email, uid)
            self.assertNotIn(suite_auth.resolve_auth_external_id(session), ("daniel", "ariel", "coakley11"), email)
            self.assertFalse(is_admin_user(session_state=session), email)
        self.assertTrue(is_admin_user(session_state=self.sign_in("coakley11@aol.com", "auth-coakley")))

    def test_new_email_claims_its_readable_id(self) -> None:
        self.assertEqual(self.profile("alice@x.example", "auth-alice"), "alice")
        self.assertEqual(self.users.rows["alice"][1], "alice@x.example")

    def test_unverifiable_legacy_row_is_not_taken_over(self) -> None:
        got = self.profile("pat@x.example", "auth-pat")
        self.assertTrue(got.startswith("pat_"), got)
        self.assertEqual(self.users.rows["pat"], ("uuid-pat", ""))  # untouched

    def test_configured_email_maps_exactly(self) -> None:
        with mock.patch("suite_auth._configured_profile_emails", return_value={"kid@school.example": "ariel"}):
            self.assertEqual(self.profile("kid@school.example", "auth-kid"), "ariel")
            self.assertNotEqual(self.profile("kid2@school.example", "auth-kid2"), "ariel")

    def test_store_unreachable_never_falls_back_to_a_shared_profile(self) -> None:
        self.users.offline = True
        for email in ("daniel.cohen11@yahoo.com", "john@a.com"):
            got = self.profile(email, f"auth-{email}")
            self.assertNotIn(got, EXISTING, email)

    def test_unbound_session_uses_its_own_id(self) -> None:
        session = {suite_auth.AUTH_SESSION_KEY: True, suite_auth.AUTH_USER_ID_KEY: "auth-z",
                   suite_auth.AUTH_USER_EMAIL_KEY: "john@b.com"}
        self.assertTrue(suite_auth.resolve_auth_external_id(session).startswith("john_"))


class IsolationAfterBindingTests(_Base):
    def test_simultaneous_accounts_resolve_their_own_rows(self) -> None:
        john_a = self.sign_in("john@a.com", "auth-john-a")
        john_b = self.sign_in("john@b.com", "auth-john-b")
        seen = []
        for session in (john_a, john_b, john_a, john_b):
            with mock.patch.object(streamlit, "session_state", session):
                seen.append(suite_user.get_account_user_id())
        self.assertEqual(seen[0], seen[2])
        self.assertEqual(seen[1], seen[3])
        self.assertNotEqual(seen[0], seen[1])

    def test_team_ownership_does_not_carry_across_look_alike_accounts(self) -> None:
        from fantasy_league_team_ownership import assign_team_owner_to_context, owned_team_for_user

        context = {"league_context_id": "ctx", "league_rosters": {"Team A": {}, "Team B": {}}}
        uid_a = self.users.ensure(self.profile("john@a.com", "auth-john-a"))
        uid_b = self.users.ensure(self.profile("john@b.com", "auth-john-b"))
        context = assign_team_owner_to_context(context, "Team A", user_id=uid_a)
        self.assertEqual(owned_team_for_user(context, uid_a), "Team A")
        self.assertEqual(owned_team_for_user(context, uid_b), "")

    def test_workspaces_differ_for_look_alike_accounts(self) -> None:
        a = suite_auth.allowed_workspaces_for_session(self.sign_in("john@a.com", "auth-john-a"))
        b = suite_auth.allowed_workspaces_for_session(self.sign_in("john@b.com", "auth-john-b"))
        self.assertEqual(a, ("john",))
        self.assertFalse(set(a) & set(b))

    def test_owner_still_reads_legacy_rows_and_others_do_not(self) -> None:
        for email, uid, ws, expect_null in (("daniel.cohen11@yahoo.com", "auth-owner", "daniel", True),
                                            ("john@b.com", "auth-john-b", "john_x", False)):
            session = self.sign_in(email, uid)
            with mock.patch.object(streamlit, "session_state", session), \
                    mock.patch("suite_workspace.get_active_workspace_id", return_value=ws):
                params: dict = {}
                sss._apply_user_scope_params(params)
                self.assertEqual("user_id.is.null" in params.get("or", ""), expect_null, email)


if __name__ == "__main__":
    unittest.main()
