"""
Cross-device full-session persistence via Supabase ``suite_app_current_state``.

Apps autosave a JSON blob under ``metrics.full_session``. On startup, when no
Continue/deep-link query params are present, ``suite_user_persistence.restore_once``
loads the newer of cloud vs local disk and applies it to ``st.session_state``.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

FULL_SESSION_KEY = "full_session"

_RESUME_QUERY_KEYS: dict[str, tuple[str, ...]] = {
    "music": ("suite_resume", "suite_page", "suite_pick_key", "suite_song"),
    "baseball": ("suite_page",),
    "investment": ("suite_page",),
    "nba": ("suite_resume", "suite_page", "suite_team"),
    "future_lens": ("suite_resume", "suite_page", "suite_sim"),
    "applied_intelligence": ("suite_page", "suite_lesson"),
}


def _qp_get(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def has_resume_query_params(st: Any, app_key: str) -> bool:
    """True when the user opened via Continue / deep link (skip cloud restore)."""
    key = str(app_key or "").strip()
    if key == "math":
        key = "applied_intelligence"
    if st.session_state.get(f"_suite_resume_launch_{key}"):
        return True
    for param in _RESUME_QUERY_KEYS.get(key, ("suite_resume", "suite_page")):
        if _qp_get(st, param):
            return True
    return False


def _parse_ts(ts: str | None) -> float:
    if not ts:
        return 0.0
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s[:26]).timestamp()
    except ValueError:
        return 0.0


def load_cloud_full_session(app_id: str) -> tuple[dict[str, Any], str | None]:
    """Return ``(session_dict, updated_at_iso)`` from cloud, or empty dict."""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return {}, None
    if not cloud_storage_enabled():
        return {}, None
    try:
        import suite_storage as storage

        app_key = storage.normalize_app_key(app_id)
        row = storage.load_current_states().get(app_key) or {}
        if not isinstance(row, dict):
            return {}, None
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        blob = metrics.get(FULL_SESSION_KEY)
        if isinstance(blob, dict) and blob:
            return copy.deepcopy(blob), str(row.get("updated_at") or "") or None
        return {}, str(row.get("updated_at") or "") or None
    except Exception:
        return {}, None


def save_cloud_full_session(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
) -> None:
    if not state:
        return
    try:
        from suite_account import sync_local_state_to_cloud

        sync_local_state_to_cloud(
            app_id,
            {
                "page": page,
                "summary": summary or "Last session",
                FULL_SESSION_KEY: state,
            },
        )
    except Exception:
        pass


def pick_newer_session(
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
) -> dict[str, Any]:
    if cloud_state and not disk_state:
        return cloud_state
    if disk_state and not cloud_state:
        return disk_state
    if not cloud_state and not disk_state:
        return {}
    if _parse_ts(cloud_ts) >= _parse_ts(disk_ts):
        return cloud_state
    return disk_state


def session_page_summary(app_id: str, state: dict[str, Any]) -> tuple[str, str]:
    """Derive dashboard page + summary from a persisted session blob."""
    app_key = str(app_id or "").strip()
    if app_key == "baseball":
        page = str(state.get("active_page") or "")
        return page, page or "Baseball session"
    if app_key == "music":
        core = state.get("core") if isinstance(state.get("core"), dict) else state
        page = str((core or {}).get("studio_page") or (core or {}).get("page") or state.get("studio_page") or "")
        song = str((core or {}).get("song") or state.get("song") or "")
        return page, song or page or "Music session"
    if app_key == "investment":
        tab = str(state.get("health_active_tab") or state.get("experience") or "")
        return tab, tab or "Portfolio session"
    if app_key == "future_lens":
        skill = str(state.get("specific_skill") or state.get("broad_domain") or "")
        year = state.get("sim_year")
        summary = skill
        if year is not None:
            summary = f"{skill} · {year}".strip(" ·")
        return str(state.get("_suite_fl_view") or "simulation"), summary or "Future Lens session"
    page = str(state.get("page") or "")
    return page, str(state.get("summary") or page or "Session")
