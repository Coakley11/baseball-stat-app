"""
Per-app persistent user state for Daniel AI Streamlit apps.

Local JSON under ``data/{app_id}_user_state.json`` plus optional Supabase
``metrics.full_session`` for cross-device restore on direct app open.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

STATE_VERSION = 1
DATA_DIR = Path(__file__).resolve().parent / "data"

APP_IDS = frozenset(
    {"music", "investment", "baseball", "basketball", "nba", "future_lens"}
)

_LEGACY_COMBINED_FILE = DATA_DIR / "app_state.json"

_SESSION_RESTORED_PREFIX = "_suite_disk_state_restored::"
_SESSION_BANNER_KEY = "_suite_persist_banner"
_SESSION_SAVED_FLASH_KEY = "_suite_persist_saved_flash"
SESSION_USER_OWNED_PAGE_KEY = "_suite_user_owned_page"
_SESSION_INVALID_WARN_KEY = "_suite_persist_invalid_warn"
_SESSION_CLOUD_BANNER_KEY = "_suite_persist_cloud_banner"
_LOCAL_DIRTY_PREFIX = "_suite_persist_local_dirty::"
_APPLIED_CLOUD_TS_PREFIX = "_suite_applied_cloud_ts::"
_RESTORED_FP_PREFIX = "_suite_restored_state_fp::"
_AUTOSAVE_BLOCK_PREFIX = "_suite_autosave_blocked::"
_WORKSPACE_SYNCED_PREFIX = "_suite_workspace_synced::"
_CLOUD_WORKSPACE_RESTORED = "_cloud_workspace_restored"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_file_path(app_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(app_id or "app"))
    return DATA_DIR / f"{safe}_user_state.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def _migrate_legacy_combined(app_id: str) -> dict[str, Any] | None:
    combined = _read_json(_LEGACY_COMBINED_FILE)
    if not combined:
        return None
    block = combined.get(app_id)
    if not isinstance(block, dict):
        return None
    out = {k: v for k, v in block.items() if k != "updated_at"}
    out["version"] = STATE_VERSION
    out["saved_at"] = block.get("updated_at") or _utc_now_iso()
    _write_json(state_file_path(app_id), out)
    return out


def _load_raw(app_id: str) -> tuple[dict[str, Any], str | None, str | None]:
    """Return ``(state_dict, warning, saved_at_iso)``."""
    path = state_file_path(app_id)
    raw = _read_json(path)
    if raw is None:
        raw = _migrate_legacy_combined(app_id)
    if raw is None:
        return {}, None, None

    version = raw.get("version", STATE_VERSION)
    if version != STATE_VERSION:
        return {}, f"Saved settings used an older format (v{version}); using defaults.", None

    state = raw.get("state")
    if not isinstance(state, dict):
        return {}, "Saved settings were invalid; using defaults.", None

    saved_at = str(raw.get("saved_at") or "") or None
    try:
        return copy.deepcopy(state), None, saved_at
    except Exception:
        return {}, "Could not read saved settings; using defaults.", None


def load_user_state(app_id: str) -> tuple[dict[str, Any], str | None]:
    state, warning, _ = _load_raw(app_id)
    return state, warning


def save_user_state(app_id: str, state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    payload = {
        "version": STATE_VERSION,
        "app": app_id,
        "saved_at": _utc_now_iso(),
        "state": state,
    }
    return _write_json(state_file_path(app_id), payload)


def reset_user_state(app_id: str) -> bool:
    path = state_file_path(app_id)
    try:
        if path.is_file():
            path.unlink()
        return True
    except OSError:
        return False


def _local_dirty_key(app_id: str) -> str:
    return f"{_LOCAL_DIRTY_PREFIX}{app_id}"


def _applied_cloud_ts_key(app_id: str) -> str:
    return f"{_APPLIED_CLOUD_TS_PREFIX}{app_id}"


def _restored_fp_key(app_id: str) -> str:
    return f"{_RESTORED_FP_PREFIX}{app_id}"


def _autosave_block_key(app_id: str) -> str:
    return f"{_AUTOSAVE_BLOCK_PREFIX}{app_id}"


def _workspace_synced_key(app_id: str) -> str:
    return f"{_WORKSPACE_SYNCED_PREFIX}{app_id}"


def _fingerprint_state(state: dict[str, Any]) -> str:
    import hashlib
    import json

    blob = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _lock_fingerprint_after_restore(st: Any, app_id: str, state: dict[str, Any]) -> None:
    """Prevent post-restore autosave from treating widget drift as local_dirty."""
    fp = _fingerprint_state(state)
    st.session_state[f"_suite_autosave_fp::{app_id}"] = fp
    st.session_state[_restored_fp_key(app_id)] = fp
    st.session_state[_local_dirty_key(app_id)] = False


def clear_workspace_autosave_block(st: Any, app_id: str) -> None:
    """Call at end of script run to allow autosave on the next rerun."""
    st.session_state.pop(_autosave_block_key(app_id), None)
    st.session_state.pop("_cloud_workspace_restored_this_run", None)
    st.session_state.pop("_suite_user_nav_sync_skipped", None)


def _extract_page_players(state: dict[str, Any], page: str) -> Any:
    pf = state.get("page_filter_state")
    if not isinstance(pf, dict):
        return None
    block = pf.get(page)
    if not isinstance(block, dict):
        return None
    if page == "Comparison Tool":
        return block.get("compare_players")
    if page == "Trend Value":
        return block.get("trend_players_multi")
    return None


def _workspace_comparison_players(state: dict[str, Any]) -> list[str]:
    cs = state.get("comparison_state")
    if isinstance(cs, dict):
        players = cs.get("players")
        if isinstance(players, list):
            return [str(p) for p in players if p][:3]
    meta = state.get("baseball_workspace_state")
    if isinstance(meta, dict):
        cp = meta.get("comparison_players")
        if isinstance(cp, list) and cp:
            return [str(p) for p in cp if p][:3]
    pf_players = _extract_page_players(state, "Comparison Tool")
    if isinstance(pf_players, list):
        return [str(p) for p in pf_players if p][:3]
    return []


def _mark_workspace_sync_skipped(st: Any, app_id: str, reason: str) -> None:
    """Block cloud autosave when startup workspace sync did not apply."""
    st.session_state["_suite_workspace_sync_skipped_no_apply"] = True
    st.session_state[_autosave_block_key(app_id)] = True
    st.session_state["_suite_autosave_block_reason"] = reason


def _mark_user_nav_sync_skipped(st: Any, reason: str) -> None:
    """User navigation intentionally skipped restore — must not block page_change cloud save."""
    st.session_state["_suite_persist_restore_skip_reason"] = reason
    st.session_state["_suite_user_nav_sync_skipped"] = True


def _comparison_user_explicitly_cleared(st: Any) -> bool:
    ss = st.session_state
    if not ss.get("comparison_state_dirty"):
        return False
    cs = ss.get("comparison_state")
    if isinstance(cs, dict) and isinstance(cs.get("players"), list):
        return len(cs.get("players") or []) == 0
    cp = ss.get("compare_players")
    return isinstance(cp, list) and len(cp) == 0


_FORCE_SAVE_CLOUD_REASONS = frozenset({
    "comparison_edit",
    "trend_edit",
    "career_edit",
    "draft_edit",
    "page_change",
    "insight_persist",
    "insight_hydrate",
    "applied_math_send",
})


def _cloud_autosave_blocked_reason(
    st: Any,
    app_id: str,
    state: dict[str, Any],
    *,
    save_reason: str = "",
) -> str | None:
    if save_reason in _FORCE_SAVE_CLOUD_REASONS:
        if save_reason == "page_change":
            return None
        if st.session_state.get("_suite_workspace_sync_skipped_no_apply"):
            return None
    elif st.session_state.get("_suite_workspace_sync_skipped_no_apply"):
        return "workspace_sync_not_applied"
    if app_id != "baseball":
        return None
    local_players = _workspace_comparison_players(state)
    if local_players:
        return None
    try:
        from suite_cloud_state import load_cloud_full_session

        cloud_state, _ = load_cloud_full_session(app_id)
        if not isinstance(cloud_state, dict) or not cloud_state:
            return None
        cloud_players = _workspace_comparison_players(cloud_state)
        if not cloud_players:
            return None
        if _comparison_user_explicitly_cleared(st):
            return None
        return "blank_comparison_would_erase_cloud"
    except Exception:
        return None


def _preserve_cloud_widget_fields_on_page_change(
    app_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Page-only save: keep cloud comparison/trend widgets when leaving those pages."""
    if app_id != "baseball":
        return state
    try:
        from suite_cloud_state import load_cloud_full_session
    except ImportError:
        return state
    cloud_state, _ = load_cloud_full_session(app_id)
    if not isinstance(cloud_state, dict) or not cloud_state:
        return state
    out = copy.deepcopy(state)
    if not _workspace_comparison_players(out) and _workspace_comparison_players(cloud_state):
        cs = cloud_state.get("comparison_state")
        if isinstance(cs, dict):
            out["comparison_state"] = copy.deepcopy(cs)
        cloud_pf = cloud_state.get("page_filter_state")
        if isinstance(cloud_pf, dict):
            cmp_block = cloud_pf.get("Comparison Tool")
            if isinstance(cmp_block, dict):
                pf = out.setdefault("page_filter_state", {})
                if not isinstance(pf, dict):
                    pf = {}
                    out["page_filter_state"] = pf
                pf["Comparison Tool"] = copy.deepcopy(cmp_block)
        meta = cloud_state.get("baseball_workspace_state")
        if isinstance(meta, dict) and meta.get("comparison_players"):
            ws = out.setdefault("baseball_workspace_state", {})
            if isinstance(ws, dict):
                ws["comparison_players"] = copy.deepcopy(meta["comparison_players"])
    cloud_trend = _extract_page_players(cloud_state, "Trend Value")
    local_trend = _extract_page_players(out, "Trend Value")
    if cloud_trend and not local_trend:
        ts = cloud_state.get("trend_state")
        if isinstance(ts, dict):
            out["trend_state"] = copy.deepcopy(ts)
        cloud_pf = cloud_state.get("page_filter_state")
        if isinstance(cloud_pf, dict):
            trend_block = cloud_pf.get("Trend Value")
            if isinstance(trend_block, dict):
                pf = out.setdefault("page_filter_state", {})
                if not isinstance(pf, dict):
                    pf = {}
                    out["page_filter_state"] = pf
                pf["Trend Value"] = copy.deepcopy(trend_block)
    return out


