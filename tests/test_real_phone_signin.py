"""Real-phone sign-in (owner, 2026-11-08): the owner still can't sign in on a physical Android phone.

Code-backed root cause (H1): a password sign-in reused the ``suite_sid`` already in the page URL to save the
refresh session. Reads require exactly one valid row per sid, so once a long-open phone tab (or a copied
link) carried a sid whose records couldn't be read back unambiguously, every attempt failed with
"its secure refresh session could not be saved (token_record_...)". The rollback then put the same sid back
in the URL, so retries failed the same way. Desktop phone emulation always starts from a clean URL.

Fixes tested here:
* a sign-in from signed out saves under a NEW sid, and a failed attempt still restores the previous one;
* a non-secret sign-in trace (steps only; no password, tokens, sid, ids or email);
* password-manager hints on the inputs (Streamlit's default for a password box is "new-password");
* a 409 foreign-key error is no longer treated as "row already exists" (which reported a zero-row PATCH
  as committed).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import suite_auth_signin_trace as trace
from suite_auth import login_with_email
from suite_auth_browser import BROWSER_PERSIST_RESULT_KEY, SESSION_QUERY_PARAM, SESSION_STATE_SID_KEY
from suite_storage_supabase import _is_duplicate_key_error

ROOT = Path(__file__).resolve().parents[1]
TOKENS = {"access_token": "access-SECRET-test", "refresh_token": "refresh-SECRET-test"}
EMAIL, PASSWORD = "coach@example.com", "hunter2-SECRET"


def _user() -> SimpleNamespace:
    return SimpleNamespace(id="auth-user-1", email=EMAIL, user_metadata={})


def _persistence(ok: bool, reason: str = "ok") -> dict:
    return {"persistence_attempted": True, "persistence_succeeded": ok, "write_committed": ok,
            "bridge_record_complete": ok, "failure_reason": reason, "handoff_phase": "INTERMEDIATE"}


class _QP(dict):
    """st.query_params stand-in (dict semantics, like Streamlit's QueryParamsProxy)."""


class _St:
    def __init__(self, session: dict, sid: str | None) -> None:
        self.session_state = session
        self.query_params = _QP({SESSION_QUERY_PARAM: sid} if sid else {})


def _sign_in(st: _St, *, persist_ok: bool, reason: str = "ok", seen: dict | None = None):
    def persist(ss, *, st=None):
        if seen is not None:  # what the save saw: the sid must already be cleared
            seen["url_sid"] = st.query_params.get(SESSION_QUERY_PARAM)
            seen["session_sid"] = ss.get(SESSION_STATE_SID_KEY)
        ss[BROWSER_PERSIST_RESULT_KEY] = _persistence(persist_ok, reason)
        return "suite-user-1"

    # auth_session_complete is NOT patched: modules that import it by name during the sign-in would keep the
    # fake for the rest of the test run (it broke an unrelated auth test in CI). The real sign-in sets the
    # session keys it checks.
    with mock.patch("suite_auth.is_auth_enabled", return_value=True), \
            mock.patch("suite_auth._auth_api") as auth_api, \
            mock.patch("suite_auth._user_from_auth_response", return_value=_user()), \
            mock.patch("suite_auth._tokens_from_auth_response", return_value=dict(TOKENS)), \
            mock.patch("suite_auth._sync_auth_account_identity", side_effect=persist), \
            mock.patch("suite_auth.enforce_workspace_ownership"), \
            mock.patch("draft_archive_visibility.sanitize_workflow_library_for_account"), \
            mock.patch("workflow_persist_guard.clear_draft_library_on_account_scope_change"):
        auth_api.return_value.sign_in_with_password.return_value = object()
        return login_with_email(st.session_state, email=EMAIL, password=PASSWORD, st=st)


class FreshSessionIdTests(unittest.TestCase):
    def test_a_stale_url_sid_is_not_reused_for_a_new_sign_in(self) -> None:
        st = _St({SESSION_STATE_SID_KEY: "stale-sid"}, "stale-sid")
        seen: dict = {}
        _sign_in(st, persist_ok=True, seen=seen)
        self.assertIsNone(seen["url_sid"])      # the save mints its own id
        self.assertIsNone(seen["session_sid"])

    def test_a_failed_attempt_restores_the_previous_sid(self) -> None:
        st = _St({SESSION_STATE_SID_KEY: "stale-sid"}, "stale-sid")
        ok, msg = _sign_in(st, persist_ok=False, reason="token_record_ambiguous")
        self.assertFalse(ok)
        self.assertIn("token_record_ambiguous", msg)
        self.assertEqual(st.query_params.get(SESSION_QUERY_PARAM), "stale-sid")
        self.assertEqual(st.session_state.get(SESSION_STATE_SID_KEY), "stale-sid")

    def test_no_sid_at_all_still_signs_in(self) -> None:
        st = _St({}, None)
        seen: dict = {}
        _sign_in(st, persist_ok=True, seen=seen)
        self.assertIsNone(seen["url_sid"])


class TraceTests(unittest.TestCase):
    def test_the_trace_shows_where_a_failed_sign_in_stopped(self) -> None:
        st = _St({}, "stale-sid")
        _sign_in(st, persist_ok=False, reason="token_record_ambiguous")
        steps = [(e["step"], e["ok"]) for e in trace.entries(st.session_state)]
        self.assertEqual(steps[:3], [("submitted", True), ("password_checked", True), ("fresh_session_id", True)])
        self.assertIn(("refresh_session_saved", False), steps)
        self.assertIn(("rolled_back", True), steps)
        saved = next(e for e in trace.entries(st.session_state) if e["step"] == "refresh_session_saved")
        self.assertEqual(saved["reason"], "token_record_ambiguous")
        self.assertEqual(next(e for e in trace.entries(st.session_state) if e["step"] == "fresh_session_id")["sid_source"], "url")

    def test_the_trace_never_holds_secrets(self) -> None:
        st = _St({}, "stale-sid")
        _sign_in(st, persist_ok=True)
        dump = repr(trace.entries(st.session_state)) + "\n".join(trace.lines(st.session_state))
        for secret in (EMAIL, PASSWORD, "access-SECRET", "refresh-SECRET", "stale-sid", "auth-user-1", "suite-user-1"):
            self.assertNotIn(secret, dump)
        self.assertEqual(trace.entries(st.session_state)[-1]["step"], "signed_in")

    def test_an_empty_field_is_recorded_without_its_value(self) -> None:
        session: dict = {}
        ok, msg = login_with_email(session, email=EMAIL, password="", st=None)
        self.assertFalse(ok)
        first = trace.entries(session)[0]
        self.assertEqual((first["step"], first["email_present"], first["password_present"]), ("submitted", True, False))

    def test_unknown_fields_are_dropped_and_text_is_sanitized(self) -> None:
        session: dict = {}
        e = trace.record(session, "x", False, reason="bad <script> value", token="abc", email=EMAIL)
        self.assertNotIn("token", e)
        self.assertNotIn("email", e)
        self.assertEqual(e["reason"], "badscriptvalue")


class FormAndStorageTests(unittest.TestCase):
    def test_password_manager_hints(self) -> None:
        src = (ROOT / "suite_auth.py").read_text(encoding="utf-8")
        self.assertIn('key="suite_auth_login_email", autocomplete="username"', src)
        self.assertIn('autocomplete="current-password"', src)

    def test_a_foreign_key_409_is_not_a_duplicate(self) -> None:
        fk = RuntimeError('Supabase POST suite_saved_items failed (409): {"code":"23503","message":"insert or update '
                          'on table violates foreign key constraint"}')
        dup = RuntimeError('Supabase POST suite_saved_items failed (409): {"code":"23505","message":"duplicate key '
                           'value violates unique constraint"}')
        self.assertFalse(_is_duplicate_key_error(fk))
        self.assertTrue(_is_duplicate_key_error(dup))

    def test_a_swallowed_pending_login_exception_is_traced(self) -> None:
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn('"pending_login_exception"', app)


if __name__ == "__main__":
    unittest.main()
