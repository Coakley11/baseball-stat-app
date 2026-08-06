"""Auth session finalization after _apply_authenticated_user (unit tests)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_draft_auth_finalize_stage1_diag import AUTH_FINALIZE4, AUTH_FINALIZE6, classify_auth_finalize_from_ledger
from live_draft_setup_ui import start_button_disabled
from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_ID_KEY,
    _apply_authenticated_user,
    auth_session_complete,
)


class AuthFinalizeTests(unittest.TestCase):
    def test_apply_sets_all_keys_required_for_complete(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            ok = _apply_authenticated_user(
                session,
                {"email": "daniel@example.com", "id": "uuid-1"},
                tokens={"access_token": "a", "refresh_token": "r"},
                st=st,
            )
        self.assertTrue(ok)
        self.assertTrue(auth_session_complete(session))
        self.assertTrue(session.get(AUTH_SESSION_KEY))

    def test_apply_return_false_when_tokens_missing(self) -> None:
        session: dict = {}
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            ok = _apply_authenticated_user(session, {"email": "a@b.com", "id": "u1"}, tokens=None)
        self.assertFalse(ok)
        self.assertFalse(auth_session_complete(session))

    def test_writes_on_actual_st_session_state(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            _apply_authenticated_user(
                st.session_state,
                {"email": "a@b.com", "id": "u1"},
                tokens={"access_token": "a", "refresh_token": "r"},
                st=st,
            )
        self.assertTrue(st.session_state.get(AUTH_SESSION_KEY))

    def test_temp_dict_does_not_count_as_st_state(self) -> None:
        session: dict = {}
        other: dict = {}
        st = mock.Mock()
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            _apply_authenticated_user(
                other,
                {"email": "a@b.com", "id": "u1"},
                tokens={"access_token": "a", "refresh_token": "r"},
                st=st,
            )
        self.assertFalse(session.get(AUTH_SESSION_KEY))

    def test_start_disabled_for_incomplete_auth(self) -> None:
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            disabled, _ = start_button_disabled({AUTH_SESSION_KEY: True, AUTH_USER_ID_KEY: "u1"})
        self.assertTrue(disabled)

    def test_start_enabled_for_complete_session(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "u1",
            AUTH_TOKENS_KEY: {"access_token": "a", "refresh_token": "r"},
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "live_draft_setup_ui.can_start_live_draft", return_value=(True, "")
        ):
            disabled, _ = start_button_disabled(session)
        self.assertFalse(disabled)

    def test_classify_finalize6_missing_tokens_at_start(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": "apply_authenticated_user_exit",
                "session_flag_present": True,
                "auth_session_complete": True,
                "session_object_id": 1,
            },
            {
                "event": "production_stage1_auth_state_before_start_control",
                "session_flag_present": True,
                "auth_session_complete": False,
                "auth_user_id_present": True,
                "access_token_present": False,
                "refresh_token_present": False,
                "session_object_id": 1,
            },
        ]
        cls, detail, _ = classify_auth_finalize_from_ledger(rows)
        self.assertEqual(cls, AUTH_FINALIZE6)

    def test_diagnostics_no_raw_tokens(self) -> None:
        session = {
            AUTH_SESSION_KEY: True,
            AUTH_USER_ID_KEY: "u1",
            AUTH_TOKENS_KEY: {"access_token": "eyJabc.def.ghi", "refresh_token": "r"},
        }
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            from live_draft_auth_snapshot_stage1_diag import auth_session_complete_breakdown

            blob = json.dumps(auth_session_complete_breakdown(session))
        self.assertNotIn("eyJabc", blob)

    def test_classify_finalize4_flag_cleared_mutation(self) -> None:
        rows = [
            {
                "event": "production_stage1_auth_prestart_mutation",
                "key": "_suite_auth_session",
                "value_present_before": True,
                "value_present_after": False,
                "source_function": "apply_baseball_disk_state",
            },
        ]
        cls, _, _ = classify_auth_finalize_from_ledger(rows)
        self.assertEqual(cls, AUTH_FINALIZE4)


if __name__ == "__main__":
    unittest.main()
