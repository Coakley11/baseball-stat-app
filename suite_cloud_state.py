"""
Cross-device full-session persistence via Supabase ``suite_app_current_state``.

Apps autosave a JSON blob under ``metrics.full_session``. On startup, when no
Continue/deep-link query params are present, ``suite_user_persistence.restore_once``
loads the newer of cloud vs local disk and applies it to ``st.session_state``.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

FULL_SESSION_KEY = "full_session"

PickSource = Literal["cloud", "disk", "none"]

# Cloud read outcomes. "error" must never be treated like "no saved data".
CLOUD_READ_OK = "ok"  # store answered and returned a saved session
CLOUD_READ_NOT_FOUND = "not_found"  # store answered: no row, or no saved session in it
CLOUD_READ_ERROR = "error"  # store did not answer (network, timeout, permissions, bad payload)
CLOUD_READ_DISABLED = "disabled"  # cloud storage is not configured (local install)

# Set when any cloud read fails. While set, save_cloud_full_session refuses to write, for every
# save reason, because this session may not hold the user's real saved data. Only the workspace
# sync clears it, after a successful read has reconciled the session with the cloud copy.
CLOUD_READ_FAILED_KEY = "_suite_cloud_read_failed"
CLOUD_RECONCILED_KEY = "_suite_cloud_reconciled"
CLOUD_WRITE_BLOCKED_KEY = "_suite_cloud_write_blocked"
CLOUD_WRITE_ERROR_KEY = "_suite_cloud_write_error"


@dataclass(frozen=True)
class CloudRead:
    state: dict[str, Any]
    updated_at: str | None
    status: str
    error: str = ""

    @property
    def answered(self) -> bool:
        """The store answered (ok or confirmed empty)."""
        return self.status in (CLOUD_READ_OK, CLOUD_READ_NOT_FOUND)


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
    for flag in (*_STALE_RESUME_SESSION_FLAGS, f"_suite_resume_launch_{key}"):
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


def invalidate_cloud_full_session_cache(app_id: str) -> None:
    """Drop cached full_session after a local or cloud write."""
    try:
        import suite_storage as storage
    except ImportError:
        return
    app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
    ss = _streamlit_session()
    if ss is None:
        return
    ts_key, blob_key = _full_session_cache_keys(app_key)
    ss.pop(ts_key, None)
    ss.pop(blob_key, None)


def load_cloud_full_session(app_id: str, *, force: bool = False) -> tuple[dict[str, Any], str | None]:
    """Return ``(session_dict, updated_at_iso)`` from cloud, or empty dict.

    An empty dict does not say whether the store answered; use
    ``load_cloud_full_session_status`` when that matters. A failed read is recorded on the
    session either way (``CLOUD_READ_FAILED_KEY``), which pauses cloud writes.
    """
    read = load_cloud_full_session_status(app_id, force=force)
    return read.state, read.updated_at


def load_cloud_full_session_status(app_id: str, *, force: bool = False) -> CloudRead:
    """Read the cloud ``full_session`` and say how the read went (see ``CLOUD_READ_*``)."""
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return CloudRead({}, None, CLOUD_READ_DISABLED)
    if not cloud_storage_enabled():
        return CloudRead({}, None, CLOUD_READ_DISABLED)
    ss = _streamlit_session()
    try:
        storage, _ = _import_storage()

        app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        meta_fn = getattr(storage, "load_current_state_meta_for_app", None)
        row_fn = getattr(storage, "load_current_state_for_app", None)
        ts_key, blob_key = _full_session_cache_keys(app_key)

        updated_at: str | None = None
        if meta_fn:
            meta = meta_fn(app_id) or {}
            updated_at = str(meta.get("updated_at") or "") or None
            if not force and ss is not None and ss.get(ts_key) == updated_at:
                cached = ss.get(blob_key)
                if isinstance(cached, dict):
                    return CloudRead(copy.deepcopy(cached), updated_at, CLOUD_READ_OK if cached else CLOUD_READ_NOT_FOUND)

        if row_fn:
            row = row_fn(app_id) or {}
        else:
            row = storage.load_current_states(include_metrics=True).get(app_key) or {}
        if not isinstance(row, dict):
            raise TypeError(f"unexpected cloud row type {type(row).__name__}")
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
        return CloudRead(session_out, updated_at, CLOUD_READ_OK if session_out else CLOUD_READ_NOT_FOUND)
    except Exception as exc:
        _record_cloud_read_failure(ss, app_id, exc)
        return CloudRead({}, None, CLOUD_READ_ERROR, f"{type(exc).__name__}: {exc}"[:300])


def _record_cloud_read_failure(ss: Any, app_id: str, exc: BaseException) -> None:
    if ss is None:
        return
    try:
        prev = ss.get(CLOUD_READ_FAILED_KEY)
        count = int(prev.get("count") or 0) + 1 if isinstance(prev, dict) else 1
        ss[CLOUD_READ_FAILED_KEY] = {
            "app_id": app_id,
            "error": type(exc).__name__,
            "count": count,
            "at": datetime.now(timezone.utc).timestamp(),
        }
    except Exception:
        pass


def cloud_read_failure(ss: Any = None) -> dict[str, Any] | None:
    """The unresolved cloud read failure for this session, if any."""
    ss = ss if ss is not None else _streamlit_session()
    try:
        value = ss.get(CLOUD_READ_FAILED_KEY) if ss is not None else None
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def mark_cloud_reconciled(ss: Any = None) -> None:
    """The session now holds (or was confirmed to match) the cloud copy: writes may resume."""
    ss = ss if ss is not None else _streamlit_session()
    if ss is None:
        return
    try:
        ss[CLOUD_RECONCILED_KEY] = True
        ss.pop(CLOUD_READ_FAILED_KEY, None)
        ss.pop(CLOUD_WRITE_BLOCKED_KEY, None)
    except Exception:
        pass


def save_cloud_full_session(
    app_id: str,
    state: dict[str, Any],
    *,
    page: str = "",
    summary: str = "",
    skip_metrics_merge_read: bool = False,
) -> bool:
    """Persist full_session to Supabase. Returns True when cloud write succeeds.

    Refuses (returns False) while a cloud read failure is unresolved: the session may not hold
    the user's saved data, and writing it could replace newer data with stale or empty state.
    """
    if not state:
        return False
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return False
    if not cloud_storage_enabled():
        return False
    failure = cloud_read_failure()
    if failure is not None:
        ss = _streamlit_session()
        try:
            if ss is not None:
                ss[CLOUD_WRITE_BLOCKED_KEY] = {"reason": "cloud_read_failed", "since": failure.get("at")}
        except Exception:
            pass
        _record_cloud_write_error("cloud storage could not be read, so writing was refused")
        return False
    try:
        storage, _ = _import_storage()
        app_key = storage.normalize_app_key(_cloud_storage_app_id(app_id))
        storage.save_current_state(
            app_key,
            page=page or "",
            summary=summary or "Last session",
            metrics={FULL_SESSION_KEY: copy.deepcopy(state)},
            skip_metrics_merge_read=skip_metrics_merge_read,
        )
        invalidate_cloud_full_session_cache(app_id)
        _record_cloud_write_error(None)
        return True
    except Exception as exc:
        _record_cloud_write_error(exc)
        return False


def _record_cloud_write_error(exc: BaseException | str | None) -> None:
    """Keep why the last full_session write failed (URLs and keys stripped) for save messages."""
    ss = _streamlit_session()
    if ss is None:
        return
    try:
        if exc is None:
            ss.pop(CLOUD_WRITE_ERROR_KEY, None)
            return
        if isinstance(exc, str):
            ss[CLOUD_WRITE_ERROR_KEY] = exc
            return
        detail = re.sub(r"https?://\S+", "<cloud>", str(exc))
        detail = re.sub(r"\b(?:sb_\w+|ey[\w-]{10,}\.[\w.-]+)", "<key>", detail)[:200]
        ss[CLOUD_WRITE_ERROR_KEY] = f"{type(exc).__name__}: {detail}"
    except Exception:
        pass


def cloud_write_error_message(ss: Any = None) -> str:
    """Why the last full_session write failed; empty when it succeeded."""
    ss = ss if ss is not None else _streamlit_session()
    try:
        return str((ss or {}).get(CLOUD_WRITE_ERROR_KEY) or "")
    except Exception:
        return ""


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
