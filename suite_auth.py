"""
Real Accounts foundation (Sprint C) — Supabase Auth email/password.

Disabled by default via ``SUITE_AUTH_ENABLED``. When off, the suite uses shared
secrets identity from ``suite_user.py`` (Workspace Profiles v1 behavior).

C2b: refresh-safe sessions via browser cookie + per-session Supabase client.

Synced to sibling repos via ``scripts/sync_suite_cloud_modules.py``.
"""

from __future__ import annotations

import os
import re
import time
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
AUTH_RECOVERY_PENDING_KEY = "_suite_auth_recovery_pending"
AUTH_RECOVERY_LAST_ERROR_KEY = "_suite_auth_recovery_last_error"
AUTH_REDIRECT_URL_ENV = "SUITE_AUTH_REDIRECT_URL"
AUTH_RECOVERY_HASH_PROBE_PARAM = "suite_auth_hash_probe"
AUTH_RECOVERY_FLAG_PARAM = "suite_auth_recovery"
AUTH_RECOVERY_ACCESS_PARAM = "suite_auth_access"
AUTH_RECOVERY_REFRESH_PARAM = "suite_auth_refresh"
AUTH_LANDING_HINT_PARAM = "suite_auth_landing"
AUTH_LANDING_DIAG_PARAM = "suite_auth_landing_diag"
AUTH_LANDING_SNAPSHOT_KEY = "_suite_auth_landing_snapshot"
AUTH_LANDING_QUERY_KEYS_KEY = "_suite_auth_landing_query_keys"
AUTH_CONFIGURED_RESET_REDIRECT_KEY = "_suite_auth_configured_reset_redirect"
AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY = "_suite_auth_recovery_verify_attempted"
AUTH_RECOVERY_QUERY_PROMOTED_PARAM = "suite_auth_recovery_promoted"
AUTH_BROWSER_QUERY_KEYS_PARAM = "suite_auth_browser_keys"
AUTH_RESET_EXPECTED_HREF_PREFIX_KEY = "_suite_auth_reset_expected_href_prefix"
AUTH_LAST_LOGIN_ERROR_KEY = "_suite_auth_last_login_error"
AUTH_LAST_LOGIN_OK_KEY = "_suite_auth_last_login_ok"
AUTH_LAST_RESTORE_ERROR_KEY = "_suite_auth_last_restore_error"
AUTH_JUST_LOGGED_IN_KEY = "_suite_auth_just_logged_in"
AUTH_PENDING_LOGIN_KEY = "_suite_pending_login"
# Snapshot taken when Start Draft arms — restored on post-start reruns before live draft gates.
AUTH_START_RERUN_SNAPSHOT_KEY = "_suite_auth_start_rerun_snapshot"
# Set only when the user explicitly picks a workspace (sidebar selector / URL after choose).
# Unsigned Guest stickiness must not survive authentication without this flag.
WORKSPACE_USER_SELECTED_KEY = "_suite_workspace_user_selected"
# Unsigned / demo seats that authenticated owners should leave unless explicitly selected.
UNSIGNED_DEFAULT_WORKSPACE_IDS = frozenset({"guest"})

AUTH_PROTECTED_SESSION_KEYS = (
    AUTH_SESSION_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    AUTH_EXTERNAL_ID_KEY,
    AUTH_TOKENS_KEY,
    AUTH_PROFILE_KEY,
    "_suite_cloud_user_id",
    AUTH_JUST_LOGGED_IN_KEY,
    AUTH_LAST_LOGIN_ERROR_KEY,
    AUTH_LAST_RESTORE_ERROR_KEY,
    AUTH_LAST_LOGIN_OK_KEY,
)

# Workspace ownership v1 — map external/auth user to allowed preset profiles.
# Daniel (admin) may switch into child/guest profiles from Command Center (W1–W6).
# Child accounts remain scoped to their own profile only (C5).
_DEFAULT_ALLOWED_WORKSPACES: dict[str, tuple[str, ...]] = {
    "daniel": ("daniel", "ariel", "guest", "test_user"),
    "ariel": ("ariel",),
    "guest": ("guest",),
    "test_user": ("test_user",),
}
# Admin login aliases — map real account emails/local-parts to the shared Daniel admin profile.
_ADMIN_EXTERNAL_ALIASES: dict[str, str] = {
    "daniel.cohen11": "daniel",
    "daniel_cohen11": "daniel",
}


def normalize_account_external_id(external_id: str) -> str:
    """Map known admin aliases (e.g. daniel.cohen11) to canonical profile ids."""
    key = str(external_id or "").strip().lower()
    if not key:
        return ""
    return _ADMIN_EXTERNAL_ALIASES.get(key, key)


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


def auth_session_complete(session_state: dict[str, Any]) -> bool:
    """True when Supabase auth session flag, user id, and refreshable tokens are all present."""
    if not is_auth_enabled():
        return True
    if not session_state.get(AUTH_SESSION_KEY):
        return False
    if not str(session_state.get(AUTH_USER_ID_KEY) or "").strip():
        return False
    tokens = dict(session_state.get(AUTH_TOKENS_KEY) or {})
    return bool(tokens.get("access_token") and tokens.get("refresh_token"))


def snapshot_auth_session(session_state: dict[str, Any]) -> dict[str, Any]:
    """Capture auth keys before workspace blob apply so restore cannot clobber login."""
    snap: dict[str, Any] = {}
    for key in AUTH_PROTECTED_SESSION_KEYS:
        if key not in session_state:
            continue
        val = session_state[key]
        if isinstance(val, dict):
            snap[key] = dict(val)
        else:
            snap[key] = val
    return snap


