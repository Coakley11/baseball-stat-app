"""
Real Accounts foundation (Sprint C) — Supabase Auth email/password.

Disabled by default via ``SUITE_AUTH_ENABLED``. When off, the suite uses shared
secrets identity from ``suite_user.py`` (Workspace Profiles v1 behavior).

Synced to sibling repos via ``scripts/sync_suite_cloud_modules.py``.
"""

from __future__ import annotations

import os
from typing import Any

AUTH_ENABLED_ENV = "SUITE_AUTH_ENABLED"
AUTH_SESSION_KEY = "_suite_auth_session"
AUTH_USER_EMAIL_KEY = "_suite_auth_user_email"
AUTH_USER_ID_KEY = "_suite_auth_user_id"
AUTH_PROFILE_KEY = "_suite_auth_profile"
AUTH_NOTICE_KEY = "_suite_auth_notice"
AUTH_EXTERNAL_ID_KEY = "_suite_auth_external_id"

# Workspace ownership v1 — map external/auth user to allowed preset profiles.
_DEFAULT_ALLOWED_WORKSPACES: dict[str, tuple[str, ...]] = {
    "daniel": ("daniel",),
    "ariel": ("ariel",),
    "guest": ("guest",),
    "test_user": ("test_user",),
}


def is_auth_enabled() -> bool:
    """True when Real Accounts auth UI and Supabase Auth flows are active."""
    env = os.environ.get(AUTH_ENABLED_ENV, "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    try:
        import streamlit as st  # noqa: WPS433

        block = st.secrets.get("suite_activity") if hasattr(st, "secrets") else None
        if block is None:
            try:
                block = st.secrets["suite_activity"]
            except Exception:
                block = None
        if block is not None:
            val = str(getattr(block, "get", lambda _k, _d=None: None)("suite_auth_enabled") or "").strip().lower()
            if val in ("1", "true", "yes", "on"):
                return True
    except Exception:
        pass
    return False


def password_auth_available() -> bool:
    return is_auth_enabled()


def is_authenticated(session_state: dict[str, Any]) -> bool:
    if not is_auth_enabled():
        return True
    return bool(session_state.get(AUTH_SESSION_KEY))


def current_auth_email(session_state: dict[str, Any]) -> str:
    return str(session_state.get(AUTH_USER_EMAIL_KEY) or "").strip()


def allowed_workspaces_for_user(external_user_id: str) -> tuple[str, ...]:
    """Workspace ownership v1 — preset profiles allowed for this account."""
    key = str(external_user_id or "").strip().lower()
    if key in _DEFAULT_ALLOWED_WORKSPACES:
        return _DEFAULT_ALLOWED_WORKSPACES[key]
    if key == "default":
        return ("daniel", "guest", "test_user")
    return ("daniel", "guest", "test_user")


def _infer_external_id_from_email(email: str) -> str:
    low = str(email or "").strip().lower()
    if not low:
        return ""
    if "ariel" in low:
        return "ariel"
    if "daniel" in low or "coakley" in low:
        return "daniel"
    local = low.split("@", 1)[0]
    if local in _DEFAULT_ALLOWED_WORKSPACES:
        return local
    return local or "daniel"


def enforce_workspace_ownership(session_state: dict[str, Any]) -> None:
    """Clamp active workspace to profiles owned by the signed-in account."""
    if not is_auth_enabled() or not is_authenticated(session_state):
        return
    try:
        from types import SimpleNamespace

        from suite_workspace import get_active_workspace_id, normalize_workspace_id, set_active_workspace_id

        st = SimpleNamespace(session_state=session_state)
        ext = str(
            session_state.get(AUTH_EXTERNAL_ID_KEY)
            or session_state.get(AUTH_USER_ID_KEY)
            or _infer_external_id_from_email(current_auth_email(session_state))
            or ""
        ).strip()
        allowed = allowed_workspaces_for_user(ext)
        active = normalize_workspace_id(get_active_workspace_id(st))
        if active not in allowed and allowed:
            set_active_workspace_id(st, allowed[0])
    except ImportError:
        pass


def logout(session_state: dict[str, Any]) -> None:
    for key in (
        AUTH_SESSION_KEY,
        AUTH_USER_EMAIL_KEY,
        AUTH_USER_ID_KEY,
        AUTH_PROFILE_KEY,
        AUTH_NOTICE_KEY,
        AUTH_EXTERNAL_ID_KEY,
    ):
        session_state.pop(key, None)


def _read_profile_settings(email: str) -> dict[str, Any]:
    try:
        from suite_account import load_settings

        return load_settings(app="_global") or {}
    except Exception:
        return {}


def save_profile_settings(session_state: dict[str, Any], profile: dict[str, Any]) -> None:
    merged = dict(_read_profile_settings(current_auth_email(session_state)))
    merged.update({k: v for k, v in profile.items() if v is not None})
    session_state[AUTH_PROFILE_KEY] = merged
    try:
        from suite_account import save_settings

        save_settings(app="_global", data=merged)
    except Exception:
        pass


def _supabase_auth_client() -> Any | None:
    if not is_auth_enabled():
        return None
    try:
        from suite_storage_supabase import get_supabase_client

        client = get_supabase_client()
        auth = getattr(client, "auth", None)
        if auth is None:
            return None
        return auth
    except Exception:
        return None


def auth_backend_status() -> dict[str, Any]:
    """Safe diagnostics for Real Accounts — no secret values."""
    out: dict[str, Any] = {
        "auth_ui_enabled": is_auth_enabled(),
        "ready": False,
        "message": "",
        "supabase_package_installed": False,
        "cloud_config": False,
        "auth_api_key_set": False,
    }
    if not is_auth_enabled():
        out["message"] = "Auth UI disabled (set suite_auth_enabled = true)."
        return out
    try:
        import supabase  # noqa: F401

        out["supabase_package_installed"] = True
    except ImportError:
        out["message"] = (
            "Python package 'supabase' is not installed. Add supabase>=2.0.0 to requirements.txt and redeploy."
        )
        return out
    try:
        from suite_storage_config import get_auth_api_key, get_cloud_config

        out["cloud_config"] = get_cloud_config() is not None
        out["auth_api_key_set"] = bool(get_auth_api_key())
    except Exception as exc:
        out["message"] = str(exc)
        return out
    if not out["cloud_config"]:
        out["message"] = (
            "Supabase cloud config missing — set supabase_url and supabase_key under [suite_activity]."
        )
        return out
    if not out["auth_api_key_set"]:
        out["message"] = (
            "Supabase Auth key missing — set supabase_anon_key under [suite_activity] "
            "(Supabase → Settings → API → anon public)."
        )
        return out
    if _supabase_auth_client() is None:
        out["message"] = "Supabase Auth client could not be initialized."
        return out
    out["ready"] = True
    out["message"] = "Auth backend ready."
    return out


def _auth_not_configured_message() -> str:
    status = auth_backend_status()
    if status.get("ready"):
        return "Auth is not configured on this deployment."
    msg = str(status.get("message") or "").strip()
    return msg or "Auth is not configured on this deployment."


def signup_with_email(session_state: dict[str, Any], *, email: str, password: str) -> tuple[bool, str]:
    auth = _supabase_auth_client()
    if auth is None:
        return False, _auth_not_configured_message()
    try:
        resp = auth.sign_up({"email": email.strip(), "password": password})
        user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)
        if user is None:
            return False, "Sign-up did not return a user — check Supabase Auth settings."
        session_state[AUTH_NOTICE_KEY] = "Account created. Check your email if confirmation is required, then log in."
        return True, str(session_state[AUTH_NOTICE_KEY])
    except Exception as exc:
        return False, str(exc)


