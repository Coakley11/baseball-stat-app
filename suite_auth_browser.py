"""
Browser-persisted Supabase Auth tokens for Streamlit refresh survival (C2b).

Uses ``extra-streamlit-components`` CookieManager — tokens survive browser F5
within the same origin (*.streamlit.app). Synced to sibling repos.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

COOKIE_NAME = "suite_auth_tokens_v1"
COOKIES_READY_KEY = "_suite_auth_browser_cookies_ready"
_COOKIE_MANAGER_KEY = "suite_auth_cookie_manager"


def _cookie_manager(st: Any) -> Any:
    cached = st.session_state.get(_COOKIE_MANAGER_KEY)
    if cached is not None:
        return cached
    import extra_streamlit_components as stx

    mgr = stx.CookieManager(key="suite_auth_cookie_mgr")
    st.session_state[_COOKIE_MANAGER_KEY] = mgr
    return mgr


def ensure_browser_cookies_loaded(st: Any) -> bool:
    """
    CookieManager returns ``None`` on the first render pass.

    Return False to ``st.stop()`` until cookies are readable.
    """
    if st.session_state.get(COOKIES_READY_KEY):
        return True
    mgr = _cookie_manager(st)
    cookies = mgr.get_all()
    if cookies is None:
        return False
    st.session_state[COOKIES_READY_KEY] = True
    return True


def load_browser_auth_tokens(st: Any) -> dict[str, Any] | None:
    """Read persisted token bundle from browser cookie, if present."""
    if not ensure_browser_cookies_loaded(st):
        return None
    mgr = _cookie_manager(st)
    raw = mgr.get(COOKIE_NAME)
    if not raw:
        cookies = mgr.get_all() or {}
        raw = cookies.get(COOKIE_NAME)
    return _decode_token_cookie(raw)


def save_browser_auth_tokens(st: Any, tokens: dict[str, Any]) -> None:
    """Persist token bundle to browser cookie (~30 days)."""
    payload = _encode_token_cookie(tokens)
    if not payload:
        return
    mgr = _cookie_manager(st)
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    refresh = str(tokens.get("refresh_token") or "")[:12]
    mgr.set(
        COOKIE_NAME,
        payload,
        expires_at=expires,
        key=f"suite_auth_cookie_set_{refresh}",
    )


def clear_browser_auth_tokens(st: Any) -> None:
    """Remove persisted auth cookie on logout."""
    try:
        mgr = _cookie_manager(st)
        mgr.delete(COOKIE_NAME, key="suite_auth_cookie_clear")
    except Exception:
        pass
    st.session_state.pop(COOKIES_READY_KEY, None)


def _encode_token_cookie(tokens: dict[str, Any]) -> str:
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    if not access or not refresh:
        return ""
    bundle = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(tokens.get("expires_at") or 0),
    }
    return json.dumps(bundle, separators=(",", ":"))


def _decode_token_cookie(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    access = str(data.get("access_token") or "").strip()
    refresh = str(data.get("refresh_token") or "").strip()
    if not access or not refresh:
        return None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(data.get("expires_at") or 0),
    }
