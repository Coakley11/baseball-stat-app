"""
Cross-device full-session persistence via Supabase ``suite_app_current_state``.

Apps autosave a JSON blob under ``metrics.full_session``. On startup, when no
Continue/deep-link query params are present, ``suite_user_persistence.restore_once``
loads the newer of cloud vs local disk and applies it to ``st.session_state``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

FULL_SESSION_KEY = "full_session"

PickSource = Literal["cloud", "disk", "none"]


@dataclass(frozen=True)
class RestorePickResult:
    state: dict[str, Any]
    source: PickSource
    reason: str
    cloud_ts: str | None
    disk_ts: str | None

_RESUME_QUERY_KEYS: dict[str, tuple[str, ...]] = {
    "music": (
        "suite_resume",
        "suite_page",
        "suite_pick_key",
        "suite_song",
        "suite_display_key",
        "suite_instrument",
        "suite_section_focus",
    ),
    "baseball": ("suite_resume", "suite_page", "suite_trend_player", "suite_player_a", "suite_player_b"),
    "investment": ("suite_page",),
    "nba": ("suite_resume", "suite_page", "suite_team"),
    "future_lens": (
        "suite_resume",
        "suite_page",
        "suite_sim",
        "suite_fl_domain",
        "suite_fl_area",
        "suite_fl_timeline_year",
        "suite_fl_sim_year",
        "suite_fl_view",
    ),
    "applied_intelligence": (
        "suite_page",
        "suite_lesson",
        "suite_ai_question",
        "suite_ai_question_id",
        "suite_ai_source_app",
        "suite_ai_context",
    ),
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


def parse_persist_timestamp(ts: str | None) -> float:
    """Parse ISO / Supabase timestamps to UTC epoch seconds (naive => UTC)."""
    if not ts:
        return 0.0
    s = str(ts).strip()
    if not s:
        return 0.0
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s[:32])
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.timestamp()


def _parse_ts(ts: str | None) -> float:
    return parse_persist_timestamp(ts)


def _import_storage() -> tuple[Any, str]:
    """Resolve storage backend; standalone deploys use ``suite_storage_supabase``."""
    try:
        import suite_storage as storage

        return storage, "suite_storage"
    except ImportError:
        import suite_storage_supabase as storage

        return storage, "suite_storage_supabase"


def probe_cloud_restore_diagnostics(st: Any, app_id: str) -> dict[str, Any]:
    """
    Explain why cloud restore may be empty (for in-app diagnostics).

    Does not mutate session state except reading query params / flags.
    """
    diag: dict[str, Any] = {
        "cloud_enabled": False,
        "account_mode": "unknown",
        "account_user_id": "",
        "suite_user_id": "",
        "storage_module": "",
        "skip_resume_params": False,
        "resume_launch_flag": False,
        "cloud_row_found": False,
        "cloud_has_full_session": False,
        "cloud_updated_at": None,
        "cloud_load_error": None,
    }
    try:
        from suite_user import account_mode, get_account_user_id, get_external_user_id

        diag["account_mode"] = account_mode()
        diag["account_user_id"] = get_account_user_id()
        diag["suite_user_id"] = get_external_user_id()
    except Exception as exc:
        diag["cloud_load_error"] = f"account probe: {exc}"

    key = str(app_id or "").strip()
    if key == "math":
        key = "applied_intelligence"
    diag["resume_launch_flag"] = bool(st.session_state.get(f"_suite_resume_launch_{key}"))
    try:
        diag["skip_resume_params"] = has_resume_query_params(st, app_id)
    except Exception:
        pass

    try:
        from suite_storage_config import cloud_storage_enabled

        diag["cloud_enabled"] = cloud_storage_enabled()
    except ImportError:
        diag["cloud_load_error"] = diag.get("cloud_load_error") or "suite_storage_config missing"
        return diag

    if not diag["cloud_enabled"]:
        return diag

    try:
        storage, diag["storage_module"] = _import_storage()
        app_key = storage.normalize_app_key(app_id)
        row = storage.load_current_states().get(app_key) or {}
        if isinstance(row, dict) and row:
            diag["cloud_row_found"] = True
            diag["cloud_updated_at"] = str(row.get("updated_at") or "") or None
            metrics = row.get("metrics")
            if isinstance(metrics, dict):
                blob = metrics.get(FULL_SESSION_KEY)
                diag["cloud_has_full_session"] = isinstance(blob, dict) and bool(blob)
    except Exception as exc:
        diag["cloud_load_error"] = str(exc)

    return diag


def load_cloud_full_session(app_id: str) -> tuple[dict[str, Any], str | None]:
    """Return ``(session_dict, updated_at_iso)`` from cloud, or empty dict."""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return {}, None
    if not cloud_storage_enabled():
        return {}, None
    try:
        storage, _ = _import_storage()

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


def pick_restore_session(
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
    *,
    local_dirty: bool = False,
    prefer_cloud_on_tie: bool = True,
) -> RestorePickResult:
    """
    Choose restore payload for direct open / cloud re-sync.

    When ``local_dirty`` is False (fresh open, no unsaved edits on this device),
    the newer timestamp wins; ties favor cloud for cross-device sync.
    When ``local_dirty`` is True, keep local disk over remote cloud.
    """
    cloud_epoch = _parse_ts(cloud_ts)
    disk_epoch = _parse_ts(disk_ts)

    if not cloud_state and not disk_state:
        return RestorePickResult({}, "none", "empty", cloud_ts, disk_ts)
    if cloud_state and not disk_state:
        return RestorePickResult(cloud_state, "cloud", "disk missing", cloud_ts, disk_ts)
    if disk_state and not cloud_state:
        return RestorePickResult(disk_state, "disk", "cloud missing", cloud_ts, disk_ts)

    if local_dirty:
        return RestorePickResult(
            disk_state,
            "disk",
            "local unsaved edits",
            cloud_ts,
            disk_ts,
        )

    if cloud_epoch > disk_epoch:
        return RestorePickResult(cloud_state, "cloud", "cloud newer", cloud_ts, disk_ts)
    if disk_epoch > cloud_epoch:
        return RestorePickResult(disk_state, "disk", "disk newer", cloud_ts, disk_ts)
    if prefer_cloud_on_tie:
        return RestorePickResult(cloud_state, "cloud", "tie → cloud", cloud_ts, disk_ts)
    return RestorePickResult(disk_state, "disk", "tie → disk", cloud_ts, disk_ts)


def pick_newer_session(
    cloud_state: dict[str, Any],
    cloud_ts: str | None,
    disk_state: dict[str, Any],
    disk_ts: str | None,
) -> dict[str, Any]:
    return pick_restore_session(
        cloud_state, cloud_ts, disk_state, disk_ts, local_dirty=False
    ).state


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
        tab = str(
            state.get("investment_active_tab")
            or state.get("health_active_tab")
            or state.get("experience")
            or ""
        )
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