def claim_user_page_ownership(st: Any, app_id: str, page: str) -> None:
    """Record explicit sidebar page selection; blocks stale cloud page overwrite."""
    selected = str(page or "").strip()
    if not selected:
        return
    ss = st.session_state
    ss[SESSION_USER_OWNED_PAGE_KEY] = selected
    ss["_suite_page_user_nav"] = True
    ss["requested_page"] = selected
    ss["active_page_source"] = "user_sidebar"
    try:
        from applied_math_return_insight import reconcile_stale_page_navigation

        reconcile_stale_page_navigation(st, app_id)
    except Exception:
        pass


def _user_page_blocks_cloud_overwrite(st: Any, cloud_page: str) -> bool:
    owned = str(st.session_state.get(SESSION_USER_OWNED_PAGE_KEY) or "").strip()
    current = _session_workspace_page(st)
    cloud = str(cloud_page or "").strip()
    if not owned or not current:
        return False
    return bool(owned == current and cloud and cloud != owned)


def _release_user_page_ownership_after_save(st: Any, saved_page: str) -> None:
    owned = str(st.session_state.get(SESSION_USER_OWNED_PAGE_KEY) or "").strip()
    saved = str(saved_page or "").strip()
    if owned and saved and owned == saved:
        st.session_state.pop(SESSION_USER_OWNED_PAGE_KEY, None)
        st.session_state["_suite_last_persisted_page"] = saved


def record_page_navigation_startup_diagnostics(st: Any, app_id: str) -> None:
    """?dev=1 trace for page ownership at startup (before sidebar interaction)."""
    ss = st.session_state
    has_resume = None
    consumed = None
    try:
        from suite_cloud_state import ami_return_resume_consumed, has_resume_query_params

        has_resume = has_resume_query_params(st, app_id)
        consumed = ami_return_resume_consumed(st, app_id)
    except Exception:
        pass
    try:
        from applied_math_return_insight import ami_resume_consumed

        consumed = ami_resume_consumed(st, app_id) if consumed is None else consumed
    except Exception:
        pass
    ss["_page_nav_startup_recorded"] = True
    ss["sidebar_selected_page"] = ss.get("main_sidebar_page")
    ss["active_page_source"] = ss.get("active_page_source")
    ss["_suite_page_user_nav"] = bool(ss.get("_suite_page_user_nav"))
    ss["_suite_cloud_target_page"] = ss.get("_suite_cloud_target_page")
    ss["_navigate_to_page"] = ss.get("_navigate_to_page")
    ss["_skip_page_restore_for"] = ss.get("_skip_page_restore_for")
    ss["ami_resume_consumed"] = consumed
    ss["has_resume_query_params"] = has_resume
    ss["final_page"] = ss.get("active_page")
    ss["_suite_user_owned_page"] = ss.get(SESSION_USER_OWNED_PAGE_KEY)


