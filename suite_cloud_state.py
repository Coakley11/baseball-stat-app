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

DRAFT_LIBRARY_CLOUD_SAVE_REASONS = frozenset({
    "manual_save_library_sync",
    "draft_archive_saved",
    "draft_archive_renamed",
    "draft_archive_duplicated",
    "draft_archive_deleted",
    "draft_archive_cleared",
    "simulator_league_context_saved",
    "live_draft_league_context_saved",
    "league_context_activated",
    "probe_test_draft_saved",
})

DRAFT_LIBRARY_WRITE_TIMEOUT_SEC = 25.0
DRAFT_LIBRARY_WRITE_ATTEMPTS = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        "suite_ami_insight",
        "suite_ai_question_id",
    ),
    "baseball": (
        "suite_resume",
        "suite_page",
        "suite_trend_player",
        "suite_player_a",
        "suite_player_b",
        "suite_draft_room",
        "suite_draft_section",
        "suite_hof_target",
        "suite_hof_case",
        "suite_ai_question_id",
        "suite_ami_insight",
    ),
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


def _normalize_resume_app_key(app_key: str) -> str:
    key = str(app_key or "").strip()
    if key == "math":
        return "applied_intelligence"
    return key


# URL params that must preserve return/source page navigation — block cloud workspace restore.
_WORKSPACE_RESTORE_BLOCKING_QUERY_KEYS: dict[str, tuple[str, ...]] = {
    "music": (
        "suite_resume",
        "suite_page",
        "suite_ami_insight",
        "suite_ai_question_id",
    ),
    "baseball": (
        "suite_resume",
        "suite_page",
        "suite_draft_room",
        "suite_draft_section",
        "suite_hof_target",
        "suite_hof_case",
        "suite_ai_question_id",
        "suite_ami_insight",
    ),
}


def _workspace_restore_blocking_keys(app_key: str) -> tuple[str, ...]:
    key = _normalize_resume_app_key(app_key)
    if key in _WORKSPACE_RESTORE_BLOCKING_QUERY_KEYS:
        return _WORKSPACE_RESTORE_BLOCKING_QUERY_KEYS[key]
    return _RESUME_QUERY_KEYS.get(key, ("suite_resume", "suite_page"))


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


def _ami_resume_consumed_flag(app_key: str) -> str:
    key = str(app_key or "").strip().lower()
    if key == "math":
        key = "applied_intelligence"
    return f"_ami_resume_consumed_{key}"


def ami_return_resume_consumed(st: Any, app_key: str) -> bool:
    """True after AMI insight was hydrated+rendered once on the source page."""
    return bool(st.session_state.get(_ami_resume_consumed_flag(app_key)))


def list_active_resume_query_params(st: Any, app_key: str) -> list[str]:
    """Resume / deep-link query param names currently present in the URL."""
    key = _normalize_resume_app_key(app_key)
    params = _RESUME_QUERY_KEYS.get(key, ("suite_resume", "suite_page"))
    return [name for name in params if _qp_get(st, name)]


def list_workspace_restore_blocking_query_params(st: Any, app_key: str) -> list[str]:
    """URL params that block cloud workspace restore (return/AMI navigation, not song hydrate)."""
    key = _normalize_resume_app_key(app_key)
    params = _workspace_restore_blocking_keys(key)
    return [name for name in params if _qp_get(st, name)]


def _ami_return_url_active(st: Any, app_key: str) -> bool:
    """True when return/AMI URL params steer page navigation (not song hydrate-only params)."""
    if list_workspace_restore_blocking_query_params(st, app_key):
        return True
    try:
        from applied_math_return_insight import _active_ami_return_query_param_keys, insight_return_query_id

        if insight_return_query_id(st) or _active_ami_return_query_param_keys(st):
            return True
    except ImportError:
        pass
    return False


_STALE_RESUME_SESSION_FLAGS: tuple[str, ...] = (
    "_suite_resume_launch_music",
    "_suite_resume_launch",
    "_suite_resume_launch_baseball",
    "_suite_resume_launch_app",
    "_suite_resume_launch_key",
    "_suite_resume_launch_applied_intelligence",
    "_suite_resume_insight_hydration_only",
    "_suite_workspace_sync_skipped_no_apply",
    "_skip_page_restore_for",
    "_navigate_to_studio_page",
    "_navigate_to_page",
    "_suite_cloud_target_page",
    "ami_return_force_active_page",
    "ami_return_forced_page",
    "_ami_insight_return_preserve",
)


def _pending_programmatic_navigation_active(session: dict[str, Any]) -> bool:
    """True when a scheduled page change is queued but not yet consumed."""
    target = str(session.get("_navigate_to_page") or "").strip()
    if not target:
        return False
    skip_for = str(session.get("_skip_page_restore_for") or "").strip()
    if skip_for and skip_for == target:
        return True
    current = str(session.get("active_page") or session.get("main_sidebar_page") or "").strip()
    return bool(current and current != target)