def restore_auth_session_snapshot(session_state: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Re-apply auth keys saved before workspace blob apply."""
    if not snapshot:
        return
    for key, val in snapshot.items():
        if isinstance(val, dict):
            session_state[key] = dict(val)
        else:
            session_state[key] = val
        try:
            from live_draft_auth_snapshot_stage1_diag import trace_auth_key_set

            trace_auth_key_set(session_state, str(key))
        except ImportError:
            pass


def build_auth_session_diagnostics(session_state: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Read-only auth session probe fields — no secret token values."""
    tokens = dict(session_state.get(AUTH_TOKENS_KEY) or {})
    out: dict[str, Any] = {
        "auth_enabled": bool(is_auth_enabled()),
        "session_flag": bool(session_state.get(AUTH_SESSION_KEY)),
        "session_complete": bool(auth_session_complete(session_state)),
        "auth_user_id": str(session_state.get(AUTH_USER_ID_KEY) or "").strip(),
        "auth_email": str(session_state.get(AUTH_USER_EMAIL_KEY) or "").strip(),
        "external_id": str(session_state.get(AUTH_EXTERNAL_ID_KEY) or "").strip(),
        "cloud_user_id": str(session_state.get("_suite_cloud_user_id") or "").strip(),
        "tokens_present": bool(tokens.get("access_token") and tokens.get("refresh_token")),
        "just_logged_in": bool(session_state.get(AUTH_JUST_LOGGED_IN_KEY)),
        "last_login_ok": bool(session_state.get(AUTH_LAST_LOGIN_OK_KEY)),
        "last_login_error": str(session_state.get(AUTH_LAST_LOGIN_ERROR_KEY) or "").strip(),
        "last_restore_error": str(session_state.get(AUTH_LAST_RESTORE_ERROR_KEY) or "").strip(),
        "browser_storage": {},
    }
    if st is not None:
        try:
            from suite_auth_browser import browser_auth_storage_status

            out["browser_storage"] = browser_auth_storage_status(st)
        except ImportError:
            pass
    return out


def current_auth_email(session_state: dict[str, Any]) -> str:
    return str(session_state.get(AUTH_USER_EMAIL_KEY) or "").strip()


def allowed_workspaces_for_user(external_user_id: str) -> tuple[str, ...]:
    """Owned workspace(s) allowed for this account — one workspace unless admin demo."""
    key = normalize_account_external_id(str(external_user_id or "").strip().lower())
    if key in _DEFAULT_ALLOWED_WORKSPACES:
        if key == "daniel":
            return _DEFAULT_ALLOWED_WORKSPACES[key]
        return (key,)
    if key == "default":
        return ("daniel", "ariel", "guest", "test_user")
    if re.fullmatch(r"[a-z0-9_]+", key):
        return (key,)
    return ("daniel", "guest", "test_user")


def resolve_auth_external_id(session_state: dict[str, Any]) -> str:
    """Best-effort suite profile id for the signed-in account."""
    ext = normalize_account_external_id(str(session_state.get(AUTH_EXTERNAL_ID_KEY) or "").strip().lower())
    if ext:
        return ext
    inferred = normalize_account_external_id(_infer_external_id_from_email(current_auth_email(session_state)))
    if inferred:
        return inferred
    return "daniel"


def allowed_workspaces_for_session(session_state: dict[str, Any]) -> tuple[str, ...]:
    """Allowed workspace ids for this session — all presets when auth is off."""
    if not is_auth_enabled() or not is_authenticated(session_state):
        try:
            from suite_workspace import WORKSPACE_PRESETS

            return tuple(p["id"] for p in WORKSPACE_PRESETS)
        except ImportError:
            return ("daniel", "ariel", "guest", "test_user")
    return allowed_workspaces_for_user(resolve_auth_external_id(session_state))


def _infer_external_id_from_email(email: str) -> str:
    low = str(email or "").strip().lower()
    if not low:
        return ""
    if "ariel" in low:
        return "ariel"
    if "daniel" in low:
        return "daniel"
    local = low.split("@", 1)[0]
    if local in _DEFAULT_ALLOWED_WORKSPACES:
        return local
    return local or "daniel"


def account_scoped_workspace_target(session_state: dict[str, Any]) -> str:
    """
    Single allowed workspace for a signed-in account with exactly one seat.

    Used to hard-clamp active workspace even when owned-workspace registry
    resolution is empty (e.g. ephemeral/read-only cloud disk).

    Developer/admin tooling does **not** expand a single-seat account onto
    Daniel's workspace — Coakley11 always resolves to ``coakley11``.
    """
    if not is_auth_enabled() or not is_authenticated(session_state):
        return ""
    try:
        from suite_workspace import normalize_workspace_id
        from suite_workspace_registry import is_admin_account

        allowed = allowed_workspaces_for_session(session_state)
        if len(allowed) == 1:
            return normalize_workspace_id(allowed[0])
        # Multi-seat admin (Daniel): no forced single target.
        if is_admin_account(session_state=session_state):
            return ""
    except ImportError:
        pass
    return ""


def _seed_owned_workspace_cache(session_state: dict[str, Any], workspace_id: str) -> None:
    """Ensure owned-workspace session keys are set for diagnostics and cloud scoping."""
    ws = str(workspace_id or "").strip()
    if not ws:
        return
    try:
        from suite_workspace_registry import (
            SESSION_OWNED_WORKSPACE_KEY,
            SESSION_OWNED_WORKSPACE_LABEL_KEY,
            derive_workspace_label,
        )

        session_state[SESSION_OWNED_WORKSPACE_KEY] = ws
        if not str(session_state.get(SESSION_OWNED_WORKSPACE_LABEL_KEY) or "").strip():
            session_state[SESSION_OWNED_WORKSPACE_LABEL_KEY] = derive_workspace_label(
                slug=ws,
                email=current_auth_email(session_state),
            )
    except ImportError:
        session_state["_suite_owned_workspace_id"] = ws


def hard_clamp_owned_workspace_before_scoped_load(session_state: dict[str, Any]) -> str:
    """Final ownership clamp immediately before any workspace-scoped cloud/disk load.

    Coakley11 (and every single-seat account) must never remain on Daniel's workspace,
    even when the account is flagged admin for developer tools.
    Never falls back to ``daniel`` for a non-daniel authenticated account.
    """
    from suite_workspace import SESSION_KEY, normalize_workspace_id, scoped_cloud_app_id

    active_before = normalize_workspace_id(str(session_state.get(SESSION_KEY) or ""))
    email = current_auth_email(session_state)
    auth_uid = str(session_state.get(AUTH_USER_ID_KEY) or "").strip()
    external = resolve_auth_external_id(session_state) if is_authenticated(session_state) else ""
    owned = ""
    clamp_error = ""
    stage = "start"

    if not is_auth_enabled() or not is_authenticated(session_state):
        session_state["_suite_workspace_ownership_trace"] = {
            "stage": "skipped_unauthenticated",
            "auth_email": email,
            "auth_user_id": auth_uid,
            "external_id": external,
            "active_before": active_before,
            "owned": "",
            "active_after": active_before,
            "cloud_key": scoped_cloud_app_id("baseball", active_before or None),
        }
        return active_before

    try:
        from suite_workspace_registry import resolve_owned_workspace_id

        stage = "resolve_owned"
        owned = normalize_workspace_id(resolve_owned_workspace_id(session_state) or "")
    except Exception as exc:
        clamp_error = f"resolve_owned: {type(exc).__name__}: {exc}"
        session_state["_suite_workspace_enforce_error"] = clamp_error

    if not owned:
        stage = "account_scoped_fallback"
        owned = normalize_workspace_id(account_scoped_workspace_target(session_state) or "")
    if not owned:
        # Last resort: authenticated external id — never invent Daniel for Coakley11.
        stage = "external_id_fallback"
        ext_n = normalize_workspace_id(external or "")
        if ext_n and ext_n != "daniel":
            owned = ext_n
        elif ext_n == "daniel":
            owned = "daniel"

    allowed = tuple(
        normalize_workspace_id(w) for w in allowed_workspaces_for_session(session_state)
    )
    active = active_before
    target = active

    if owned and len(allowed) == 1:
        # Single-seat accounts (Coakley11): admin/dev tools must not keep an unrelated seat.
        target = owned
        stage = "single_seat_hard_clamp"
    elif owned and active and active not in allowed and allowed:
        target = owned
        stage = "active_not_allowed"
    elif owned and owned != "daniel" and active == "daniel":
        target = owned
        stage = "never_linger_on_daniel"
    elif owned and not active:
        target = owned
        stage = "empty_active"

    if target and target != active:
        session_state[SESSION_KEY] = target
        _seed_owned_workspace_cache(session_state, target)
        session_state["_suite_workspace_last_clamp"] = f"{active}->{target}:hard"
        try:
            from suite_workspace import persist_active_workspace_id

            persist_active_workspace_id(target, session_state=session_state)
        except Exception as exc:
            clamp_error = (clamp_error + "; " if clamp_error else "") + f"persist: {type(exc).__name__}: {exc}"
            session_state["_suite_workspace_enforce_error"] = clamp_error
        active = target

    cloud_key = scoped_cloud_app_id("baseball", active or None)
    session_state["_suite_workspace_ownership_trace"] = {
        "stage": stage,
        "auth_email": email,
        "auth_user_id": auth_uid,
        "external_id": external,
        "active_before": active_before,
        "owned": owned,
        "allowed": list(allowed),
        "active_after": active,
        "cloud_key": cloud_key,
        "clamp_error": clamp_error,
        "last_clamp": str(session_state.get("_suite_workspace_last_clamp") or ""),
    }
    return active


def enforce_workspace_ownership(session_state: dict[str, Any]) -> None:
    """Clamp active workspace to the signed-in account's owned workspace."""
    session_state.pop("_suite_workspace_enforce_error", None)
    if not is_auth_enabled() or not is_authenticated(session_state):
        return
    try:
        from types import SimpleNamespace

        from suite_workspace import get_active_workspace_id, normalize_workspace_id, set_active_workspace_id
        from suite_workspace_registry import (
            ensure_owned_workspace_for_session,
            get_owned_workspace_id,
            is_admin_account,
            workspace_access_allowed,
        )

        try:
            from suite_workspace_registry import resolve_owned_workspace_id as _resolve_owned
        except ImportError:
            _resolve_owned = get_owned_workspace_id

        st = SimpleNamespace(session_state=session_state)
        ensure_owned_workspace_for_session(session_state)
        allowed = tuple(
            normalize_workspace_id(w)
            for w in allowed_workspaces_for_session(session_state)
        )
        active = normalize_workspace_id(get_active_workspace_id(st))
        admin = is_admin_account(session_state=session_state)

        # Non-admin: hard-clamp to the single allowed workspace even when owned
        # registry resolution is empty (production: scope=coakley11 but active=daniel).
        scoped_target = account_scoped_workspace_target(session_state)
        if scoped_target and not admin:
            _seed_owned_workspace_cache(session_state, scoped_target)
            if active != scoped_target:
                set_active_workspace_id(st, scoped_target)
                session_state["_suite_workspace_last_clamp"] = f"{active}->{scoped_target}"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return

        # Single-seat accounts that are also "admin" for developer tools (Coakley11):
        # still hard-clamp — admin must not keep Daniel's workspace active.
        if scoped_target and admin and len(allowed) == 1:
            _seed_owned_workspace_cache(session_state, scoped_target)
            if active != scoped_target:
                set_active_workspace_id(st, scoped_target)
                session_state["_suite_workspace_last_clamp"] = f"{active}->{scoped_target}:admin_single"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return

        owned = normalize_workspace_id(_resolve_owned(session_state))
        if owned:
            _seed_owned_workspace_cache(session_state, owned)

        # Leave unsigned Guest (and other demo seats) after sign-in. Admins may still
        # switch to Guest explicitly via the workspace selector.
        user_selected = bool(session_state.get(WORKSPACE_USER_SELECTED_KEY))
        just_logged_in = bool(session_state.get(AUTH_JUST_LOGGED_IN_KEY))
        if (
            owned
            and owned != active
            and active in UNSIGNED_DEFAULT_WORKSPACE_IDS
            and (just_logged_in or not user_selected)
        ):
            set_active_workspace_id(st, owned)
            session_state["_suite_workspace_last_clamp"] = f"{active}->{owned}:unsigned"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return

        # Prefer owned home when active seat is outside this account's allowed set.
        if owned and active != owned and not workspace_access_allowed(active, session_state=session_state):
            set_active_workspace_id(st, owned)
            session_state["_suite_workspace_last_clamp"] = f"{active}->{owned}:access"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return
        if active not in allowed and allowed:
            target = owned or allowed[0]
            set_active_workspace_id(st, target)
            session_state["_suite_workspace_last_clamp"] = f"{active}->{target}:allowed"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return

        # Home preference: without an explicit picker selection, stay on owned workspace
        # rather than another account's primary seat (daniel) after login/restore.
        if (
            owned
            and owned != active
            and not user_selected
            and (just_logged_in or (owned != "daniel" and active == "daniel"))
        ):
            set_active_workspace_id(st, owned)
            session_state["_suite_workspace_last_clamp"] = f"{active}->{owned}:home"
            hard_clamp_owned_workspace_before_scoped_load(session_state)
            return
        hard_clamp_owned_workspace_before_scoped_load(session_state)
    except ImportError as exc:
        session_state["_suite_workspace_enforce_error"] = f"ImportError: {exc}"
        hard_clamp_owned_workspace_before_scoped_load(session_state)
    except Exception as exc:
        session_state["_suite_workspace_enforce_error"] = f"{type(exc).__name__}: {exc}"
        hard_clamp_owned_workspace_before_scoped_load(session_state)


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
    # supabase-py AuthResponse (Pydantic) — session may need model_dump on edge builds
    if session is not None and hasattr(session, "model_dump"):
        try:
            tokens = _tokens_from_session_obj(session.model_dump())
            if tokens:
                return tokens
        except Exception:
            pass
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
    st: Any | None = None,
) -> bool:
    try:
        from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

        emit_apply_write_checkpoint(session_state, "apply_authenticated_user_entry", st=st)
    except ImportError:
        try:
            from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

            emit_prestart_hydration_checkpoint(
                session_state,
                "apply_authenticated_user_entry",
                authenticated_before=bool(is_authenticated(session_state)) if is_auth_enabled() else True,
                st=st,
            )
        except ImportError:
            pass
    try:
        from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

        emit_apply_write_checkpoint(
            session_state, "apply_authenticated_user_before_session_flag", st=st, write_key=AUTH_SESSION_KEY
        )
    except ImportError:
        pass
    session_state[AUTH_SESSION_KEY] = True
    try:
        from live_draft_auth_prestart_stage1_diag import trace_prestart_key_set

        trace_prestart_key_set(session_state, AUTH_SESSION_KEY, st=st)
    except ImportError:
        pass
    try:
        from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

        emit_apply_write_checkpoint(
            session_state, "apply_authenticated_user_after_session_flag", st=st, write_key=AUTH_SESSION_KEY
        )
    except ImportError:
        pass
    email = str(getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None) or email_fallback).strip()
    session_state[AUTH_USER_EMAIL_KEY] = email
    session_state[AUTH_EXTERNAL_ID_KEY] = normalize_account_external_id(_infer_external_id_from_email(email))
    try:
        from live_draft_auth_prestart_stage1_diag import trace_prestart_key_set

        trace_prestart_key_set(session_state, AUTH_USER_EMAIL_KEY, st=st)
    except ImportError:
        pass
    uid = str(getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None) or "").strip()
    if uid:
        try:
            from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

            emit_apply_write_checkpoint(
                session_state, "apply_authenticated_user_before_user_id", st=st, write_key=AUTH_USER_ID_KEY
            )
        except ImportError:
            pass
        session_state[AUTH_USER_ID_KEY] = uid
        try:
            from live_draft_auth_prestart_stage1_diag import trace_prestart_key_set

            trace_prestart_key_set(session_state, AUTH_USER_ID_KEY, st=st)
        except ImportError:
            pass
        try:
            from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

            emit_apply_write_checkpoint(
                session_state, "apply_authenticated_user_after_user_id", st=st, write_key=AUTH_USER_ID_KEY
            )
        except ImportError:
            pass
    if tokens:
        try:
            from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

            emit_apply_write_checkpoint(
                session_state, "apply_authenticated_user_before_tokens", st=st, write_key=AUTH_TOKENS_KEY
            )
        except ImportError:
            pass
        session_state[AUTH_TOKENS_KEY] = dict(tokens)
        try:
            from live_draft_auth_prestart_stage1_diag import trace_prestart_key_set

            trace_prestart_key_set(session_state, AUTH_TOKENS_KEY, st=st)
        except ImportError:
            pass
        try:
            from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

            emit_apply_write_checkpoint(
                session_state, "apply_authenticated_user_after_tokens", st=st, write_key=AUTH_TOKENS_KEY
            )
        except ImportError:
            pass
    apply_ok = bool(auth_session_complete(session_state)) if is_auth_enabled() else True
    if apply_ok:
        try:
            from live_draft_state import reconcile_live_draft_auth_restore_block

            reconcile_live_draft_auth_restore_block(session_state)
        except ImportError:
            pass
    try:
        from live_draft_auth_prestart_stage1_diag import arm_prestart_mutation_trace, emit_prestart_hydration_checkpoint
        from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

        arm_prestart_mutation_trace(session_state, reason="apply_authenticated_user")
        emit_apply_write_checkpoint(
            session_state,
            "apply_authenticated_user_exit",
            st=st,
            apply_return_ok=apply_ok,
        )
    except ImportError:
        try:
            from live_draft_auth_prestart_stage1_diag import arm_prestart_mutation_trace, emit_prestart_hydration_checkpoint

            arm_prestart_mutation_trace(session_state, reason="apply_authenticated_user")
            emit_prestart_hydration_checkpoint(
                session_state,
                "apply_authenticated_user_exit",
                st=st,
                authenticated_after=bool(is_authenticated(session_state)) if is_auth_enabled() else True,
                extra={"apply_return_ok": apply_ok},
            )
        except ImportError:
            pass
    return apply_ok


