"""Disk persistence for Baseball Stat App (global + per-page filter store)."""

from __future__ import annotations

import copy
from typing import Any

import page_state as pg_state
from suite_user_persistence import (
    autosave_if_changed,
    finalize_suite_reset,
    restore_once,
)

APP_ID = "baseball"

_DEFAULT_PAGE = "Historical Explorer"
_DEFAULT_SIDEBAR_PAGE = "🔎 Historical Explorer"

_GLOBAL_KEYS = (
    "active_page",
    "comparison_user_team",
    "draft_room_table",
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
)


def build_baseball_disk_state(st: Any) -> dict[str, Any]:
    ss = st.session_state
    state: dict[str, Any] = {}
    for key in _GLOBAL_KEYS:
        if key in ss:
            val = ss[key]
            try:
                state[key] = copy.deepcopy(val)
            except Exception:
                state[key] = val
    store = ss.get("page_filter_state")
    if isinstance(store, dict) and store:
        state["page_filter_state"] = copy.deepcopy(store)
    return state


def apply_baseball_disk_state(st: Any, state: dict[str, Any]) -> None:
    for key, val in state.items():
        if key == "page_filter_state" and isinstance(val, dict):
            st.session_state["page_filter_state"] = copy.deepcopy(val)
        else:
            try:
                st.session_state[key] = copy.deepcopy(val)
            except Exception:
                st.session_state[key] = val
    st.session_state.setdefault("page_filter_state", {})
    active = st.session_state.get("active_page")
    if active:
        st.session_state["main_sidebar_page"] = active
        pg_state.restore_page_state(st.session_state, active, st.session_state["page_filter_state"])
        st.session_state["_page_state_last_active"] = active


def apply_baseball_session_defaults(st: Any) -> None:
    ss = st.session_state
    for key in list(ss.keys()):
        if str(key).startswith("_suite_"):
            ss.pop(key, None)
    ss.pop("page_filter_state", None)
    ss.pop("_page_state_last_active", None)
    ss["active_page"] = _DEFAULT_PAGE
    ss["main_sidebar_page"] = _DEFAULT_SIDEBAR_PAGE


def restore_baseball_disk_state_once(st: Any) -> bool:
    return restore_once(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
    )


def autosave_baseball_state(st: Any) -> None:
    autosave_if_changed(st, APP_ID, build_state=build_baseball_disk_state)


def default_reset_baseball_session(st: Any) -> None:
    """Full baseball reset: session, disk, and cloud ``full_session``."""
    apply_baseball_session_defaults(st)
    fresh = build_baseball_disk_state(st)
    finalize_suite_reset(
        st,
        APP_ID,
        fresh,
        page=_DEFAULT_PAGE,
        summary="Reset to defaults",
    )