def reconcile_stale_resume_session_flags(st: Any, app_key: str) -> list[str]:
    """
    Drop stale resume/AMI session flags when the URL no longer carries resume params.

    Returns flag names cleared. Does not clear flags during a live URL resume/AMI return.
    """
    ss = st.session_state
    if _ami_return_url_active(st, app_key):
        return []
    cleared: list[str] = []
    key = _normalize_resume_app_key(app_key)
    preserve_nav = _pending_programmatic_navigation_active(ss)
    for flag in (*_STALE_RESUME_SESSION_FLAGS, f"_suite_resume_launch_{key}"):
        if preserve_nav and flag in ("_navigate_to_page", "_skip_page_restore_for"):
            continue
        if flag in ss:
            ss.pop(flag, None)
            cleared.append(flag)
    for flag in list(ss.keys()):
        name = str(flag)
        if name.startswith("_suite_resume_launch_") and name not in cleared:
            ss.pop(flag, None)
            cleared.append(name)
    try:
        from applied_math_return_insight import reconcile_stale_page_navigation

        reconcile_stale_page_navigation(st, app_key)
    except ImportError:
        pass
    return cleared


def should_skip_workspace_restore_for_resume(
    st: Any,
    app_key: str,
    *,
    reconcile_first: bool = True,
) -> bool:
    """
    Skip cloud workspace restore only for live URL resume params or URL-driven AMI return.

    Session-only ``_suite_resume_launch_*`` / ``_ami_insight_return_preserve`` flags
    must not block cross-device page sync.
    """
    if ami_return_resume_consumed(st, app_key):
        if reconcile_first:
            reconcile_stale_resume_session_flags(st, app_key)
        return False
    if reconcile_first:
        reconcile_stale_resume_session_flags(st, app_key)
    if list_workspace_restore_blocking_query_params(st, app_key):
        return True
    try:
        from applied_math_return_insight import ami_return_navigation_active

        return ami_return_navigation_active(st, app_key)
    except ImportError:
        return False


def has_resume_query_params(st: Any, app_key: str) -> bool:
    """True when live URL resume/AMI params should defer cloud workspace restore."""
    return should_skip_workspace_restore_for_resume(st, app_key, reconcile_first=True)


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
        meta_fn = getattr(storage, "load_current_state_meta_for_app", None)
        row_fn = getattr(storage, "load_current_state_for_app", None)
        if meta_fn and row_fn:
            meta = meta_fn(app_id) or {}
            if isinstance(meta, dict) and meta:
                diag["cloud_row_found"] = True
                diag["cloud_updated_at"] = str(meta.get("updated_at") or "") or None
            row = row_fn(app_id) if diag["cloud_row_found"] else {}
        else:
            row = storage.load_current_states(include_metrics=True).get(app_key) or {}
            if isinstance(row, dict) and row:
                diag["cloud_row_found"] = True
                diag["cloud_updated_at"] = str(row.get("updated_at") or "") or None
        if isinstance(row, dict) and row:
            metrics = row.get("metrics")
            if isinstance(metrics, dict):
                blob = metrics.get(FULL_SESSION_KEY)
                diag["cloud_has_full_session"] = isinstance(blob, dict) and bool(blob)
    except Exception as exc:
        diag["cloud_load_error"] = str(exc)

    return diag


def _cloud_storage_app_id(app_id: str) -> str:
    try:
        from suite_workspace import scoped_cloud_app_id

        return scoped_cloud_app_id(app_id)
    except ImportError:
        return str(app_id or "").strip()


def _full_session_cache_keys(app_key: str) -> tuple[str, str]:
    return f"_suite_full_session_ts_{app_key}", f"_suite_full_session_blob_{app_key}"


def _streamlit_session() -> Any | None:
    try:
        import streamlit as st  # noqa: WPS433

        return st.session_state
    except Exception:
        return None


def _resolve_cloud_app_key(app_id: str, storage: Any | None = None) -> str:
    if storage is None:
        storage, _ = _import_storage()
    return storage.normalize_app_key(_cloud_storage_app_id(app_id))


def _state_draft_pick_count(state: dict[str, Any]) -> int:
    try:
        from draft_room_state import draft_room_restore_stats

        return int(draft_room_restore_stats(state).get("pick_count") or 0)
    except ImportError:
        return 0