def _clear_auth_session(
    session_state: dict[str, Any],
    *,
    st: Any | None = None,
    invalidate_bridge: bool = False,
) -> None:
    """Clear in-memory Streamlit auth keys.

    ``invalidate_bridge=True`` only for explicit sign-out (invalidates Supabase browser bridge).
    Failed restore / hydration must not destroy a reusable bridge row for other contexts.
    """
    try:
        from live_draft_navigation import clear_private_baseball_simulator_runtime

        clear_private_baseball_simulator_runtime(session_state, reason="auth_sign_out")
    except ImportError:
        pass
    for key in (
        AUTH_SESSION_KEY,
        AUTH_USER_EMAIL_KEY,
        AUTH_USER_ID_KEY,
        AUTH_PROFILE_KEY,
        AUTH_NOTICE_KEY,
        AUTH_EXTERNAL_ID_KEY,
        AUTH_TOKENS_KEY,
        AUTH_CLIENT_KEY,
        AUTH_JUST_LOGGED_IN_KEY,
        AUTH_LAST_LOGIN_OK_KEY,
    ):
        try:
            from live_draft_auth_snapshot_stage1_diag import trace_auth_key_pop

            trace_auth_key_pop(session_state, key, st=st)
        except ImportError:
            session_state.pop(key, None)
    try:
        from live_draft_auth_snapshot_stage1_diag import trace_auth_key_pop

        trace_auth_key_pop(session_state, AUTH_START_RERUN_SNAPSHOT_KEY, st=st)
    except ImportError:
        session_state.pop(AUTH_START_RERUN_SNAPSHOT_KEY, None)
    if st is not None and invalidate_bridge:
        try:
            from suite_auth_browser import clear_browser_auth_tokens

            clear_browser_auth_tokens(
                st,
                reason="explicit_sign_out",
                caller="_clear_auth_session",
            )
        except ImportError:
            pass


def _sync_auth_account_identity(session_state: dict[str, Any], *, st: Any | None = None) -> str:
    """Resolve suite_users cloud row for the signed-in account; refresh account cache."""
    suite_user_id = ""
    try:
        from suite_user import get_account_user_id, reset_account_cache

        reset_account_cache()
        from suite_storage_supabase import ensure_user_row

        suite_user_id = ensure_user_row(
            resolve_auth_external_id(session_state),
            email=str(session_state.get(AUTH_USER_EMAIL_KEY) or ""),
        )
        reset_account_cache()
        suite_user_id = str(get_account_user_id() or suite_user_id or "").strip()
        if suite_user_id:
            session_state["_suite_cloud_user_id"] = suite_user_id
    except Exception:
        pass
    if st is not None and session_state.get(AUTH_TOKENS_KEY):
        browser_uid = suite_user_id or str(session_state.get(AUTH_USER_ID_KEY) or "").strip()
        if browser_uid:
            try:
                from suite_auth_browser import save_browser_auth_tokens

                save_browser_auth_tokens(
                    st,
                    dict(session_state.get(AUTH_TOKENS_KEY) or {}),
                    auth_user_id=browser_uid,
                )
            except ImportError:
                pass
    return suite_user_id


def _persist_auth_session(
    session_state: dict[str, Any],
    *,
    user: Any,
    tokens: dict[str, Any],
    email_fallback: str = "",
    st: Any | None = None,
) -> None:
    old_uid = str(session_state.get(AUTH_USER_ID_KEY) or "").strip()
    old_ext = str(session_state.get(AUTH_EXTERNAL_ID_KEY) or "").strip()
    old_cloud = str(session_state.get("_suite_cloud_user_id") or "").strip()
    _apply_authenticated_user(session_state, user, tokens=tokens, email_fallback=email_fallback, st=st)
    new_uid = str(session_state.get(AUTH_USER_ID_KEY) or "").strip()
    session_state[AUTH_JUST_LOGGED_IN_KEY] = True
    session_state[AUTH_LAST_LOGIN_OK_KEY] = True
    session_state.pop(AUTH_LAST_LOGIN_ERROR_KEY, None)
    session_state.pop(AUTH_LAST_RESTORE_ERROR_KEY, None)
    suite_user_id = ""
    try:
        suite_user_id = _sync_auth_account_identity(session_state, st=st)
    except Exception:
        pass
    new_ext = str(session_state.get(AUTH_EXTERNAL_ID_KEY) or "").strip()
    new_cloud = str(suite_user_id or session_state.get("_suite_cloud_user_id") or "").strip()
    scope_changed = bool(
        (old_uid and new_uid and old_uid != new_uid)
        or (old_ext and new_ext and old_ext != new_ext)
        or (old_cloud and new_cloud and old_cloud != new_cloud)
    )
    if scope_changed:
        try:
            from workflow_persist_guard import clear_draft_library_on_account_scope_change

            clear_draft_library_on_account_scope_change(session_state)
        except ImportError:
            pass
        try:
            from live_draft_navigation import clear_private_baseball_simulator_runtime

            clear_private_baseball_simulator_runtime(
                session_state,
                reason="auth_account_scope_changed",
            )
        except ImportError:
            pass
    if old_uid != new_uid:
        try:
            from draft_room_participant_state import on_auth_user_switch

            on_auth_user_switch(session_state, from_user_id=old_uid, to_user_id=new_uid)
        except ImportError:
            pass
    try:
        from suite_user_persistence import preserve_page_through_auth

        preserve_page_through_auth(session_state, app_id="baseball")
    except ImportError:
        pass
    # Fresh sign-in always prefers the owned workspace over sticky unsigned Guest.
    session_state.pop(WORKSPACE_USER_SELECTED_KEY, None)
    session_state["_suite_workspace_force_sync"] = True
    session_state["_suite_workspace_refresh_needed"] = True
    try:
        from suite_workspace_registry import ensure_owned_workspace_for_session

        ensure_owned_workspace_for_session(session_state)
    except ImportError:
        pass
    enforce_workspace_ownership(session_state)
    try:
        from suite_user_persistence import preserve_page_through_auth

        # Re-apply after workspace ownership clamp — clamp must not drop the page.
        preserve_page_through_auth(session_state, app_id="baseball")
    except ImportError:
        pass
    if is_authenticated(session_state):
        try:
            from draft_archive_visibility import sanitize_workflow_library_for_account

            sanitize_workflow_library_for_account(session_state, st=st, persist_cleanup=True)
        except ImportError:
            pass