def record_sidebar_nav_diagnostics(
    st: Any,
    *,
    phase: str,
    rerun_source: str = "",
    requested_page: str = "",
    active_page_before: str | None = None,
    active_page_after: str | None = None,
    page_overwrite_source: str = "",
    page_change_detected: bool | None = None,
    page_change_force_save: bool | None = None,
) -> None:
    """?dev=1 trace for manual sidebar navigation vs cloud restore."""
    ss = st.session_state
    cloud_page = ss.get("_suite_cloud_fetch_active_page") or ss.get("_suite_page_sync_cloud_page")
    if cloud_page is None:
        try:
            from suite_cloud_state import load_cloud_full_session

            cloud_state, _ = load_cloud_full_session(str(ss.get("_suite_persist_app_id") or "baseball"))
            if isinstance(cloud_state, dict):
                cloud_page = cloud_state.get("active_page")
        except Exception:
            cloud_page = None
    ss["_suite_sidebar_nav_phase"] = phase
    if rerun_source:
        ss["_suite_sidebar_nav_rerun_source"] = rerun_source
    if requested_page:
        ss["requested_page"] = requested_page
    ss["sidebar_selected_page"] = ss.get("main_sidebar_page")
    ss["active_page_before"] = active_page_before if active_page_before is not None else ss.get("_suite_nav_active_page_before")
    ss["active_page_after"] = active_page_after if active_page_after is not None else ss.get("active_page")
    ss["final_page_after_sidebar_click"] = ss.get("active_page")
    ss["_suite_sidebar_nav_main_sidebar_page"] = ss.get("main_sidebar_page")
    ss["_suite_sidebar_nav_active_page"] = ss.get("active_page")
    ss["_suite_sidebar_nav_user_nav"] = bool(ss.get("_suite_page_user_nav"))
    ss["_suite_sidebar_nav_cloud_target"] = ss.get("_suite_cloud_target_page")
    ss["_suite_sidebar_nav_last_persisted_page"] = ss.get("_suite_last_persisted_page")
    ss["_navigate_to_page"] = ss.get("_navigate_to_page")
    ss["_skip_page_restore_for"] = ss.get("_skip_page_restore_for")
    ss["active_page_source"] = ss.get("active_page_source")
    ss["_suite_user_owned_page"] = ss.get(SESSION_USER_OWNED_PAGE_KEY)
    ss["_suite_sidebar_nav_cloud_restored_this_run"] = bool(
        ss.get("_cloud_workspace_restored_this_run")
    )
    ss["_suite_page_user_nav_flag"] = bool(ss.get("_suite_page_user_nav"))
    ss["cloud_active_page"] = cloud_page
    ss["final_page"] = ss.get("active_page")
    if page_overwrite_source:
        ss["page_overwrite_source"] = page_overwrite_source
    if page_change_detected is not None:
        ss["page_change_detected"] = page_change_detected
    if page_change_force_save is not None:
        ss["page_change_force_save"] = page_change_force_save


def _session_comparison_players(st: Any) -> list[str]:
    ss = st.session_state
    cs = ss.get("comparison_state")
    if isinstance(cs, dict):
        players = cs.get("players")
        if isinstance(players, list):
            return [str(p) for p in players if p][:3]
    cp = ss.get("compare_players")
    if isinstance(cp, list):
        return [str(p) for p in cp if p][:3]
    return []


def _record_workspace_sync_trace(
    st: Any,
    app_id: str,
    *,
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
    winner: str,
    reason: str,
    applied: bool,
    applied_state: dict[str, Any] | None = None,
) -> None:
    meta = {}
    if isinstance(cloud_state, dict):
        meta = cloud_state.get("baseball_workspace_state") or {}
        if not isinstance(meta, dict):
            meta = {}
    st.session_state["_suite_workspace_cloud_loaded"] = bool(cloud_state)
    st.session_state["_suite_workspace_local_loaded"] = bool(disk_state)
    st.session_state["_suite_workspace_winner"] = winner
    st.session_state["_suite_workspace_winner_reason"] = reason
    st.session_state["_suite_workspace_apply_success"] = applied
    if applied and isinstance(applied_state, dict):
        page = str(applied_state.get("active_page") or "")
        st.session_state["_suite_workspace_applied_page"] = page
        st.session_state["_suite_workspace_applied_comparison_players"] = _extract_page_players(
            applied_state, "Comparison Tool"
        )
        st.session_state["_suite_workspace_applied_trend_players"] = _extract_page_players(
            applied_state, "Trend Value"
        )
    st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
    st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
    st.session_state["_suite_persist_debug_pick_source"] = winner
    st.session_state["_suite_persist_debug_pick_reason"] = reason


def _record_startup_restore_diagnostics(
    st: Any,
    app_id: str,
    *,
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
    picked_source: str,
    picked_reason: str,
    should_apply: bool,
    apply_reason: str,
    skip_reason: str | None = None,
    applied: bool = False,
) -> None:
    try:
        from suite_cloud_state import probe_cloud_restore_diagnostics
    except ImportError:
        probe_cloud_restore_diagnostics = None  # type: ignore[assignment]

    diag = probe_cloud_restore_diagnostics(st, app_id) if probe_cloud_restore_diagnostics else {}
    cloud_players = _workspace_comparison_players(cloud_state) if cloud_state else []
    st.session_state["_suite_cloud_fetch_attempted"] = True
    st.session_state["_suite_cloud_fetch_success"] = bool(cloud_state) or bool(
        diag.get("cloud_has_full_session")
    )
    st.session_state["_suite_cloud_fetch_user_id"] = (diag.get("suite_user_id") or "")[:32] or None
    st.session_state["_suite_cloud_fetch_updated_at"] = cloud_ts or diag.get("cloud_updated_at")
    st.session_state["_suite_cloud_fetch_active_page"] = (
        cloud_state.get("active_page")
        if isinstance(cloud_state, dict)
        else None
    )
    st.session_state["_suite_cloud_fetch_comparison_players"] = cloud_players or None
    st.session_state["_suite_restore_decision"] = "applied" if applied else "skipped"
    st.session_state["_suite_restore_skip_reason"] = skip_reason
    st.session_state["_suite_restore_should_apply"] = should_apply
    st.session_state["_suite_restore_apply_reason"] = apply_reason
    st.session_state["_suite_restore_pick_source"] = picked_source
    st.session_state["_suite_restore_pick_reason"] = picked_reason
    st.session_state["_suite_disk_restore_after_cloud"] = picked_source == "disk" and bool(cloud_state)
    st.session_state["_suite_post_restore_active_page"] = st.session_state.get("active_page")
    st.session_state["_suite_post_restore_comparison_players"] = _session_comparison_players(st) or None