def _draft_room_slice_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Compact durable blob: draft board keys only (for pick persistence when full save fails)."""
    try:
        from draft_room_state import (
            CANONICAL_DRAFT_META_KEY,
            DRAFT_ROOM_PAGE_BLOCK,
            DRAFT_ROOM_STATE_KEY,
            DRAFT_ROOM_TABLE_KEY,
            draft_room_restore_stats,
        )
    except ImportError:
        return {}
    slice_out: dict[str, Any] = {}
    for key in (DRAFT_ROOM_STATE_KEY, DRAFT_ROOM_TABLE_KEY, CANONICAL_DRAFT_META_KEY):
        if key in state and state[key] is not None:
            slice_out[key] = copy.deepcopy(state[key])
    pf = state.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get(DRAFT_ROOM_PAGE_BLOCK)
        if isinstance(block, dict) and block:
            slice_out.setdefault("page_filter_state", {})[DRAFT_ROOM_PAGE_BLOCK] = copy.deepcopy(block)
    page = str(state.get("active_page") or "").strip()
    if page:
        slice_out["active_page"] = page
    if int(draft_room_restore_stats(slice_out).get("pick_count") or 0) <= 0:
        return {}
    return slice_out


def _record_cloud_write_session_meta(
    ss: dict[str, Any] | None,
    *,
    app_key: str,
    write_mode: str = "",
    payload_bytes: int = 0,
    used_workflow_fallback: bool = False,
    used_draft_room_slice: bool = False,
) -> None:
    if ss is None:
        return
    ss["_suite_last_cloud_app_key"] = app_key
    if write_mode:
        ss["_suite_last_cloud_write_mode"] = write_mode
    if payload_bytes:
        ss["_suite_last_cloud_payload_bytes"] = payload_bytes
    if used_workflow_fallback:
        ss["_suite_cloud_write_used_workflow_fallback"] = True
    else:
        ss.pop("_suite_cloud_write_used_workflow_fallback", None)
    if used_draft_room_slice:
        ss["_suite_cloud_write_used_draft_room_slice"] = True
    else:
        ss.pop("_suite_cloud_write_used_draft_room_slice", None)


def last_cloud_write_meta() -> dict[str, Any]:
    ss = _streamlit_session()
    if not isinstance(ss, dict):
        return {}
    return {
        "write_mode": str(ss.get("_suite_last_cloud_write_mode") or ""),
        "cloud_app_key": str(ss.get("_suite_last_cloud_app_key") or ""),
        "payload_bytes": int(ss.get("_suite_last_cloud_payload_bytes") or 0),
        "used_workflow_fallback": bool(ss.get("_suite_cloud_write_used_workflow_fallback")),
        "used_draft_room_slice": bool(ss.get("_suite_cloud_write_used_draft_room_slice")),
    }


def verify_cloud_draft_room_readback(
    app_id: str = "baseball",
    *,
    min_picks: int = 1,
    cloud_app_key: str = "",
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh Supabase readback after a draft-room write — confirms picks landed."""
    out: dict[str, Any] = {
        "ok": False,
        "pick_count": 0,
        "cloud_app_key": "",
        "workspace_id": "",
        "scope_user_id": None,
        "selected_row_user_id": None,
        "row_found": False,
        "row_inspection": {},
        "error": "",
    }
    try:
        from suite_storage_config import cloud_storage_enabled

        if not cloud_storage_enabled():
            out["error"] = "cloud_storage_disabled"
            return out
    except ImportError:
        out["error"] = "cloud_storage_config_unavailable"
        return out
    try:
        from workflow_persist_guard import _resolve_workspace_id_for_cloud_probe

        ws = _resolve_workspace_id_for_cloud_probe("", session=session)
        out["workspace_id"] = ws
    except Exception:
        ws = ""
    app_key = str(cloud_app_key or "").strip()
    if not app_key:
        try:
            storage, _ = _import_storage()
            app_key = _resolve_cloud_app_key(app_id, storage)
        except Exception as exc:
            out["error"] = str(exc)
            return out
    out["cloud_app_key"] = app_key
    invalidate_cloud_full_session_cache(app_id)
    try:
        from suite_storage_supabase import inspect_cloud_state_rows

        inspection = inspect_cloud_state_rows(app_key)
        out["row_inspection"] = inspection
        out["scope_user_id"] = inspection.get("scope_user_id")
        out["selected_row_user_id"] = inspection.get("selected_row_user_id")
    except Exception:
        pass
    try:
        storage, _ = _import_storage()
        row = storage.load_current_state_for_app(app_key)
        if not isinstance(row, dict) or not row:
            out["error"] = "cloud_row_not_found"
            return out
        out["row_found"] = True
        if out.get("selected_row_user_id") is None:
            out["selected_row_user_id"] = row.get("user_id")
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        blob = metrics.get(FULL_SESSION_KEY) if isinstance(metrics, dict) else None
        from draft_room_state import draft_room_restore_stats

        out["pick_count"] = int(draft_room_restore_stats(blob if isinstance(blob, dict) else None).get("pick_count") or 0)
        out["ok"] = out["pick_count"] >= max(0, int(min_picks or 0))
        if not out["ok"] and not out["error"]:
            out["error"] = f"readback_pick_count_{out['pick_count']}_lt_{min_picks}"
    except Exception as exc:
        out["error"] = str(exc)
    return out