def restore_auth_session(session_state: dict[str, Any], *, st: Any | None = None) -> bool:
    """
    Restore login from session_state tokens or browser cookie (C2b).

    Call before ``render_auth_gate`` once browser cookies are loaded.
    """
    auth_before = bool(is_authenticated(session_state)) if is_auth_enabled() else True
    session_state["_suite_auth_last_restore_attempted"] = True
    try:
        seq = int(session_state.get("_suite_auth_restore_attempt_seq") or 0) + 1
    except (TypeError, ValueError):
        seq = 1
    session_state["_suite_auth_restore_attempt_seq"] = seq
    restore_attempt_ts = time.time()

    def _finish(ok: bool, reason: str = "") -> bool:
        session_state["_suite_auth_last_restore_ok"] = bool(ok)
        try:
            from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

            emit_prestart_hydration_checkpoint(
                session_state,
                "restore_auth_session_exit",
                st=st,
                authenticated_before=auth_before,
                authenticated_after=bool(is_authenticated(session_state)) if is_auth_enabled() else True,
                skip_or_failure_reason=reason,
                extra={
                    "restore_attempt_seq": int(session_state.get("_suite_auth_restore_attempt_seq") or 0),
                    "restore_attempt_exit_ts": time.time(),
                },
            )
        except ImportError:
            pass
        return ok

    try:
        from live_draft_auth_prestart_stage1_diag import emit_prestart_hydration_checkpoint

        emit_prestart_hydration_checkpoint(
            session_state,
            "restore_auth_session_entry",
            st=st,
            authenticated_before=auth_before,
            hydration_attempted=True,
            extra={
                "restore_attempt_seq": seq,
                "restore_attempt_entry_ts": restore_attempt_ts,
            },
        )
        if st is not None:
            try:
                from suite_auth_browser import sync_suite_sid_from_query

                sync_suite_sid_from_query(st)
            except ImportError:
                pass
        emit_prestart_hydration_checkpoint(session_state, "suite_sid_detection", st=st)
    except ImportError:
        pass

    if not is_auth_enabled():
        return _finish(True, "auth_disabled")
    if is_authenticated(session_state):
        if auth_session_complete(session_state):
            try:
                _sync_auth_account_identity(session_state, st=st)
            except Exception:
                pass
            try:
                enforce_workspace_ownership(session_state)
            except Exception:
                pass
            try:
                from draft_archive_visibility import sanitize_workflow_library_for_account

                sanitize_workflow_library_for_account(session_state, st=st, persist_cleanup=True)
            except ImportError:
                pass
            session_state.pop(AUTH_JUST_LOGGED_IN_KEY, None)
            session_state.pop(AUTH_LAST_RESTORE_ERROR_KEY, None)
            return _finish(True, "already_complete")
        # Stale/partial session flag without tokens — fall through to token restore.
        try:
            from live_draft_auth_snapshot_stage1_diag import trace_auth_key_pop

            trace_auth_key_pop(session_state, AUTH_SESSION_KEY, st=st)
        except ImportError:
            session_state.pop(AUTH_SESSION_KEY, None)

    tokens = dict(session_state.get(AUTH_TOKENS_KEY) or {})
    if not tokens.get("access_token") and st is not None:
        try:
            from suite_auth_browser import load_browser_auth_tokens

            browser_tokens = load_browser_auth_tokens(st)
            try:
                from live_draft_auth_prestart_stage1_diag import arm_prestart_mutation_trace, emit_prestart_hydration_checkpoint

                emit_prestart_hydration_checkpoint(
                    session_state,
                    "load_browser_auth_tokens",
                    st=st,
                    extra={
                        "browser_tokens_loaded": bool(browser_tokens),
                        "access_token_present": bool(str((browser_tokens or {}).get("access_token") or "").strip()),
                        "refresh_token_present": bool(str((browser_tokens or {}).get("refresh_token") or "").strip()),
                    },
                )
                if browser_tokens:
                    arm_prestart_mutation_trace(session_state, reason="browser_tokens_loaded")
            except ImportError:
                pass
            if browser_tokens:
                tokens = browser_tokens
                session_state[AUTH_TOKENS_KEY] = dict(tokens)
        except ImportError:
            pass

    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        fail_reason = "tokens_missing"
        if st is not None:
            try:
                from suite_auth_browser import BROWSER_LOAD_REASON_KEY

                br = str(st.session_state.get(BROWSER_LOAD_REASON_KEY) or "").strip()
                if br and br not in ("ok", ""):
                    fail_reason = br
            except ImportError:
                pass
        return _finish(False, fail_reason)

    try:
        from suite_auth_bridge_restore import (
            RESTORE_FINAL_3B_KEY,
            execute_bridge_set_session_restore,
            load_bridge_tokens_with_meta,
        )
    except ImportError:
        RESTORE_FINAL_3B_KEY = "_suite_auth_bridge_restore_final_3b"
        execute_bridge_set_session_restore = None  # type: ignore[assignment,misc]
        load_bridge_tokens_with_meta = None  # type: ignore[assignment,misc]

    if session_state.get(RESTORE_FINAL_3B_KEY):
        return _finish(False, "auth_hydrate_3b_final")

    if st is not None and execute_bridge_set_session_restore is not None:
        _, token_meta = load_bridge_tokens_with_meta(st)
        token_meta = token_meta or {}
        bridge_handled = execute_bridge_set_session_restore(
            session_state,
            st=st,
            tokens=dict(tokens),
            token_meta=token_meta,
            auth_before=auth_before,
            finish=_finish,
        )
        if bridge_handled is not None:
            if not bridge_handled:
                return False
            try:
                enforce_workspace_ownership(session_state)
            except Exception:
                pass
            try:
                from draft_archive_visibility import sanitize_workflow_library_for_account

                sanitize_workflow_library_for_account(session_state, st=st, persist_cleanup=True)
            except ImportError:
                pass
            return True

    try:
        auth = _auth_api(session_state)
        resp = auth.set_session(str(tokens["access_token"]), str(tokens["refresh_token"]))
        user = _user_from_auth_response(resp)
        if user is None:
            user_resp = auth.get_user()
            user = _user_from_obj(getattr(user_resp, "user", None))
        if user is None:
            _clear_auth_session(session_state, st=st, invalidate_bridge=False)
            return _finish(False, "user_missing")
        refreshed = _tokens_from_auth_response(resp)
        if refreshed:
            tokens = refreshed
        _apply_authenticated_user(session_state, user, tokens=tokens, st=st)
        try:
            from live_draft_auth_finalize_stage1_diag import emit_apply_write_checkpoint

            emit_apply_write_checkpoint(
                session_state,
                "restore_auth_session_after_apply",
                st=st,
                apply_return_ok=bool(auth_session_complete(session_state)),
            )
        except ImportError:
            pass
        try:
            _sync_auth_account_identity(session_state, st=st)
        except Exception:
            pass
    except Exception as exc:
        session_state[AUTH_LAST_RESTORE_ERROR_KEY] = str(exc)
        try:
            from suite_auth_restore_diag import emit_restore_auth_exception_checkpoint

            emit_restore_auth_exception_checkpoint(session_state, exc, phase="set_session", st=st)
        except ImportError:
            pass
        if session_state.get(AUTH_JUST_LOGGED_IN_KEY):
            # Workspace sync must not undo a login that just succeeded this session.
            return _finish(bool(auth_session_complete(session_state)), "exception_just_logged_in")
        _clear_auth_session(session_state, st=st, invalidate_bridge=False)
        return _finish(False, f"exception:{type(exc).__name__}")
    # Clamp workspace outside the session-clearing try: a workspace resolution
    # failure must never invalidate an otherwise-valid authenticated session.
    try:
        enforce_workspace_ownership(session_state)
    except Exception:
        pass
    try:
        from draft_archive_visibility import sanitize_workflow_library_for_account

        sanitize_workflow_library_for_account(session_state, st=st, persist_cleanup=True)
    except ImportError:
        pass
    if st is not None and auth_session_complete(session_state):
        try:
            from suite_auth_browser import save_browser_auth_tokens

            save_browser_auth_tokens(
                st,
                dict(session_state.get(AUTH_TOKENS_KEY) or {}),
                auth_user_id=str(session_state.get(AUTH_USER_ID_KEY) or ""),
            )
        except ImportError:
            pass
    return _finish(True, "ok")


def ensure_authenticated_session_hydrated(session_state: dict[str, Any], *, st: Any | None = None) -> bool:
    """
    Ensure ``is_authenticated`` reflects a validated Supabase session.

    Uses existing tokens in session_state or browser ``suite_sid`` storage — never
    query-param shortcuts. Safe to call on warm workspace skips and before draft restore.
    """
    if not is_auth_enabled():
        return True
    if auth_session_complete(session_state):
        session_state["_suite_auth_last_hydration_source"] = "already_complete"
        return True
    snap = session_state.get(AUTH_START_RERUN_SNAPSHOT_KEY)
    if isinstance(snap, dict) and snap:
        restore_auth_session_snapshot(session_state, snap)
        if auth_session_complete(session_state):
            session_state["_suite_auth_last_hydration_source"] = "start_rerun_snapshot"
            return True
    ok = restore_auth_session(session_state, st=st)
    session_state["_suite_auth_last_hydration_source"] = "browser_restore" if ok else "restore_failed"
    return ok


def snapshot_auth_for_start_draft_rerun(session_state: dict[str, Any], *, st: Any | None = None) -> None:
    """Preserve validated session auth when arming Start Draft (same Streamlit session)."""
    try:
        from live_draft_auth_snapshot_stage1_diag import record_auth_snapshot_capture

        record_auth_snapshot_capture(session_state, st=st)
        return
    except ImportError:
        pass
    if not is_auth_enabled():
        return
    if not auth_session_complete(session_state):
        return
    session_state[AUTH_START_RERUN_SNAPSHOT_KEY] = snapshot_auth_session(session_state)


def logout(session_state: dict[str, Any], *, st: Any | None = None) -> None:
    if st is None:
        try:
            import streamlit as st_mod  # noqa: WPS433

            st = st_mod
        except Exception:
            st = None
    try:
        from draft_room_participant_state import on_auth_logout_save_workflow

        on_auth_logout_save_workflow(session_state)
    except ImportError:
        pass
    try:
        if session_state.get(AUTH_TOKENS_KEY) or session_state.get(AUTH_CLIENT_KEY):
            auth = _auth_api(session_state)
            auth.sign_out()
    except Exception:
        pass
    _clear_auth_session(session_state, st=st, invalidate_bridge=True)
    session_state.pop(WORKSPACE_USER_SELECTED_KEY, None)
    try:
        from suite_user import reset_account_cache

        reset_account_cache()
    except ImportError:
        pass
    for key in list(session_state.keys()):
        sk = str(key)
        if sk.startswith("_suite_workspace_synced::") or sk.startswith("_suite_disk_state_restored::"):
            session_state.pop(key, None)
    # Signed-out browsers attach to Guest — not an owned workspace.
    session_state["_suite_active_workspace_id"] = "guest"
    session_state["suite_workspace_id"] = "guest"
    session_state.pop("_suite_owned_workspace_id", None)


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
    out["password_reset_redirect_url"] = auth_password_reset_redirect_url()
    out["supabase_redirect_urls"] = list(supabase_auth_redirect_url_checklist())
    return out


def _auth_not_configured_message() -> str:
    status = auth_backend_status()
    if status.get("ready"):
        return "Auth is not configured on this deployment."
    msg = str(status.get("message") or "").strip()
    return msg or "Auth is not configured on this deployment."


def _read_secret_auth_redirect_url() -> str:
    env = os.environ.get(AUTH_REDIRECT_URL_ENV, "").strip()
    if env:
        return env.rstrip("/")
    try:
        import streamlit as st  # noqa: WPS433

        block = st.secrets.get("suite_activity") if hasattr(st, "secrets") else None
        if block is None:
            try:
                block = st.secrets["suite_activity"]
            except Exception:
                block = None
        if block is not None:
            raw = ""
            if hasattr(block, "get"):
                raw = str(block.get("suite_auth_redirect_url") or "").strip()
            elif isinstance(block, dict):
                raw = str(block.get("suite_auth_redirect_url") or "").strip()
            if raw:
                return raw.rstrip("/")
    except Exception:
        pass
    return ""


