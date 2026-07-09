"""Baseball sidebar — Real Accounts sign-in status and controls for shared draft rooms."""

from __future__ import annotations

from typing import Any

ACCOUNT_EXPANDER_FLAG = "_baseball_account_expander_open"


def prepare_baseball_auth_session(st: Any) -> None:
    """Restore Supabase Auth from browser tokens before sidebar/widgets render."""
    try:
        from suite_auth import enforce_workspace_ownership, is_auth_enabled, restore_auth_session

        if is_auth_enabled():
            restore_auth_session(st.session_state, st=st)
            if st.session_state.get("_suite_auth_session"):
                enforce_workspace_ownership(st.session_state)
    except ImportError:
        pass


def _dev_auth_details_visible(session: dict[str, Any]) -> bool:
    try:
        from suite_workspace import developer_ui_visible_from_session

        return developer_ui_visible_from_session(session)
    except ImportError:
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
            auth_session_complete,
            current_auth_email,
            is_auth_enabled,
            is_authenticated,
        )

        out["auth_enabled"] = bool(is_auth_enabled())
        if not out["auth_enabled"]:
            out["message"] = "Real Accounts disabled on this deploy."
            return out
        out["signed_in"] = bool(auth_session_complete(session))
        out["email"] = str(current_auth_email(session) or "").strip()
        out["auth_user_id"] = str(session.get(AUTH_USER_ID_KEY) or "").strip()
        if is_authenticated(session) and not out["signed_in"]:
            out["message"] = "Session incomplete — sign in again."
        elif out["signed_in"]:
            out["message"] = f"Signed in as {out['email'] or 'account'}"
        else:
            out["message"] = "Not signed in"
    except ImportError:
        out["message"] = "Auth module unavailable"
    return out


def build_baseball_auth_status(session: dict[str, Any]) -> dict[str, Any]:
    """Structured auth + workspace snapshot for Developer Mode and save diagnostics."""
    status = dict(real_account_status(session))
    status["authenticated"] = bool(status.get("signed_in"))
    status["account_email"] = status.get("email") or ""
    status["account_user_id"] = status.get("auth_user_id") or ""
    status["external_id"] = ""
    status["owner_user_id"] = ""
    status["workspace_id"] = ""
    status["workspace_label"] = ""
    status["cloud_app_key"] = ""
    status["cloud_enabled"] = False
    status["shared_drafts_require_auth"] = False
    status["shared_drafts_auth_ok"] = True
    status["save_block_reason"] = ""
    try:
        from suite_auth import resolve_auth_external_id

        status["external_id"] = str(resolve_auth_external_id(session) or "").strip()
    except ImportError:
        status["external_id"] = str(session.get("_suite_auth_external_id") or "").strip()
    try:
        from suite_workspace_registry import _account_context

        ctx = _account_context(session)
        status["owner_user_id"] = str(ctx.get("owner_user_id") or "").strip()
        if not status["account_email"]:
            status["account_email"] = str(ctx.get("email") or "").strip()
    except ImportError:
        try:
            from suite_user import get_account_user_id

            status["owner_user_id"] = str(get_account_user_id() or "").strip()
        except ImportError:
            status["owner_user_id"] = str(session.get("_suite_auth_user_id") or "").strip()
    try:
        from suite_workspace import get_active_workspace_id, workspace_label as ws_label, workspace_persistence_meta

        class _St:
            session_state = session

        workspace_id = str(get_active_workspace_id(_St()) or "").strip()
        status["workspace_id"] = workspace_id
        status["workspace_label"] = ws_label(workspace_id) if workspace_id else ""
        meta = workspace_persistence_meta("baseball", st=_St())
        status["cloud_app_key"] = str(meta.get("cloud_app_key") or "").strip()
    except Exception:
        status["workspace_id"] = str(
            session.get("_suite_owned_workspace_id")
            or session.get("_suite_active_workspace_id")
            or session.get("suite_workspace_id")
            or ""
        ).strip()
    try:
        from suite_storage_config import cloud_storage_enabled

        status["cloud_enabled"] = bool(cloud_storage_enabled())
    except ImportError:
        pass
    try:
        from draft_room_membership import shared_room_requires_auth

        status["shared_drafts_require_auth"] = bool(shared_room_requires_auth())
        status["shared_drafts_auth_ok"] = (
            not status["shared_drafts_require_auth"]
            or (status["authenticated"] and status["account_user_id"])
        )
    except ImportError:
        pass
    if status["auth_enabled"] and not status["authenticated"]:
        if status["shared_drafts_require_auth"]:
            status["save_block_reason"] = (
                "Shared drafts require Real Account sign-in. "
                "Solo simulator saves (board/league context) still use workspace/disk."
            )
        else:
            status["save_block_reason"] = (
                "Real Accounts enabled but session not signed in. "
                "Workspace profile may still save locally."
            )
    elif not status["cloud_enabled"]:
        status["save_block_reason"] = "Cloud storage not configured — disk/workspace saves only."
    return status


