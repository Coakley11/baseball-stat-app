"""Baseball sidebar — Real Accounts sign-in status and controls for shared draft rooms."""

from __future__ import annotations

from typing import Any

ACCOUNT_EXPANDER_FLAG = "_baseball_account_expander_open"


def prepare_baseball_auth_session(st: Any) -> None:
    """Restore Supabase Auth from browser tokens before sidebar/widgets render."""
    try:
        from suite_auth import is_auth_enabled, restore_auth_session

        if is_auth_enabled():
            restore_auth_session(st.session_state, st=st)
    except ImportError:
        pass


def _dev_auth_details_visible(session: dict[str, Any]) -> bool:
    if session.get("dev_mode") or session.get("app_developer_mode"):
        return True
    try:
        from suite_workspace import _developer_query_enabled

        if _developer_query_enabled(st=type("S", (), {"session_state": session})()):
            return True
    except ImportError:
        pass
    return False


def real_account_status(session: dict[str, Any]) -> dict[str, Any]:
    """Structured Real Accounts status for UI and join diagnostics."""
    out: dict[str, Any] = {
        "auth_enabled": False,
        "signed_in": False,
        "email": "",
        "auth_user_id": "",
        "message": "",
    }
    try:
        from suite_auth import (
            AUTH_USER_ID_KEY,
            current_auth_email,
            is_auth_enabled,
            is_authenticated,
        )

        out["auth_enabled"] = bool(is_auth_enabled())
        if not out["auth_enabled"]:
            out["message"] = "Real Accounts disabled on this deploy."
            return out
        out["signed_in"] = bool(is_authenticated(session))
        out["email"] = str(current_auth_email(session) or "").strip()
        out["auth_user_id"] = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if out["signed_in"] and not out["auth_user_id"]:
            out["signed_in"] = False
            out["message"] = "Session incomplete — sign in again."
        elif out["signed_in"]:
            out["message"] = f"Signed in as {out['email'] or 'account'}"
        else:
            out["message"] = "Not signed in"
    except ImportError:
        out["message"] = "Auth module unavailable"
    return out


def request_account_sign_in_panel(session: dict[str, Any]) -> None:
    """Open the sidebar Account expander on the next rerun (e.g. from Live Draft join)."""
    session[ACCOUNT_EXPANDER_FLAG] = True


def render_baseball_account_sidebar(st: Any) -> None:
    """Compact sidebar account status + sign-in controls."""
    session = st.session_state
    prepare_baseball_auth_session(st)
    status = real_account_status(session)

    try:
        from suite_auth import is_auth_enabled

        if not is_auth_enabled():
            return
    except ImportError:
        return

    expanded = bool(session.pop(ACCOUNT_EXPANDER_FLAG, False))
    if status["signed_in"]:
        st.sidebar.caption(f"Account: **{status['email'] or 'signed in'}**")
    else:
        st.sidebar.caption("Account: **not signed in** (shared drafts need Real Accounts)")

    with st.sidebar.expander("Account & sign-in", expanded=expanded):
        if status["signed_in"]:
            st.success(status["message"])
        else:
            st.warning(
                "**Not signed in** — shared draft rooms require Real Account sign-in. "
                "Workspace and cloud sync alone are not enough."
            )
        if _dev_auth_details_visible(session) and status.get("auth_user_id"):
            st.caption(f"Supabase auth user id: `{status['auth_user_id']}`")
        elif _dev_auth_details_visible(session):
            st.caption("Supabase auth user id: —")

        try:
            from suite_auth import render_auth_panel

            render_auth_panel(st, expanded=not status["signed_in"])
        except ImportError:
            st.caption("Sign-in controls unavailable.")