def sync_workspace_protocol(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
    cloud_first: bool = True,
) -> bool:
    """
    Authoritative workspace sync before sidebar widgets.

    On first sync per browser session, apply the picked cloud/disk blob atomically,
    block autosave for this rerun, and lock the restore fingerprint so stale local
    state is not written back to cloud on startup.
    """
    st.session_state["_suite_persist_app_id"] = app_id
    st.session_state["_suite_workspace_sync_attempted"] = True
    st.session_state.pop("_suite_persist_restore_skip_reason", None)
    record_page_navigation_startup_diagnostics(st, app_id)
    try:
        from applied_math_return_insight import reconcile_stale_page_navigation

        reconcile_stale_page_navigation(st, app_id)
    except Exception:
        pass

    try:
        from suite_cloud_state import (
            has_resume_query_params,
            load_cloud_full_session,
            parse_persist_timestamp,
            pick_restore_session,
        )
    except ImportError:
        st.session_state["_suite_persist_restore_skip_reason"] = "cloud module missing"
        _record_workspace_sync_trace(
            st, app_id, cloud_state={}, cloud_ts=None, disk_state={}, disk_ts=None,
            winner="none", reason="cloud module missing", applied=False,
        )
        return False

    if has_resume_query_params(st, app_id):
        st.session_state["_suite_resume_insight_hydration_only"] = True

    dirty_key = _local_dirty_key(app_id)
    st.session_state.pop("_suite_workspace_sync_skipped_no_apply", None)

    cloud_state, cloud_ts = load_cloud_full_session(app_id)
    disk_state, disk_warn, disk_ts = _load_raw(app_id)
    if disk_warn:
        st.session_state[_SESSION_INVALID_WARN_KEY] = disk_warn

    cloud_epoch = parse_persist_timestamp(cloud_ts)
    disk_epoch = parse_persist_timestamp(disk_ts)
    cloud_newer_than_disk = bool(cloud_ts and cloud_epoch > disk_epoch)

    if st.session_state.get(dirty_key) and not cloud_newer_than_disk:
        reason = "local unsaved edits — workspace sync skipped"
        st.session_state["_suite_persist_restore_skip_reason"] = reason
        _mark_workspace_sync_skipped(st, app_id, reason)
        _record_startup_restore_diagnostics(
            st, app_id,
            cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts,
            picked_source="none", picked_reason=reason,
            should_apply=False, apply_reason="", skip_reason=reason,
        )
        return False

    if st.session_state.get("_suite_page_user_nav"):
        reason = "user page navigation — workspace sync skipped"
        _mark_user_nav_sync_skipped(st, reason)
        _record_startup_restore_diagnostics(
            st, app_id,
            cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts,
            picked_source="none", picked_reason=reason,
            should_apply=False, apply_reason="", skip_reason=reason,
        )
        return False

    if not cloud_state and not disk_state:
        reason = "no workspace blob"
        _record_workspace_sync_trace(
            st, app_id, cloud_state={}, cloud_ts=cloud_ts, disk_state={}, disk_ts=disk_ts,
            winner="none", reason="empty", applied=False,
        )
        st.session_state["_suite_persist_restore_skip_reason"] = reason
        _mark_workspace_sync_skipped(st, app_id, reason)
        _record_startup_restore_diagnostics(
            st, app_id,
            cloud_state={}, cloud_ts=cloud_ts, disk_state={}, disk_ts=disk_ts,
            picked_source="none", picked_reason=reason,
            should_apply=False, apply_reason="", skip_reason=reason,
        )
        return False

    picked = pick_restore_session(
        cloud_state,
        cloud_ts,
        disk_state,
        disk_ts,
        local_dirty=False,
        cloud_first=cloud_first,
    )
    if not picked.state:
        _record_workspace_sync_trace(
            st, app_id, cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts, winner="none",
            reason=picked.reason, applied=False,
        )
        _mark_workspace_sync_skipped(st, app_id, picked.reason)
        _record_startup_restore_diagnostics(
            st, app_id,
            cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts,
            picked_source="none", picked_reason=picked.reason,
            should_apply=False, apply_reason="", skip_reason=picked.reason,
        )
        return False

    synced_key = _workspace_synced_key(app_id)
    applied_key = _applied_cloud_ts_key(app_id)
    applied_ts = st.session_state.get(applied_key)
    applied_epoch = parse_persist_timestamp(applied_ts)
    already_synced = bool(st.session_state.get(synced_key))
    first_sync = not already_synced
    cloud_newer_than_applied = bool(cloud_ts and cloud_epoch > applied_epoch)
    page = str(picked.state.get("active_page") or "")
    current_page = _session_workspace_page(st)
    page_mismatch = bool(page and current_page and page != current_page)
    cloud_players = _workspace_comparison_players(picked.state) if picked.source == "cloud" else []
    local_players = _session_comparison_players(st)
    comparison_mismatch = bool(
        picked.source == "cloud"
        and cloud_players != local_players
    )
    st.session_state["_suite_workspace_cloud_comparison_players"] = cloud_players or None
    st.session_state["_suite_workspace_local_comparison_players"] = local_players or None
    st.session_state["_suite_workspace_comparison_mismatch"] = comparison_mismatch
    st.session_state["_suite_already_synced_before_restore"] = already_synced

    apply_reasons: list[str] = []
    if first_sync:
        apply_reasons.append("first_sync")
    if cloud_newer_than_applied:
        apply_reasons.append("cloud_newer_than_applied")
    if cloud_newer_than_disk:
        apply_reasons.append("cloud_newer_than_disk")
    page_mismatch_apply = bool(
        page_mismatch
        and (first_sync or cloud_newer_than_applied or cloud_newer_than_disk)
        and not _user_page_blocks_cloud_overwrite(st, page)
    )
    if page_mismatch:
        apply_reasons.append("page_mismatch")
    if page_mismatch_apply:
        apply_reasons.append("page_mismatch_apply")
    comparison_mismatch_apply = bool(
        comparison_mismatch
        and (first_sync or cloud_newer_than_applied or cloud_newer_than_disk)
    )
    if comparison_mismatch:
        apply_reasons.append("comparison_mismatch")
    if comparison_mismatch_apply:
        apply_reasons.append("comparison_mismatch_apply")

    should_apply = bool(
        picked.state
        and (
            first_sync
            or cloud_newer_than_applied
            or cloud_newer_than_disk
            or page_mismatch_apply
            or comparison_mismatch_apply
        )
    )
    apply_reason = ", ".join(apply_reasons) if apply_reasons else "none"

    if cloud_newer_than_disk and picked.source == "cloud":
        st.session_state.pop(synced_key, None)

    if not should_apply:
        skip_reason = f"workspace already synced ({apply_reason or 'no trigger'})"
        st.session_state["_suite_persist_restore_skip_reason"] = skip_reason
        _record_workspace_sync_trace(
            st, app_id, cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts, winner=picked.source,
            reason="already synced", applied=False,
        )
        _mark_workspace_sync_skipped(st, app_id, skip_reason)
        _record_startup_restore_diagnostics(
            st, app_id,
            cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts,
            picked_source=picked.source, picked_reason=picked.reason,
            should_apply=False, apply_reason=apply_reason, skip_reason=skip_reason,
        )
        return False

    try:
        apply_state(st, picked.state)
    except Exception as exc:
        reason = f"apply_state failed: {exc}"
        st.session_state["_suite_persist_restore_skip_reason"] = reason
        _mark_workspace_sync_skipped(st, app_id, reason)
        _record_workspace_sync_trace(
            st, app_id, cloud_state=cloud_state, cloud_ts=cloud_ts,
            disk_state=disk_state, disk_ts=disk_ts, winner=picked.source,
            reason=str(exc), applied=False,
        )
        return False

    _lock_fingerprint_after_restore(st, app_id, picked.state)
    st.session_state[synced_key] = True
    st.session_state[f"{_SESSION_RESTORED_PREFIX}{app_id}"] = True
    st.session_state[dirty_key] = False
    st.session_state[_autosave_block_key(app_id)] = True
    st.session_state["_suite_autosave_block_reason"] = "post-restore cooldown"
    st.session_state["_cloud_workspace_restored"] = picked.source == "cloud"
    st.session_state["_cloud_workspace_restored_this_run"] = picked.source == "cloud"
    st.session_state["_suite_persist_restore_applied"] = True
    st.session_state["_suite_persist_last_restore_at"] = _utc_now_iso()
    st.session_state["_suite_persist_last_restore_source"] = picked.source
    st.session_state["_suite_persist_last_restore_reason"] = picked.reason

    if picked.source == "cloud":
        st.session_state[applied_key] = cloud_ts or _utc_now_iso()
        save_user_state(app_id, picked.state)
        st.session_state[_SESSION_CLOUD_BANNER_KEY] = True
    elif picked.source == "disk":
        st.session_state[applied_key] = disk_ts or _utc_now_iso()
        st.session_state[_SESSION_BANNER_KEY] = "Loaded your last session"

    _record_workspace_sync_trace(
        st, app_id, cloud_state=cloud_state, cloud_ts=cloud_ts,
        disk_state=disk_state, disk_ts=disk_ts, winner=picked.source,
        reason=picked.reason, applied=True, applied_state=picked.state,
    )
    _record_startup_restore_diagnostics(
        st, app_id,
        cloud_state=cloud_state, cloud_ts=cloud_ts,
        disk_state=disk_state, disk_ts=disk_ts,
        picked_source=picked.source, picked_reason=picked.reason,
        should_apply=True, apply_reason=apply_reason, skip_reason=None, applied=True,
    )
    st.session_state.pop("_suite_persist_restore_skip_reason", None)
    return True


