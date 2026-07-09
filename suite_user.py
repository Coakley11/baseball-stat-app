"""
Resolve the unified suite account (same user on phone, laptop, and all apps).

Set ``suite_user_id`` in Streamlit secrets (or ``SUITE_USER_ID`` env) to the same
value on every deployment so activity and state sync across devices.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from suite_storage_config import get_cloud_config, reset_cloud_config_cache


def get_external_user_id() -> str:
    """Stable account key from env or [suite_activity] secrets; prefers signed-in auth when available."""
    try:
        import streamlit as st  # noqa: WPS433
        from suite_auth import is_auth_enabled, is_authenticated, resolve_auth_external_id

        if is_auth_enabled() and is_authenticated(st.session_state):
            ext = str(resolve_auth_external_id(st.session_state) or "").strip()
            if ext:
                return ext
    except Exception:
        pass
    env_id = os.environ.get("SUITE_USER_ID", "").strip()
    if env_id:
        return env_id
    try:
        import streamlit as st  # noqa: WPS433

        block = None
        try:
            block = st.secrets.get("suite_activity")
        except Exception:
            try:
                block = st.secrets["suite_activity"]
            except Exception:
                block = None
        if block is not None:
            for name in ("suite_user_id", "user_id", "account_id"):
                val = _read_secret(block, name)
                if val:
                    return val
    except Exception:
        pass
    return "default"


def get_user_email() -> str:
    try:
        import streamlit as st  # noqa: WPS433
        from suite_auth import current_auth_email, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(st.session_state):
            email = str(current_auth_email(st.session_state) or "").strip()
            if email:
                return email
    except Exception:
        pass
    env = os.environ.get("SUITE_USER_EMAIL", "").strip()
    if env:
        return env
    try:
        import streamlit as st  # noqa: WPS433

        block = st.secrets.get("suite_activity") if hasattr(st, "secrets") else None
        if block is None:
            try:
                block = st.secrets["suite_activity"]
            except Exception:
                block = None
        if block is not None:
            for name in ("suite_user_email", "user_email", "email"):
                val = _read_secret(block, name)
                if val:
                    return val
    except Exception:
        pass
    return ""


def get_display_name() -> str:
    env = os.environ.get("SUITE_USER_DISPLAY_NAME", "").strip()
    if env:
        return env
    try:
        import streamlit as st  # noqa: WPS433

        block = st.secrets.get("suite_activity") if hasattr(st, "secrets") else None
        if block is None:
            try:
                block = st.secrets["suite_activity"]
            except Exception:
                block = None
        if block is not None:
            val = _read_secret(block, "display_name")
            if val:
                return val
    except Exception:
        pass
    email = get_user_email()
    if email and "@" in email:
        return email.split("@", 1)[0].replace(".", " ").title()
    ext = get_external_user_id()
    return ext.replace("_", " ").replace("-", " ").title()


def _read_secret(block: Any, name: str) -> str:
    if block is None:
        return ""
    val: Any = None
    if hasattr(block, "get"):
        try:
            val = block.get(name)
        except Exception:
            val = None
    if val is None and hasattr(block, name):
        try:
            val = getattr(block, name)
        except Exception:
            val = None
    return str(val or "").strip()


def reset_account_cache() -> None:
    reset_cloud_config_cache()
    _resolve_account_user_id_cached.cache_clear()


@lru_cache(maxsize=16)
def _resolve_account_user_id_cached(external_id: str, email: str) -> str:
    """
    Return Supabase suite_users UUID for one external account key.

    Keyed by external_id + email so switching accounts on a shared Streamlit worker
    cannot reuse another user's cached cloud row id.
    """
    ext = str(external_id or "default").strip() or "default"
    cfg = get_cloud_config()
    if cfg is None:
        return f"local:{ext}"
    try:
        from suite_storage_supabase import ensure_user_row

        return ensure_user_row(
            ext,
            email=str(email or "").strip(),
            display_name=get_display_name(),
        )
    except Exception:
        return f"local:{ext}"


def get_account_user_id() -> str:
    external = get_external_user_id()
    email = get_user_email()
    return _resolve_account_user_id_cached(external, email)


def account_mode() -> str:
    """``cloud`` when Supabase user UUID is active, else ``local``."""
    uid = get_account_user_id()
    return "cloud" if uid and not uid.startswith("local:") else "local"
