"""Disk persistence for Baseball Stat App (global + per-page filter store)."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import page_state as pg_state
from suite_user_persistence import (
    DATA_DIR,
    autosave_if_changed,
    clear_workspace_autosave_block,
    finalize_suite_reset,
    force_autosave,
    sync_workspace_protocol,
)

APP_ID = "baseball"
WORKSPACE_SCHEMA_VERSION = 1

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

_DEVICE_ID_FILE = DATA_DIR / f"{APP_ID}_device_id.txt"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get_device_id(st: Any) -> str:
    ss = st.session_state
    key = "_suite_device_id"
    existing = ss.get(key)
    if existing:
        return str(existing)
    try:
        if _DEVICE_ID_FILE.is_file():
            did = _DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if did:
                ss[key] = did
                return did
    except OSError:
        pass
    did = uuid.uuid4().hex[:12]
    ss[key] = did
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DEVICE_ID_FILE.write_text(did, encoding="utf-8")
    except OSError:
        pass
    return did


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


def _build_workspace_envelope(st: Any, state: dict[str, Any], *, save_reason: str) -> dict[str, Any]:
    cmp_block = _page_block(state, "Comparison Tool")
    trend_block = _page_block(state, "Trend Value")
    hist_block = _page_block(state, "Historical Explorer")
    draft_block = _page_block(state, "Draft Room")
    return {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "updated_at": _utc_now_iso(),
        "device_id": _get_device_id(st),
        "save_reason": save_reason or "autosave",
        "page": state.get("active_page"),
        "comparison_players": cmp_block.get("compare_players"),
        "trend_players": trend_block.get("trend_players_multi"),
        "historical_filters": _historical_filter_summary(hist_block) or None,
        "draft_state": {
            k: draft_block[k]
            for k in ("room_your_team", "room_team_count", "room_rounds", "room_format")
            if k in draft_block
        }
        or None,
    }


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
    save_reason = str(ss.pop("_suite_pending_save_reason", None) or "autosave")
    state["baseball_workspace_state"] = _build_workspace_envelope(st, state, save_reason=save_reason)
    return state


def apply_baseball_disk_state(st: Any, state: dict[str, Any]) -> None:
    """Apply one authoritative workspace blob atomically (page + all page_filter_state)."""
    ss = st.session_state
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        ss["page_filter_state"] = copy.deepcopy(pf)
    else:
        ss.setdefault("page_filter_state", {})

    for key in _GLOBAL_KEYS + _INSIGHT_KEYS:
        if key not in state:
            continue
        val = state[key]
        if key == "page_filter_state" and isinstance(val, dict):
            continue
        try:
            ss[key] = copy.deepcopy(val)
        except Exception:
            ss[key] = val

    active = str(ss.get("active_page") or state.get("active_page") or "").strip()
    if active:
        _clear_page_widget_keys(ss, active)
        ss["active_page"] = active
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


def prepare_baseball_workspace(st: Any) -> bool:
    """Single authoritative cloud/disk workspace sync before sidebar widgets."""
    return sync_workspace_protocol(
        st,
        APP_ID,
        apply_state=lambda st_obj, s: apply_baseball_disk_state(st_obj, s),
        cloud_first=True,
    )


def restore_baseball_disk_state_once(st: Any) -> bool:
    """Deprecated — use prepare_baseball_workspace() before sidebar instead."""
    return False


def sync_baseball_cloud_workspace(st: Any) -> bool:
    """Backward-compatible alias for prepare_baseball_workspace."""
    return prepare_baseball_workspace(st)


def autosave_baseball_state(st: Any) -> None:
    autosave_if_changed(st, APP_ID, build_state=build_baseball_disk_state)


def force_save_baseball_state(st: Any, *, reason: str = "") -> bool:
    if reason:
        st.session_state["_suite_pending_save_reason"] = reason
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


def _workspace_meta(state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("baseball_workspace_state")
    return meta if isinstance(meta, dict) else {}


def render_cross_device_sync_debug(st: Any) -> None:
    """Developer / ?dev=1 panel — authoritative workspace sync trace."""
    try:
        from suite_cloud_state import FULL_SESSION_KEY, parse_persist_timestamp, probe_cloud_restore_diagnostics
        from suite_user_persistence import _applied_cloud_ts_key, _local_dirty_key, state_file_path
    except ImportError:
        return

    ss = st.session_state
    diag = probe_cloud_restore_diagnostics(st, APP_ID)
    cloud_state, _cloud_ts_direct = _load_cloud_workspace_snapshot()
    if not cloud_state and diag.get("cloud_has_full_session"):
        cloud_state, _ = _load_cloud_workspace_snapshot()

    cloud_meta = _workspace_meta(cloud_state)
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
    disk_state: dict[str, Any] = {}
    try:
        import json

        path = state_file_path(APP_ID)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                disk_ts = raw.get("saved_at")
                inner = raw.get("state")
                if isinstance(inner, dict):
                    disk_state = inner
    except Exception:
        disk_ts = None

    local_meta = _workspace_meta(disk_state)
    cloud_ts = diag.get("cloud_updated_at") or ss.get("_suite_persist_debug_cloud_ts")
    applied_ts = ss.get(_applied_cloud_ts_key(APP_ID))
    cloud_epoch = parse_persist_timestamp(str(cloud_ts) if cloud_ts else None)
    disk_epoch = parse_persist_timestamp(str(disk_ts) if disk_ts else None)
    applied_epoch = parse_persist_timestamp(str(applied_ts) if applied_ts else None)
    local_epoch = max(disk_epoch, applied_epoch)

    cloud_rows = {
        "updated_at": cloud_ts or cloud_meta.get("updated_at"),
        "page": cloud_meta.get("page") or cloud_state.get("active_page") or ss.get("_suite_page_sync_cloud_page"),
        "comparison_players": cloud_meta.get("comparison_players") or cloud_cmp.get("compare_players"),
        "trend_players": cloud_meta.get("trend_players") or cloud_trend.get("trend_players_multi"),
        "save_reason": cloud_meta.get("save_reason") or ss.get("_suite_persist_last_save_reason"),
        "device_id": cloud_meta.get("device_id"),
        "schema_version": cloud_meta.get("schema_version"),
        "historical_filters": cloud_meta.get("historical_filters") or _historical_filter_summary(cloud_hist) or None,
    }
    local_rows = {
        "updated_at": disk_ts or applied_ts or local_meta.get("updated_at"),
        "page": ss.get("active_page"),
        "comparison_players": local_cmp.get("compare_players") or ss.get("compare_players"),
        "trend_players": local_trend.get("trend_players_multi") or ss.get("trend_players_multi"),
        "dirty_flag": ss.get(_local_dirty_key(APP_ID)),
        "page_filter_pages": local_pf_pages or None,
        "device_id": local_meta.get("device_id") or ss.get("_suite_device_id"),
    }
    decision_rows = {
        "cloud_loaded": ss.get("_suite_workspace_cloud_loaded"),
        "local_loaded": ss.get("_suite_workspace_local_loaded"),
        "winner": ss.get("_suite_workspace_winner") or ss.get("_suite_persist_debug_pick_source"),
        "reason": ss.get("_suite_workspace_winner_reason") or ss.get("_suite_persist_debug_pick_reason"),
        "cloud_first_enabled": ss.get("_suite_page_sync_cloud_first", True),
        "cloud_newer_than_local": ss.get(
            "_suite_page_sync_cloud_newer_than_local",
            cloud_epoch > local_epoch if cloud_ts else False,
        ),
        "restore_skipped_reason": ss.get("_suite_persist_restore_skip_reason"),
        "cloud_workspace_restored": ss.get("_cloud_workspace_restored"),
    }
    apply_rows = {
        "applied_page": ss.get("_suite_workspace_applied_page"),
        "applied_comparison_players": ss.get("_suite_workspace_applied_comparison_players"),
        "applied_trend_players": ss.get("_suite_workspace_applied_trend_players"),
        "applied_success": ss.get("_suite_workspace_apply_success"),
    }
    autosave_rows = {
        "autosave_blocked_after_restore": ss.get("_suite_autosave_blocked_after_restore"),
        "autosave_reason": ss.get("_suite_autosave_reason") or ss.get("_suite_persist_last_save_reason"),
        "autosave_wrote_cloud": ss.get("_suite_autosave_wrote_cloud"),
        "autosave_payload_page": ss.get("_suite_autosave_payload_page"),
        "autosave_payload_comparison_players": ss.get("_suite_autosave_payload_comparison_players"),
    }
    final_rows = {
        "final_page": ss.get("active_page"),
        "final_comparison_players": ss.get("compare_players"),
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

    with st.sidebar.expander("Workspace sync trace", expanded=True):
        st.caption(f"Authoritative blob: baseball_workspace_state ({FULL_SESSION_KEY}).")
        st.markdown("**Cloud workspace**")
        for k, v in cloud_rows.items():
            if v is not None and v != "" and v != {}:
                st.text(f"{k}: {v}")
        st.markdown("**Local workspace**")
        for k, v in local_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**Startup decision**")
        for k, v in decision_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Apply**")
        for k, v in apply_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Autosave**")
        for k, v in autosave_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Final**")
        for k, v in final_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        with st.expander("Infra", expanded=False):
            for k, v in infra_rows.items():
                if v is not None and v != "":
                    st.text(f"{k}: {v}")


__all__ = [
    "APP_ID",
    "WORKSPACE_SCHEMA_VERSION",
    "apply_baseball_disk_state",
    "apply_baseball_session_defaults",
    "autosave_baseball_state",
    "build_baseball_disk_state",
    "clear_workspace_autosave_block",
    "default_reset_baseball_session",
    "force_save_baseball_state",
    "prepare_baseball_workspace",
    "render_cross_device_sync_debug",
    "restore_baseball_disk_state_once",
    "sync_baseball_cloud_workspace",
]