def _record_restore_debug_meta(
    st: Any,
    app_id: str,
    *,
    cloud_ts: str | None,
    disk_ts: str | None,
    pick_source: str,
    pick_reason: str,
    local_dirty: bool,
) -> None:
    st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
    st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
    st.session_state["_suite_persist_debug_pick_source"] = pick_source
    st.session_state["_suite_persist_debug_pick_reason"] = pick_reason
    st.session_state[_local_dirty_key(app_id)] = local_dirty


def _set_restore_skip_reason(st: Any, reason: str) -> None:
    st.session_state["_suite_persist_restore_skip_reason"] = reason


def restore_once(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
) -> bool:
    """
    Restore on direct open; re-apply when cloud is newer than last apply.

    Skipped when Continue/deep-link query params are present, or when this
    device has unsaved local edits (``_suite_persist_local_dirty``).
    """
    st.session_state["_suite_persist_app_id"] = app_id
    st.session_state.pop("_suite_persist_restore_skip_reason", None)
    flag = f"{_SESSION_RESTORED_PREFIX}{app_id}"
    dirty_key = _local_dirty_key(app_id)
    applied_cloud_key = _applied_cloud_ts_key(app_id)
    local_dirty = bool(st.session_state.get(dirty_key))

    disk_state, disk_warn, disk_ts = _load_raw(app_id)
    if disk_warn:
        st.session_state[_SESSION_INVALID_WARN_KEY] = disk_warn

    skip_cloud = False
    try:
        from suite_cloud_state import has_resume_query_params

        skip_cloud = has_resume_query_params(st, app_id)
    except ImportError:
        pass

    if skip_cloud:
        st.session_state["_suite_resume_insight_hydration_only"] = True

    cloud_state: dict[str, Any] = {}
    cloud_ts: str | None = None
    pick_source = "none"
    pick_reason = "none"
    from_cloud = False
    state: dict[str, Any] = {}

    try:
        from suite_cloud_state import load_cloud_full_session, pick_restore_session, parse_persist_timestamp

        cloud_state, cloud_ts = load_cloud_full_session(app_id)
        already_restored = st.session_state.get(flag)
        applied_cloud_ts = st.session_state.get(applied_cloud_key)

        if already_restored:
            if local_dirty:
                _set_restore_skip_reason(st, "already restored this session; local unsaved edits")
                _record_restore_debug_meta(
                    st,
                    app_id,
                    cloud_ts=cloud_ts,
                    disk_ts=disk_ts,
                    pick_source="skipped",
                    pick_reason="local unsaved edits",
                    local_dirty=True,
                )
                return False
            if cloud_state and parse_persist_timestamp(cloud_ts) <= parse_persist_timestamp(applied_cloud_ts):
                _set_restore_skip_reason(st, "already restored this session; cloud not newer than last apply")
                _record_restore_debug_meta(
                    st,
                    app_id,
                    cloud_ts=cloud_ts,
                    disk_ts=disk_ts,
                    pick_source="skipped",
                    pick_reason="cloud not newer than last apply",
                    local_dirty=False,
                )
                return False

        picked = pick_restore_session(
            cloud_state,
            cloud_ts,
            disk_state,
            disk_ts,
            local_dirty=local_dirty,
            cloud_first=True,
        )
        state = picked.state
        pick_source = picked.source
        pick_reason = picked.reason
        from_cloud = picked.source == "cloud"

        st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
        st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
        st.session_state["_suite_persist_debug_pick_source"] = pick_source
        st.session_state["_suite_persist_debug_pick_reason"] = pick_reason
    except ImportError:
        state = disk_state
        pick_source = "disk"
        pick_reason = "cloud module missing"
        _set_restore_skip_reason(st, "cloud module missing; disk-only pick")
    except Exception as exc:
        state = disk_state
        pick_source = "disk"
        pick_reason = "cloud load error"
        _set_restore_skip_reason(st, f"cloud load error: {exc}; disk-only pick")

    if not state:
        _set_restore_skip_reason(
            st,
            "no restore source loaded "
            f"(cloud_blob={'yes' if cloud_state else 'no'}, disk_blob={'yes' if disk_state else 'no'}, "
            f"pick_reason={pick_reason!r})",
        )
        return False

    try:
        apply_state(st, state)
    except Exception as exc:
        _set_restore_skip_reason(st, f"apply_state failed: {exc}")
        st.session_state[_SESSION_INVALID_WARN_KEY] = (
            "Some saved settings could not be restored; using defaults."
        )
        return False

    st.session_state[flag] = True

    try:
        import hashlib
        import json

        blob = json.dumps(state, sort_keys=True, default=str)
        st.session_state[_restored_fp_key(app_id)] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
    except Exception:
        pass

    if from_cloud:
        st.session_state[applied_cloud_key] = cloud_ts or _utc_now_iso()
    elif pick_source == "disk":
        st.session_state[applied_cloud_key] = disk_ts or _utc_now_iso()
    st.session_state[dirty_key] = False

    if from_cloud:
        save_user_state(app_id, state)

    st.session_state["_suite_persist_last_restore_at"] = _utc_now_iso()
    st.session_state["_suite_persist_last_restore_source"] = pick_source
    st.session_state["_suite_persist_last_restore_reason"] = pick_reason
    st.session_state["_suite_persist_restore_applied"] = True

    if from_cloud:
        st.session_state[_SESSION_CLOUD_BANNER_KEY] = True
    else:
        st.session_state[_SESSION_BANNER_KEY] = "Loaded your last session"
    return True