def login_with_email(session_state: dict[str, Any], *, email: str, password: str) -> tuple[bool, str]:
    auth = _supabase_auth_client()
    if auth is None:
        return False, _auth_not_configured_message()
    try:
        resp = auth.sign_in_with_password({"email": email.strip(), "password": password})
        user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)
        if user is None:
            return False, "Invalid email or password."
        session_state[AUTH_SESSION_KEY] = True
        session_state[AUTH_USER_EMAIL_KEY] = str(getattr(user, "email", None) or email).strip()
        session_state[AUTH_EXTERNAL_ID_KEY] = _infer_external_id_from_email(
            session_state[AUTH_USER_EMAIL_KEY]
        )
        uid = str(getattr(user, "id", None) or "").strip()
        if uid:
            session_state[AUTH_USER_ID_KEY] = uid
        try:
            from suite_storage_supabase import ensure_user_row

            ensure_user_row(external_id=session_state[AUTH_USER_EMAIL_KEY] or uid)
        except Exception:
            pass
        enforce_workspace_ownership(session_state)
        session_state[AUTH_NOTICE_KEY] = "Signed in."
        return True, "Signed in."
    except Exception as exc:
        return False, str(exc)


def request_password_reset(email: str) -> tuple[bool, str]:
    auth = _supabase_auth_client()
    if auth is None:
        return False, _auth_not_configured_message()
    try:
        auth.reset_password_email(email.strip())
        return True, "Password reset email sent."
    except Exception as exc:
        return False, str(exc)


def render_auth_panel(st: Any, *, expanded: bool = False) -> None:
    """Login / sign-up panel when Real Accounts are enabled."""
    if not is_auth_enabled():
        return
    session = st.session_state
    notice = session.pop(AUTH_NOTICE_KEY, None)
    if notice:
        st.info(str(notice))
    if is_authenticated(session):
        st.success(f"Signed in as **{current_auth_email(session) or 'account'}**")
        if st.button("Log out", key="suite_auth_logout_btn", use_container_width=True):
            logout(session)
            st.rerun()
        return
    title = "Sign in"
    with st.expander(title, expanded=expanded):
        tab_login, tab_signup, tab_reset = st.tabs(["Log in", "Create account", "Reset password"])
        with tab_login:
            email = st.text_input("Email", key="suite_auth_login_email")
            password = st.text_input("Password", type="password", key="suite_auth_login_password")
            if st.button("Log in", key="suite_auth_login_btn", use_container_width=True):
                ok, msg = login_with_email(session, email=email, password=password)
                if ok:
                    st.rerun()
                else:
                    st.error(msg)
        with tab_signup:
            su_email = st.text_input("Email", key="suite_auth_signup_email")
            su_password = st.text_input("Password", type="password", key="suite_auth_signup_password")
            if st.button("Create account", key="suite_auth_signup_btn", use_container_width=True):
                ok, msg = signup_with_email(session, email=su_email, password=su_password)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
        with tab_reset:
            reset_email = st.text_input("Email", key="suite_auth_reset_email")
            if st.button("Send reset email", key="suite_auth_reset_btn", use_container_width=True):
                ok, msg = request_password_reset(reset_email)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


def render_auth_gate(st: Any) -> bool:
    """
    When auth is enabled, block app body until the user signs in.

    Returns True when the app may continue rendering.
    """
    if not is_auth_enabled():
        return True
    if is_authenticated(st.session_state):
        enforce_workspace_ownership(st.session_state)
        return True
    st.title("Daniel AI Suite")
    st.caption("Sign in to continue.")
    render_auth_panel(st, expanded=True)
    st.stop()
    return False
