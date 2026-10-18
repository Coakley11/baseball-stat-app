"""Focused regressions for Baseball login, sidebar reruns, and billing identity."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from baseball_billing_client import billing_ui_state, create_checkout_url
from baseball_monetization import authenticated_subject
from suite_auth import (
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    login_with_email,
    restore_auth_session,
)
from suite_auth_browser import BROWSER_PERSIST_RESULT_KEY, browser_auth_storage_status
from suite_sidebar_run import (
    GUARD_ACCOUNT,
    claim_sidebar_render,
    reset_sidebar_run_guards,
    reset_sidebar_run_guards_for_tests,
)


ROOT = Path(__file__).resolve().parents[1]
TOKENS = {"access_token": "access-test", "refresh_token": "refresh-test"}


def _persistence(*, ok: bool, reason: str = "ok") -> dict:
    return {
        "persistence_attempted": True,
        "persistence_succeeded": ok,
        "write_committed": ok,
        "bridge_record_complete": ok,
        "failure_reason": reason,
        "handoff_phase": "INTERMEDIATE",
    }


def _user() -> SimpleNamespace:
    return SimpleNamespace(id="auth-user-1", email="coach@example.com", user_metadata={})


def test_account_guard_resets_for_login_and_subsequent_reruns() -> None:
    reset_sidebar_run_guards_for_tests()
    session: dict = {}
    for _ in range(3):
        reset_sidebar_run_guards(session)
        assert claim_sidebar_render(session, GUARD_ACCOUNT)
        assert not claim_sidebar_render(session, GUARD_ACCOUNT)
    source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    block = source[
        source.index("def _render_baseball_sidebar_chrome") : source.index(
            "def _on_resume_live_draft_sidebar"
        )
    ]
    assert "claim_sidebar_render" in block
    assert "_baseball_sidebar_chrome_run_token" not in block
    assert "get_script_run_ctx" not in block


def test_signed_in_account_workspace_renders_on_consecutive_reruns() -> None:
    from baseball_account_workspace import render_baseball_account_workspace_control

    st = mock.MagicMock()
    st.session_state = {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: "auth-user-1",
        AUTH_USER_EMAIL_KEY: "coach@example.com",
        AUTH_TOKENS_KEY: dict(TOKENS),
    }
    st.sidebar.expander.return_value.__enter__ = mock.MagicMock(return_value=None)
    st.sidebar.expander.return_value.__exit__ = mock.MagicMock(return_value=False)
    st.button.return_value = False
    patches = (
        mock.patch("baseball_account_sidebar.prepare_baseball_auth_session"),
        mock.patch("suite_workspace.bootstrap_suite_workspace"),
        mock.patch("suite_account_settings.init_suite_workspace"),
        mock.patch(
            "suite_account_settings.build_account_settings_context",
            return_value={"active_workspace_label": "Coach", "email_display": "coach@example.com"},
        ),
        mock.patch("suite_workspace.can_show_developer_tools", return_value=False),
        mock.patch("baseball_account_workspace._render_command_center_entry"),
        mock.patch("baseball_account_workspace._render_saved_sessions_section"),
        mock.patch("baseball_monetization_ui.render_account_subscription"),
        mock.patch("suite_auth.is_auth_enabled", return_value=True),
        mock.patch("suite_auth.is_authenticated", return_value=True),
        mock.patch("suite_auth.current_auth_email", return_value="coach@example.com"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as command_center, patches[6] as saved, patches[7], patches[8], patches[9], patches[10]:
        render_baseball_account_workspace_control(st, on_reset=lambda _st: None)
        render_baseball_account_workspace_control(st, on_reset=lambda _st: None)
    assert st.sidebar.expander.call_count == 2
    signed_in_calls = [c for c in st.markdown.call_args_list if c.args == ("Signed in as **coach@example.com**",)]
    assert len(signed_in_calls) == 2
    assert command_center.call_count == 2
    assert saved.call_count == 2


def test_billing_widget_failure_does_not_hide_workspace_controls() -> None:
    from baseball_account_workspace import _render_consolidated_body

    st = mock.MagicMock()
    session = {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: "auth-user-1",
        AUTH_USER_EMAIL_KEY: "coach@example.com",
        AUTH_TOKENS_KEY: dict(TOKENS),
    }
    st.session_state = session
    with mock.patch(
        "baseball_monetization_ui.render_account_subscription",
        side_effect=RuntimeError("billing unavailable"),
    ), mock.patch("baseball_account_workspace._render_command_center_entry") as command_center, mock.patch(
        "baseball_account_workspace._render_saved_sessions_section"
    ) as saved, mock.patch("suite_auth.current_auth_email", return_value="coach@example.com"), mock.patch(
        "suite_auth.is_auth_enabled", return_value=True
    ), mock.patch("suite_auth.is_authenticated", return_value=True):
        _render_consolidated_body(
            st,
            session,
            {"active_workspace_label": "Coach", "email_display": "coach@example.com"},
            app_id="baseball",
            on_reset=lambda _st: None,
            reset_label="Reset",
            reset_help="help",
        )
    command_center.assert_called_once()
    saved.assert_called_once()
    assert session["_baseball_subscription_widget_error_type"] == "RuntimeError"
    st.caption.assert_any_call("Subscription details are temporarily unavailable.")


def test_login_success_requires_durable_bridge_and_preserves_saved_workspace() -> None:
    saved = [{"draft_id": "draft-1", "name": "Keep Me"}]
    session: dict = {"draft_archive_teams": deepcopy(saved), "active_page": "Saved Draft Library"}
    before = deepcopy(session["draft_archive_teams"])
    st = mock.MagicMock(query_params={})
    st.session_state = session

    def persist_ok(ss: dict, *, st=None) -> str:
        ss[BROWSER_PERSIST_RESULT_KEY] = _persistence(ok=True)
        return "suite-user-1"

    with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
        "suite_auth._auth_api"
    ) as auth_api, mock.patch("suite_auth._user_from_auth_response", return_value=_user()), mock.patch(
        "suite_auth._tokens_from_auth_response", return_value=dict(TOKENS)
    ), mock.patch("suite_auth._sync_auth_account_identity", side_effect=persist_ok), mock.patch(
        "suite_workspace_registry.ensure_owned_workspace_for_session"
    ), mock.patch("suite_auth.enforce_workspace_ownership"), mock.patch(
        "suite_user_persistence.preserve_page_through_auth"
    ), mock.patch("draft_archive_visibility.sanitize_workflow_library_for_account") as sanitize, mock.patch(
        "draft_room_participant_state.on_auth_user_switch"
    ):
        auth_api.return_value.sign_in_with_password.return_value = object()
        ok, message = login_with_email(
            session,
            email="coach@example.com",
            password="secret",
            st=st,
        )
    assert ok and message == "Signed in."
    assert auth_session_complete(session)
    assert session["draft_archive_teams"] == before
    sanitize.assert_called_once()


def test_persistence_failure_rolls_back_login_without_workspace_cleanup() -> None:
    saved = [{"draft_id": "draft-1", "name": "Keep Me"}]
    session: dict = {"draft_archive_teams": deepcopy(saved), "active_page": "Saved Draft Library"}
    before = deepcopy(session)
    st = mock.MagicMock(query_params={})
    st.session_state = session

    def persist_failed(ss: dict, *, st=None) -> str:
        ss[BROWSER_PERSIST_RESULT_KEY] = _persistence(ok=False, reason="save_error:RuntimeError")
        return "suite-user-1"

    with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
        "suite_auth._auth_api"
    ) as auth_api, mock.patch("suite_auth._user_from_auth_response", return_value=_user()), mock.patch(
        "suite_auth._tokens_from_auth_response", return_value=dict(TOKENS)
    ), mock.patch("suite_auth._sync_auth_account_identity", side_effect=persist_failed), mock.patch(
        "suite_auth.enforce_workspace_ownership"
    ) as ownership, mock.patch(
        "draft_archive_visibility.sanitize_workflow_library_for_account"
    ) as sanitize, mock.patch("workflow_persist_guard.clear_draft_library_on_account_scope_change") as clear_library:
        auth_api.return_value.sign_in_with_password.return_value = object()
        ok, message = login_with_email(
            session,
            email="coach@example.com",
            password="secret",
            st=st,
        )
    assert not ok
    assert "secure refresh session could not be saved" in message
    assert session["draft_archive_teams"] == before["draft_archive_teams"]
    assert session["active_page"] == before["active_page"]
    assert not session.get(AUTH_SESSION_KEY)
    assert session[BROWSER_PERSIST_RESULT_KEY]["failure_reason"] == "save_error:RuntimeError"
    ownership.assert_not_called()
    sanitize.assert_not_called()
    clear_library.assert_not_called()


def test_auth_diagnostics_do_not_expose_session_identifier_or_tokens() -> None:
    st = mock.MagicMock(query_params={"suite_sid": "opaque-secret-session-id"})
    st.session_state = {BROWSER_PERSIST_RESULT_KEY: _persistence(ok=True)}
    with mock.patch("suite_storage_supabase.load_browser_auth_session", return_value=dict(TOKENS)):
        status = browser_auth_storage_status(st)
    rendered = repr(status)
    assert status["session_id_present"]
    assert "session_id_prefix" not in status
    assert "opaque-secret-session-id" not in rendered
    assert "access-test" not in rendered
    assert "refresh-test" not in rendered


def test_browser_refresh_restores_auth_without_changing_saved_workspace() -> None:
    saved = [{"draft_id": "draft-1", "name": "Keep Me"}]
    session: dict = {"draft_archive_teams": deepcopy(saved)}
    st = mock.MagicMock(query_params={"suite_sid": "opaque-test-value"})
    st.session_state = session

    def persist_ok(ss: dict, *, st=None) -> str:
        ss[BROWSER_PERSIST_RESULT_KEY] = _persistence(ok=True)
        return "suite-user-1"

    auth_response = SimpleNamespace(user=_user())
    with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
        "suite_auth_browser.load_browser_auth_tokens", return_value=dict(TOKENS)
    ), mock.patch("suite_auth_bridge_restore.execute_bridge_set_session_restore", new=None), mock.patch(
        "suite_auth._auth_api"
    ) as auth_api, mock.patch("suite_auth._user_from_auth_response", return_value=_user()), mock.patch(
        "suite_auth._tokens_from_auth_response", return_value=dict(TOKENS)
    ), mock.patch("suite_auth._sync_auth_account_identity", side_effect=persist_ok), mock.patch(
        "suite_auth.enforce_workspace_ownership"
    ), mock.patch("draft_archive_visibility.sanitize_workflow_library_for_account"):
        auth_api.return_value.set_session.return_value = auth_response
        assert restore_auth_session(session, st=st)
    assert auth_session_complete(session)
    assert session["draft_archive_teams"] == saved


def test_stripe_checkout_requires_complete_authentication() -> None:
    incomplete = {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: "auth-user-1",
        AUTH_TOKENS_KEY: {"access_token": "access-only"},
    }
    complete = {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: "auth-user-1",
        AUTH_TOKENS_KEY: dict(TOKENS),
    }
    from baseball_billing_config import RolloutMode

    config = SimpleNamespace(
        rollout=RolloutMode.TEST,
        client_checkout_enabled=True,
        billing_service_url="https://billing.test",
        test_mode=True,
    )
    with mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
        "baseball_billing_client.load_client_billing_config", return_value=config
    ), mock.patch("baseball_billing_client.requests.post") as post:
        assert authenticated_subject(incomplete) == ("", False, "")
        assert billing_ui_state(incomplete)["action"] == "signin"
        with pytest.raises(RuntimeError, match="Sign in"):
            create_checkout_url(incomplete)
        post.assert_not_called()

        response = mock.Mock(ok=True)
        response.json.return_value = {"url": "https://checkout.stripe.com/c/pay/test"}
        post.return_value = response
        assert authenticated_subject(complete) == ("auth-user-1", True, "access-test")
        assert create_checkout_url(complete) == "https://checkout.stripe.com/c/pay/test"
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer access-test"}