def read_cloud_persistence_boundary(app_id: str = "baseball") -> dict[str, Any]:
    """Authoritative Supabase read-back for draft-room save/restore diagnostics."""
    out: dict[str, Any] = {
        "cloud_fetch_attempted": True,
        "cloud_fetch_success": False,
        "cloud_target_user_id": None,
        "cloud_target_app_id": "",
        "cloud_fetch_user_id": None,
        "cloud_fetch_app_id": "",
        "cloud_fetch_updated_at": None,
        "cloud_fetch_pick_count": 0,
        "supabase_row_pick_count_after_write": 0,
        "supabase_row_updated_at_after_write": None,
        "cloud_row_count": 0,
        "cloud_row_pick_counts": [],
        "cloud_load_error": None,
    }
    try:
        from suite_storage_config import cloud_storage_enabled

        if not cloud_storage_enabled():
            out["cloud_load_error"] = "cloud_storage_disabled"
            return out
    except ImportError:
        out["cloud_load_error"] = "cloud_storage_config_unavailable"
        return out
    try:
        storage, _ = _import_storage()
        app_key = _resolve_cloud_app_key(app_id, storage)
        out["cloud_target_app_id"] = app_key
        out["cloud_fetch_app_id"] = app_key
        try:
            from suite_storage_supabase import _cloud_user_id, inspect_cloud_state_rows

            out["cloud_target_user_id"] = _cloud_user_id()
            out["cloud_fetch_user_id"] = out["cloud_target_user_id"]
            inspection = inspect_cloud_state_rows(app_key)
            out["cloud_row_count"] = int(inspection.get("row_count") or 0)
            out["selected_row_user_id"] = inspection.get("selected_row_user_id")
            out["scope_user_id"] = inspection.get("scope_user_id")
            row_summaries = inspection.get("rows") if isinstance(inspection.get("rows"), list) else []
            out["cloud_row_pick_counts"] = [
                {
                    "user_id": row.get("user_id"),
                    "archive_draft_count": row.get("draft_count"),
                    "updated_at": row.get("updated_at"),
                }
                for row in row_summaries
                if isinstance(row, dict)
            ]
        except Exception:
            pass
        row = storage.load_current_state_for_app(app_key)
        if not isinstance(row, dict) or not row:
            return out
        out["cloud_fetch_success"] = True
        updated_at = str(row.get("updated_at") or "") or None
        out["cloud_fetch_updated_at"] = updated_at
        out["supabase_row_updated_at_after_write"] = updated_at
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        blob = metrics.get(FULL_SESSION_KEY) if isinstance(metrics, dict) else None
        from draft_room_state import draft_room_restore_stats

        pick_count = int(draft_room_restore_stats(blob if isinstance(blob, dict) else None).get("pick_count") or 0)
        out["cloud_fetch_pick_count"] = pick_count
        out["supabase_row_pick_count_after_write"] = pick_count
    except Exception as exc:
        out["cloud_load_error"] = str(exc)
    return out


def invalidate_cloud_full_session_cache(app_id: str) -> None:
    """Drop cached full_session after a local or cloud write."""
    try:
        storage, _ = _import_storage()
    except Exception:
        return
    app_key = _resolve_cloud_app_key(app_id, storage)
    ss = _streamlit_session()
    if ss is None:
        return
    ts_key, blob_key = _full_session_cache_keys(app_key)
    ss.pop(ts_key, None)
    ss.pop(blob_key, None)


def load_cloud_full_session(app_id: str, *, force: bool = False) -> tuple[dict[str, Any], str | None]:
    """Return ``(session_dict, updated_at_iso)`` from cloud, or empty dict."""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return {}, None
    if not cloud_storage_enabled():
        return {}, None
    try:
        storage, _ = _import_storage()

        app_key = _resolve_cloud_app_key(app_id, storage)
        meta_fn = getattr(storage, "load_current_state_meta_for_app", None)
        row_fn = getattr(storage, "load_current_state_for_app", None)
        ss = _streamlit_session()
        ts_key, blob_key = _full_session_cache_keys(app_key)

        updated_at: str | None = None
        run_guard_key = f"_suite_full_session_fetch_run::{app_key}"
        if not force and ss is not None and ss.get(run_guard_key):
            cached = ss.get(blob_key)
            if isinstance(cached, dict):
                return copy.deepcopy(cached), ss.get(ts_key)

        if meta_fn:
            meta = meta_fn(app_key) or {}
            updated_at = str(meta.get("updated_at") or "") or None
            if not force and ss is not None and ss.get(ts_key) == updated_at:
                cached = ss.get(blob_key)
                if isinstance(cached, dict):
                    return copy.deepcopy(cached), updated_at

        if row_fn:
            row = row_fn(app_key) or {}
        else:
            row = storage.load_current_states(include_metrics=True).get(app_key) or {}
        if not isinstance(row, dict):
            return {}, None
        updated_at = str(row.get("updated_at") or "") or updated_at
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        blob = metrics.get(FULL_SESSION_KEY)
        session_out: dict[str, Any] = {}
        if isinstance(blob, dict) and blob:
            session_out = copy.deepcopy(blob)
        if ss is not None:
            ss[blob_key] = copy.deepcopy(session_out)
            ss[ts_key] = updated_at
            ss[run_guard_key] = True
        return session_out, updated_at
    except Exception:
        return {}, None


def save_cloud_full_session(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
) -> bool:
    """Persist full_session to Supabase. Returns True when cloud write succeeds."""
    ok, _error, _app_key = save_cloud_full_session_with_details(
        app_id, state, page=page, summary=summary
    )
    return ok


def is_draft_library_cloud_save_reason(reason: str) -> bool:
    """True when a Saved Draft Library action should use the small cloud payload."""
    raw = str(reason or "").strip()
    if not raw:
        return False
    if raw in DRAFT_LIBRARY_CLOUD_SAVE_REASONS:
        return True
    base = raw[:-6] if raw.endswith("_retry") else raw
    return base in DRAFT_LIBRARY_CLOUD_SAVE_REASONS


