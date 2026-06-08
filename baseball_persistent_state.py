"""Disk persistence for Baseball Stat App (global + per-page filter store)."""

from __future__ import annotations

import copy
from typing import Any

import page_state as pg_state
from suite_user_persistence import (
    autosave_if_changed,
    finalize_suite_reset,
    force_autosave,
    restore_once,
    sync_cloud_workspace_if_newer,
)

APP_ID = "baseball"

_DEFAULT_PAGE = "Historical Explorer"
_DEFAULT_SIDEBAR_PAGE = "Historical Explorer"

_GLOBAL_KEYS = (
    "active_page",
    "main_sidebar_page",
    "comparison_user_team",
    "draft_room_table",
    "room_your_team",
    "room_team_count",
    "room_rounds",
    "room_format",
)

_COMPARE_WIDGET_KEYS = (
    "compare_players",
    "compare_players_saved",
    "sig_player_a_clean",
    "sig_player_b_clean",
)

_TREND_WIDGET_KEYS = (
    "trend_players_multi",
    "single_trend_dashboard_player",
    "trend_plot_stat",
)


def _clear_page_widget_keys(session: dict[str, Any], page_name: str) -> None:
    for key in pg_state._collect_keys_for_page(session, page_name):
        session.pop(key, None)


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
    ss = st.session_state
    for key, val in state.items():
        if key == "page_filter_state" and isinstance(val, dict):
            ss["page_filter_state"] = copy.deepcopy(val)
        else:
            try:
                ss[key] = copy.deepcopy(val)
            except Exception:
                ss[key] = val
    ss.setdefault("page_filter_state", {})
    active = str(ss.get("active_page") or "").strip()
    if active:
        _clear_page_widget_keys(ss, active)
        ss["main_sidebar_page"] = active
        ss["_navigate_to_page"] = active
        pg_state.restore_page_state(ss, active, ss["page_filter_state"])
        ss["_page_state_last_active"] = active
    ss["_suite_cloud_workspace_applied"] = True


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


def sync_baseball_cloud_workspace(st: Any) -> bool:
    return sync_cloud_workspace_if_newer(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
    )


def autosave_baseball_state(st: Any) -> None:
    autosave_if_changed(st, APP_ID, build_state=build_baseball_disk_state)


def force_save_baseball_state(st: Any, *, reason: str = "") -> bool:
    return force_autosave(st, APP_ID, build_state=build_baseball_disk_state, reason=reason)


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


def _cloud_session_fields(diag: dict[str, Any]) -> dict[str, Any]:
    try:
        from suite_cloud_state import load_cloud_full_session

        cloud_state, cloud_ts = load_cloud_full_session(APP_ID)
    except ImportError:
        return {}
    if not isinstance(cloud_state, dict):
        return {"cloud_updated_at": diag.get("cloud_updated_at")}
    pf = cloud_state.get("page_filter_state") if isinstance(cloud_state.get("page_filter_state"), dict) else {}
    cmp_block = pf.get("Comparison Tool") if isinstance(pf.get("Comparison Tool"), dict) else {}
    trend_block = pf.get("Trend Value") if isinstance(pf.get("Trend Value"), dict) else {}
    return {
        "cloud_updated_at": diag.get("cloud_updated_at") or cloud_ts,
        "cloud_current_page": cloud_state.get("active_page"),
        "cloud_comparison_player_a": cmp_block.get("sig_player_a_clean"),
        "cloud_comparison_player_b": cmp_block.get("sig_player_b_clean"),
        "cloud_compare_players": cmp_block.get("compare_players"),
        "cloud_trend_players_multi": trend_block.get("trend_players_multi"),
    }