def auth_password_reset_redirect_url(*, with_landing_hint: bool = True) -> str:
    """
    Landing URL embedded in Supabase password-reset emails (redirect_to).

    Must match Supabase Auth → URL configuration (Site URL + Redirect URLs).
    """
    custom = _read_secret_auth_redirect_url()
    if custom:
        base = custom
    else:
        try:
            from app_urls import HOMEPAGE_DEV_URL, HOMEPAGE_PRODUCTION_URL

            base = (HOMEPAGE_DEV_URL or HOMEPAGE_PRODUCTION_URL or "").strip().rstrip("/")
        except ImportError:
            base = ""
        if not base:
            try:
                from suite_command_center_link import _HOMEPAGE_DEV_URL

                base = str(_HOMEPAGE_DEV_URL or "").strip().rstrip("/")
            except ImportError:
                base = ""
    if not base:
        return ""
    if not with_landing_hint:
        return base
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(base)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[AUTH_LANDING_HINT_PARAM] = ["recovery"]
    new_query = urlencode(params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def expected_recovery_email_href_prefix(*, site_url: str | None = None) -> str:
    """Prefix of the href Supabase must put in the Recovery email (TokenHash appended by template)."""
    base = str(site_url or auth_password_reset_redirect_url(with_landing_hint=False) or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}?suite_auth_landing=recovery&token_hash="


def supabase_auth_redirect_url_checklist() -> tuple[str, ...]:
    """Public app URLs to whitelist in Supabase Auth → URL configuration."""
    candidates: list[str] = []
    custom = _read_secret_auth_redirect_url()
    if custom:
        candidates.append(custom)
    reset_target = auth_password_reset_redirect_url(with_landing_hint=False)
    if reset_target:
        candidates.append(reset_target)
    try:
        from app_urls import (
            APPLIED_INTELLIGENCE_URL,
            BASEBALL_APP_URL,
            FUTURE_LENS_URL,
            HOMEPAGE_DEV_URL,
            HOMEPAGE_PRODUCTION_URL,
            INVESTMENT_APP_URL,
            MUSIC_APP_URL,
            NBA_APP_URL,
        )

        for raw in (
            HOMEPAGE_DEV_URL,
            HOMEPAGE_PRODUCTION_URL,
            MUSIC_APP_URL,
            INVESTMENT_APP_URL,
            NBA_APP_URL,
            APPLIED_INTELLIGENCE_URL,
            FUTURE_LENS_URL,
            BASEBALL_APP_URL,
        ):
            text = str(raw or "").strip().rstrip("/")
            if text:
                candidates.append(text)
    except ImportError:
        pass
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return tuple(out)


def _bridge_supabase_recovery_hash_to_query(st: Any) -> None:
    """
    Streamlit cannot read URL hash fragments server-side.

    Supabase recovery redirects with #access_token=...&type=recovery — promote to query params.
    """
    if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1":
        return
    if _qp_get(st, "type") == "recovery" and _recovery_token_hash_present(st):
        return
    if _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM) == "none":
        return
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return
    components.html(
        """
<script>
(function () {
  function pickWindow() {
    try { if (window.top && window.top.location) return window.top; } catch (e) {}
    try { if (window.parent && window.parent.location) return window.parent; } catch (e) {}
    return window;
  }
  try {
    var w = pickWindow();
    var href = String(w.location.href || "");
    var hash = (w.location.hash || "").replace(/^#/, "");
    var base = href.split("#")[0];
    var u = new URL(base);
    if (hash) {
      var params = new URLSearchParams(hash);
      var type = params.get("type") || "";
      var access = params.get("access_token");
      var refresh = params.get("refresh_token");
      if (type === "recovery" && access && refresh) {
        u.searchParams.set("suite_auth_recovery", "1");
        u.searchParams.set("suite_auth_access", access);
        u.searchParams.set("suite_auth_refresh", refresh);
        u.searchParams.delete("suite_auth_hash_probe");
        w.location.replace(u.toString());
        return;
      }
    }
    var probe = "none";
    if (hash && (hash.indexOf("type=recovery") !== -1 || hash.indexOf("type%3Drecovery") !== -1)) {
      probe = "recovery";
    }
    if (u.searchParams.get("suite_auth_hash_probe") !== probe) {
      u.searchParams.set("suite_auth_hash_probe", probe);
      w.location.replace(u.toString());
    }
  } catch (e) {}
})();
</script>
        """.strip(),
        height=0,
        width=0,
    )


def _browser_query_keys_from_snapshot(snapshot: str) -> list[str]:
    for part in str(snapshot or "").split(","):
        if part.startswith("keys:"):
            raw = part[5:]
            if raw in ("", "none"):
                return []
            return [k for k in raw.split("|") if k]
    return []


def _recovery_landing_signal_present(st: Any) -> bool:
    """True only when URL or snapshot indicates a password-reset landing (not a normal homepage visit)."""
    if _qp_get(st, AUTH_LANDING_HINT_PARAM) == "recovery":
        return True
    if _qp_get(st, "type") == "recovery":
        return True
    if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1":
        return True
    if _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM) == "recovery":
        return True
    if _qp_get(st, "code") or _recovery_token_hash_present(st):
        return True
    if _qp_get(st, "access_token") and _qp_get(st, "refresh_token"):
        return True
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or _qp_get(st, AUTH_LANDING_DIAG_PARAM) or "")
    for token in ("th:1", "rec:1", "code:1", "at:1"):
        if token in snap:
            return True
    if _qp_get(st, AUTH_LANDING_HINT_PARAM) or _qp_get(st, "token_hash"):
        return True
    return False


def _clear_stale_recovery_state(st: Any) -> None:
    """Drop recovery-only session keys when this is a normal visit (bare homepage)."""
    ss = st.session_state
    for key in (
        AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY,
        AUTH_LANDING_SNAPSHOT_KEY,
        AUTH_LANDING_QUERY_KEYS_KEY,
        AUTH_RECOVERY_LAST_ERROR_KEY,
        AUTH_CONFIGURED_RESET_REDIRECT_KEY,
        AUTH_RESET_EXPECTED_HREF_PREFIX_KEY,
    ):
        ss.pop(key, None)
    _clear_recovery_query_params(st)


def _recovery_token_query_param_keys(st: Any) -> set[str]:
    keys = set(_safe_query_param_keys(st))
    token_keys = {
        "token_hash",
        "type",
        "code",
        "access_token",
        "refresh_token",
        AUTH_RECOVERY_FLAG_PARAM,
        AUTH_RECOVERY_ACCESS_PARAM,
        AUTH_RECOVERY_REFRESH_PARAM,
    }
    return keys.intersection(token_keys)


def _recovery_bare_site_landing(st: Any) -> bool:
    """
    True when a reset landing was signaled but neither server nor browser has recovery tokens.

    Not triggered on a normal bare homepage visit (no recovery query hint).
    """
    if not _recovery_landing_signal_present(st):
        return False
    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        return False
    if _recovery_token_hash_present(st) or _recovery_token_query_param_keys(st):
        return False
    browser_keys_raw = _qp_get(st, AUTH_BROWSER_QUERY_KEYS_PARAM)
    if browser_keys_raw and browser_keys_raw != "none":
        recovery_keys = {"token_hash", "type", "code", "access_token", "refresh_token"}
        if recovery_keys.intersection(browser_keys_raw.split("|")):
            return False
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or "")
    if snap:
        if "th:1" in snap:
            return False
        browser_keys = _browser_query_keys_from_snapshot(snap)
        if browser_keys:
            recovery_keys = {"token_hash", "type", "code", "access_token", "refresh_token"}
            if recovery_keys.intersection(browser_keys):
                return False
        return "keys:none" in snap or "th:0" in snap
    if browser_keys_raw == "none":
        return True
    return False


def _needs_recovery_hash_bridge(st: Any) -> bool:
    """Promote #access_token hash fragments — only when recovery landing was signaled."""
    if not _recovery_landing_signal_present(st):
        return False
    if _recovery_bare_site_landing(st):
        return False
    probe = _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM)
    if probe == "none":
        return False
    if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1":
        return False
    if _qp_get(st, "type") == "recovery" and _recovery_token_hash_present(st):
        return False
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or "")
    if "th:1" in snap or _needs_recovery_query_promotion(st):
        return False
    if probe == "recovery":
        return True
    if "rec:1" in snap:
        return True
    return False


def _read_query_param(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        raw = None
    if raw is None:
        try:
            legacy = st.experimental_get_query_params()
            raw = legacy.get(name)
        except Exception:
            raw = None
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def _qp_get(st: Any, name: str) -> str:
    return _read_query_param(st, name)


def _recovery_token_hash_from_query(st: Any) -> str:
    """
    Read PKCE recovery token_hash from query params.

    Email templates that append ``?token_hash=`` to a RedirectTo URL that already
    contains ``?suite_auth_landing=recovery`` produce a malformed query where
    token_hash is embedded in the landing param value — parse that fallback too.
    """
    direct = _qp_get(st, "token_hash")
    if direct:
        return direct
    landing = _qp_get(st, AUTH_LANDING_HINT_PARAM)
    if landing and "token_hash=" in landing:
        from urllib.parse import unquote

        tail = landing.split("token_hash=", 1)[1]
        token = tail.split("&")[0].split("?")[0].strip()
        if token:
            return unquote(token)
    return ""


def _recovery_type_from_query(st: Any) -> str:
    recovery_type = _qp_get(st, "type")
    if recovery_type:
        return recovery_type
    if _recovery_token_hash_from_query(st):
        return "recovery"
    return ""


def _recovery_token_hash_present(st: Any) -> bool:
    return bool(_recovery_token_hash_from_query(st))


def _needs_recovery_query_promotion(st: Any) -> bool:
    """
    Browser URL shows token_hash (landing snapshot th:1) but Streamlit query_params
    did not surface token_hash — normalize via client-side location.replace.
    """
    if not _recovery_landing_signal_present(st):
        return False
    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        return False
    if _recovery_token_hash_from_query(st):
        return False
    if _qp_get(st, AUTH_RECOVERY_QUERY_PROMOTED_PARAM) == "done":
        return False
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or _qp_get(st, AUTH_LANDING_DIAG_PARAM) or "")
    if "th:1" in snap:
        return True
    if _qp_get(st, AUTH_LANDING_HINT_PARAM) == "recovery" and _qp_get(st, "type") == "recovery":
        return True
    return False


def _promote_recovery_query_from_browser(st: Any) -> None:
    """Re-write recovery query params from window.location so Streamlit can read them."""
    if _qp_get(st, AUTH_RECOVERY_QUERY_PROMOTED_PARAM) == "done":
        return
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return
    components.html(
        """
<script>
(function () {
  function pickWindow() {
    try { if (window.top && window.top.location) return window.top; } catch (e) {}
    try { if (window.parent && window.parent.location) return window.parent; } catch (e) {}
    return window;
  }
  try {
    var w = pickWindow();
    var href = String(w.location.href || "").split("#")[0];
    var u = new URL(href);
    var th = u.searchParams.get("token_hash") || "";
    var typ = u.searchParams.get("type") || "";
    if (!th) {
      var landing = u.searchParams.get("suite_auth_landing") || "";
      if (landing.indexOf("token_hash=") !== -1) {
        var tail = landing.split("token_hash=")[1];
        th = tail.split("&")[0].split("?")[0];
      }
    }
    if (typ !== "recovery" || !th) {
      u.searchParams.set("suite_auth_recovery_promoted", "done");
      w.location.replace(u.toString());
      return;
    }
    u.searchParams.set("suite_auth_landing", "recovery");
    u.searchParams.set("token_hash", th);
    u.searchParams.set("type", "recovery");
    u.searchParams.set("suite_auth_recovery_promoted", "done");
    u.searchParams.delete("suite_auth_landing_diag");
    u.searchParams.delete("suite_auth_hash_probe");
    w.location.replace(u.toString());
  } catch (e) {}
})();
</script>
        """.strip(),
        height=0,
        width=0,
    )