def _session_workspace_page(st: Any) -> str:
    ss = st.session_state
    active = str(ss.get("active_page") or "").strip()
    sidebar = str(ss.get("main_sidebar_page") or "").strip()
    if sidebar and active and sidebar != active:
        return sidebar
    return active or sidebar


def _record_page_sync_decision(
    st: Any,
    app_id: str,
    *,
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
    picked_source: str,
    picked_reason: str,
    cloud_first: bool,
    local_dirty: bool,
) -> None:
    try:
        from suite_cloud_state import parse_persist_timestamp
    except ImportError:
        parse_persist_timestamp = _parse_ts_simple  # type: ignore[assignment]

    applied_ts = st.session_state.get(_applied_cloud_ts_key(app_id))
    cloud_epoch = parse_persist_timestamp(cloud_ts)
    disk_epoch = parse_persist_timestamp(disk_ts)
    applied_epoch = parse_persist_timestamp(applied_ts)
    local_epoch = max(disk_epoch, applied_epoch)

    st.session_state["_suite_page_sync_cloud_first"] = cloud_first
    st.session_state["_suite_page_sync_cloud_exists"] = bool(cloud_state)
    st.session_state["_suite_page_sync_local_exists"] = bool(disk_state)
    st.session_state["_suite_page_sync_local_dirty"] = local_dirty
    st.session_state["_suite_page_sync_cloud_newer_than_local"] = (
        cloud_epoch > local_epoch if cloud_ts else False
    )
    st.session_state["_suite_persist_debug_cloud_ts"] = cloud_ts
    st.session_state["_suite_persist_debug_disk_ts"] = disk_ts
    st.session_state["_suite_persist_debug_pick_source"] = picked_source
    st.session_state["_suite_persist_debug_pick_reason"] = picked_reason
    if isinstance(cloud_state, dict):
        st.session_state["_suite_page_sync_cloud_page"] = cloud_state.get("active_page")


def sync_cloud_workspace_before_sidebar(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
    cloud_first: bool = True,
) -> bool:
    """
    Apply cloud workspace before sidebar widgets render.

    Re-applies when the cloud page differs from the current session page, when
    cloud is newer than last apply, or on first open — not only when cloud ts
    beats applied ts (which restore_once may have already set this run).
    """
    st.session_state["_suite_persist_app_id"] = app_id
    st.session_state["_suite_page_sync_restore_attempted"] = True
    record_page_navigation_startup_diagnostics(st, app_id)
    try:
        from applied_math_return_insight import reconcile_stale_page_navigation

        reconcile_stale_page_navigation(st, app_id)
    except Exception:
        pass

    try:
        from suite_cloud_state import (
            has_resume_query_params,
            load_cloud_full_session,
            parse_persist_timestamp,
            pick_restore_session,
        )
    except ImportError:
        st.session_state["_suite_persist_restore_skip_reason"] = "cloud module missing"
        return False

    if has_resume_query_params(st, app_id):
        st.session_state["_suite_resume_insight_hydration_only"] = True

    dirty_key = _local_dirty_key(app_id)
    local_dirty = bool(st.session_state.get(dirty_key))
    if local_dirty:
        st.session_state["_suite_persist_restore_skip_reason"] = (
            "local unsaved edits — page sync skipped"
        )
        return False

    if st.session_state.get("_suite_page_user_nav"):
        st.session_state["_suite_persist_restore_skip_reason"] = (
            "user page navigation — page sync skipped"
        )
        return False

    cloud_state, cloud_ts = load_cloud_full_session(app_id)
    disk_state, _, disk_ts = _load_raw(app_id)
    if not isinstance(cloud_state, dict) or not cloud_state:
        _record_page_sync_decision(
            st,
            app_id,
            cloud_state={},
            cloud_ts=cloud_ts,
            disk_state=disk_state,
            disk_ts=disk_ts,
            picked_source="none",
            picked_reason="cloud full_session empty",
            cloud_first=cloud_first,
            local_dirty=local_dirty,
        )
        st.session_state["_suite_persist_restore_skip_reason"] = "cloud full_session empty"
        return False

    picked = pick_restore_session(
        cloud_state,
        cloud_ts,
        disk_state,
        disk_ts,
        local_dirty=False,
        cloud_first=cloud_first,
    )
    _record_page_sync_decision(
        st,
        app_id,
        cloud_state=cloud_state,
        cloud_ts=cloud_ts,
        disk_state=disk_state,
        disk_ts=disk_ts,
        picked_source=picked.source,
        picked_reason=picked.reason,
        cloud_first=cloud_first,
        local_dirty=local_dirty,
    )

    if not picked.state or picked.source != "cloud":
        st.session_state["_suite_persist_restore_skip_reason"] = (
            f"page sync skipped ({picked.reason})"
        )
        return False

    cloud_page = str(picked.state.get("active_page") or "").strip()
    current_page = _session_workspace_page(st)
    applied_key = _applied_cloud_ts_key(app_id)
    applied_ts = st.session_state.get(applied_key)
    cloud_epoch = parse_persist_timestamp(cloud_ts)
    applied_epoch = parse_persist_timestamp(applied_ts)
    user_page_nav = bool(st.session_state.get("_suite_page_user_nav"))
    ami_return_active = False
    try:
        from suite_cloud_state import ami_return_resume_consumed

        ami_return_active = bool(
            has_resume_query_params(st, app_id)
            or st.session_state.get("_ami_insight_return_preserve")
        ) and not ami_return_resume_consumed(st, app_id)
    except Exception:
        ami_return_active = bool(st.session_state.get("_ami_insight_return_preserve"))
    page_mismatch = bool(
        cloud_page and current_page and cloud_page != current_page and not user_page_nav
    )
    cloud_newer_than_applied = bool(cloud_ts and cloud_epoch > applied_epoch)
    page_mismatch_apply = bool(
        page_mismatch and cloud_newer_than_applied and not ami_return_active
        and not _user_page_blocks_cloud_overwrite(st, cloud_page)
    )

    if (
        not cloud_newer_than_applied
        and not page_mismatch_apply
        and applied_ts
        and current_page == cloud_page
    ):
        st.session_state["_suite_persist_restore_skip_reason"] = (
            "cloud page already applied this session"
        )
        return False

    if applied_ts and not cloud_newer_than_applied and not page_mismatch_apply:
        st.session_state["_suite_persist_restore_skip_reason"] = (
            "page sync skipped (cloud not newer than applied)"
        )
        return False

    if _user_page_blocks_cloud_overwrite(st, cloud_page):
        st.session_state["_suite_persist_restore_skip_reason"] = (
            "user page ownership — page sync skipped"
        )
        return False

    try:
        apply_state(st, picked.state)
    except Exception as exc:
        st.session_state["_suite_persist_restore_skip_reason"] = f"apply_state failed: {exc}"
        return False

    flag = f"{_SESSION_RESTORED_PREFIX}{app_id}"
    st.session_state[flag] = True
    st.session_state[applied_key] = cloud_ts or _utc_now_iso()
    st.session_state[dirty_key] = False
    st.session_state["_suite_persist_last_restore_at"] = _utc_now_iso()
    st.session_state["_suite_persist_last_restore_source"] = picked.source
    st.session_state["_suite_persist_last_restore_reason"] = picked.reason
    st.session_state["_suite_persist_restore_applied"] = True
    st.session_state.pop("_suite_cloud_target_page", None)
    st.session_state.pop("_suite_persist_restore_skip_reason", None)

    save_user_state(app_id, picked.state)
    st.session_state[_SESSION_CLOUD_BANNER_KEY] = True
    return True


