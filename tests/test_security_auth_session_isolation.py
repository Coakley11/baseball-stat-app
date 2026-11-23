"""Security hotfix 2026-11-23: a copied URL, a reload, a partial restore or an account switch can never
give a visitor another account's sign-in or data."""

from __future__ import annotations

import unittest
from unittest import mock

import account_session_boundary as asb
import suite_auth_browser as sab
from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, AUTH_USER_ID_KEY


class _QP(dict):
    pass


def _st(query=None, session=None):
    st = mock.Mock()
    st.query_params = _QP(query or {})
    st.session_state = dict(session or {})
    return st


def _signed_in(uid="user-a"):
    return {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: uid,
        AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
    }


class UrlRestoreDisabledTests(unittest.TestCase):
    def test_flag_is_off(self):
        self.assertFalse(sab.url_auth_restore_enabled())

    def test_copied_url_never_loads_tokens_and_is_revoked(self):
        st = _st({"suite_sid": "copied-sid"})
        with mock.patch("suite_storage_supabase.load_browser_auth_session") as load, \
                mock.patch("suite_storage_supabase.invalidate_browser_auth_session") as inv:
            self.assertIsNone(sab.load_browser_auth_tokens(st))
        load.assert_not_called()
        inv.assert_called_once_with("copied-sid")
        self.assertNotIn("suite_sid", st.query_params)
        self.assertNotIn(sab.SESSION_STATE_SID_KEY, st.session_state)
        self.assertEqual(st.session_state[sab.BROWSER_LOAD_REASON_KEY], sab.URL_RESTORE_DISABLED_REASON)

    def test_forged_or_expired_sid_is_also_stripped(self):
        st = _st({"suite_sid": "expired-or-forged"})
        with mock.patch("suite_storage_supabase.invalidate_browser_auth_session"):
            self.assertEqual(sab.sync_suite_sid_from_query(st), "")
        self.assertNotIn("suite_sid", st.query_params)

    def test_session_state_sid_is_not_used(self):
        st = _st({}, {sab.SESSION_STATE_SID_KEY: "left-over"})
        with mock.patch("suite_storage_supabase.load_browser_auth_session") as load:
            self.assertIsNone(sab.load_browser_auth_tokens(st))
        load.assert_not_called()
        self.assertNotIn(sab.SESSION_STATE_SID_KEY, st.session_state)

    def test_sign_in_never_writes_tokens_or_puts_an_id_in_the_url(self):
        st = _st({}, _signed_in())
        with mock.patch("suite_storage_supabase.save_browser_auth_session") as save:
            out = sab.save_browser_auth_tokens(st, {"access_token": "a", "refresh_token": "r"}, auth_user_id="user-a")
        save.assert_not_called()
        self.assertFalse(out["persistence_attempted"])
        self.assertNotIn("suite_sid", st.query_params)

    def test_revocation_runs_once_per_session(self):
        st = _st({"suite_sid": "s1"})
        with mock.patch("suite_storage_supabase.invalidate_browser_auth_session") as inv:
            sab.strip_url_auth_param(st)
            st.query_params["suite_sid"] = "s1"
            sab.strip_url_auth_param(st)
        self.assertEqual(inv.call_count, 1)

    def test_storage_layer_refuses_bridge_reads_and_writes(self):
        import suite_storage_supabase as ss

        with mock.patch.object(ss, "_request") as req:
            self.assertIsNone(ss.load_browser_auth_session("sid"))
            self.assertIsNone(ss.load_browser_auth_session_record("sid"))
            meta = ss.save_browser_auth_session_versioned(
                "sid", user_id="u", tokens={"access_token": "a", "refresh_token": "r"}
            )
        req.assert_not_called()
        self.assertFalse(meta["write_committed"])

    def test_invalidation_erases_stored_tokens(self):
        import suite_storage_supabase as ss

        with mock.patch.object(ss, "_request") as req, \
                mock.patch("suite_auth_browser_bridge_diag.probe_browser_auth_storage", return_value={}):
            ss.invalidate_browser_auth_session("sid")
        body = req.call_args.kwargs["json_body"]
        self.assertFalse(body["valid"])
        self.assertNotIn("access_token", body["payload"])
        self.assertNotIn("refresh_token", body["payload"])
        self.assertEqual(req.call_args.kwargs["params"]["item_key"], "eq.sid")


class AccountBoundaryTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("suite_auth.is_auth_enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _account_data(self, session):
        session.update({
            "draft_queue": ["Cal Raleigh"],
            "draft_archive_teams": [{"draft_name": "A's draft"}],
            "page_filter_state": {"ML Predictions": {"ml_sort_by": "x"}},
            "projections_state": {"meta": {"owner": "user-a"}},
            "_suite_active_workspace_id": "qa_danny",
            "_suite_owned_workspace_id": "qa_danny",
        })

    def test_verified_identity_requires_a_complete_auth_session(self):
        self.assertEqual(asb.verified_account_id(_signed_in("user-a")), "user-a")
        self.assertEqual(asb.verified_account_id({AUTH_USER_ID_KEY: "user-a"}), "")
        self.assertEqual(asb.verified_account_id({AUTH_SESSION_KEY: True, AUTH_USER_ID_KEY: "user-a"}), "")
        self.assertFalse(asb.account_data_load_allowed({"_suite_auth_user_id": "user-a"}))

    def test_sign_out_clears_the_previous_accounts_data(self):
        session = _signed_in("user-a"); self._account_data(session)
        asb.enforce_account_session_boundary(session)
        for k in (AUTH_SESSION_KEY, AUTH_USER_ID_KEY, AUTH_TOKENS_KEY):
            session.pop(k)
        out = asb.enforce_account_session_boundary(session)
        self.assertTrue(out["changed"])
        for k in ("draft_queue", "draft_archive_teams", "projections_state", "_suite_owned_workspace_id"):
            self.assertNotIn(k, session)
        self.assertNotIn("ML Predictions", session.get("page_filter_state") or {})
        self.assertTrue(str(session["_suite_active_workspace_id"]).startswith("guest_"))

    def test_partial_restore_is_demoted_to_a_guest_and_cleared(self):
        session = _signed_in("user-a"); self._account_data(session)
        asb.enforce_account_session_boundary(session)
        session.pop(AUTH_TOKENS_KEY)  # flag and user id left behind, no tokens
        out = asb.enforce_account_session_boundary(session)
        self.assertTrue(out["demoted"])
        self.assertNotIn(AUTH_SESSION_KEY, session)
        self.assertNotIn(AUTH_USER_ID_KEY, session)
        self.assertNotIn("draft_queue", session)

    def test_account_switch_starts_clean(self):
        session = _signed_in("user-a"); self._account_data(session)
        asb.enforce_account_session_boundary(session)
        session.update(_signed_in("user-b"))
        out = asb.enforce_account_session_boundary(session)
        self.assertTrue(out["changed"])
        self.assertNotIn("draft_archive_teams", session)
        self.assertEqual(session[asb.SESSION_DATA_OWNER_KEY], "user-b")

    def test_same_identity_keeps_its_data(self):
        session = _signed_in("user-a"); self._account_data(session)
        asb.enforce_account_session_boundary(session)
        out = asb.enforce_account_session_boundary(session)
        self.assertFalse(out["changed"])
        self.assertEqual(session["draft_queue"], ["Cal Raleigh"])

    def test_raw_user_id_or_workspace_label_is_not_identity(self):
        session = {"_suite_auth_user_id": "user-a", "_suite_active_workspace_id": "qa_danny"}
        asb.enforce_account_session_boundary(session)
        self.assertEqual(session[asb.SESSION_DATA_OWNER_KEY], "")
        self.assertTrue(str(session["_suite_active_workspace_id"]).startswith("guest_"))

    def test_guest_blob_apply_is_refused(self):
        from baseball_persistent_state import apply_baseball_disk_state

        st = _st({}, {"_suite_auth_user_id": "user-a"})
        apply_baseball_disk_state(st, {"draft_queue": ["Cal Raleigh"], "draft_archive_teams": [{"x": 1}]})
        self.assertNotIn("draft_queue", st.session_state)
        self.assertEqual(st.session_state["_suite_workspace_apply_refused"], "no_verified_identity")


class SignInWithoutUrlRestoreTests(unittest.TestCase):
    def test_password_sign_in_succeeds_without_saving_a_refresh_session(self):
        from types import SimpleNamespace

        import baseball_persistent_state  # noqa: F401 — registers the account clearer
        from suite_auth import auth_session_complete, login_with_email

        st = _st({})
        session = st.session_state
        user = SimpleNamespace(id="auth-user-1", email="coach@example.com", user_metadata={})
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), \
                mock.patch("suite_auth._auth_api") as auth_api, \
                mock.patch("suite_auth._user_from_auth_response", return_value=user), \
                mock.patch("suite_auth._tokens_from_auth_response",
                           return_value={"access_token": "a", "refresh_token": "r"}), \
                mock.patch("suite_storage_supabase.ensure_user_row", return_value="suite-user-1"), \
                mock.patch("suite_storage_supabase.save_browser_auth_session") as save, \
                mock.patch("suite_storage_supabase._request") as req, \
                mock.patch("suite_workspace_registry.ensure_owned_workspace_for_session"), \
                mock.patch("suite_auth.enforce_workspace_ownership"), \
                mock.patch("suite_user_persistence.preserve_page_through_auth"), \
                mock.patch("draft_archive_visibility.sanitize_workflow_library_for_account"), \
                mock.patch("draft_room_participant_state.on_auth_user_switch"):
            auth_api.return_value.sign_in_with_password.return_value = object()
            ok, message = login_with_email(session, email="coach@example.com", password="pw", st=st)
        self.assertTrue(ok, message)
        self.assertTrue(auth_session_complete(session))
        save.assert_not_called()
        for call in req.call_args_list:  # no bridge row is written or read
            self.assertNotIn("_auth_browser", str(call))
        self.assertNotIn("suite_sid", st.query_params)


if __name__ == "__main__":
    unittest.main()