def _safe_query_param_keys(st: Any) -> list[str]:
    try:
        qp = st.query_params
        if hasattr(qp, "keys"):
            return sorted(str(k) for k in qp.keys())
    except Exception:
        pass
    return []


def _redact_url_for_log(st: Any) -> str:
    """Loggable landing URL — path + query keys only, no secret values."""
    try:
        from urllib.parse import urlparse

        keys = _safe_query_param_keys(st)
        path = ""
        try:
            import streamlit as st_mod  # noqa: WPS433

            ctx = getattr(st_mod, "context", None)
            if ctx is not None:
                path = str(getattr(ctx, "url", None) or getattr(ctx, "path", None) or "")
        except Exception:
            pass
        if not path:
            path = "streamlit.app/"
        parsed = urlparse(path)
        base = parsed.path or "/"
        if keys:
            return f"{base}?{'&'.join(keys)}"
        return base
    except Exception:
        return "(unavailable)"


def _capture_auth_landing_snapshot(st: Any) -> None:
    diag = _qp_get(st, AUTH_LANDING_DIAG_PARAM)
    browser_keys = _qp_get(st, AUTH_BROWSER_QUERY_KEYS_PARAM)
    if not diag and not browser_keys:
        return
    if diag:
        st.session_state[AUTH_LANDING_SNAPSHOT_KEY] = diag
    if browser_keys:
        st.session_state[AUTH_LANDING_QUERY_KEYS_KEY] = [
            k for k in browser_keys.split("|") if k and k != "none"
        ]
    elif diag:
        st.session_state[AUTH_LANDING_QUERY_KEYS_KEY] = _browser_query_keys_from_snapshot(diag)
    else:
        st.session_state[AUTH_LANDING_QUERY_KEYS_KEY] = _safe_query_param_keys(st)
    _qp_clear(st, AUTH_LANDING_DIAG_PARAM, AUTH_BROWSER_QUERY_KEYS_PARAM)


def _inject_auth_landing_client_probe(st: Any, *, force: bool = False) -> None:
    """Report whether the browser URL has a Supabase recovery hash or PKCE query params."""
    if not force:
        if _qp_get(st, AUTH_LANDING_DIAG_PARAM):
            return
        if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1":
            return
        if _recovery_token_hash_present(st):
            return
        if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
            return
    try:
        import streamlit.components.v1 as components
    except ImportError:
        return
    components.html(
        """
<script>
(function () {
  function pickWindow() {
    try { if (window.top && window.top.location) return window.top; } catch (e) {}
    try { if (window.parent && window.parent.location) return window.parent; } catch (e) {}
    return window;
  }
  try {
    var w = pickWindow();
    var href = String(w.location.href || "");
    var hash = String(w.location.hash || "");
    var search = String(w.location.search || "");
    var base = href.split("#")[0];
    var u = new URL(base);
    var keyList = [];
    u.searchParams.forEach(function (_v, k) { keyList.push(k); });
    keyList.sort();
    var browserKeys = keyList.length ? keyList.join("|") : "none";
    var diag = [
      "hash:" + (hash.length > 1 ? "1" : "0"),
      "rec:" + ((hash.indexOf("type=recovery") !== -1 || hash.indexOf("type%3Drecovery") !== -1) ? "1" : "0"),
      "code:" + (search.indexOf("code=") !== -1 ? "1" : "0"),
      "th:" + (search.indexOf("token_hash=") !== -1 ? "1" : "0"),
      "at:" + (search.indexOf("access_token=") !== -1 ? "1" : "0"),
      "keys:" + browserKeys
    ].join(",");
    var changed = false;
    if (u.searchParams.get("suite_auth_landing_diag") !== diag) {
      u.searchParams.set("suite_auth_landing_diag", diag);
      changed = true;
    }
    if (u.searchParams.get("suite_auth_browser_keys") !== browserKeys) {
      u.searchParams.set("suite_auth_browser_keys", browserKeys);
      changed = true;
    }
    if (changed) {
      w.location.replace(u.toString());
    }
  } catch (e) {}
})();
</script>
        """.strip(),
        height=0,
        width=0,
    )


def _recovery_landing_failed(st: Any) -> bool:
    """True when reset redirect landed on CC but no recovery token shape was detected."""
    if _qp_get(st, AUTH_LANDING_HINT_PARAM) != "recovery":
        return False
    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        return False
    if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1":
        return False
    if _qp_get(st, "type") == "recovery" and _recovery_token_hash_present(st):
        return False
    if _qp_get(st, "code"):
        return False
    if _qp_get(st, "access_token") and _qp_get(st, "refresh_token"):
        return False
    if _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM) == "recovery":
        return False
    if _needs_recovery_hash_bridge(st):
        return False
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or _qp_get(st, AUTH_LANDING_DIAG_PARAM) or "")
    if not snap:
        # Client landing probe has not finished — keep waiting, do not declare failure yet.
        return False
    for token in ("th:1", "code:1", "rec:1", "at:1"):
        if token in snap:
            return False
    return True


def auth_recovery_diagnostics(st: Any | None = None) -> dict[str, Any]:
    """Safe recovery-flow diagnostics for dev panels (no secret values)."""
    if st is None:
        try:
            import streamlit as st_mod  # noqa: WPS433

            st = st_mod
        except Exception:
            return {"available": False}
    ss = st.session_state
    recovery_query = _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) == "1"
    token_hash_query = _recovery_type_from_query(st) == "recovery" and _recovery_token_hash_present(st)
    token_hash_parsed = _recovery_token_hash_from_query(st)
    pkce_code_query = bool(_qp_get(st, "code"))
    access_in_query = bool(_qp_get(st, "access_token"))
    refresh_in_query = bool(_qp_get(st, "refresh_token"))
    access_query = bool(_qp_get(st, AUTH_RECOVERY_ACCESS_PARAM))
    refresh_query = bool(_qp_get(st, AUTH_RECOVERY_REFRESH_PARAM))
    hash_probe = _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM)
    landing_hint = _qp_get(st, AUTH_LANDING_HINT_PARAM)
    landing_snapshot = str(ss.get(AUTH_LANDING_SNAPSHOT_KEY) or _qp_get(st, AUTH_LANDING_DIAG_PARAM) or "")
    query_keys = ss.get(AUTH_LANDING_QUERY_KEYS_KEY) or _safe_query_param_keys(st)
    pending = bool(ss.get(AUTH_RECOVERY_PENDING_KEY))
    recovery_mode = pending or (
        _recovery_landing_signal_present(st)
        and (
            recovery_query
            or token_hash_query
            or pkce_code_query
            or (access_in_query and refresh_in_query)
            or hash_probe == "recovery"
            or landing_hint == "recovery"
        )
    )
    landing_failed = _recovery_landing_failed(st) if landing_hint == "recovery" else False
    verify_attempted = bool(ss.get(AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY))
    query_promotion_needed = _needs_recovery_query_promotion(st)
    configured_redirect = str(ss.get(AUTH_CONFIGURED_RESET_REDIRECT_KEY) or "")
    site_url_expected = auth_password_reset_redirect_url(with_landing_hint=False)
    expected_href_prefix = str(
        ss.get(AUTH_RESET_EXPECTED_HREF_PREFIX_KEY) or expected_recovery_email_href_prefix()
    )
    browser_keys = ss.get(AUTH_LANDING_QUERY_KEYS_KEY) or _browser_query_keys_from_snapshot(landing_snapshot)
    bare_site_landing = _recovery_bare_site_landing(st)
    return {
        "available": True,
        "reset_redirect_to_sent": configured_redirect or site_url_expected,
        "supabase_site_url_expected": site_url_expected,
        "expected_email_href_prefix": expected_href_prefix,
        "configured_reset_redirect_to": configured_redirect or site_url_expected,
        "redacted_incoming_url": _redact_url_for_log(st),
        "query_param_keys": list(query_keys) if isinstance(query_keys, list) else [],
        "browser_query_keys": list(browser_keys) if isinstance(browser_keys, list) else [],
        "landing_hint": landing_hint or "",
        "client_landing_snapshot": landing_snapshot,
        "recovery_token_in_query": recovery_query and access_query and refresh_query,
        "recovery_token_hash_in_query": token_hash_query,
        "recovery_token_hash_parsed": bool(token_hash_parsed),
        "recovery_token_hash_malformed_landing": bool(
            token_hash_parsed and not _qp_get(st, "token_hash")
        ),
        "recovery_pkce_code_in_query": pkce_code_query,
        "recovery_access_token_in_query": access_in_query and refresh_in_query,
        "recovery_hash_probe": hash_probe or "",
        "recovery_mode_detected": recovery_mode,
        "recovery_pending_session": pending,
        "set_password_panel_enabled": pending,
        "hash_bridge_waiting": hash_probe == "recovery" and not pending,
        "recovery_landing_failed": landing_failed,
        "recovery_query_promotion_needed": query_promotion_needed,
        "recovery_verify_attempted": verify_attempted,
        "recovery_bare_site_landing": bare_site_landing,
        "recovery_landing_signal_present": _recovery_landing_signal_present(st),
        "last_recovery_error": str(ss.get(AUTH_RECOVERY_LAST_ERROR_KEY) or ""),
        "authenticated_before_recovery_panel": bool(ss.get(AUTH_SESSION_KEY)) and not pending,
        "email_template_action_required": landing_failed or bare_site_landing,
    }


def render_auth_recovery_diagnostics(st: Any, *, expanded: bool = False, force: bool = False) -> None:
    """Admin-only recovery landing diagnostics (``force`` kept for call-site compat; still gated)."""
    del force  # never bypass admin gate
    try:
        from suite_workspace_registry import is_admin_user

        if not is_admin_user(session_state=getattr(st, "session_state", None)):
            return
    except ImportError:
        return
    with st.expander("Auth recovery (dev)", expanded=expanded):
        st.json(auth_recovery_diagnostics(st=st))
        st.caption(
            "Supabase recovery should arrive as ?token_hash=...&type=recovery (PKCE email template) "
            "or #access_token=...&type=recovery (legacy hash). See docs/SUPABASE_RECOVERY_EMAIL_TEMPLATE.md."
        )


def _qp_clear(st: Any, *keys: str) -> None:
    for key in keys:
        try:
            if hasattr(st.query_params, "pop"):
                st.query_params.pop(key, None)
            else:
                del st.query_params[key]
        except Exception:
            pass