def _draft_library_slice_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Compact durable blob: saved drafts + league contexts (no 28MB app state)."""
    try:
        from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY
    except ImportError:
        from workflow_persist_guard import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY
    try:
        from workflow_persist_guard import LEAGUE_CONTEXT_STATE_KEY, _league_context_store_nonempty
    except ImportError:
        LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"

        def _league_context_store_nonempty(val: Any) -> bool:
            return isinstance(val, dict) and isinstance(val.get("contexts"), dict) and bool(val.get("contexts"))

    slice_out: dict[str, Any] = {}
    archives = state.get(DRAFT_ARCHIVE_KEY)
    if isinstance(archives, list):
        slice_out[DRAFT_ARCHIVE_KEY] = copy.deepcopy(archives)
    active_id = str(state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    if active_id:
        slice_out[ACTIVE_DRAFT_ARCHIVE_KEY] = active_id
    try:
        from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY
    except ImportError:
        DELETED_DRAFT_ARCHIVE_IDS_KEY = "_deleted_draft_archive_ids"
    tombstones = state.get(DELETED_DRAFT_ARCHIVE_IDS_KEY)
    if isinstance(tombstones, list) and tombstones:
        slice_out[DELETED_DRAFT_ARCHIVE_IDS_KEY] = copy.deepcopy(tombstones)
    flc = state.get(LEAGUE_CONTEXT_STATE_KEY)
    if _league_context_store_nonempty(flc):
        slice_out[LEAGUE_CONTEXT_STATE_KEY] = copy.deepcopy(flc)
    page = str(state.get("active_page") or "").strip()
    if page:
        slice_out["active_page"] = page
    return slice_out


def _workflow_slice_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Smaller full_session blob with draft library / league context keys only."""
    try:
        from workflow_persist_guard import PROTECTED_WORKFLOW_PERSIST_KEYS
    except ImportError:
        return {}
    slice_out: dict[str, Any] = {}
    for key in PROTECTED_WORKFLOW_PERSIST_KEYS:
        if key in state:
            slice_out[key] = copy.deepcopy(state[key])
    page = str(state.get("active_page") or "").strip()
    if page:
        slice_out["active_page"] = page
    return slice_out


def _format_cloud_save_error(
    *,
    err: str,
    write_mode: str,
    app_key: str,
    payload_bytes: int,
    extra: str = "",
) -> str:
    base = f"{err} (mode={write_mode}, app={app_key}, payload_bytes={payload_bytes})"
    if extra:
        return f"{base}; {extra}"
    return base


