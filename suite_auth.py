"""
Real Accounts foundation (Sprint C) — Supabase Auth email/password.

Disabled by default via ``SUITE_AUTH_ENABLED``. When off, the suite uses shared
secrets identity from ``suite_user.py`` (Workspace Profiles v1 behavior).

C2b: refresh-safe sessions via browser cookie + per-session Supabase client.

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
AUTH_TOKENS_KEY = "_suite_auth_tokens"
AUTH_CLIENT_KEY = "_suite_auth_supabase_client"

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


def _create_fresh_supabase_client() -> Any:
    from suite_storage_config import get_auth_api_key, get_cloud_config

    cfg = get_cloud_config()
    if cfg is None:
        raise RuntimeError("Supabase cloud config missing.")
    auth_key = get_auth_api_key()
    if not auth_key:
        raise RuntimeError("Supabase Auth key missing — set supabase_anon_key.")
    from supabase import create_client

    return create_client(cfg.url, auth_key)


def _auth_api(session_state: dict[str, Any]) -> Any:
    """Per-Streamlit-session Supabase Auth API — not the PostgREST singleton."""
    client = session_state.get(AUTH_CLIENT_KEY)
    if client is None:
        client = _create_fresh_supabase_client()
        session_state[AUTH_CLIENT_KEY] = client
    auth = getattr(client, "auth", None)
    if auth is None:
        raise RuntimeError("Supabase Auth API unavailable.")
    return auth


def _tokens_from_session_obj(session: Any) -> dict[str, Any]:
    if session is None:
        return {}
    access = str(getattr(session, "access_token", None) or "").strip()
    refresh = str(getattr(session, "refresh_token", None) or "").strip()
    if not access or not refresh:
        if isinstance(session, dict):
            access = str(session.get("access_token") or "").strip()
            refresh = str(session.get("refresh_token") or "").strip()
    if not access or not refresh:
        return {}
    expires_at = getattr(session, "expires_at", None)
    if expires_at is None and isinstance(session, dict):
        expires_at = session.get("expires_at")
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(expires_at or 0),
    }


def _tokens_from_auth_response(resp: Any) -> dict[str, Any]:
    session = getattr(resp, "session", None)
    if session is None and isinstance(resp, dict):
        session = resp.get("session")
    tokens = _tokens_from_session_obj(session)
    if tokens:
        return tokens
    access = getattr(resp, "access_token", None)
    refresh = getattr(resp, "refresh_token", None)
    if access and refresh:
        return {
            "access_token": str(access),
            "refresh_token": str(refresh),
            "expires_at": int(getattr(resp, "expires_at", None) or 0),
        }
    return {}


def _user_from_obj(user: Any) -> Any | None:
    if user is None:
        return None
    if getattr(user, "id", None) or getattr(user, "email", None):
        return user
    if isinstance(user, dict) and (user.get("id") or user.get("email")):
        return user
    return None


def _user_from_auth_response(resp: Any) -> Any | None:
    user = getattr(resp, "user", None)
    if user is None and isinstance(resp, dict):
        user = resp.get("user")
    user = _user_from_obj(user)
    if user is not None:
        return user
    session = getattr(resp, "session", None)
    if session is not None:
        nested = getattr(session, "user", None)
        return _user_from_obj(nested)
    return None


def _apply_authenticated_user(
    session_state: dict[str, Any],
    user: Any,
    *,
    tokens: dict[str, Any] | None = None,
    email_fallback: str = "",
) -> None:
    session_state[AUTH_SESSION_KEY] = True
    email = str(getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None) or email_fallback).strip()
    session_state[AUTH_USER_EMAIL_KEY] = email
    session_state[AUTH_EXTERNAL_ID_KEY] = _infer_external_id_from_email(email)
    uid = str(getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None) or "").strip()
    if uid:
        session_state[AUTH_USER_ID_KEY] = uid
    if tokens:
        session_state[AUTH_TOKENS_KEY] = dict(tokens)


def _clear_auth_session(session_state: dict[str, Any], *, st: Any | None = None) -> None:
    for key in (
        AUTH_SESSION_KEY,
        AUTH_USER_EMAIL_KEY,
        AUTH_USER_ID_KEY,
        AUTH_PROFILE_KEY,
        AUTH_NOTICE_KEY,
        AUTH_EXTERNAL_ID_KEY,
        AUTH_TOKENS_KEY,
        AUTH_CLIENT_KEY,
    ):
        session_state.pop(key, None)
    if st is not None:
        try:
            from suite_auth_browser import clear_browser_auth_tokens

            clear_browser_auth_tokens(st)
        except ImportError:
            pass


def _persist_auth_session(
    session_state: dict[str, Any],
    *,
    user: Any,
    tokens: dict[str, Any],
    email_fallback: str = "",
    st: Any | None = None,
) -> None:
    _apply_authenticated_user(session_state, user, tokens=tokens, email_fallback=email_fallback)
    suite_user_id = ""
    try:
        from suite_storage_supabase import ensure_user_row

        suite_user_id = ensure_user_row(
            external_id=session_state.get(AUTH_USER_EMAIL_KEY) or session_state.get(AUTH_USER_ID_KEY) or ""
        )
        try:
            from suite_user import reset_account_cache

            reset_account_cache()
        except ImportError:
            pass
    except Exception:
        pass
    if st is not None and tokens and suite_user_id:
        try:
            from suite_auth_browser import save_browser_auth_tokens

            save_browser_auth_tokens(st, tokens, auth_user_id=suite_user_id)
        except ImportError:
            pass


def restore_auth_session(session_state: dict[str, Any], *, st: Any | None = None) -> bool:
    """
    Restore login from session_state tokens or browser cookie (C2b).

    Call before ``render_auth_gate`` once browser cookies are loaded.
    """
    if not is_auth_enabled():
        return True
    if is_authenticated(session_state):
        return True

    tokens = dict(session_state.get(AUTH_TOKENS_KEY) or {})
    if not tokens.get("access_token") and st is not None:
        try:
            from suite_auth_browser import load_browser_auth_tokens

            browser_tokens = load_browser_auth_tokens(st)
            if browser_tokens:
                tokens = browser_tokens
                session_state[AUTH_TOKENS_KEY] = dict(tokens)
        except ImportError:
            pass

    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        return False

    try:
        auth = _auth_api(session_state)
        resp = auth.set_session(str(tokens["access_token"]), str(tokens["refresh_token"]))
        user = _user_from_auth_response(resp)
        if user is None:
            user_resp = auth.get_user()
            user = _user_from_obj(getattr(user_resp, "user", None))
        if user is None:
            _clear_auth_session(session_state, st=st)
            return False
        refreshed = _tokens_from_auth_response(resp)
        if refreshed:
            tokens = refreshed
        _apply_authenticated_user(session_state, user, tokens=tokens)
        if st is not None and session_state.get(AUTH_USER_EMAIL_KEY):
            try:
                from suite_auth_browser import save_browser_auth_tokens
                from suite_user import get_account_user_id

                save_browser_auth_tokens(
                    st,
                    tokens,
                    auth_user_id=get_account_user_id(),
                )
            except ImportError:
                pass
        enforce_workspace_ownership(session_state)
        return True
    except Exception:
        _clear_auth_session(session_state, st=st)
        return False


def logout(session_state: dict[str, Any], *, st: Any | None = None) -> None:
    if st is None:
        try:
            import streamlit as st_mod  # noqa: WPS433

            st = st_mod
        except Exception:
            st = None
    try:
        if session_state.get(AUTH_TOKENS_KEY) or session_state.get(AUTH_CLIENT_KEY):
            auth = _auth_api(session_state)
            auth.sign_out()
    except Exception:
        pass
    _clear_auth_session(session_state, st=st)


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
    """Backend readiness probe only — not used as per-user session source."""
    if not is_auth_enabled():
        return None
    try:
        client = _create_fresh_supabase_client()
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
        "browser_persistence": True,
        "browser_persistence_mode": "supabase_query_param",
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
    out["message"] = "Auth backend ready (C2b query-param + Supabase session storage)."
    return out


def _auth_not_configured_message() -> str:
    status = auth_backend_status()
    if status.get("ready"):
        return "Auth is not configured on this deployment."
    msg = str(status.get("message") or "").strip()
    return msg or "Auth is not configured on this deployment."


def signup_with_email(session_state: dict[str, Any], *, email: str, password: str) -> tuple[bool, str]:
    try:
        auth = _auth_api(session_state)
    except Exception:
        return False, _auth_not_configured_message()
    try:
        resp = auth.sign_up({"email": email.strip(), "password": password})
        user = _user_from_auth_response(resp)
        if user is None:
            return False, "Sign-up did not return a user — check Supabase Auth settings."
        session_state[AUTH_NOTICE_KEY] = "Account created. Check your email if confirmation is required, then log in."
        return True, str(session_state[AUTH_NOTICE_KEY])
    except Exception as exc:
        return False, str(exc)


def login_with_email(session_state: dict[str, Any], *, email: str, password: str) -> tuple[bool, str]:
    try:
        auth = _auth_api(session_state)
    except Exception:
        return False, _auth_not_configured_message()
    st = None
    try:
        import streamlit as st_mod  # noqa: WPS433

        st = st_mod
    except Exception:
        pass
    try:
        resp = auth.sign_in_with_password({"email": email.strip(), "password": password})
        user = _user_from_auth_response(resp)
        if user is None:
            return False, "Invalid email or password."
        tokens = _tokens_from_auth_response(resp)
        if not tokens:
            return False, "Login succeeded but no session tokens returned."
        _persist_auth_session(session_state, user=user, tokens=tokens, email_fallback=email.strip(), st=st)
        enforce_workspace_ownership(session_state)
        session_state[AUTH_NOTICE_KEY] = "Signed in."
        return True, "Signed in."
    except Exception as exc:
        return False, str(exc)


def request_password_reset(email: str) -> tuple[bool, str]:
    if not is_auth_enabled():
        return False, "Auth is disabled."
    try:
        auth = _create_fresh_supabase_client().auth
    except Exception:
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
            logout(session, st=st)
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
    restore_auth_session(st.session_state, st=st)
    if is_authenticated(st.session_state):
        enforce_workspace_ownership(st.session_state)
        return True
    st.title("Daniel AI Suite")
    st.caption("Sign in to continue.")
    render_auth_panel(st, expanded=True)
    st.stop()
    return False
