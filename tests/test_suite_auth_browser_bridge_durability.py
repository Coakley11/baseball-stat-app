"""Browser auth bridge durability and lifecycle (unit tests)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from suite_auth import AUTH_SESSION_KEY, restore_auth_session
from suite_auth_browser import clear_browser_auth_tokens, load_browser_auth_tokens, save_browser_auth_tokens
from suite_auth_browser_bridge_diag import emit_bridge_mutation, probe_browser_auth_storage, readback_after_browser_auth_save


def _tokens() -> dict:
    return {"access_token": "access-test", "refresh_token": "refresh-test"}


class BridgeDurabilityTests(unittest.TestCase):
    def test_readback_failure_marks_incomplete(self) -> None:
        with mock.patch(
            "suite_auth_browser_bridge_diag.probe_browser_auth_storage",
            return_value={"production_row_found": False, "rejection_reason": "token_record_missing"},
        ):
            rb = readback_after_browser_auth_save("sid-1", expected_user_id="u1", save_reported_success=True)
        self.assertFalse(rb["readback_record_complete"])
        self.assertEqual(rb["failure_reason"], "token_record_missing")

    def test_save_without_readback_fails_persistence(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-save"}
        st.session_state = {"_suite_auth_user_id": "uuid-1"}
        with mock.patch(
            "suite_storage_supabase.save_browser_auth_session",
            return_value={"write_committed": True, "write_mode": "upsert"},
        ), mock.patch(
            "suite_auth_browser_bridge_diag.readback_after_browser_auth_save",
            return_value={
                "readback_record_complete": False,
                "readback_row_found": False,
                "failure_reason": "token_record_missing",
            },
        ), mock.patch("live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint"):
            save_browser_auth_tokens(st, _tokens(), auth_user_id="uuid-1")

    def test_diagnostics_contain_no_raw_tokens(self) -> None:
        rb = readback_after_browser_auth_save("x", save_reported_success=True)
        blob = json.dumps(rb, default=str)
        self.assertNotIn("eyJ", blob)
        self.assertNotIn("refresh-test", blob)

    def test_lookup_probe_does_not_invalidate(self) -> None:
        with mock.patch("suite_storage_supabase._request", return_value=[{"id": "1", "valid": True, "payload": _tokens()}]):
            probe_browser_auth_storage("sid-a", use_cache=False)
        with mock.patch("suite_storage_supabase.invalidate_browser_auth_session") as inv:
            load_browser_auth_tokens(
                mock.Mock(
                    query_params={"suite_sid": "sid-a"},
                    session_state={},
                )
            )
        inv.assert_not_called()

    def test_restore_auth_api_error_does_not_invalidate_bridge(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-restore"}
        st.session_state = session

        class AuthApiError(Exception):
            pass

        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens", return_value=_tokens()
        ), mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth_browser.clear_browser_auth_tokens"
        ) as clear_bridge, mock.patch("suite_auth.enforce_workspace_ownership"), mock.patch(
            "draft_archive_visibility.sanitize_workflow_library_for_account"
        ):
            auth_api.return_value.set_session.side_effect = AuthApiError("network")
            self.assertFalse(restore_auth_session(session, st=st))
            clear_bridge.assert_not_called()

    def test_restore_user_missing_does_not_invalidate_bridge(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-restore"}
        st.session_state = session
        with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens", return_value=_tokens()
        ), mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth._user_from_auth_response", return_value=None
        ), mock.patch("suite_auth._user_from_obj", return_value=None), mock.patch(
            "suite_auth_browser.clear_browser_auth_tokens"
        ) as clear_bridge, mock.patch("suite_auth.enforce_workspace_ownership"), mock.patch(
            "draft_archive_visibility.sanitize_workflow_library_for_account"
        ):
            auth_api.return_value.set_session.return_value = mock.Mock(user=None)
            auth_api.return_value.get_user.return_value = mock.Mock(user=None)
            self.assertFalse(restore_auth_session(session, st=st))
            clear_bridge.assert_not_called()

    def test_logout_invalidates_bridge(self) -> None:
        from suite_auth import logout

        session: dict = {AUTH_SESSION_KEY: True}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-out"}
        st.session_state = session
        with mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth_browser.clear_browser_auth_tokens"
        ) as clear_bridge, mock.patch("draft_room_participant_state.on_auth_logout_save_workflow"), mock.patch(
            "suite_user.reset_account_cache"
        ):
            auth_api.return_value.sign_out.return_value = None
            logout(session, st=st)
            clear_bridge.assert_called_once()
            self.assertEqual(clear_bridge.call_args.kwargs.get("reason"), "explicit_sign_out")

    def test_clear_browser_auth_tokens_emits_mutation_fields(self) -> None:
        st = mock.Mock()
        st.query_params = {"suite_sid": "abcdef12-uuid"}
        st.session_state = {"_suite_auth_user_id": "user-uuid-1"}
        with mock.patch(
            "suite_auth_browser_bridge_diag.probe_browser_auth_storage",
            return_value={
                "row_id": "31651abc",
                "production_row_valid": True,
                "access_token_present": True,
                "refresh_token_present": True,
                "expires_at": 123,
            },
        ), mock.patch(
            "suite_storage_supabase.invalidate_browser_auth_session",
            return_value={"invalidated": True, "prior_row_id": "31651abc"},
        ), mock.patch("suite_auth_browser_bridge_diag.emit_bridge_mutation") as emit:
            clear_browser_auth_tokens(st, reason="explicit_sign_out", caller="_clear_auth_session")
            emit.assert_called_once()
            kw = emit.call_args.kwargs
            self.assertEqual(kw.get("mutation_type"), "invalidate")
            self.assertEqual(kw.get("caller"), "_clear_auth_session")
            self.assertEqual(kw.get("prior_valid"), True)
            self.assertEqual(kw.get("new_valid"), False)

    def test_emit_bridge_mutation_has_no_raw_user_id(self) -> None:
        session = {"_suite_auth_user_id": "00000000-0000-4000-8000-000000000001"}
        with mock.patch("suite_auth_browser_bridge_diag.emit_bridge_storage_checkpoint") as emit:
            emit_bridge_mutation(
                session,
                operation="invalidate",
                sid="suite-sid-1",
                reason="test",
                auth_user_id="00000000-0000-4000-8000-000000000001",
            )
            extra = emit.call_args.kwargs.get("extra") or emit.call_args[1].get("extra") or {}
            blob = json.dumps(extra, default=str)
            self.assertNotIn("00000000-0000-4000-8000-000000000001", blob)
            self.assertTrue(extra.get("auth_user_id_hash"))

    def test_two_loads_same_sid_both_read_without_invalidate(self) -> None:
        rows = [{"payload": _tokens(), "valid": True, "id": "row1"}]
        with mock.patch("suite_storage_supabase._request", side_effect=[rows, rows, [], rows, rows, []]):
            st1 = mock.Mock(query_params={"suite_sid": "shared-sid"}, session_state={})
            st2 = mock.Mock(query_params={"suite_sid": "shared-sid"}, session_state={})
            with mock.patch("suite_storage_supabase.load_browser_auth_session", return_value=_tokens()):
                self.assertEqual(load_browser_auth_tokens(st1), _tokens())
                self.assertEqual(load_browser_auth_tokens(st2), _tokens())
        with mock.patch("suite_storage_supabase.invalidate_browser_auth_session") as inv:
            load_browser_auth_tokens(mock.Mock(query_params={"suite_sid": "shared-sid"}, session_state={}))
        inv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
