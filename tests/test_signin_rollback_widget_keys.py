"""Phone sign-in root cause (D4J 2026-11-08): "Account control failed — see developer diagnostics.
(StreamlitValueAssignmentNotAllowedError)".

When the password is verified but the browser refresh session cannot be saved, login_with_email
rolls the attempt back. It used to do ``session_state.clear(); session_state.update(before)``,
which re-assigned every widget value (button and form-submit keys included) through
st.session_state. The next keyed button drawn in the Account & Workspace control then raised
StreamlitValueAssignmentNotAllowedError. The rollback now touches only what the attempt changed
and never writes a widget value back.
"""

from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

from suite_auth import rollback_session_state, snapshot_session_state


def _control(rollback: str) -> None:
    import streamlit as st

    from suite_auth import rollback_session_state, snapshot_session_state

    st.session_state.setdefault("active_page", "Draft Strategy")
    with st.form("suite_auth_login_form"):
        st.text_input("Email", key="suite_auth_login_email")
        submitted = st.form_submit_button("Log in")
    if submitted:
        before = dict(st.session_state) if rollback == "old" else snapshot_session_state(st.session_state)
        st.session_state["_suite_auth_session"] = True  # the failed attempt's own keys
        st.session_state["active_page"] = "Home"
        st.session_state.pop("suite_reset_btn::baseball", None)  # e.g. an account clearer
        if rollback == "old":
            st.session_state.clear()
            st.session_state.update(before)
        else:
            rollback_session_state(st.session_state, before)
        st.markdown(f"page={st.session_state.get('active_page')} "
                    f"auth={st.session_state.get('_suite_auth_session')}")
    try:  # baseball_account_workspace draws the saved-sessions buttons after the auth panel
        st.button("Home", key="suite_nav_home_btn")
        st.button("Reset to default", key="suite_reset_btn::baseball")
        st.markdown("control rendered")
    except Exception as exc:  # noqa: BLE001
        st.markdown(f"FAILED: {type(exc).__name__}")


def _run(rollback: str) -> list[str]:
    at = AppTest.from_function(_control, default_timeout=30, kwargs={"rollback": rollback})
    at.run()
    assert any(m.value == "control rendered" for m in at.markdown)
    at.button[0].click().run()  # Log in, with a failed refresh-session save
    return [m.value for m in at.markdown]


class SignInRollbackTests(unittest.TestCase):
    def test_the_old_rollback_reproduces_the_phone_error(self) -> None:
        self.assertIn("FAILED: StreamlitValueAssignmentNotAllowedError", _run("old"))

    def test_the_new_rollback_keeps_the_control_working(self) -> None:
        out = _run("new")
        self.assertIn("control rendered", out)
        self.assertIn("page=Draft Strategy auth=None", out)  # the attempt is fully undone

    def test_plain_dict_rollback_restores_changes_and_drops_additions(self) -> None:
        keep = {"k": 1}
        session = {"draft_archive_teams": keep, "active_page": "Library", "gone": 2}
        before = dict(session)
        session["active_page"] = "Home"
        session["_suite_auth_session"] = True
        del session["gone"]
        rollback_session_state(session, before)
        self.assertEqual(session, before)
        self.assertIs(session["draft_archive_teams"], keep)

    def test_form_submitter_keys_are_never_written_back(self) -> None:
        session = {"FormSubmitter:suite_auth_login_form-Log in": True}
        before = dict(session)
        session.clear()
        rollback_session_state(session, before)
        self.assertNotIn("FormSubmitter:suite_auth_login_form-Log in", session)

    def test_login_with_email_uses_the_safe_rollback(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parents[1].joinpath("suite_auth.py").read_text(encoding="utf-8")
        body = src[src.index("def login_with_email("):]
        body = body[: body.index("\ndef ", 10)]
        self.assertIn("rollback_session_state(session_state, pre_login_state)", body)
        self.assertNotIn("session_state.clear()", body)


class LeftoverHandoffFreezeTests(unittest.TestCase):
    """The second half of the phone failure: after an implicit sign-out (expired token, no Log out
    click) the previous handoff freeze stayed set, so the next password sign-in skipped the
    refresh-session save (handoff_frozen_skip_intermediate) and always took the rollback path."""

    def _login(self, session: dict):
        from types import SimpleNamespace
        from unittest import mock

        from suite_auth import login_with_email

        user = SimpleNamespace(id="auth-user-1", email="coach@example.com", user_metadata={})
        tokens = {"access_token": "access-test", "refresh_token": "refresh-test"}
        st = mock.MagicMock(query_params={})
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth._auth_api"
        ) as api, mock.patch("suite_auth._user_from_auth_response", return_value=user), mock.patch(
            "suite_auth._tokens_from_auth_response", return_value=dict(tokens)
        ), mock.patch("suite_storage_supabase.ensure_user_row", return_value="suite-user-1"), mock.patch(
            "suite_user.get_account_user_id", return_value="suite-user-1"
        ), mock.patch("suite_storage_supabase.save_browser_auth_session", side_effect=RuntimeError("offline")) as save:
            api.return_value.sign_in_with_password.return_value = object()
            ok, msg = login_with_email(session, email="coach@example.com", password="pw", st=st)
        return ok, msg, save

    def test_a_leftover_freeze_no_longer_skips_the_save(self) -> None:
        from suite_auth_bridge_handoff import HANDOFF_FREEZE_KEY

        session = {HANDOFF_FREEZE_KEY: True}
        ok, msg, save = self._login(session)
        save.assert_called_once()  # the save is attempted (it then fails here: no database)
        self.assertNotIn("handoff_frozen_skip_intermediate", msg)
        self.assertFalse(ok)
        self.assertTrue(session.get(HANDOFF_FREEZE_KEY))  # failed attempt: rolled back unchanged


if __name__ == "__main__":
    unittest.main()