def sync_cloud_workspace_if_newer(
    st: Any,
    app_id: str,
    *,
    apply_state: Callable[[Any, dict[str, Any]], None],
) -> bool:
    """Backward-compatible alias — page-aware cloud sync before sidebar."""
    return sync_cloud_workspace_before_sidebar(
        st,
        app_id,
        apply_state=apply_state,
        cloud_first=True,
    )


def _record_autosave_trace(st: Any, app_id: str, *, reason: str, wrote_cloud: bool, state: dict[str, Any]) -> None:
    st.session_state["_suite_autosave_reason"] = reason or "autosave"
    st.session_state["_suite_autosave_wrote_cloud"] = wrote_cloud
    st.session_state["_suite_autosave_payload_page"] = state.get("active_page")
    st.session_state["_suite_autosave_payload_comparison_players"] = _extract_page_players(
        state, "Comparison Tool"
    )
    st.session_state["_suite_autosave_payload_trend_players"] = _extract_page_players(
        state, "Trend Value"
    )


def force_autosave(
    st: Any,
    app_id: str,
    *,
    build_state: Callable[[Any], dict[str, Any]],
    reason: str = "",
) -> bool:
    """Persist workspace immediately (e.g. after meaningful user action)."""
    try:
        import hashlib
        import json

        from suite_cloud_state import load_cloud_full_session, save_cloud_full_session, session_page_summary

        block_key = _autosave_block_key(app_id)
        bypass_block = reason in (
            "comparison_edit",
            "trend_edit",
            "career_edit",
            "draft_edit",
            "page_change",
            "insight_persist",
            "insight_hydrate",
            "applied_math_send",
        )
        if st.session_state.get(block_key) and not bypass_block:
            st.session_state["_suite_autosave_blocked_after_restore"] = True
            st.session_state["_suite_autosave_block_reason"] = st.session_state.get(
                "_suite_autosave_block_reason", "post-restore cooldown"
            )
            return False

        if reason:
            st.session_state["_suite_pending_save_reason"] = reason
        state = build_state(st)
        if reason == "page_change":
            state = _preserve_cloud_widget_fields_on_page_change(app_id, state)
        blob = json.dumps(state, sort_keys=True, default=str)
        fp = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
        saved_disk = save_user_state(app_id, state)
        page, summary = session_page_summary(app_id, state)
        cloud_block = _cloud_autosave_blocked_reason(st, app_id, state, save_reason=reason)
        saved_cloud = False
        if cloud_block:
            st.session_state["_suite_autosave_cloud_blocked_reason"] = cloud_block
        else:
            saved_cloud = bool(save_cloud_full_session(app_id, state, page=page, summary=summary))
        if saved_disk or saved_cloud:
            st.session_state[f"_suite_autosave_fp::{app_id}"] = fp
            st.session_state[_restored_fp_key(app_id)] = fp
            st.session_state[_local_dirty_key(app_id)] = False
            if reason == "page_change":
                _release_user_page_ownership_after_save(st, str(state.get("active_page") or ""))
            if saved_cloud:
                _, cloud_ts = load_cloud_full_session(app_id)
                st.session_state[_applied_cloud_ts_key(app_id)] = cloud_ts or _utc_now_iso()
            st.session_state["_suite_persist_last_save_at"] = _utc_now_iso()
            st.session_state["_suite_persist_last_save_disk"] = saved_disk
            st.session_state["_suite_persist_last_save_cloud"] = saved_cloud
            st.session_state["_suite_persist_last_save_reason"] = reason or "force_autosave"
            st.session_state["_suite_last_force_save_at"] = st.session_state["_suite_persist_last_save_at"]
            st.session_state["_suite_last_cloud_payload_comparison_players"] = _workspace_comparison_players(
                state
            ) or None
            _record_autosave_trace(
                st, app_id, reason=reason or "force_autosave", wrote_cloud=saved_cloud, state=state
            )
            st.session_state[_SESSION_SAVED_FLASH_KEY] = True
            return True
    except Exception:
        pass
    return False


def _parse_ts_simple(ts: str | None) -> float:
    try:
        from suite_cloud_state import parse_persist_timestamp

        return parse_persist_timestamp(ts)
    except ImportError:
        if not ts:
            return 0.0
        try:
            return datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00")[:26]).timestamp()
        except ValueError:
            return 0.0


