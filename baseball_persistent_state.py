"""Disk persistence for Baseball Stat App (global + per-page filter store)."""

from __future__ import annotations

import copy
from typing import Any

import page_state as pg_state
from suite_user_persistence import (
    autosave_if_changed,
    reset_user_state,
    restore_once,
)

APP_ID = "baseball"

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


def restore_baseball_disk_state_once(st: Any) -> bool:
    return restore_once(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
    )


def autosave_baseball_state(st: Any) -> None:
    autosave_if_changed(st, APP_ID, build_state=build_baseball_disk_state)


def default_reset_baseball_session(st: Any) -> None:
    reset_user_state(APP_ID)
    for key in list(st.session_state.keys()):
        if str(key).startswith("_suite_"):
            st.session_state.pop(key, None)
    st.session_state.pop("page_filter_state", None)
    st.session_state.pop("_page_state_last_active", None)
    st.session_state["active_page"] = "Historical Explorer"
