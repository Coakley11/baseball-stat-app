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
    active = ss.get("active_page")
    if active:
        try:
            store = ss.setdefault("page_filter_state", {})
            if not isinstance(store, dict):
                store = {}
                ss["page_filter_state"] = store
            pg_state.save_page_state(ss, str(active), store)
        except Exception:
            pass
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


def render_cross_device_sync_debug(st: Any) -> None:
    """Developer / ?dev=1 panel: cloud vs local persistence trace."""
    try:
        from suite_cloud_state import FULL_SESSION_KEY, probe_cloud_restore_diagnostics
    except ImportError:
        return

    ss = st.session_state
    diag = probe_cloud_restore_diagnostics(st, APP_ID)
    pf = ss.get("page_filter_state")
    cmp_block = {}
    trend_block = {}
    if isinstance(pf, dict):
        cmp_block = pf.get("Comparison Tool") or {}
        trend_block = pf.get("Trend Value") or {}

    rows = {
        "cloud_enabled": diag.get("cloud_enabled"),
        "account_mode": diag.get("account_mode"),
        "suite_user_id": (diag.get("suite_user_id") or "")[:24],
        "storage_module": diag.get("storage_module"),
        "cloud_row_found": diag.get("cloud_row_found"),
        "cloud_has_full_session": diag.get("cloud_has_full_session"),
        "cloud_updated_at": diag.get("cloud_updated_at"),
        "cloud_load_error": diag.get("cloud_load_error"),
        "restore_skip_reason": ss.get("_suite_persist_restore_skip_reason"),
        "pick_source": ss.get("_suite_persist_debug_pick_source"),
        "pick_reason": ss.get("_suite_persist_debug_pick_reason"),
        "cloud_ts_debug": ss.get("_suite_persist_debug_cloud_ts"),
        "disk_ts_debug": ss.get("_suite_persist_debug_disk_ts"),
        "last_save_at": ss.get("_suite_persist_last_save_at"),
        "last_save_cloud": ss.get("_suite_persist_last_save_cloud"),
        "last_save_disk": ss.get("_suite_persist_last_save_disk"),
        "last_cloud_error": ss.get("_suite_persist_last_cloud_error"),
        "local_dirty": ss.get("_suite_persist_local_dirty::baseball"),
        "active_page": ss.get("active_page"),
        "compare_player_a": cmp_block.get("sig_player_a_clean") or ss.get("sig_player_a_clean"),
        "compare_player_b": cmp_block.get("sig_player_b_clean") or ss.get("sig_player_b_clean"),
        "compare_players_saved": cmp_block.get("compare_players") or ss.get("compare_players"),
        "trend_players_multi": trend_block.get("trend_players_multi") or ss.get("trend_players_multi"),
        "trend_plot_stat": trend_block.get("trend_plot_stat") or ss.get("trend_plot_stat"),
    }

    with st.sidebar.expander("Cross-device sync trace", expanded=True):
        st.caption("Phone ↔ Dell workspace persistence (full_session cloud blob).")
        for k, v in rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
