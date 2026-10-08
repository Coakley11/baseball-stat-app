"""
Baseball Account & Workspace — single sidebar entry point.

Mirrors Investment/Music: one top-left Login / Account & Workspace control that nests
Command Center + Saved Sessions + Log out, so Baseball no longer shows separate
Command Center / Saved session chrome above Choose Page.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = ("render_baseball_account_workspace_control",)

_APP_ID = "baseball"

# One header in every normal-mode state (Music parity). It used to read "Login"
# even on deploys where sign-in is switched off, implying a local workspace was a
# real account; who you are and which workspace you are in now live inside.
ACCOUNT_WORKSPACE_HEADER = "Account & Workspace"


def _workspace_label(ctx: dict[str, Any]) -> str:
    return str(ctx.get("active_workspace_label") or "Workspace").strip() or "Workspace"


def _shared_drafts_require_sign_in() -> bool:
    """What the stabilized product enforces -- the copy must never claim more."""
    try:
        from draft_room_membership import shared_room_requires_auth

        return bool(shared_room_requires_auth())
    except Exception:
        return False


def _signed_in_email(ctx: dict[str, Any], session_state: dict[str, Any]) -> str:
    try:
        from suite_auth import current_auth_email, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session_state):
            email = str(current_auth_email(session_state) or "").strip()
            if email:
                return email
    except ImportError:
        pass
    email = str(ctx.get("email_display") or "").strip()
    if email and email != "(not configured — set suite_user_email in secrets)":
        return email
    return ""


def _render_command_center_entry(st: Any) -> None:
    try:
        from suite_command_center_link import command_center_url
        from suite_workspace import get_active_workspace_id

        url = command_center_url(workspace_id=get_active_workspace_id(st))
    except Exception:
        try:
            from suite_command_center_link import command_center_url

            url = command_center_url()
        except Exception:
            return
    if not url:
        return
    st.link_button("← Command Center", url, use_container_width=True)


def _render_saved_sessions_section(
    st: Any,
    app_id: str,
    *,
    on_reset: Callable[[Any], None],
    label: str = "Reset to default",
    help_text: str = "Clears your saved session for this app only.",
) -> None:
    from suite_user_persistence import (
        clear_reset_confirm_state,
        execute_suite_reset,
        request_reset_confirm_state,
        reset_confirm_session_key,
    )

    pending = bool(st.session_state.get(reset_confirm_session_key(app_id)))
    st.markdown("**Saved Sessions**")
    st.caption("Your last page, filters, and inputs reload automatically.")
    if pending:
        st.warning("This clears saved preferences for this app. Continue?")
        c1, c2 = st.columns(2)
        with c1:
            st.button(
                "Yes, reset",
                key=f"suite_reset_yes::{app_id}",
                type="primary",
                on_click=execute_suite_reset,
                kwargs={
                    "st": st,
                    "app_id": app_id,
                    "on_reset": on_reset,
                },
            )
        with c2:
            st.button(
                "Cancel",
                key=f"suite_reset_no::{app_id}",
                on_click=clear_reset_confirm_state,
                kwargs={"session_state": st.session_state, "app_id": app_id},
            )
    else:
        st.button(
            label,
            key=f"suite_reset_btn::{app_id}",
            help=help_text,
            on_click=request_reset_confirm_state,
            kwargs={"session_state": st.session_state, "app_id": app_id},
        )


def _auth_session_active(session_state: dict[str, Any]) -> bool:
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        return bool(is_auth_enabled() and is_authenticated(session_state))
    except ImportError:
        return False


def _render_logout_entry(st: Any, session_state: dict[str, Any]) -> None:
    try:
        from suite_auth import is_auth_enabled, is_authenticated, logout

        if is_auth_enabled() and is_authenticated(session_state):
            if st.button("Log out", key="suite_account_workspace_logout_btn", use_container_width=True):
                logout(session_state, st=st)
                st.rerun()
    except ImportError:
        pass


def _render_consolidated_body(
    st: Any,
    session_state: dict[str, Any],
    ctx: dict[str, Any],
    *,
    app_id: str,
    on_reset: Callable[[Any], None],
    reset_label: str,
    reset_help: str,
) -> None:
    email = _signed_in_email(ctx, session_state)
    if email:
        st.markdown(f"Signed in as **{email}**")
    else:
        # Local/shared profile: say plainly that this is not an authenticated account.
        st.caption("Local workspace — sign-in isn't available on this deploy.")
    st.caption(f"Workspace: **{_workspace_label(ctx)}**")

    try:
        from baseball_monetization_ui import render_account_subscription

        st.divider()
        render_account_subscription(st, session_state)
    except ImportError:
        pass

    st.divider()
    st.markdown("**Command Center**")
    _render_command_center_entry(st)
    st.divider()
    _render_saved_sessions_section(
        st,
        app_id,
        on_reset=on_reset,
        label=reset_label,
        help_text=reset_help,
    )
    # Divider only when a Log out button follows it. Unconditionally it left a
    # dangling rule and dead space at the bottom of the panel whenever nobody is
    # signed in (always, on deploys with sign-in switched off).
    if _signed_in_email(ctx, session_state) and _auth_session_active(session_state):
        st.divider()
        _render_logout_entry(st, session_state)


def render_baseball_account_workspace_control(
    st: Any,
    *,
    app_id: str = _APP_ID,
    on_reset: Callable[[Any], None] | None = None,
    reset_label: str = "Reset to default",
    reset_help: str = (
        "Clears saved page, filters, and workspace for this app. Lahman data is not deleted."
    ),
) -> None:
    """Single top-left Login / Account & Workspace control for Baseball."""
    try:
        from baseball_account_sidebar import prepare_baseball_auth_session

        prepare_baseball_auth_session(st)
    except ImportError:
        pass

    try:
        from suite_workspace import bootstrap_suite_workspace

        bootstrap_suite_workspace(st)
    except ImportError:
        pass

    try:
        from suite_workspace import can_show_developer_tools

        if can_show_developer_tools(st=st):
            try:
                from suite_app_shell import render_suite_namespace_notices

                render_suite_namespace_notices(st)
            except ImportError:
                pass
    except ImportError:
        pass

    try:
        from suite_account_settings import (
            build_account_settings_context,
            init_suite_workspace,
            render_account_settings_panel,
        )
    except ImportError:
        st.sidebar.caption("Account settings module unavailable on this deploy.")
        return

    if on_reset is None:
        try:
            from baseball_persistent_state import default_reset_baseball_session

            on_reset = default_reset_baseball_session
        except ImportError:

            def on_reset(_st: Any) -> None:
                return None

    init_suite_workspace(st)
    ctx = build_account_settings_context(st=st)

    try:
        from suite_auth import is_auth_enabled, is_authenticated, render_auth_panel

        auth_on = is_auth_enabled()
        signed_in = is_authenticated(st.session_state)
    except ImportError:
        auth_on = False
        signed_in = True

    # Logged out: one clear Login entry (auth panel), no separate CC/Saved chrome.
    if auth_on and not signed_in:
        open_login = bool(st.session_state.pop("_baseball_account_expander_open", False))
        with st.sidebar.expander(
            ACCOUNT_WORKSPACE_HEADER,
            expanded=open_login or True,
            key="suite_account_workspace_expander",
        ):
            st.markdown("**Not signed in**")
            if _shared_drafts_require_sign_in():
                st.caption(
                    f"Solo work saves to the **{_workspace_label(ctx)}** workspace on this "
                    "device. Sign in with a Real Account to create or join Shared Draft "
                    "rooms and sync across devices."
                )
            else:
                st.caption(
                    f"Working in the local **{_workspace_label(ctx)}** workspace. Sign in "
                    "with a Real Account to sync suite data across devices."
                )
            render_auth_panel(st, expanded=True, show_signed_in_status=False, flat_sidebar=True)
            st.divider()
            st.markdown("**Command Center**")
            _render_command_center_entry(st)
            st.divider()
            _render_saved_sessions_section(
                st,
                app_id,
                on_reset=on_reset,
                label=reset_label,
                help_text=reset_help,
            )
        return

    # Auth disabled / shared profile: still one top control (Investment parity).
    # Label as Login when there is no signed-in identity so the human path matches
    # the requested top-left entry point.
    if not auth_on:
        with st.sidebar.expander(
            ACCOUNT_WORKSPACE_HEADER, expanded=False, key="suite_account_workspace_expander"
        ):
            _render_consolidated_body(
                st,
                st.session_state,
                ctx,
                app_id=app_id,
                on_reset=on_reset,
                reset_label=reset_label,
                reset_help=reset_help,
            )
        return

    dev_mode = False
    try:
        from suite_workspace import can_show_developer_tools

        dev_mode = can_show_developer_tools(st=st)
    except ImportError:
        pass

    if dev_mode:
        render_account_settings_panel(st, expanded=True, show_title=True, sidebar=True)
        with st.sidebar.expander("Suite navigation (dev)", expanded=True):
            _render_consolidated_body(
                st,
                st.session_state,
                ctx,
                app_id=app_id,
                on_reset=on_reset,
                reset_label=reset_label,
                reset_help=reset_help,
            )
        return

    open_account = bool(st.session_state.pop("_baseball_account_expander_open", False))
    with st.sidebar.expander(
        ACCOUNT_WORKSPACE_HEADER, expanded=open_account, key="suite_account_workspace_expander"
    ):
        # Single Log out lives in the body. The auth panel used to be appended here
        # "for password/session management", but when signed in render_auth_panel
        # renders only its own Log out button -- a duplicate. Password tabs exist
        # only in its signed-out branch, which the signed-out view above still uses.
        _render_consolidated_body(
            st,
            st.session_state,
            ctx,
            app_id=app_id,
            on_reset=on_reset,
            reset_label=reset_label,
            reset_help=reset_help,
        )