def render_developer_auth_badge(st: Any) -> None:
    """Developer Mode sidebar: who Baseball thinks you are and what auth blocks."""
    if not _dev_auth_details_visible(st.session_state):
        return
    session = st.session_state
    prepare_baseball_auth_session(st)
    status = build_baseball_auth_status(session)
    with st.sidebar.expander("Auth & workspace", expanded=True):
        rows = {
            "auth_enabled": status.get("auth_enabled"),
            "authenticated": status.get("authenticated"),
            "account_email": status.get("account_email") or "—",
            "external_id": status.get("external_id") or "—",
            "owner_user_id": status.get("owner_user_id") or "—",
            "workspace": f"{status.get('workspace_label') or '—'} (`{status.get('workspace_id') or '—'}`)",
            "cloud_app_key": status.get("cloud_app_key") or "—",
            "cloud_enabled": status.get("cloud_enabled"),
            "shared_drafts_require_auth": status.get("shared_drafts_require_auth"),
            "shared_drafts_auth_ok": status.get("shared_drafts_auth_ok"),
            "save_block_reason": status.get("save_block_reason") or "—",
        }
        import pandas as pd

        st.dataframe(
            pd.DataFrame([{"key": k, "value": v} for k, v in rows.items()]),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "**Requires Real Accounts:** Create/join **Shared Draft Room** (multiplayer). "
            "**Does not require Real Accounts:** solo Draft Room Simulator, Save Draft Board, "
            "Save League/Mock Context, Saved Draft Library (uses workspace + disk/cloud profile)."
        )


def request_account_sign_in_panel(session: dict[str, Any]) -> None:
    """Open the sidebar Account expander on the next rerun (e.g. from Live Draft join)."""
    session[ACCOUNT_EXPANDER_FLAG] = True


def account_sidebar_should_render(session: dict[str, Any] | None = None) -> bool:
    """True when the Account & sign-in sidebar block must always be shown."""
    try:
        from suite_auth import is_auth_enabled

        return bool(is_auth_enabled())
    except ImportError:
        return False


def render_baseball_account_sidebar(st: Any) -> None:
    """Compact sidebar account status + sign-in controls — always when auth is enabled."""
    if not account_sidebar_should_render(st.session_state):
        return
    session = st.session_state
    prepare_baseball_auth_session(st)
    status = real_account_status(session)

    st.sidebar.markdown("**Account & sign-in**")
    if status["signed_in"]:
        st.sidebar.caption(f"Signed in as **{status['email'] or 'account'}**")
    else:
        st.sidebar.caption("Not signed in — shared drafts require Real Accounts")

    if not status["signed_in"]:
        st.sidebar.warning(
            "Sign in with your Real Account to unlock authenticated cloud saves and shared draft rooms."
        )
    if status.get("auth_user_id"):
        st.sidebar.caption(f"Supabase auth user id: `{status['auth_user_id']}`")

    try:
        from suite_auth import render_auth_panel

        render_auth_panel(
            st,
            expanded=True,
            show_signed_in_status=False,
            flat_sidebar=True,
        )
    except ImportError:
        st.sidebar.caption("Sign-in controls unavailable.")