def render_cross_device_sync_debug(st: Any) -> None:
    """Developer / ?dev=1 panel: cloud vs local persistence trace."""
    try:
        from suite_cloud_state import FULL_SESSION_KEY, load_cloud_full_session, parse_persist_timestamp, probe_cloud_restore_diagnostics
        from suite_user_persistence import _applied_cloud_ts_key, state_file_path
    except ImportError:
        return

    ss = st.session_state
    diag = probe_cloud_restore_diagnostics(st, APP_ID)
    cloud_fields = _cloud_session_fields(diag)
    pf = ss.get("page_filter_state")
    cmp_block: dict[str, Any] = {}
    trend_block: dict[str, Any] = {}
    if isinstance(pf, dict):
        cmp_block = pf.get("Comparison Tool") or {}
        trend_block = pf.get("Trend Value") or {}

    disk_ts = None
    try:
        import json

        path = state_file_path(APP_ID)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                disk_ts = raw.get("saved_at")
    except Exception:
        disk_ts = None
    applied_ts = ss.get(_applied_cloud_ts_key(APP_ID))
    cloud_ts = cloud_fields.get("cloud_updated_at") or ss.get("_suite_persist_debug_cloud_ts")
    cloud_epoch = parse_persist_timestamp(str(cloud_ts) if cloud_ts else None)
    applied_epoch = parse_persist_timestamp(str(applied_ts) if applied_ts else None)
    disk_epoch = parse_persist_timestamp(str(disk_ts) if disk_ts else None)
    local_epoch = max(applied_epoch, disk_epoch)

    restore_attempted = bool(
        ss.get("_suite_persist_restore_applied")
        or ss.get("_suite_persist_last_restore_at")
        or ss.get(f"_suite_disk_state_restored::{APP_ID}")
    )
    restore_applied = bool(ss.get("_suite_persist_restore_applied"))
    skip_reason = ss.get("_suite_persist_restore_skip_reason")

    rows = {
        "cloud_enabled": diag.get("cloud_enabled"),
        "account_mode": diag.get("account_mode"),
        "suite_user_id": (diag.get("suite_user_id") or "")[:24],
        "storage_module": diag.get("storage_module"),
        "cloud_row_found": diag.get("cloud_row_found"),
        "cloud_has_full_session": diag.get("cloud_has_full_session"),
        "cloud_load_error": diag.get("cloud_load_error"),
        **cloud_fields,
        "cloud_last_save_reason": ss.get("_suite_persist_last_save_reason"),
        "local_current_page": ss.get("active_page"),
        "local_page_filter_state_page": ss.get("_page_state_last_active"),
        "local_comparison_player_a": cmp_block.get("sig_player_a_clean") or ss.get("sig_player_a_clean"),
        "local_comparison_player_b": cmp_block.get("sig_player_b_clean") or ss.get("sig_player_b_clean"),
        "local_compare_players": cmp_block.get("compare_players") or ss.get("compare_players"),
        "local_trend_players_multi": trend_block.get("trend_players_multi") or ss.get("trend_players_multi"),
        "local_last_applied_cloud_ts": applied_ts,
        "local_disk_ts": disk_ts,
        "cloud_newer_than_local": cloud_epoch > local_epoch if cloud_ts else False,
        "restore_attempted": restore_attempted,
        "restore_applied": restore_applied,
        "restore_skipped_reason": skip_reason,
        "pick_source": ss.get("_suite_persist_debug_pick_source"),
        "pick_reason": ss.get("_suite_persist_debug_pick_reason"),
        "final_page_after_restore": ss.get("active_page"),
        "final_player_a": ss.get("sig_player_a_clean"),
        "final_player_b": ss.get("sig_player_b_clean"),
        "local_dirty": ss.get("_suite_persist_local_dirty::baseball"),
        "last_save_at": ss.get("_suite_persist_last_save_at"),
        "last_save_cloud": ss.get("_suite_persist_last_save_cloud"),
        "last_save_disk": ss.get("_suite_persist_last_save_disk"),
        "last_cloud_error": ss.get("_suite_persist_last_cloud_error"),
        "cloud_workspace_applied_flag": ss.get("_suite_cloud_workspace_applied"),
    }

    with st.sidebar.expander("Cross-device sync trace", expanded=True):
        st.caption(f"Phone ↔ Dell workspace persistence ({FULL_SESSION_KEY} cloud blob).")
        for k, v in rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
