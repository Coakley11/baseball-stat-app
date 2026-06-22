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

# Workspace ownership v1 — map external/auth user to allowed preset profiles.
# Daniel (admin) may switch into child/guest profiles from Command Center (W1–W6).
# Child accounts remain scoped to their own profile only (C5).
_DEFAULT_ALLOWED_WORKSPACES: dict[str, tuple[str, ...]] = {
    "daniel": ("daniel", "ariel", "guest", "test_user"),
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
        return ("daniel", "ariel", "guest", "test_user")
    return ("daniel", "guest", "test_user")


def resolve_auth_external_id(session_state: dict[str, Any]) -> str:
    """Best-effort suite profile id for the signed-in account."""
    ext = str(session_state.get(AUTH_EXTERNAL_ID_KEY) or "").strip().lower()
    if ext:
        return ext
    inferred = _infer_external_id_from_email(current_auth_email(session_state))
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
        allowed = allowed_workspaces_for_session(session_state)
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


def _recovery_bare_site_landing(st: Any) -> bool:
    """
    True when neither server nor browser URL contains recovery query params.

    Usually means the reset email href still uses ConfirmationURL / bare Site URL.
    """
    if st.session_state.get(AUTH_RECOVERY_PENDING_KEY):
        return False
    if _recovery_token_hash_present(st) or _safe_query_param_keys(st):
        return False
    browser_keys_raw = _qp_get(st, AUTH_BROWSER_QUERY_KEYS_PARAM)
    if browser_keys_raw and browser_keys_raw != "none":
        recovery_keys = {"token_hash", "type", "suite_auth_landing", "code", "access_token"}
        if recovery_keys.intersection(browser_keys_raw.split("|")):
            return False
    snap = str(st.session_state.get(AUTH_LANDING_SNAPSHOT_KEY) or "")
    if snap:
        if "th:1" in snap:
            return False
        browser_keys = _browser_query_keys_from_snapshot(snap)
        if browser_keys:
            recovery_keys = {"token_hash", "type", "suite_auth_landing", "code", "access_token"}
            if recovery_keys.intersection(browser_keys):
                return False
        return "keys:none" in snap or "th:0" in snap
    if browser_keys_raw == "none":
        return True
    return False


def _needs_recovery_hash_bridge(st: Any) -> bool:
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
    return True


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
    recovery_mode = (
        pending
        or recovery_query
        or token_hash_query
        or pkce_code_query
        or (access_in_query and refresh_in_query)
        or hash_probe == "recovery"
        or landing_hint == "recovery"
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
        "last_recovery_error": str(ss.get(AUTH_RECOVERY_LAST_ERROR_KEY) or ""),
        "authenticated_before_recovery_panel": bool(ss.get(AUTH_SESSION_KEY)) and not pending,
        "email_template_action_required": landing_failed or bare_site_landing,
    }


def render_auth_recovery_diagnostics(st: Any, *, expanded: bool = False, force: bool = False) -> None:
    """Developer-only recovery landing diagnostics (force=True during recovery wait screen)."""
    if not force:
        try:
            from suite_workspace import can_show_developer_tools

            if not can_show_developer_tools(st=st):
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
    _inject_auth_landing_client_probe(st, force=True)
    render_auth_recovery_diagnostics(st, expanded=True, force=True)
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

    restore_auth_session(st.session_state, st=st)
    if is_authenticated(st.session_state):
        enforce_workspace_ownership(st.session_state)
        return True
    st.title("Daniel AI Suite")
    st.caption("Sign in to continue.")
    render_auth_panel(st, expanded=True)
    st.stop()
    return False