def _recovery_landing_in_progress(st: Any) -> bool:
    if not _recovery_landing_signal_present(st):
        return False
    if _recovery_verify_failed(st):
        return False
    if _recovery_bare_site_landing(st):
        return False
    diag = auth_recovery_diagnostics(st=st)
    return bool(diag.get("recovery_mode_detected"))


def _mark_recovery_session(session_state: dict[str, Any], *, user: Any | None, tokens: dict[str, Any]) -> None:
    if user is not None:
        _apply_authenticated_user(session_state, user, tokens=tokens)
    else:
        session_state[AUTH_TOKENS_KEY] = dict(tokens)
        session_state[AUTH_SESSION_KEY] = True
    session_state[AUTH_RECOVERY_PENDING_KEY] = True
    session_state.pop(AUTH_RECOVERY_LAST_ERROR_KEY, None)


def _recovery_verify_failed(st: Any) -> bool:
    """True when token_hash was parsed but verify_otp did not establish a recovery session."""
    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        return False
    err = str(st.session_state.get(AUTH_RECOVERY_LAST_ERROR_KEY) or "").strip()
    attempted = st.session_state.get(AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY)
    if err:
        return bool(attempted) or _recovery_token_hash_present(st)
    if attempted and not _recovery_token_hash_present(st):
        snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or "")
        if "th:1" in snap:
            return True
    return False


def _clear_recovery_query_params(st: Any) -> None:
    _qp_clear(
        st,
        "type",
        "token_hash",
        AUTH_LANDING_HINT_PARAM,
        AUTH_LANDING_DIAG_PARAM,
        AUTH_RECOVERY_HASH_PROBE_PARAM,
        AUTH_RECOVERY_FLAG_PARAM,
        AUTH_RECOVERY_ACCESS_PARAM,
        AUTH_RECOVERY_REFRESH_PARAM,
        "code",
        "access_token",
        "refresh_token",
        AUTH_RECOVERY_QUERY_PROMOTED_PARAM,
        AUTH_BROWSER_QUERY_KEYS_PARAM,
    )


def _consume_auth_recovery_token_hash(st: Any) -> bool:
    """PKCE-style recovery links put token_hash and type=recovery in the query string."""
    token_hash = _recovery_token_hash_from_query(st)
    if not token_hash:
        return False
    if _recovery_type_from_query(st) != "recovery":
        return False
    session_state = st.session_state
    if session_state.get(AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY) == token_hash:
        return False
    session_state[AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY] = token_hash
    try:
        client = _create_fresh_supabase_client()
        auth = client.auth
        resp = auth.verify_otp({"token_hash": token_hash, "type": "recovery"})
        user = _user_from_auth_response(resp)
        tokens = _tokens_from_auth_response(resp)
        if not tokens:
            session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = "Recovery verify_otp returned no session tokens."
            _clear_recovery_query_params(st)
            return False
        session_state[AUTH_CLIENT_KEY] = client
        _mark_recovery_session(session_state, user=user, tokens=tokens)
    except Exception as exc:
        session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = str(exc)
        _clear_recovery_query_params(st)
        return False
    _clear_recovery_query_params(st)
    return True


def _consume_auth_recovery_query(st: Any) -> bool:
    """Exchange recovery tokens promoted from the URL hash into a temporary auth session."""
    if _qp_get(st, AUTH_RECOVERY_FLAG_PARAM) != "1":
        return False
    access = _qp_get(st, AUTH_RECOVERY_ACCESS_PARAM)
    refresh = _qp_get(st, AUTH_RECOVERY_REFRESH_PARAM)
    if not access or not refresh:
        return False
    session_state = st.session_state
    try:
        auth = _auth_api(session_state)
        resp = auth.set_session(access, refresh)
        user = _user_from_auth_response(resp)
        tokens = _tokens_from_auth_response(resp) or {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": 0,
        }
        _mark_recovery_session(session_state, user=user, tokens=tokens)
    except Exception as exc:
        session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = str(exc)
        return False
    _qp_clear(
        st,
        AUTH_RECOVERY_FLAG_PARAM,
        AUTH_RECOVERY_ACCESS_PARAM,
        AUTH_RECOVERY_REFRESH_PARAM,
        AUTH_RECOVERY_HASH_PROBE_PARAM,
    )
    return True


def _consume_auth_recovery_code(st: Any) -> bool:
    """PKCE auth-code recovery redirect (?code=...) after Supabase verify."""
    code = _qp_get(st, "code")
    if not code:
        return False
    session_state = st.session_state
    try:
        auth = _create_fresh_supabase_client().auth
        resp = auth.exchange_code_for_session(code)
        user = _user_from_auth_response(resp)
        tokens = _tokens_from_auth_response(resp)
        if not tokens:
            session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = "Recovery code exchange returned no session tokens."
            return False
        _mark_recovery_session(session_state, user=user, tokens=tokens)
    except Exception as exc:
        session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = str(exc)
        return False
    _qp_clear(st, "code", AUTH_RECOVERY_HASH_PROBE_PARAM, AUTH_LANDING_DIAG_PARAM)
    return True


def _consume_auth_recovery_implicit_query(st: Any) -> bool:
    """Legacy implicit recovery tokens already present in the query string."""
    if _qp_get(st, "type") != "recovery":
        return False
    access = _qp_get(st, "access_token")
    refresh = _qp_get(st, "refresh_token")
    if not access or not refresh:
        return False
    session_state = st.session_state
    try:
        auth = _auth_api(session_state)
        resp = auth.set_session(access, refresh)
        user = _user_from_auth_response(resp)
        tokens = _tokens_from_auth_response(resp) or {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": 0,
        }
        _mark_recovery_session(session_state, user=user, tokens=tokens)
    except Exception as exc:
        session_state[AUTH_RECOVERY_LAST_ERROR_KEY] = str(exc)
        return False
    _qp_clear(st, "type", "access_token", "refresh_token", AUTH_RECOVERY_HASH_PROBE_PARAM)
    return True


def _render_recovery_verify_failed(st: Any) -> None:
    st.title("Password reset verification failed")
    err = str(st.session_state.get(AUTH_RECOVERY_LAST_ERROR_KEY) or "").strip()
    st.error(err or "Could not verify the recovery link.")
    st.markdown(
        "Request a **new** reset email. If this keeps failing, confirm the Recovery template uses "
        "`?suite_auth_landing=recovery&token_hash=...` (see `docs/SUPABASE_RECOVERY_EMAIL_TEMPLATE.md`)."
    )
    render_auth_recovery_diagnostics(st, expanded=True, force=True)
    if st.button("Back to sign in", key="suite_auth_recovery_verify_failed_back", use_container_width=True):
        st.session_state.pop(AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY, None)
        st.session_state.pop(AUTH_RECOVERY_LAST_ERROR_KEY, None)
        st.session_state.pop(AUTH_LANDING_SNAPSHOT_KEY, None)
        _clear_recovery_query_params(st)
        st.rerun()
    st.stop()


def _render_recovery_bare_site_landing(st: Any) -> None:
    st.title("Password reset link missing tokens")
    diag = auth_recovery_diagnostics(st=st)
    prefix = str(diag.get("expected_email_href_prefix") or "")
    site = str(diag.get("supabase_site_url_expected") or "")
    st.error(
        "Command Center opened **without any recovery query parameters** (`/` only). "
        "The reset email link is almost certainly **not** the PKCE `token_hash` template — "
        "Supabase is likely still sending `{{ .ConfirmationURL }}` or a bare Site URL redirect."
    )
    st.markdown(
        f"""
**Verify the actual email href** (right-click → Copy link address). It must visibly contain:

- `suite_auth_landing=recovery`
- `token_hash=`
- `type=recovery`

**Expected start of href:** `{prefix}<TokenHash>&type=recovery`

**Supabase Site URL must be exactly:** `{site}` (no path, no extra query)

**Reset password template** (use `{{{{ .SiteURL }}}}` — not `{{{{ .ConfirmationURL }}}}`):

```html
<a href="{{{{ .SiteURL }}}}?suite_auth_landing=recovery&token_hash={{{{.TokenHash}}}}&type=recovery">Reset password</a>
```

Save the template, then send a **new** reset email.
"""
    )
    render_auth_recovery_diagnostics(st, expanded=True, force=True)
    if st.button("Back to sign in", key="suite_auth_recovery_bare_back", use_container_width=True):
        st.session_state.pop(AUTH_LANDING_SNAPSHOT_KEY, None)
        st.session_state.pop(AUTH_LANDING_QUERY_KEYS_KEY, None)
        _clear_recovery_query_params(st)
        st.rerun()
    st.stop()


def _render_recovery_landing_wait(st: Any) -> None:
    st.title("Daniel AI Suite")
    st.info("Processing password reset link…")
    err = str(st.session_state.get(AUTH_RECOVERY_LAST_ERROR_KEY) or "").strip()
    if err:
        st.error(err)
    st.caption(
        "If this screen does not advance within a few seconds, **do not keep clicking the email link**. "
        "Open an incognito window, request a **new** reset email, right-click the link → **Copy link address**, "
        "and paste that URL (redact the token_hash value) before clicking."
    )
    diag = auth_recovery_diagnostics(st=st)
    st.markdown(
        "**Recovery status (safe):** "
        f"server keys={diag.get('query_param_keys') or []} · "
        f"browser keys={diag.get('browser_query_keys') or []} · "
        f"token_parsed={diag.get('recovery_token_hash_parsed')} · "
        f"verify_attempted={diag.get('recovery_verify_attempted')} · "
        f"bare_landing={diag.get('recovery_bare_site_landing')}"
    )
    _inject_auth_landing_client_probe(st, force=True)
    render_auth_recovery_diagnostics(st, expanded=True, force=True)
    if st.button("Back to sign in", key="suite_auth_recovery_wait_back", use_container_width=True):
        st.session_state.pop(AUTH_RECOVERY_VERIFY_ATTEMPTED_KEY, None)
        st.session_state.pop(AUTH_RECOVERY_LAST_ERROR_KEY, None)
        st.session_state.pop(AUTH_LANDING_SNAPSHOT_KEY, None)
        st.session_state.pop(AUTH_LANDING_QUERY_KEYS_KEY, None)
        _clear_recovery_query_params(st)
        st.rerun()
    st.stop()


