"""
Browser-persisted Supabase Auth tokens for Streamlit refresh survival (C2b).

Uses ``extra-streamlit-components`` CookieManager. The component returns ``{}`` on
the first render before the iframe reads browser cookies — callers must bootstrap
with one rerun (``init_browser_auth_storage``) before restore/login cookie writes.

Synced to sibling repos.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

COOKIE_NAME = "suite_auth_tokens_v1"
COOKIE_BOOTSTRAP_KEY = "_suite_auth_cookie_bootstrap_done"
COOKIE_SYNC_PENDING_KEY = "_suite_auth_cookie_sync_pending"
_COOKIE_MANAGER_KEY = "_suite_auth_cookie_manager"

InitState = Literal["wait", "sync_pending", "ready"]


def _cookie_manager(st: Any) -> Any:
    cached = st.session_state.get(_COOKIE_MANAGER_KEY)
    if cached is not None:
        cached.get_all()
        return cached
    import extra_streamlit_components as stx

    mgr = stx.CookieManager(key="suite_auth_cookie_mgr")
    st.session_state[_COOKIE_MANAGER_KEY] = mgr
    mgr.get_all()
    return mgr


def init_browser_auth_storage(st: Any) -> InitState:
    """
    Mount CookieManager and sync with the browser cookie jar.

    Returns ``wait`` — component just mounted; caller must ``st.stop()``.
    Returns ``sync_pending`` — cookie write in flight; caller must ``st.rerun()``.
    Returns ``ready`` — safe to read/write auth cookies.
    """
    mgr = _cookie_manager(st)

    if st.session_state.get(COOKIE_SYNC_PENDING_KEY):
        written = _read_cookie_raw(mgr)
        if written:
            st.session_state.pop(COOKIE_SYNC_PENDING_KEY, None)
        else:
            return "sync_pending"

    if not st.session_state.get(COOKIE_BOOTSTRAP_KEY):
        st.session_state[COOKIE_BOOTSTRAP_KEY] = True
        return "wait"

    return "ready"


def load_browser_auth_tokens(st: Any) -> dict[str, Any] | None:
    """Read persisted token bundle from browser cookie, if present."""
    state = init_browser_auth_storage(st)
    if state != "ready":
        return None
    return _decode_token_cookie(_read_cookie_raw(_cookie_manager(st)))


def save_browser_auth_tokens(st: Any, tokens: dict[str, Any]) -> None:
    """Persist token bundle to browser cookie (~30 days). Requires a follow-up rerun."""
    payload = _encode_token_cookie(tokens)
    if not payload:
        return
    state = init_browser_auth_storage(st)
    if state == "wait":
        return
    mgr = _cookie_manager(st)
    refresh = str(tokens.get("refresh_token") or "")[:12]
    mgr.set(
        COOKIE_NAME,
        payload,
        max_age=30 * 24 * 3600,
        path="/",
        secure=True,
        same_site="lax",
        key=f"suite_auth_cookie_set_{refresh}",
    )
    st.session_state[COOKIE_SYNC_PENDING_KEY] = True


def clear_browser_auth_tokens(st: Any) -> None:
    """Remove persisted auth cookie on logout."""
    try:
        state = init_browser_auth_storage(st)
        if state == "ready":
            mgr = _cookie_manager(st)
            mgr.delete(COOKIE_NAME, key="suite_auth_cookie_clear")
    except Exception:
        pass
    st.session_state.pop(COOKIE_BOOTSTRAP_KEY, None)
    st.session_state.pop(COOKIE_SYNC_PENDING_KEY, None)


def browser_auth_storage_status(st: Any) -> dict[str, Any]:
    """Dev diagnostics — no secret values."""
    out = {
        "bootstrap_done": bool(st.session_state.get(COOKIE_BOOTSTRAP_KEY)),
        "sync_pending": bool(st.session_state.get(COOKIE_SYNC_PENDING_KEY)),
        "cookie_present": False,
        "cookie_bytes": 0,
    }
    try:
        if init_browser_auth_storage(st) == "ready":
            raw = _read_cookie_raw(_cookie_manager(st))
            out["cookie_present"] = bool(raw)
            out["cookie_bytes"] = len(str(raw or ""))
    except Exception:
        pass
    return out


def _read_cookie_raw(mgr: Any) -> Any:
    raw = mgr.get(COOKIE_NAME)
    if not raw:
        cookies = mgr.get_all() or {}
        raw = cookies.get(COOKIE_NAME)
    return raw


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


# Backward-compatible alias used by suite_auth.render_auth_gate
def ensure_browser_cookies_loaded(st: Any) -> bool:
    state = init_browser_auth_storage(st)
    return state == "ready"