def autosave_if_changed(
    st: Any,
    app_id: str,
    *,
    build_state: Callable[[Any], dict[str, Any]],
) -> None:
    """Persist to disk and Supabase when the session snapshot changes."""
    try:
        import hashlib

        block_key = _autosave_block_key(app_id)
        if st.session_state.get(block_key):
            st.session_state["_suite_autosave_blocked_after_restore"] = True
            st.session_state["_suite_autosave_block_reason"] = st.session_state.get(
                "_suite_autosave_block_reason", "post-restore cooldown"
            )
            return

        state = build_state(st)
        blob = json.dumps(state, sort_keys=True, default=str)
        fp = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]
        key = f"_suite_autosave_fp::{app_id}"
        restored_fp = st.session_state.get(_restored_fp_key(app_id))
        reconciled_key = f"_suite_restore_reconciled::{app_id}"
        if restored_fp and fp != restored_fp:
            if st.session_state.get(_CLOUD_WORKSPACE_RESTORED) and not st.session_state.get(reconciled_key):
                st.session_state[key] = fp
                st.session_state[_restored_fp_key(app_id)] = fp
                st.session_state[reconciled_key] = True
            else:
                st.session_state[_local_dirty_key(app_id)] = True
        if st.session_state.get(key) == fp:
            return
        saved_disk = save_user_state(app_id, state)
        saved_cloud = False
        cloud_err = ""
        try:
            from suite_cloud_state import save_cloud_full_session, session_page_summary

            page, summary = session_page_summary(app_id, state)
            cloud_block = _cloud_autosave_blocked_reason(st, app_id, state, save_reason="autosave")
            if cloud_block:
                st.session_state["_suite_autosave_cloud_blocked_reason"] = cloud_block
            else:
                saved_cloud = bool(
                    save_cloud_full_session(app_id, state, page=page, summary=summary)
                )
                if saved_cloud:
                    from suite_cloud_state import load_cloud_full_session

                    _, cloud_ts_after = load_cloud_full_session(app_id)
                    if cloud_ts_after:
                        st.session_state[_applied_cloud_ts_key(app_id)] = cloud_ts_after
        except Exception as exc:
            cloud_err = str(exc)
        if saved_disk or saved_cloud:
            st.session_state[key] = fp
            st.session_state[_restored_fp_key(app_id)] = fp
            if saved_cloud:
                st.session_state[_local_dirty_key(app_id)] = False
                if _applied_cloud_ts_key(app_id) not in st.session_state or not st.session_state.get(
                    _applied_cloud_ts_key(app_id)
                ):
                    st.session_state[_applied_cloud_ts_key(app_id)] = _utc_now_iso()
            st.session_state["_suite_persist_last_save_at"] = _utc_now_iso()
            st.session_state["_suite_last_autosave_at"] = st.session_state["_suite_persist_last_save_at"]
            st.session_state["_suite_persist_last_save_disk"] = saved_disk
            st.session_state["_suite_persist_last_save_cloud"] = saved_cloud
            _record_autosave_trace(
                st, app_id, reason="autosave", wrote_cloud=saved_cloud, state=state
            )
            st.session_state["_suite_last_cloud_payload_comparison_players"] = _workspace_comparison_players(
                state
            ) or None
            if cloud_err:
                st.session_state["_suite_persist_last_cloud_error"] = cloud_err
            st.session_state[_SESSION_SAVED_FLASH_KEY] = True
    except Exception:
        pass


def show_persistence_messages(st: Any) -> None:
    warn = st.session_state.pop(_SESSION_INVALID_WARN_KEY, None)
    if warn:
        st.warning(str(warn))
    if st.session_state.pop(_SESSION_CLOUD_BANNER_KEY, None):
        st.success("Restored your last session from the cloud")
    else:
        banner = st.session_state.pop(_SESSION_BANNER_KEY, None)
        if banner:
            st.success(str(banner))
    if st.session_state.pop(_SESSION_SAVED_FLASH_KEY, False):
        st.toast("Settings saved", icon="💾")


def reset_confirm_session_key(app_id: str) -> str:
    return f"_suite_reset_confirm::{app_id}"


def clear_reset_confirm_state(session_state: Any, app_id: str) -> None:
    session_state.pop(reset_confirm_session_key(app_id), None)


def request_reset_confirm_state(session_state: Any, app_id: str) -> None:
    session_state[reset_confirm_session_key(app_id)] = True


def _clear_suite_reset_cache_keys(
    session_state: Any,
    app_id: str,
    *,
    extra_prefixes: tuple[str, ...] = (),
) -> None:
    prefixes = (_SESSION_RESTORED_PREFIX, "_suite_autosave_fp::", *extra_prefixes)
    confirm_key = reset_confirm_session_key(app_id)
    for key in list(session_state.keys()):
        sk = str(key)
        if sk == confirm_key:
            session_state.pop(key, None)
            continue
        if any(sk.startswith(prefix) for prefix in prefixes):
            session_state.pop(key, None)


def execute_suite_reset(
    st: Any,
    app_id: str,
    on_reset: Callable[[Any], None],
    *,
    extra_prefixes: tuple[str, ...] = (),
) -> None:
    session_state = st.session_state
    clear_reset_confirm_state(session_state, app_id)
    reset_user_state(app_id)
    _clear_suite_reset_cache_keys(session_state, app_id, extra_prefixes=extra_prefixes)
    on_reset(st)
    session_state[_SESSION_BANNER_KEY] = "Reset to defaults"


def render_reset_controls(
    st: Any,
    app_id: str,
    *,
    on_reset: Callable[[Any], None],
    label: str = "Reset to default",
    help_text: str = "Clears your saved session for this app only.",
    extra_reset_clear_prefixes: tuple[str, ...] = (
        _LOCAL_DIRTY_PREFIX,
        _APPLIED_CLOUD_TS_PREFIX,
        _RESTORED_FP_PREFIX,
    ),
) -> None:
    pending = bool(st.session_state.get(reset_confirm_session_key(app_id)))
    with st.sidebar.expander("Saved session", expanded=pending):
        st.caption("Your last page, filters, and inputs reload automatically.")
        if pending:
            st.warning("This clears saved preferences for this app. Continue?")
            c1, c2 = st.columns(2)
            with c1:
                st.button(
                    "Yes, reset",
                    key=f"suite_reset_yes::{app_id}",
                    type="primary",
                    on_click=execute_suite_reset,
                    kwargs={
                        "st": st,
                        "app_id": app_id,
                        "on_reset": on_reset,
                        "extra_prefixes": extra_reset_clear_prefixes,
                    },
                )
            with c2:
                st.button(
                    "Cancel",
                    key=f"suite_reset_no::{app_id}",
                    on_click=clear_reset_confirm_state,
                    kwargs={"session_state": st.session_state, "app_id": app_id},
                )
        else:
            st.button(
                label,
                key=f"suite_reset_btn::{app_id}",
                help=help_text,
                on_click=request_reset_confirm_state,
                kwargs={"session_state": st.session_state, "app_id": app_id},
            )


def finalize_suite_reset(
    st: Any,
    app_id: str,
    fresh_state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "Reset to defaults",
) -> None:
    """Persist fresh defaults to disk and cloud after ``reset_user_state`` removed the local file."""
    save_user_state(app_id, fresh_state)
    try:
        from suite_cloud_state import (
            clear_cloud_full_session,
            save_cloud_full_session,
            session_page_summary,
        )

        clear_cloud_full_session(app_id)
        auto_page, auto_summary = session_page_summary(app_id, fresh_state)
        save_cloud_full_session(
            app_id,
            fresh_state,
            page=page or auto_page,
            summary=summary or auto_summary or "Reset to defaults",
        )
    except Exception:
        pass
    st.session_state[f"{_SESSION_RESTORED_PREFIX}{app_id}"] = True
    st.session_state.pop(f"_suite_autosave_fp::{app_id}", None)
    st.session_state.pop(_local_dirty_key(app_id), None)
    st.session_state.pop(_applied_cloud_ts_key(app_id), None)
    st.session_state.pop(_restored_fp_key(app_id), None)
