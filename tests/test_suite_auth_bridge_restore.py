"""Bridge restore single-flight, rotation persist, AUTH_HYDRATE3B recovery."""

from __future__ import annotations

import unittest
from unittest import mock

from suite_auth import AUTH_SESSION_KEY, AUTH_TOKENS_KEY, restore_auth_session
from suite_auth_bridge_restore import (
    RESTORE_FINAL_3B_KEY,
    RESTORE_INFLIGHT_KEY,
    execute_bridge_set_session_restore,
)
from suite_auth_bridge_token_meta import enrich_bridge_payload, token_fingerprint
from suite_storage_supabase import save_browser_auth_session_versioned


def _tokens(*, access: str = "access-a", refresh: str = "refresh-a") -> dict:
    return {"access_token": access, "refresh_token": refresh, "expires_at": 999}


class BridgeRestoreTests(unittest.TestCase):
    def test_single_flight_second_attempt_skips_set_session(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-1"}
        st.session_state = session
        calls: list[int] = []

        def finish(ok: bool, reason: str) -> bool:
            return ok

        inflight = {
            "owner": "owner-a",
            "attempt_id": "attempt-1",
            "started_ts": __import__("time").time(),
            "restore_generation": 1,
        }
        session[RESTORE_INFLIGHT_KEY] = inflight
        meta = {"token_generation": 1, "refresh_fp": token_fingerprint("refresh-a")}
        with mock.patch("suite_auth._auth_api") as auth_api:
            auth_api.return_value.set_session.side_effect = lambda *a, **k: calls.append(1)
            result = execute_bridge_set_session_restore(
                session,
                st=st,
                tokens=_tokens(),
                token_meta=meta,
                auth_before=False,
                finish=finish,
            )
        self.assertFalse(result)
        self.assertEqual(calls, [])

    def test_rotation_persist_bumps_generation(self) -> None:
        store: dict = {"gen": 2, "payload": enrich_bridge_payload(_tokens(refresh="refresh-old"), token_generation=2)}

        def fake_load(sid: str):
            return {
                "row_id": "31726",
                "user_id": "user-1",
                "token_generation": store["gen"],
                "refresh_fp": store["payload"]["refresh_fp"],
                "payload": store["payload"],
                "access_token": store["payload"]["access_token"],
                "refresh_token": store["payload"]["refresh_token"],
                "expires_at": 0,
            }

        def fake_request(method, table, **kwargs):
            if method == "PATCH" or method == "POST":
                new_tokens = kwargs.get("json_body", {}).get("payload") or kwargs.get("json_body", {})
                if isinstance(new_tokens, dict) and "access_token" in new_tokens:
                    store["gen"] = int(new_tokens.get("token_generation") or store["gen"] + 1)
                    store["payload"] = new_tokens
            return []

        with mock.patch(
            "suite_storage_supabase.load_browser_auth_session_record",
            side_effect=fake_load,
        ), mock.patch("suite_storage_supabase._request", side_effect=fake_request):
            w1 = save_browser_auth_session_versioned(
                "sid-1",
                user_id="user-1",
                tokens=_tokens(refresh="refresh-new"),
                expected_generation=2,
            )
        self.assertTrue(w1.get("write_committed"))
        self.assertEqual(w1.get("token_generation"), 3)
        with mock.patch(
            "suite_storage_supabase.load_browser_auth_session_record",
            side_effect=fake_load,
        ):
            w2 = save_browser_auth_session_versioned(
                "sid-1",
                user_id="user-1",
                tokens=_tokens(refresh="refresh-stale"),
                expected_generation=2,
            )
        self.assertTrue(w2.get("stale_generation_rejected"))
        self.assertFalse(w2.get("write_committed"))

    def test_refresh_already_used_recovery_with_newer_generation(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-1"}
        st.session_state = session

        class AlreadyUsed(Exception):
            code = "refresh_token_already_used"

        user = mock.Mock(id="user-1")
        rotated = _tokens(access="access-new", refresh="refresh-new")
        meta_old = {"token_generation": 1, "refresh_fp": token_fingerprint("refresh-old")}
        meta_new = {"token_generation": 2, "refresh_fp": token_fingerprint("refresh-new")}

        def finish(ok: bool, reason: str) -> bool:
            return ok

        with mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth._user_from_auth_response",
            return_value=user,
        ), mock.patch(
            "suite_auth._tokens_from_auth_response",
            side_effect=[rotated, rotated],
        ), mock.patch(
            "suite_auth._apply_authenticated_user",
        ), mock.patch(
            "suite_auth._clear_auth_session",
        ), mock.patch(
            "suite_auth_bridge_restore._persist_rotated_tokens_immediately",
            return_value={"write_committed": True, "token_generation": 2},
        ), mock.patch(
            "suite_auth_bridge_restore._load_bridge_tokens_with_meta",
            return_value=(_tokens(refresh="refresh-new"), meta_new),
        ):
            auth_api.return_value.set_session.side_effect = [AlreadyUsed("used"), mock.Mock()]
            ok = execute_bridge_set_session_restore(
                session,
                st=st,
                tokens=_tokens(refresh="refresh-old"),
                token_meta=meta_old,
                auth_before=False,
                finish=finish,
            )
        self.assertTrue(ok)
        self.assertEqual(auth_api.return_value.set_session.call_count, 2)

    def test_refresh_already_used_final_when_bridge_unchanged(self) -> None:
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-1"}
        st.session_state = session

        class AlreadyUsed(Exception):
            code = "refresh_token_already_used"

        meta = {"token_generation": 3, "refresh_fp": token_fingerprint("refresh-x")}

        def finish(ok: bool, reason: str) -> bool:
            self.assertFalse(ok)
            self.assertEqual(reason, "auth_hydrate_3b_final")
            return ok

        with mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth._clear_auth_session",
        ), mock.patch(
            "suite_auth_bridge_restore._load_bridge_tokens_with_meta",
            return_value=(_tokens(refresh="refresh-x"), meta),
        ):
            auth_api.return_value.set_session.side_effect = AlreadyUsed("used")
            execute_bridge_set_session_restore(
                session,
                st=st,
                tokens=_tokens(refresh="refresh-x"),
                token_meta=meta,
                auth_before=False,
                finish=finish,
            )
        self.assertTrue(session.get(RESTORE_FINAL_3B_KEY))
        with mock.patch("suite_auth._auth_api") as auth_api2, mock.patch(
            "suite_auth.is_auth_enabled",
            return_value=True,
        ), mock.patch(
            "suite_auth_browser.load_browser_auth_tokens",
            return_value=_tokens(refresh="refresh-x"),
        ), mock.patch(
            "suite_auth_bridge_restore.load_bridge_tokens_with_meta",
            return_value=(_tokens(refresh="refresh-x"), meta),
        ):
            auth_api2.return_value.set_session.side_effect = AlreadyUsed("used")
            self.assertFalse(restore_auth_session(session, st=st))
        self.assertEqual(auth_api2.return_value.set_session.call_count, 0)

    def test_successful_restore_persists_before_apply_order(self) -> None:
        order: list[str] = []
        session: dict = {}
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-1"}
        st.session_state = session
        user = mock.Mock(id="user-1")
        rotated = _tokens(refresh="refresh-rotated")

        def finish(ok: bool, reason: str) -> bool:
            return ok

        def persist(*args, **kwargs):
            order.append("persist")
            return {"write_committed": True, "token_generation": 2}

        def apply(*args, **kwargs):
            order.append("apply")

        with mock.patch("suite_auth._auth_api") as auth_api, mock.patch(
            "suite_auth._user_from_auth_response",
            return_value=user,
        ), mock.patch(
            "suite_auth._tokens_from_auth_response",
            return_value=rotated,
        ), mock.patch(
            "suite_auth_bridge_restore._persist_rotated_tokens_immediately",
            side_effect=persist,
        ), mock.patch(
            "suite_auth._apply_authenticated_user",
            side_effect=apply,
        ):
            auth_api.return_value.set_session.return_value = mock.Mock()
            self.assertTrue(
                execute_bridge_set_session_restore(
                    session,
                    st=st,
                    tokens=_tokens(refresh="refresh-orig"),
                    token_meta={"token_generation": 1, "refresh_fp": token_fingerprint("refresh-orig")},
                    auth_before=False,
                    finish=finish,
                )
            )
        self.assertEqual(order, ["persist", "apply"])

    def test_already_applied_generation_skips_set_session(self) -> None:
        session: dict = {
            AUTH_TOKENS_KEY: _tokens(),
            AUTH_SESSION_KEY: True,
            "_suite_auth_user_id": "user-1",
        }
        st = mock.Mock()
        st.query_params = {"suite_sid": "sid-1"}
        st.session_state = session
        from suite_auth_bridge_restore import RESTORE_APPLIED_GEN_KEY

        session[RESTORE_APPLIED_GEN_KEY] = 5

        def finish(ok: bool, reason: str) -> bool:
            return ok

        with mock.patch("suite_auth._auth_api") as auth_api:
            ok = execute_bridge_set_session_restore(
                session,
                st=st,
                tokens=_tokens(),
                token_meta={"token_generation": 5, "refresh_fp": token_fingerprint("refresh-a")},
                auth_before=False,
                finish=finish,
            )
        self.assertTrue(ok)
        auth_api.return_value.set_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