def _attempt_cloud_metrics_save(
    storage: Any,
    app_key: str,
    *,
    page: str,
    summary: str,
    metrics: dict[str, Any],
    write_label: str,
    skip_metrics_merge: bool = False,
    direct_upsert: bool = False,
    request_timeout_sec: float | None = None,
    write_attempts: int | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    result_fn = getattr(storage, "save_current_state_with_result", None)
    if callable(result_fn):
        result = result_fn(
            app_key,
            page=page or "",
            summary=summary or "Last session",
            metrics=metrics,
            skip_metrics_merge=skip_metrics_merge,
            direct_upsert=direct_upsert,
            request_timeout_sec=request_timeout_sec,
            write_attempts=write_attempts,
        )
        if isinstance(result, dict) and result.get("ok"):
            out = dict(result)
            out["write_label"] = write_label
            return True, "", out
        err = str((result or {}).get("error") or "cloud_save_failed").strip()
        write_mode = str((result or {}).get("write_mode") or "")
        payload_bytes = int((result or {}).get("payload_bytes") or 0)
        return (
            False,
            _format_cloud_save_error(
                err=err,
                write_mode=write_mode,
                app_key=app_key,
                payload_bytes=payload_bytes,
            ),
            dict(result or {}),
        )
    storage.save_current_state(
        app_key,
        page=page or "",
        summary=summary or "Last session",
        metrics=metrics,
    )
    return True, "", {"write_mode": "post", "write_label": write_label}


def save_cloud_draft_library_with_details(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
) -> tuple[bool, str, str]:
    """Persist saved-draft library keys only — fast, small cloud write for Save Draft."""
    if not state:
        return False, "empty_state", ""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return False, "cloud_storage_config_unavailable", ""
    if not cloud_storage_enabled():
        return False, "cloud_storage_disabled", ""
    storage: Any | None = None
    app_key = ""
    try:
        storage, _ = _import_storage()
        app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        ss = _streamlit_session()
        if ss is not None:
            try:
                from workflow_persist_guard import inject_session_draft_library_into_save_state

                state = inject_session_draft_library_into_save_state(state, ss)
            except ImportError:
                pass
        draft_slice = _draft_library_slice_from_state(state)
        try:
            from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY, DELETED_DRAFT_ARCHIVE_IDS_KEY
        except ImportError:
            from workflow_persist_guard import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY
            DELETED_DRAFT_ARCHIVE_IDS_KEY = "_deleted_draft_archive_ids"
        try:
            from workflow_persist_guard import LEAGUE_CONTEXT_STATE_KEY
        except ImportError:
            LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"
        has_archives = DRAFT_ARCHIVE_KEY in draft_slice
        has_tombstones = bool(draft_slice.get(DELETED_DRAFT_ARCHIVE_IDS_KEY))
        has_contexts = bool(draft_slice.get(LEAGUE_CONTEXT_STATE_KEY))
        if (
            not has_archives
            and not draft_slice.get(ACTIVE_DRAFT_ARCHIVE_KEY)
            and not has_tombstones
            and not has_contexts
        ):
            return False, "empty_draft_library_slice", app_key
        payload = {FULL_SESSION_KEY: draft_slice}
        estimate_fn = getattr(storage, "estimate_metrics_payload_bytes", None)
        if callable(estimate_fn):
            payload_bytes = int(estimate_fn(payload))
        else:
            from suite_app_current_state_health import estimate_json_bytes

            payload_bytes = estimate_json_bytes(payload)

        ok, detail, result = _attempt_cloud_metrics_save(
            storage,
            app_key,
            page=page,
            summary=summary or "Saved Draft Library",
            metrics=payload,
            write_label="draft_library_slice",
            skip_metrics_merge=False,
            direct_upsert=False,
            request_timeout_sec=DRAFT_LIBRARY_WRITE_TIMEOUT_SEC,
            write_attempts=DRAFT_LIBRARY_WRITE_ATTEMPTS,
        )
        ss = _streamlit_session()
        if ss is not None:
            ss["_suite_last_cloud_payload_bytes"] = payload_bytes
            ss["_suite_last_cloud_write_mode"] = str((result or {}).get("write_mode") or "")
            ss["_suite_cloud_write_used_draft_library_slice"] = True
            ss.pop("_suite_cloud_write_used_workflow_fallback", None)
        if not ok:
            return False, detail, app_key

        readback: dict[str, Any] = {}
        try:
            from workflow_persist_guard import (
                count_draft_archives,
                record_draft_library_readback,
                verify_cloud_draft_library_readback,
            )

            expected_id = str(state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
            expected_count = int(count_draft_archives(draft_slice.get(DRAFT_ARCHIVE_KEY)))
            ws = ""
            if ss is not None:
                try:
                    from suite_workspace import get_active_workspace_id

                    ws = str(get_active_workspace_id(type("_St", (), {"session_state": ss})()))
                except Exception:
                    ws = str(ss.get("_suite_active_workspace_id") or ss.get("_suite_owned_workspace_id") or "")
                ss["_suite_last_cloud_app_key"] = app_key
            readback = verify_cloud_draft_library_readback(
                app_id,
                min_drafts=1,
                expected_draft_id=expected_id,
                workspace_id=ws,
                cloud_app_key=app_key,
                expected_draft_count=expected_count,
                session=ss if isinstance(ss, dict) else None,
            )
            if ss is not None:
                record_draft_library_readback(ss, readback)
                ss["_suite_last_draft_save_readback"] = {
                    "cloud_app_key": app_key,
                    "workspace_id": ws,
                    "scope_user_id": readback.get("scope_user_id"),
                    "selected_row_user_id": readback.get("selected_row_user_id"),
                    "draft_count": readback.get("draft_count"),
                    "draft_ids": list(readback.get("draft_ids") or []),
                    "expected_draft_count": expected_count,
                    "expected_draft_id": expected_id,
                }
        except Exception as exc:
            readback = {"ok": False, "error": str(exc), "draft_count": 0}
            if ss is not None:
                try:
                    from workflow_persist_guard import record_draft_library_readback

                    record_draft_library_readback(ss, readback)
                except Exception:
                    pass
        if not readback.get("ok"):
            err = str(readback.get("error") or "cloud_readback_failed")
            if ss is not None:
                ss["_suite_persist_last_cloud_error"] = err
                ss["_draft_archive_persist_error"] = err
                ss["_suite_persist_last_save_cloud"] = False
            return False, err, app_key

        if ss is not None:
            ts_key, blob_key = _full_session_cache_keys(app_key)
            ss[blob_key] = copy.deepcopy(draft_slice)
            ss[ts_key] = _utc_now_iso()
            ss.pop(f"_suite_full_session_fetch_run::{app_key}", None)
            ss["_suite_persist_last_save_cloud"] = True
        return True, "", app_key
    except Exception as exc:
        try:
            if storage is not None:
                app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        except Exception:
            app_key = app_key or ""
        return False, f"{type(exc).__name__}: {exc}", app_key


def save_cloud_full_session_with_details(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
) -> tuple[bool, str, str]:
    """Persist full_session to cloud; return (success, error_message, storage_app_key)."""
    if not state:
        return False, "empty_state", ""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return False, "cloud_storage_config_unavailable", ""
    if not cloud_storage_enabled():
        return False, "cloud_storage_disabled", ""
    storage: Any | None = None
    app_key = ""
    try:
        storage, _ = _import_storage()
        app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        ss = _streamlit_session()
        if ss is not None:
            try:
                from workflow_persist_guard import count_draft_archives, draft_archive_shrink_blocked_reason

                outbound = count_draft_archives(state.get("draft_archive_teams"))
                if outbound <= 0:
                    block = draft_archive_shrink_blocked_reason(
                        type("_St", (), {"session_state": ss})(),
                        app_id,
                        state,
                        save_reason=str(ss.get("_suite_pending_save_reason") or "cloud_full_session"),
                        scope="cloud",
                    )
                    if block:
                        ss["_suite_empty_startup_write_blocked"] = block
                        ss["_suite_persist_last_cloud_error"] = block
                        return False, block, app_key
            except Exception:
                pass
            try:
                from workflow_persist_guard import merge_protected_workflow_into_save

                state = merge_protected_workflow_into_save(
                    copy.deepcopy(state),
                    ss,
                    app_id=app_id,
                    st=type("_St", (), {"session_state": ss})(),
                    save_reason=str(ss.get("_suite_pending_save_reason") or "cloud_full_session"),
                )
            except Exception:
                pass
        full_payload = {FULL_SESSION_KEY: copy.deepcopy(state)}
        estimate_fn = getattr(storage, "estimate_metrics_payload_bytes", None)
        if callable(estimate_fn):
            full_bytes = int(estimate_fn(full_payload))
        else:
            from suite_app_current_state_health import estimate_json_bytes

            full_bytes = estimate_json_bytes(full_payload)

        ok, detail, result = _attempt_cloud_metrics_save(
            storage,
            app_key,
            page=page,
            summary=summary,
            metrics=full_payload,
            write_label="full_session",
        )
        if not ok:
            pick_count = _state_draft_pick_count(state)
            dr_slice = _draft_room_slice_from_state(state) if pick_count > 0 else {}
            if dr_slice:
                dr_payload = {FULL_SESSION_KEY: dr_slice}
                dr_bytes = (
                    int(estimate_fn(dr_payload))
                    if callable(estimate_fn)
                    else estimate_json_bytes(dr_payload)
                )
                dr_ok, dr_detail, dr_result = _attempt_cloud_metrics_save(
                    storage,
                    app_key,
                    page=page,
                    summary=summary or "Draft room slice",
                    metrics=dr_payload,
                    write_label="draft_room_slice",
                )
                if dr_ok:
                    ss = _streamlit_session()
                    _record_cloud_write_session_meta(
                        ss,
                        app_key=app_key,
                        write_mode=str((dr_result or {}).get("write_mode") or ""),
                        payload_bytes=dr_bytes,
                        used_draft_room_slice=True,
                    )
                    ts_key, blob_key = _full_session_cache_keys(app_key)
                    if ss is not None:
                        ss[blob_key] = copy.deepcopy(dr_slice)
                        ss[ts_key] = _utc_now_iso()
                        ss.pop(f"_suite_full_session_fetch_run::{app_key}", None)
                    return True, "", app_key
                detail = f"{detail}; draft_room_slice_failed={dr_detail}"

            wf_slice = _workflow_slice_from_state(state)
            wf_payload = {FULL_SESSION_KEY: wf_slice}
            wf_bytes = (
                int(estimate_fn(wf_payload))
                if callable(estimate_fn)
                else estimate_json_bytes(wf_payload)
            )
            if wf_slice and wf_bytes + 4096 < full_bytes and pick_count <= 0:
                wf_ok, wf_detail, wf_result = _attempt_cloud_metrics_save(
                    storage,
                    app_key,
                    page=page,
                    summary=summary or "Workflow slice",
                    metrics=wf_payload,
                    write_label="workflow_slice_fallback",
                )
                if wf_ok:
                    ss = _streamlit_session()
                    _record_cloud_write_session_meta(
                        ss,
                        app_key=app_key,
                        write_mode=str((wf_result or {}).get("write_mode") or ""),
                        payload_bytes=wf_bytes,
                        used_workflow_fallback=True,
                    )
                    ts_key, blob_key = _full_session_cache_keys(app_key)
                    if ss is not None:
                        ss[blob_key] = copy.deepcopy(wf_slice)
                        ss[ts_key] = _utc_now_iso()
                        ss.pop(f"_suite_full_session_fetch_run::{app_key}", None)
                    return True, "", app_key
                detail = f"{detail}; workflow_fallback_failed={wf_detail}"
            elif pick_count > 0:
                detail = f"{detail}; workflow_fallback_skipped_preserves_draft_room_picks"

            likely = ""
            health: dict[str, Any] = {}
            try:
                from suite_app_current_state_health import classify_cloud_save_failure, probe_suite_app_current_state_health

                health = probe_suite_app_current_state_health(
                    run_write_probe=True,
                    run_size_ladder=False,
                    scoped_app_key=app_key,
                )
                likely = classify_cloud_save_failure(
                    error=detail,
                    payload_bytes=full_bytes,
                    minimal_write_ok=bool(health.get("minimal_write_ok")),
                )
                ss = _streamlit_session()
                if ss is not None:
                    ss["_suite_cloud_health_probe"] = health
                    ss["_suite_last_cloud_payload_bytes"] = full_bytes
            except Exception:
                pass
            extra_bits = []
            if likely:
                extra_bits.append(f"likely_cause={likely}")
            if health:
                extra_bits.append(f"minimal_write_ok={health.get('minimal_write_ok')}")
            err_out = detail if not extra_bits else f"{detail}; {'; '.join(extra_bits)}"
            return False, err_out, app_key

        ss = _streamlit_session()
        _record_cloud_write_session_meta(
            ss,
            app_key=app_key,
            write_mode=str((result or {}).get("write_mode") or ""),
            payload_bytes=full_bytes,
        )
        ts_key, blob_key = _full_session_cache_keys(app_key)
        if ss is not None:
            ss[blob_key] = copy.deepcopy(state)
            ss[ts_key] = _utc_now_iso()
            ss.pop(f"_suite_full_session_fetch_run::{app_key}", None)
        return True, "", app_key
    except Exception as exc:
        try:
            if storage is not None:
                app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        except Exception:
            app_key = app_key or ""
        return False, f"{type(exc).__name__}: {exc}", app_key


def save_cloud_full_session_with_result(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
    min_draft_pick_count: int | None = None,
) -> tuple[bool, str]:
    """Persist full_session to cloud; return (success, error_message)."""
    try:
        ok, error, app_key = save_cloud_full_session_with_details(
            app_id, state, page=page, summary=summary
        )
        if not ok:
            return False, error or "cloud_save_failed"
        ss = _streamlit_session()
        if min_draft_pick_count is not None and int(min_draft_pick_count) > 0:
            if isinstance(ss, dict) and ss.get("_suite_cloud_write_used_workflow_fallback"):
                return False, "workflow_fallback_omitted_draft_room_picks"
            readback = verify_cloud_draft_room_readback(
                app_id,
                min_picks=int(min_draft_pick_count),
                cloud_app_key=app_key,
                session=ss if isinstance(ss, dict) else None,
            )
            if not readback.get("ok"):
                err = str(readback.get("error") or "readback_pick_mismatch")
                expected = int(min_draft_pick_count)
                got = int(readback.get("pick_count") or 0)
                if "readback_pick_mismatch" not in err:
                    err = f"readback_pick_mismatch:expected={expected} got={got}"
                row_uid = readback.get("selected_row_user_id")
                ws = readback.get("workspace_id") or ""
                key = readback.get("cloud_app_key") or app_key
                suffix = f"key={key}, workspace={ws or '—'}"
                if row_uid is not None:
                    suffix += f", row_user_id={row_uid}"
                return False, f"{err}; {suffix}"
            if isinstance(ss, dict):
                ss["_suite_last_draft_room_readback"] = {
                    "cloud_app_key": readback.get("cloud_app_key") or app_key,
                    "workspace_id": readback.get("workspace_id"),
                    "scope_user_id": readback.get("scope_user_id"),
                    "selected_row_user_id": readback.get("selected_row_user_id"),
                    "pick_count": readback.get("pick_count"),
                    "expected_pick_count": int(min_draft_pick_count),
                }
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def clear_cloud_full_session(app_id: str) -> None:
    """Remove persisted full_session blob from cloud (reset flows)."""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return
    if not cloud_storage_enabled():
        return
    try:
        storage, _ = _import_storage()
        app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        storage.save_current_state(
            app_key,
            page="",
            summary="",
            metrics={FULL_SESSION_KEY: {}},
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
    cloud_first: bool = True,
) -> RestorePickResult:
    """
    Choose restore payload for direct open / cloud re-sync.

    When ``local_dirty`` is False and ``cloud_first`` is True (default), cloud
    ``full_session`` is the cross-device source of truth whenever it exists.
    Local disk is a per-device cache used only when cloud is empty/unavailable
    or this device has unsaved local edits.
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

    try:
        from workflow_persist_guard import PROTECTED_WORKFLOW_PERSIST_KEYS, workflow_richness

        cloud_wf = sum(workflow_richness(k, cloud_state.get(k)) for k in PROTECTED_WORKFLOW_PERSIST_KEYS)
        disk_wf = sum(workflow_richness(k, disk_state.get(k)) for k in PROTECTED_WORKFLOW_PERSIST_KEYS)
        if disk_wf > cloud_wf:
            return RestorePickResult(
                disk_state,
                "disk",
                "disk richer saved drafts / league contexts",
                cloud_ts,
                disk_ts,
            )
        if cloud_wf > disk_wf:
            return RestorePickResult(
                cloud_state,
                "cloud",
                "cloud richer saved drafts / league contexts",
                cloud_ts,
                disk_ts,
            )
    except ImportError:
        pass

    try:
        from workflow_persist_guard import summarize_cloud_workflow_blob

        disk_summary = summarize_cloud_workflow_blob(disk_state)
        cloud_summary = summarize_cloud_workflow_blob(cloud_state)
        disk_drafts = int(disk_summary.get("draft_archive_count") or 0)
        cloud_drafts = int(cloud_summary.get("draft_archive_count") or 0)
        if disk_drafts > cloud_drafts:
            return RestorePickResult(
                disk_state,
                "disk",
                f"disk has more saved drafts ({disk_drafts}>{cloud_drafts})",
                cloud_ts,
                disk_ts,
            )
        disk_ctx = int(disk_summary.get("league_context_count") or 0)
        cloud_ctx = int(cloud_summary.get("league_context_count") or 0)
        if disk_ctx > cloud_ctx:
            return RestorePickResult(
                disk_state,
                "disk",
                f"disk has more saved contexts ({disk_ctx}>{cloud_ctx})",
                cloud_ts,
                disk_ts,
            )
    except ImportError:
        pass

    if not cloud_first and disk_state:
        return RestorePickResult(
            disk_state,
            "disk",
            "local/demo disk-first restore",
            cloud_ts,
            disk_ts,
        )

    if cloud_first and cloud_state:
        return RestorePickResult(
            cloud_state,
            "cloud",
            "cloud-first workspace sync",
            cloud_ts,
            disk_ts,
        )

    if cloud_epoch > disk_epoch:
        return RestorePickResult(cloud_state, "cloud", "cloud newer", cloud_ts, disk_ts)
    if disk_epoch > cloud_epoch:
        return RestorePickResult(disk_state, "disk", "disk newer", cloud_ts, disk_ts)
    if prefer_cloud_on_tie and cloud_first:
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
        meta = state.get("music_workspace_state") if isinstance(state.get("music_workspace_state"), dict) else {}
        core = state.get("core") if isinstance(state.get("core"), dict) else state
        page = str(
            meta.get("studio_page")
            or (core or {}).get("studio_page")
            or (core or {}).get("page")
            or state.get("studio_page")
            or ""
        )
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
