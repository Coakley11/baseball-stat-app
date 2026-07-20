"""Supabase egress reduction policy — workspace sync, polling, and autosave throttles."""

from __future__ import annotations

import os
import time
from typing import Any

LOW_EGRESS_SESSION_KEY = "suite_low_egress_mode"
WORKSPACE_META_TTL_SEC = 300.0
CLOUD_AUTOSAVE_MIN_INTERVAL_SEC = 45.0
SHARED_DRAFT_POLL_INTERVAL_SEC = 2.5
SHARED_DRAFT_POLL_LOW_EGRESS_SEC = 8.0
MULTIPLAYER_CLOUD_AUTOSAVE_INTERVAL_SEC = 90.0


def low_egress_mode(session: dict[str, Any] | None = None) -> bool:
    if os.environ.get("SUITE_LOW_EGRESS", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if isinstance(session, dict) and session.get(LOW_EGRESS_SESSION_KEY):
        return True
    try:
        import streamlit as st  # noqa: WPS433

        if st.session_state.get(LOW_EGRESS_SESSION_KEY):
            return True
        if str(st.query_params.get("low_egress", "")).strip().lower() in ("1", "true", "yes"):
            return True
    except Exception:
        pass
    return False


def set_low_egress_mode(session: dict[str, Any], enabled: bool) -> None:
    if enabled:
        session[LOW_EGRESS_SESSION_KEY] = True
    else:
        session.pop(LOW_EGRESS_SESSION_KEY, None)


def _workspace_synced_key(app_id: str) -> str:
    return f"_suite_workspace_synced::{app_id}"


def workspace_cloud_fetch_needed(st: Any, app_id: str) -> bool:
    """False when this rerun can skip downloading full_session from Supabase."""
    ss = st.session_state
    if ss.get("_suite_workspace_force_sync"):
        return True
    if not ss.get(_workspace_synced_key(app_id)):
        return True
    if low_egress_mode(ss):
        return False
    last_meta = float(ss.get(f"_suite_workspace_meta_probe_ts::{app_id}") or 0)
    if time.time() - last_meta >= WORKSPACE_META_TTL_SEC:
        return True
    return False


def record_workspace_meta_probe(st: Any, app_id: str) -> None:
    st.session_state[f"_suite_workspace_meta_probe_ts::{app_id}"] = time.time()


def lightweight_workspace_meta_check(st: Any, app_id: str) -> bool:
    """Optional updated_at-only probe; returns True if cloud may be newer than applied."""
    try:
        from suite_cloud_state import parse_persist_timestamp
        from suite_storage_supabase import load_current_state_meta_for_app
    except ImportError:
        return False
    record_workspace_meta_probe(st, app_id)
    ss = st.session_state
    try:
        from suite_user_persistence import _applied_cloud_ts_key

        applied_key = _applied_cloud_ts_key(app_id)
    except ImportError:
        applied_key = f"_suite_applied_cloud_ts::{app_id}"
    applied_ts = str(ss.get(applied_key) or "")
    meta = load_current_state_meta_for_app(app_id) or {}
    cloud_ts = str(meta.get("updated_at") or "")
    if not cloud_ts:
        return False
    return parse_persist_timestamp(cloud_ts) > parse_persist_timestamp(applied_ts)


def cloud_autosave_allowed(st: Any, app_id: str, *, save_reason: str = "") -> tuple[bool, str]:
    ss = st.session_state
    reason = str(save_reason or "autosave").strip() or "autosave"
    # Low-egress only suppresses routine autosaves — explicit user actions still persist.
    if low_egress_mode(ss) and reason in ("", "autosave"):
        return False, "low_egress_mode"
    try:
        from draft_room_context import is_multiplayer_draft_active
    except ImportError:
        is_multiplayer_draft_active = lambda _s: False  # type: ignore[assignment]
    if app_id == "baseball" and is_multiplayer_draft_active(ss):
        min_iv = MULTIPLAYER_CLOUD_AUTOSAVE_INTERVAL_SEC
        last = float(ss.get("_suite_last_cloud_autosave_ts") or 0)
        if reason == "autosave" and time.time() - last < min_iv:
            return False, "multiplayer_autosave_throttled"
    if reason == "autosave":
        last = float(ss.get("_suite_last_cloud_autosave_ts") or 0)
        if time.time() - last < CLOUD_AUTOSAVE_MIN_INTERVAL_SEC:
            return False, "autosave_throttled"
    return True, ""


def mark_cloud_autosave(st: Any) -> None:
    st.session_state["_suite_last_cloud_autosave_ts"] = time.time()


def shared_draft_poll_interval_sec(session: dict[str, Any]) -> float:
    if low_egress_mode(session):
        return SHARED_DRAFT_POLL_LOW_EGRESS_SEC
    return SHARED_DRAFT_POLL_INTERVAL_SEC


def block_cloud_autosave_for_poll_sync(session: dict[str, Any]) -> None:
    session["_suite_defer_cloud_autosave_until"] = time.time() + 5.0


def poll_sync_defer_active(session: dict[str, Any]) -> bool:
    until = float(session.get("_suite_defer_cloud_autosave_until") or 0)
    return time.time() < until
