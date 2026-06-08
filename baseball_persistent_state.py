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
    sync_cloud_workspace_before_sidebar,
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

_INSIGHT_KEYS = (
    "_ami_pending_insight",
    "_ami_return_context",
    "_ami_dismissed_insight_ids",
)


def _clear_page_widget_keys(session: dict[str, Any], page_name: str) -> None:
    for key in pg_state._collect_keys_for_page(session, page_name):
        session.pop(key, None)


def _page_block(state: dict[str, Any], page_name: str) -> dict[str, Any]:
    pf = state.get("page_filter_state")
    if not isinstance(pf, dict):
        return {}
    block = pf.get(page_name)
    return block if isinstance(block, dict) else {}


def _historical_filter_summary(block: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "hist_year",
        "historical_year_range_filter",
        "hist_team",
        "hist_pos",
        "hist_bats",
        "historical_sort_stat_filter",
    )
    return {k: block[k] for k in keys if k in block}


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
    for key in _INSIGHT_KEYS:
        if key in ss:
            try:
                state[key] = copy.deepcopy(ss[key])
            except Exception:
                state[key] = ss[key]
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
        ss["_suite_cloud_target_page"] = active
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
    return sync_cloud_workspace_before_sidebar(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
        cloud_first=True,
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


def _load_cloud_workspace_snapshot() -> tuple[dict[str, Any], str | None]:
    try:
        from suite_cloud_state import load_cloud_full_session

        cloud_state, cloud_ts = load_cloud_full_session(APP_ID)
        if isinstance(cloud_state, dict):
            return cloud_state, cloud_ts
    except ImportError:
        pass
    return {}, None


def render_cross_device_sync_debug(st: Any) -> None:
    """Developer / ?dev=1 panel — page sync trace (primary) + player context."""
    try:
        from suite_cloud_state import FULL_SESSION_KEY, parse_persist_timestamp, probe_cloud_restore_diagnostics
        from suite_user_persistence import _applied_cloud_ts_key, state_file_path
    except ImportError:
        return

    ss = st.session_state
    diag = probe_cloud_restore_diagnostics(st, APP_ID)
    cloud_state, _cloud_ts_direct = _load_cloud_workspace_snapshot()
    if not cloud_state and diag.get("cloud_has_full_session"):
        cloud_state, _ = _load_cloud_workspace_snapshot()

    cloud_pf = cloud_state.get("page_filter_state") if isinstance(cloud_state.get("page_filter_state"), dict) else {}
    cloud_cmp = cloud_pf.get("Comparison Tool") if isinstance(cloud_pf.get("Comparison Tool"), dict) else {}
    cloud_trend = cloud_pf.get("Trend Value") if isinstance(cloud_pf.get("Trend Value"), dict) else {}
    cloud_hist = cloud_pf.get("Historical Explorer") if isinstance(cloud_pf.get("Historical Explorer"), dict) else {}

    local_pf = ss.get("page_filter_state")
    local_cmp: dict[str, Any] = {}
    local_trend: dict[str, Any] = {}
    local_pf_pages: list[str] = []
    if isinstance(local_pf, dict):
        local_pf_pages = sorted(str(k) for k in local_pf.keys())
        local_cmp = local_pf.get("Comparison Tool") or {}
        local_trend = local_pf.get("Trend Value") or {}

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

    cloud_ts = diag.get("cloud_updated_at") or ss.get("_suite_persist_debug_cloud_ts")
    applied_ts = ss.get(_applied_cloud_ts_key(APP_ID))
    cloud_epoch = parse_persist_timestamp(str(cloud_ts) if cloud_ts else None)
    disk_epoch = parse_persist_timestamp(str(disk_ts) if disk_ts else None)
    applied_epoch = parse_persist_timestamp(str(applied_ts) if applied_ts else None)
    local_epoch = max(disk_epoch, applied_epoch)

    cloud_rows = {
        "cloud_current_page": cloud_state.get("active_page") or ss.get("_suite_page_sync_cloud_page"),
        "cloud_updated_at": cloud_ts,
        "cloud_save_reason": ss.get("_suite_persist_last_save_reason"),
        "cloud_compare_players": cloud_cmp.get("compare_players"),
        "cloud_trend_players": cloud_trend.get("trend_players_multi"),
        "cloud_historical_filters": _historical_filter_summary(cloud_hist) or None,
    }
    local_rows = {
        "local_current_page": ss.get("active_page"),
        "local_updated_at": disk_ts or applied_ts,
        "local_page_filter_state": local_pf_pages or None,
        "local_compare_players": local_cmp.get("compare_players") or ss.get("compare_players"),
        "local_trend_players": local_trend.get("trend_players_multi") or ss.get("trend_players_multi"),
    }
    decision_rows = {
        "pick_source": ss.get("_suite_persist_debug_pick_source"),
        "cloud_first_enabled": ss.get("_suite_page_sync_cloud_first", True),
        "cloud_exists": ss.get("_suite_page_sync_cloud_exists", diag.get("cloud_has_full_session")),
        "local_exists": ss.get("_suite_page_sync_local_exists", bool(disk_ts)),
        "local_dirty": ss.get("_suite_page_sync_local_dirty", ss.get("_suite_persist_local_dirty::baseball")),
        "cloud_newer_than_local": ss.get(
            "_suite_page_sync_cloud_newer_than_local",
            cloud_epoch > local_epoch if cloud_ts else False,
        ),
        "restore_attempted": ss.get("_suite_page_sync_restore_attempted"),
        "restore_applied": ss.get("_suite_persist_restore_applied"),
        "restore_skipped_reason": ss.get("_suite_persist_restore_skip_reason"),
    }
    final_rows = {
        "final_page": ss.get("active_page"),
        "final_compare_players": ss.get("compare_players"),
        "final_trend_players": ss.get("trend_players_multi"),
    }
    infra_rows = {
        "cloud_enabled": diag.get("cloud_enabled"),
        "suite_user_id": (diag.get("suite_user_id") or "")[:24],
        "storage_module": diag.get("storage_module"),
        "cloud_load_error": diag.get("cloud_load_error"),
        "last_save_cloud": ss.get("_suite_persist_last_save_cloud"),
        "last_save_disk": ss.get("_suite_persist_last_save_disk"),
        "last_cloud_error": ss.get("_suite_persist_last_cloud_error"),
        "cloud_target_page": ss.get("_suite_cloud_target_page"),
        "main_sidebar_page": ss.get("main_sidebar_page"),
    }

    with st.sidebar.expander("Cross-device page sync trace", expanded=True):
        st.caption(f"Page sync first — then filters ({FULL_SESSION_KEY}).")
        st.markdown("**CLOUD**")
        for k, v in cloud_rows.items():
            if v is not None and v != "" and v != {}:
                st.text(f"{k}: {v}")
        st.markdown("**LOCAL**")
        for k, v in local_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**DECISION**")
        for k, v in decision_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**FINAL**")
        for k, v in final_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        with st.expander("Infra", expanded=False):
            for k, v in infra_rows.items():
                if v is not None and v != "":
                    st.text(f"{k}: {v}")