def _render_recovery_landing_failed(st: Any) -> None:
    st.title("Password reset link incomplete")
    st.error(
        "Command Center opened from your reset email, but **no recovery token reached the app**. "
        "This usually means the Supabase **Recovery email template** still uses the default "
        "`{{ .ConfirmationURL }}` link (hash tokens are lost on Streamlit Cloud)."
    )
    st.markdown(
        "Update **Supabase → Authentication → Email Templates → Reset password** to the PKCE template in "
        "`docs/SUPABASE_RECOVERY_EMAIL_TEMPLATE.md`, then send a **new** reset email."
    )
    render_auth_recovery_diagnostics(st, expanded=True, force=True)
    if st.button("Back to sign in", key="suite_auth_recovery_failed_back", use_container_width=True):
        _qp_clear(st, AUTH_LANDING_HINT_PARAM, AUTH_LANDING_DIAG_PARAM, AUTH_RECOVERY_HASH_PROBE_PARAM)
        st.session_state.pop(AUTH_LANDING_SNAPSHOT_KEY, None)
        st.rerun()
    st.stop()


def complete_password_recovery(session_state: dict[str, Any], new_password: str) -> tuple[bool, str]:
    """Finish Supabase recovery flow after user sets a new password."""
    if not str(new_password or "").strip():
        return False, "Enter a new password."
    try:
        auth = _auth_api(session_state)
        auth.update_user({"password": str(new_password)})
    except Exception as exc:
        return False, str(exc)
    session_state.pop(AUTH_RECOVERY_PENDING_KEY, None)
    session_state[AUTH_NOTICE_KEY] = "Password updated. You are signed in."
    return True, "Password updated."


def _render_password_recovery_panel(st: Any) -> None:
    """Block app until the user chooses a new password from an email recovery link."""
    st.title("Set new password")
    st.caption("You opened a password reset link. Choose a new password to continue.")
    pw1 = st.text_input("New password", type="password", key="suite_auth_recovery_pw1")
    pw2 = st.text_input("Confirm password", type="password", key="suite_auth_recovery_pw2")
    if st.button("Update password", key="suite_auth_recovery_submit", use_container_width=True):
        if pw1 != pw2:
            st.error("Passwords do not match.")
        elif len(str(pw1 or "")) < 6:
            st.error("Password must be at least 6 characters.")
        else:
            ok, msg = complete_password_recovery(st.session_state, pw1)
            if ok:
                try:
                    from suite_auth_browser import save_browser_auth_tokens
                    from suite_user import get_account_user_id

                    tokens = dict(st.session_state.get(AUTH_TOKENS_KEY) or {})
                    if tokens.get("access_token"):
                        save_browser_auth_tokens(
                            st,
                            tokens,
                            auth_user_id=get_account_user_id(),
                        )
                except ImportError:
                    pass
                enforce_workspace_ownership(st.session_state)
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    st.stop()


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


def process_pending_auth_login(st: Any) -> bool:
    """
    Complete a sidebar login before workspace sync.

    Sidebar form submit stores credentials in session and reruns; this runs on the
    next script pass before cloud/disk restore so auth keys survive force-sync.
    """
    session = st.session_state
    pending = session.pop(AUTH_PENDING_LOGIN_KEY, None)
    if not isinstance(pending, dict):
        return False
    email = str(pending.get("email") or "").strip()
    password = str(pending.get("password") or "")
    session["_baseball_account_expander_open"] = True
    ok, _msg = login_with_email(session, email=email, password=password, st=st)
    return ok


def login_with_email(
    session_state: dict[str, Any],
    *,
    email: str,
    password: str,
    st: Any | None = None,
) -> tuple[bool, str]:
    email_clean = str(email or "").strip()
    password_clean = str(password or "")
    if not email_clean or not password_clean:
        msg = "Enter both email and password."
        session_state[AUTH_LAST_LOGIN_ERROR_KEY] = msg
        session_state[AUTH_LAST_LOGIN_OK_KEY] = False
        return False, msg
    if st is None:
        try:
            import streamlit as st_mod  # noqa: WPS433

            st = st_mod
        except Exception:
            pass
    try:
        auth = _auth_api(session_state)
    except Exception:
        return False, _auth_not_configured_message()
    try:
        resp = auth.sign_in_with_password({"email": email_clean, "password": password_clean})
        user = _user_from_auth_response(resp)
        if user is None:
            msg = "Invalid email or password."
            session_state[AUTH_LAST_LOGIN_ERROR_KEY] = msg
            session_state[AUTH_LAST_LOGIN_OK_KEY] = False
            return False, msg
        tokens = _tokens_from_auth_response(resp)
        if not tokens:
            msg = "Login succeeded but no session tokens returned."
            session_state[AUTH_LAST_LOGIN_ERROR_KEY] = msg
            session_state[AUTH_LAST_LOGIN_OK_KEY] = False
            return False, msg
        _persist_auth_session(session_state, user=user, tokens=tokens, email_fallback=email_clean, st=st)
        enforce_workspace_ownership(session_state)
        if not auth_session_complete(session_state):
            msg = "Login incomplete — missing user id or session tokens. Try again."
            session_state[AUTH_LAST_LOGIN_ERROR_KEY] = msg
            session_state[AUTH_LAST_LOGIN_OK_KEY] = False
            _clear_auth_session(session_state, st=st, invalidate_bridge=False)
            return False, msg
        session_state[AUTH_NOTICE_KEY] = "Signed in."
        session_state[AUTH_LAST_LOGIN_OK_KEY] = True
        session_state.pop(AUTH_LAST_LOGIN_ERROR_KEY, None)
        session_state["_baseball_account_expander_open"] = True
        return True, "Signed in."
    except Exception as exc:
        msg = str(exc)
        session_state[AUTH_LAST_LOGIN_ERROR_KEY] = msg
        session_state[AUTH_LAST_LOGIN_OK_KEY] = False
        return False, msg


def request_password_reset(email: str, *, redirect_to: str | None = None) -> tuple[bool, str]:
    if not is_auth_enabled():
        return False, "Auth is disabled."
    try:
        auth = _create_fresh_supabase_client().auth
    except Exception:
        return False, _auth_not_configured_message()
    target = str(
        redirect_to or auth_password_reset_redirect_url(with_landing_hint=False) or ""
    ).strip().rstrip("/")
    if not target:
        return (
            False,
            "Password reset redirect URL is not configured. Set suite_auth_redirect_url in secrets "
            "or deploy app_urls with HOMEPAGE_DEV_URL.",
        )
    try:
        import streamlit as st_mod  # noqa: WPS433

        st_mod.session_state[AUTH_CONFIGURED_RESET_REDIRECT_KEY] = target
        st_mod.session_state[AUTH_RESET_EXPECTED_HREF_PREFIX_KEY] = expected_recovery_email_href_prefix(
            site_url=target
        )
    except Exception:
        pass
    try:
        auth.reset_password_email(email.strip(), {"redirect_to": target})
        href_prefix = expected_recovery_email_href_prefix(site_url=target)
        return (
            True,
            f"Password reset email sent. redirect_to={target}. "
            f"Email href must start with: {href_prefix}<TokenHash>&type=recovery "
            "(Supabase template must use {{ .SiteURL }} + token_hash — see docs/SUPABASE_RECOVERY_EMAIL_TEMPLATE.md).",
        )
    except Exception as exc:
        return False, str(exc)


def render_auth_panel(
    st: Any,
    *,
    expanded: bool = False,
    show_signed_in_status: bool = True,
    flat_sidebar: bool = False,
) -> None:
    """Login / sign-up panel when Real Accounts are enabled."""
    if not is_auth_enabled():
        return
    session = st.session_state
    notice = session.pop(AUTH_NOTICE_KEY, None)
    if notice:
        st.info(str(notice))
    last_login_error = str(session.get(AUTH_LAST_LOGIN_ERROR_KEY) or "").strip()
    if last_login_error and not auth_session_complete(session):
        st.error(last_login_error)
    if auth_session_complete(session):
        if show_signed_in_status:
            st.success(f"Signed in as **{current_auth_email(session) or 'account'}**")
        if st.button("Log out", key="suite_auth_logout_btn", use_container_width=True):
            logout(session, st=st)
            st.rerun()
        return

    def _render_login_tabs() -> None:
        tab_login, tab_signup, tab_reset = st.tabs(["Log in", "Create account", "Reset password"])
        with tab_login:
            with st.form("suite_auth_login_form", clear_on_submit=False):
                email = st.text_input("Email", key="suite_auth_login_email")
                password = st.text_input("Password", type="password", key="suite_auth_login_password")
                submitted = st.form_submit_button("Log in", use_container_width=True)
            if submitted:
                session[AUTH_PENDING_LOGIN_KEY] = {
                    "email": email,
                    "password": password,
                }
                session["_baseball_account_expander_open"] = True
                st.rerun()
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

    if flat_sidebar:
        _render_login_tabs()
        return

    title = "Sign in"
    with st.expander(title, expanded=expanded):
        _render_login_tabs()


def render_auth_gate(st: Any) -> bool:
    """
    When auth is enabled, block app body until the user signs in.

    Returns True when the app may continue rendering.
    """
    if not is_auth_enabled():
        return True

    if _qp_get(st, AUTH_RECOVERY_HASH_PROBE_PARAM) == "none":
        _qp_clear(st, AUTH_RECOVERY_HASH_PROBE_PARAM)

    # Consume recovery tokens before landing probe can trigger an early rerun.
    if _consume_auth_recovery_token_hash(st):
        st.rerun()
    if _consume_auth_recovery_code(st):
        st.rerun()
    if _consume_auth_recovery_implicit_query(st):
        st.rerun()
    if _consume_auth_recovery_query(st):
        st.rerun()

    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        _render_password_recovery_panel(st)
        return False

    if _recovery_landing_failed(st):
        _render_recovery_landing_failed(st)
        return False

    if _recovery_verify_failed(st):
        _render_recovery_verify_failed(st)
        return False

    if _recovery_landing_signal_present(st):
        if not _recovery_token_hash_present(st) and not st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
            _inject_auth_landing_client_probe(st)
            if _qp_get(st, AUTH_LANDING_DIAG_PARAM) or _qp_get(st, AUTH_BROWSER_QUERY_KEYS_PARAM):
                _capture_auth_landing_snapshot(st)
                st.rerun()

        if _recovery_bare_site_landing(st):
            _render_recovery_bare_site_landing(st)
            return False

        if _needs_recovery_query_promotion(st):
            _promote_recovery_query_from_browser(st)
            _render_recovery_landing_wait(st)
            return False

        if _needs_recovery_hash_bridge(st):
            _bridge_supabase_recovery_hash_to_query(st)
            _render_recovery_landing_wait(st)
            return False

        if _recovery_landing_in_progress(st):
            _render_recovery_landing_wait(st)
            return False
    else:
        _clear_stale_recovery_state(st)

    restore_auth_session(st.session_state, st=st)
    if is_authenticated(st.session_state):
        enforce_workspace_ownership(st.session_state)
        return True
    st.title("Daniel AI Suite")
    st.caption("Sign in to continue.")
    render_auth_panel(st, expanded=True)
    st.stop()
    return False
