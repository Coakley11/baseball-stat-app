"""Protect saved drafts / league contexts from accidental partial-save overwrites."""

from __future__ import annotations

import copy
import json
from typing import Any


def _utc_now_iso() -> str:
    try:
        from activity_time import utc_now_iso

        return utc_now_iso()
    except ImportError:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


DRAFT_ARCHIVE_KEY = "draft_archive_teams"
LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"
ACTIVE_DRAFT_ARCHIVE_KEY = "active_draft_archive_id"
try:
    from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY
except ImportError:
    DELETED_DRAFT_ARCHIVE_IDS_KEY = "_deleted_draft_archive_ids"

PROTECTED_WORKFLOW_PERSIST_KEYS: tuple[str, ...] = (
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    ACTIVE_DRAFT_ARCHIVE_KEY,
)

WORKFLOW_PERSIST_ALLOW_CLEAR_KEY = "_suite_allow_workflow_persist_clear"

AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY = "_suite_auth_migration_writeback_attempted"
AUTH_MIGRATION_WRITEBACK_OK_KEY = "_suite_auth_migration_writeback_ok"
AUTH_MIGRATION_WRITEBACK_TRACE_KEY = "_suite_auth_migration_writeback_trace"
AUTH_MIGRATION_WRITEBACK_FORCE_KEY = "_suite_auth_migration_writeback_force"
AUTH_RESTORE_CYCLE_COMPLETE_KEY = "_suite_auth_restore_cycle_complete"
WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY = "_suite_draft_archive_prewrite_backup"
ACTIVE_DRAFT_RESTORE_TRACE_KEY = "_suite_active_draft_restore_trace"
WORKFLOW_CLOUD_DRAFT_ARCHIVE_BACKUP_KEY = "_suite_cloud_draft_archive_prewrite_backup"
WORKFLOW_DRAFT_ARCHIVE_HISTORY_KEY = "_suite_draft_archive_version_history"
DRAFT_ARCHIVE_HISTORY_MAX = 8

_EXPLICIT_WORKFLOW_CLEAR_REASONS = frozenset(
    {
        "draft_archive_cleared",
        "draft_archive_deleted",
        "league_context_deleted",
        "suite_reset",
        "reset_user_state",
        "user_reset",
        "workflow_library_sanitized",
    }
)


def mark_workflow_persist_authoritative(session: dict[str, Any]) -> None:
    """Call after intentional draft archive or league-context mutations."""
    session[WORKFLOW_PERSIST_ALLOW_CLEAR_KEY] = True


def is_draft_library_mutation_save_reason(reason: str) -> bool:
    """True when a save should carry draft_archive_teams / league contexts to disk+cloud."""
    raw = str(reason or "").strip()
    if not raw:
        return False
    base = raw[:-6] if raw.endswith("_retry") else raw
    return base in {
        "draft_archive_saved",
        "draft_archive_renamed",
        "draft_archive_duplicated",
        "draft_archive_deleted",
        "draft_archive_cleared",
        "simulator_league_context_saved",
        "live_draft_league_context_saved",
        "imported_league_context_saved",
        "manual_save_library_sync",
        "league_context_activated",
        "probe_test_draft_saved",
        "workflow_library_sanitized",
        "authenticated_migration_writeback",
        "team_claimed",
        "league_invite_sent",
        "admin_draft_archive_repair",
    }


def inject_session_draft_library_into_save_state(
    state: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    """Copy live session draft library keys into the outbound save blob."""
    out = dict(state or {})
    allow_clear = bool(session.get(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY))
    for key in PROTECTED_WORKFLOW_PERSIST_KEYS:
        session_val = session.get(key)
        if protected_workflow_nonempty(key, session_val):
            try:
                out[key] = copy.deepcopy(session_val)
            except Exception:
                out[key] = session_val
        elif allow_clear and key == DRAFT_ARCHIVE_KEY and isinstance(session_val, list):
            out[key] = copy.deepcopy(session_val)
        elif key not in out and protected_workflow_nonempty(key, out.get(key)):
            continue
    tombstones = session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY)
    if isinstance(tombstones, list) and tombstones:
        try:
            out[DELETED_DRAFT_ARCHIVE_IDS_KEY] = copy.deepcopy(tombstones)
        except Exception:
            out[DELETED_DRAFT_ARCHIVE_IDS_KEY] = list(tombstones)
    return out


def _draft_archive_nonempty(val: Any) -> bool:
    return isinstance(val, list) and len(val) > 0


def _league_context_store_nonempty(val: Any) -> bool:
    if not isinstance(val, dict):
        return False
    contexts = val.get("contexts")
    return isinstance(contexts, dict) and len(contexts) > 0


def protected_workflow_nonempty(key: str, val: Any) -> bool:
    if key == DRAFT_ARCHIVE_KEY:
        return _draft_archive_nonempty(val)
    if key == LEAGUE_CONTEXT_STATE_KEY:
        return _league_context_store_nonempty(val)
    if key == ACTIVE_DRAFT_ARCHIVE_KEY:
        return bool(str(val or "").strip())
    return bool(val)


def count_draft_archives(val: Any) -> int:
    return len(val) if isinstance(val, list) else 0


def count_league_contexts(val: Any) -> int:
    if not isinstance(val, dict):
        return 0
    contexts = val.get("contexts")
    return len(contexts) if isinstance(contexts, dict) else 0


def workflow_richness(key: str, val: Any) -> int:
    """Higher means richer workflow snapshot (used to prefer session over stale blobs)."""
    if key == DRAFT_ARCHIVE_KEY:
        return count_draft_archives(val)
    if key == LEAGUE_CONTEXT_STATE_KEY:
        return count_league_contexts(val)
    if key == ACTIVE_DRAFT_ARCHIVE_KEY:
        return 1 if str(val or "").strip() else 0
    return 0


def should_keep_session_workflow_over_blob(key: str, session_val: Any, blob_val: Any) -> bool:
    """Keep in-memory workflow data when it is at least as rich as an incoming blob field."""
    if key not in PROTECTED_WORKFLOW_PERSIST_KEYS:
        return False
    session_score = workflow_richness(key, session_val)
    if session_score <= 0:
        return False
    blob_score = workflow_richness(key, blob_val)
    return session_score >= blob_score


def should_skip_empty_blob_workflow_over_persisted(
    key: str,
    blob_val: Any,
    *,
    app_id: str = "baseball",
    st: Any | None = None,
) -> bool:
    """On cold restore, do not apply an empty/stale blob field over richer disk/cloud data."""
    if key not in PROTECTED_WORKFLOW_PERSIST_KEYS:
        return False
    blob_score = workflow_richness(key, blob_val)
    if blob_score > 0:
        return False
    disk_state = _load_disk_workflow_snapshot(app_id)
    disk_score = workflow_richness(key, disk_state.get(key))
    cloud_state = _load_cloud_workflow_snapshot(app_id, st) if st is not None else {}
    cloud_score = workflow_richness(key, cloud_state.get(key))
    return max(disk_score, cloud_score) > blob_score


def _session_allows_workflow_clear(session: dict[str, Any], save_reason: str) -> bool:
    if session.get(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY):
        return True
    return str(save_reason or "").strip() in _EXPLICIT_WORKFLOW_CLEAR_REASONS


def _session_workflow_authoritative(session: dict[str, Any], key: str) -> bool:
    """True when the live session intentionally owns this workflow key."""
    if key not in session:
        return False
    if key == DRAFT_ARCHIVE_KEY:
        return _draft_archive_nonempty(session.get(key))
    if key == LEAGUE_CONTEXT_STATE_KEY:
        return _league_context_store_nonempty(session.get(key))
    return True


def _load_disk_workflow_snapshot(
    app_id: str,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(session, dict):
        durable = _load_durable_workflow_snapshot(session, app_id, st=None)
        if durable:
            return durable
    try:
        from suite_user_persistence import _load_raw

        state, _, _ = _load_raw(app_id)
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    return {}


def _load_durable_workflow_snapshot(
    session: dict[str, Any],
    app_id: str = "baseball",
    *,
    st: Any | None = None,
) -> dict[str, Any]:
    """Union workflow keys from all migration disk paths and cloud fallback rows."""
    blobs: list[dict[str, Any]] = []
    for ws in _disk_migration_candidate_workspace_ids(session):
        disk = _load_disk_workflow_at_workspace(app_id, ws)
        if disk:
            blobs.append(disk)
    if st is not None:
        cloud = _load_cloud_workflow_snapshot(app_id, st)
        if cloud:
            blobs.append(cloud)
    if not blobs:
        return {}
    return _merge_cloud_workflow_blobs(*blobs)


def summarize_durable_draft_sources(
    session: dict[str, Any],
    app_id: str = "baseball",
    *,
    st: Any | None = None,
) -> dict[str, Any]:
    """Read-only: max recoverable draft counts across session, disk paths, cloud, migration scan."""
    session_count = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    disk_counts: dict[str, int] = {}
    best_disk = 0
    for ws in _disk_migration_candidate_workspace_ids(session):
        disk_state = _load_disk_workflow_at_workspace(app_id, ws)
        n = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
        disk_counts[ws] = n
        best_disk = max(best_disk, n)
    cloud_count = 0
    if st is not None:
        live_probe = read_live_cloud_draft_probe(st, app_id)
        cloud_count = int(live_probe.get("draft_archive_count") or 0)
        if cloud_count <= 0:
            try:
                from suite_workspace import get_active_workspace_id

                probe = probe_cloud_workflow_for_workspace(str(get_active_workspace_id(st=st)))
                cloud_count = int(probe.get("draft_archive_count") or 0)
            except Exception:
                cloud_state = _load_cloud_workflow_snapshot(app_id, st)
                cloud_count = count_draft_archives(cloud_state.get(DRAFT_ARCHIVE_KEY))
    migration_recoverable = 0
    try:
        discovery = discover_workflow_migration_sources(session, app_id=app_id)
        migration_recoverable = int(discovery.get("recoverable_draft_count") or 0)
    except Exception:
        pass
    max_count = max(session_count, best_disk, cloud_count, migration_recoverable)
    return {
        "session_count": session_count,
        "disk_max": best_disk,
        "disk_by_workspace": disk_counts,
        "cloud_count": cloud_count,
        "migration_recoverable": migration_recoverable,
        "max_draft_count": max_count,
    }


def read_live_cloud_draft_probe(st: Any | None, app_id: str = "baseball") -> dict[str, Any]:
    """Fresh Supabase read of draft_archive_teams for the active workspace (not session cache)."""
    out: dict[str, Any] = {
        "cloud_app_key": "",
        "workspace_id": "",
        "draft_archive_count": 0,
        "row_found": False,
        "updated_at": None,
        "error": None,
    }
    if st is None or app_id != "baseball":
        return out
    try:
        from suite_workspace import get_active_workspace_id

        ws = str(get_active_workspace_id(st=st))
        out["workspace_id"] = ws
        probe = probe_cloud_workflow_for_workspace(ws, max_attempts=2)
        if isinstance(probe, dict):
            out.update(probe)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _persist_draft_archive_backup_file(
    session: dict[str, Any],
    archives: list[dict[str, Any]],
    *,
    kind: str,
    save_reason: str,
) -> str | None:
    """Write workspace-local backup JSON before shrinking draft archives."""
    if not archives:
        return None
    try:
        from suite_workspace import get_active_workspace_id, workspace_dir

        st_stub = type("_St", (), {"session_state": session})()
        ws = str(get_active_workspace_id(st=st_stub))
        path = workspace_dir(ws) / f"draft_archive_{kind}_backup.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": _utc_now_iso(),
            "reason": str(save_reason or "save"),
            "workspace_id": ws,
            "draft_count": count_draft_archives(archives),
            "draft_archive_teams": copy.deepcopy(archives),
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def append_draft_archive_version_history(
    session: dict[str, Any],
    archives: list[dict[str, Any]],
    *,
    source: str,
    save_reason: str,
    cloud_app_key: str = "",
) -> None:
    """Keep a short in-session version history before destructive draft writes."""
    if not archives:
        return
    entry = {
        "at": _utc_now_iso(),
        "source": str(source or "unknown"),
        "reason": str(save_reason or "save"),
        "cloud_app_key": str(cloud_app_key or "").strip() or None,
        "draft_count": count_draft_archives(archives),
        "draft_ids": [
            str(row.get("draft_id") or "").strip()
            for row in archives
            if isinstance(row, dict) and str(row.get("draft_id") or "").strip()
        ],
    }
    history = session.get(WORKFLOW_DRAFT_ARCHIVE_HISTORY_KEY)
    if not isinstance(history, list):
        history = []
    history = [dict(x) for x in history if isinstance(x, dict)]
    history.append(entry)
    session[WORKFLOW_DRAFT_ARCHIVE_HISTORY_KEY] = history[-DRAFT_ARCHIVE_HISTORY_MAX:]


def maybe_backup_draft_archive_before_shrink(
    session: dict[str, Any],
    state: dict[str, Any],
    *,
    app_id: str = "baseball",
    st: Any | None = None,
    save_reason: str = "",
) -> dict[str, Any]:
    """
    Snapshot durable draft archives before an outbound empty write.

    Returns backup metadata for diagnostics.
    """
    meta: dict[str, Any] = {
        "backed_up": False,
        "session_backup_count": 0,
        "cloud_backup_count": 0,
        "disk_backup_count": 0,
        "history_appended": False,
        "backup_paths": [],
    }
    outbound = count_draft_archives(state.get(DRAFT_ARCHIVE_KEY))
    if outbound > 0:
        return meta
    if _session_allows_workflow_clear(session, save_reason):
        return meta

    live_probe = read_live_cloud_draft_probe(st, app_id) if st is not None else {}
    live_cloud_count = int(live_probe.get("draft_archive_count") or 0)
    durable = summarize_durable_draft_sources(session, app_id, st=st)
    disk_max = int(durable.get("disk_max") or 0)
    max_durable = max(int(durable.get("max_draft_count") or 0), live_cloud_count, disk_max)
    if max_durable <= 0:
        return meta

    durable_blob = _load_durable_workflow_snapshot(session, app_id, st=st)
    archives = durable_blob.get(DRAFT_ARCHIVE_KEY)
    if not _draft_archive_nonempty(archives):
        if live_cloud_count > 0 and st is not None:
            cloud_blob = _load_cloud_workflow_snapshot(app_id, st)
            archives = cloud_blob.get(DRAFT_ARCHIVE_KEY)
    if not _draft_archive_nonempty(archives):
        return meta

    archive_list = [dict(x) for x in archives if isinstance(x, dict)]
    try:
        session[WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY] = copy.deepcopy(archive_list)
    except Exception:
        session[WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY] = list(archive_list)
    session["_suite_draft_archive_backup_at"] = _utc_now_iso()
    session["_suite_draft_archive_backup_reason"] = str(save_reason or "save")
    meta["session_backup_count"] = len(archive_list)
    meta["backed_up"] = True

    cloud_app_key = str(live_probe.get("cloud_app_key") or "").strip()
    if live_cloud_count > 0:
        try:
            session[WORKFLOW_CLOUD_DRAFT_ARCHIVE_BACKUP_KEY] = copy.deepcopy(archive_list)
            meta["cloud_backup_count"] = len(archive_list)
        except Exception:
            pass
        cloud_path = _persist_draft_archive_backup_file(
            session, archive_list, kind="cloud_prewrite", save_reason=save_reason
        )
        if cloud_path:
            meta["backup_paths"].append(cloud_path)
        append_draft_archive_version_history(
            session,
            archive_list,
            source="cloud",
            save_reason=save_reason,
            cloud_app_key=cloud_app_key,
        )
        meta["history_appended"] = True

    if disk_max > 0:
        disk_blob = _load_durable_workflow_snapshot(session, app_id, st=None)
        disk_archives = disk_blob.get(DRAFT_ARCHIVE_KEY)
        if _draft_archive_nonempty(disk_archives):
            disk_list = [dict(x) for x in disk_archives if isinstance(x, dict)]
            disk_path = _persist_draft_archive_backup_file(
                session, disk_list, kind="disk_prewrite", save_reason=save_reason
            )
            if disk_path:
                meta["backup_paths"].append(disk_path)
            meta["disk_backup_count"] = len(disk_list)
            append_draft_archive_version_history(
                session,
                disk_list,
                source="disk",
                save_reason=save_reason,
            )
    return meta


def draft_archive_shrink_blocked_reason(
    st: Any,
    app_id: str,
    state: dict[str, Any],
    *,
    save_reason: str = "",
    scope: str = "all",
) -> str | None:
    """Block saves that would persist zero drafts over richer live cloud/disk storage."""
    if app_id != "baseball":
        return None
    reason = str(save_reason or "").strip()
    session = st.session_state
    if _session_allows_workflow_clear(session, reason):
        return None
    outbound = count_draft_archives(state.get(DRAFT_ARCHIVE_KEY))
    if outbound > 0:
        return None

    live_probe = read_live_cloud_draft_probe(st, app_id)
    live_cloud_count = int(live_probe.get("draft_archive_count") or 0)
    durable = summarize_durable_draft_sources(session, app_id, st=st)
    disk_max = int(durable.get("disk_max") or 0)
    max_durable = max(int(durable.get("max_draft_count") or 0), live_cloud_count, disk_max)

    if max_durable <= 0:
        return None

    backup_meta = maybe_backup_draft_archive_before_shrink(
        session, state, app_id=app_id, st=st, save_reason=reason
    )
    session["_suite_draft_archive_wipe_guard"] = {
        "blocked": True,
        "save_reason": reason,
        "scope": scope,
        "outbound_draft_count": outbound,
        "live_cloud_draft_count": live_cloud_count,
        "disk_draft_max": disk_max,
        "max_durable_draft_count": max_durable,
        "backup": backup_meta,
        "at": _utc_now_iso(),
    }

    if reason == "page_change":
        if live_cloud_count > 0:
            return "page_change_empty_draft_archive_live_cloud_blocked"
        if disk_max > 0:
            return "page_change_empty_draft_archive_disk_blocked"
        return "page_change_empty_draft_archive_blocked"
    if live_cloud_count > 0 and outbound == 0:
        return "empty_outgoing_would_erase_live_cloud_drafts"
    return "empty_workflow_would_erase_durable_drafts"


def maybe_backup_draft_archive_prewrite(
    session: dict[str, Any],
    state: dict[str, Any],
    *,
    app_id: str = "baseball",
    st: Any | None = None,
    save_reason: str = "",
) -> None:
    """Retain last non-empty draft_archive_teams before an outbound empty write."""
    maybe_backup_draft_archive_before_shrink(
        session, state, app_id=app_id, st=st, save_reason=save_reason
    )


def workflow_empty_save_blocked_reason(
    st: Any,
    app_id: str,
    state: dict[str, Any],
    *,
    save_reason: str = "",
    scope: str = "all",
) -> str | None:
    """Block saves that would persist zero drafts over richer durable storage."""
    if app_id != "baseball":
        return None
    reason = str(save_reason or "").strip()
    session = st.session_state
    if _session_allows_workflow_clear(session, reason):
        return None
    if _is_force_save_cloud_reason(reason) and reason not in ("page_change", "autosave"):
        return None

    try:
        from suite_auth import auth_session_complete, is_auth_enabled

        auth_enabled = is_auth_enabled()
        signed_in = auth_session_complete(session) if auth_enabled else True
    except ImportError:
        auth_enabled = False
        signed_in = True
    if scope == "cloud" and reason == "page_change" and auth_enabled:
        if not session.get(AUTH_RESTORE_CYCLE_COMPLETE_KEY):
            return "auth_restore_incomplete_page_change_cloud_blocked"
    if reason == "page_change" and auth_enabled and not signed_in:
        outbound = count_draft_archives(state.get(DRAFT_ARCHIVE_KEY))
        if outbound <= 0:
            durable = summarize_durable_draft_sources(session, app_id, st=st)
            if int(durable.get("max_draft_count") or 0) > 0:
                maybe_backup_draft_archive_before_shrink(
                    session, state, app_id=app_id, st=st, save_reason=reason
                )
                return "signed_out_page_change_would_erase_durable_drafts"

    shrink_block = draft_archive_shrink_blocked_reason(
        st, app_id, state, save_reason=reason, scope=scope
    )
    if shrink_block:
        return shrink_block

    return None


def _is_force_save_cloud_reason(reason: str) -> bool:
    try:
        from suite_user_persistence import _is_force_save_cloud_reason as _impl

        return _impl(reason)
    except ImportError:
        return False


def _full_session_blob_from_storage_app_key(storage_app_key: str) -> dict[str, Any]:
    """Load metrics.full_session for an explicit scoped cloud app key (e.g. baseball__coakley11)."""
    try:
        import suite_storage_supabase as storage

        row = storage.load_current_state_for_app(storage_app_key)
        if not isinstance(row, dict):
            return {}
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            return {}
        blob = metrics.get("full_session")
        return copy.deepcopy(blob) if isinstance(blob, dict) else {}
    except Exception:
        return {}


def _authenticated_cloud_migration_eligible(session: dict[str, Any]) -> bool:
    """Admin-only cross-user cloud migration (Daniel recovery). Never for child accounts."""
    try:
        from suite_auth import is_auth_enabled, is_authenticated
        from suite_workspace_registry import is_admin_account

        return bool(
            is_auth_enabled()
            and is_authenticated(session)
            and is_admin_account(session_state=session)
        )
    except ImportError:
        return False


def _cloud_app_keys_to_scan_for_migration(app_id: str, session: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (workspace_id, cloud_app_key) pairs to scan for draft migration."""
    from suite_workspace import DEFAULT_WORKSPACE_ID, get_active_workspace_id, normalize_workspace_id, scoped_cloud_app_id

    keys: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(ws: str) -> None:
        ws_norm = normalize_workspace_id(str(ws or "").strip())
        if not ws_norm:
            return
        cloud_key = scoped_cloud_app_id(app_id, ws_norm)
        if cloud_key in seen:
            return
        seen.add(cloud_key)
        keys.append((ws_norm, cloud_key))

    try:
        st_stub = type("_St", (), {"session_state": session})()
        add(get_active_workspace_id(st=st_stub))
    except Exception:
        add(str(session.get("_suite_active_workspace_id") or "daniel"))
    add(DEFAULT_WORKSPACE_ID)
    for fb_ws in _cloud_workflow_fallback_workspace_ids(session):
        add(fb_ws)
    try:
        from suite_auth import allowed_workspaces_for_session, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session):
            for ws in allowed_workspaces_for_session(session):
                add(ws)
    except ImportError:
        pass
    for alias in ("daniel_cohen11",):
        add(alias)
    return keys


def _disk_migration_candidate_workspace_ids(session: dict[str, Any]) -> list[str]:
    """Workspace disk profiles that may hold pre-migration saved drafts."""
    from suite_workspace import DEFAULT_WORKSPACE_ID, get_active_workspace_id, normalize_workspace_id

    ids: list[str] = []
    seen: set[str] = set()

    def add(ws: str) -> None:
        ws_norm = normalize_workspace_id(str(ws or "").strip())
        if ws_norm and ws_norm not in seen:
            seen.add(ws_norm)
            ids.append(ws_norm)

    try:
        st_stub = type("_St", (), {"session_state": session})()
        add(get_active_workspace_id(st=st_stub))
    except Exception:
        add(str(session.get("_suite_active_workspace_id") or "daniel"))
    add(DEFAULT_WORKSPACE_ID)
    add("daniel_cohen11")
    for fb_ws in _cloud_workflow_fallback_workspace_ids(session):
        add(fb_ws)
    try:
        from suite_auth import allowed_workspaces_for_session, is_auth_enabled, is_authenticated

        if is_auth_enabled() and is_authenticated(session):
            for ws in allowed_workspaces_for_session(session):
                add(ws)
    except ImportError:
        pass
    return ids


def _load_disk_workflow_at_workspace(app_id: str, workspace_id: str) -> dict[str, Any]:
    try:
        from suite_user_persistence import _load_raw

        state, _, _ = _load_raw(app_id, workspace_id)
        if isinstance(state, dict) and state:
            return state
    except Exception:
        pass
    return {}


def _draft_names_from_workflow_blob(blob: dict[str, Any] | None) -> list[str]:
    if not isinstance(blob, dict):
        return []
    archives = blob.get(DRAFT_ARCHIVE_KEY)
    if not isinstance(archives, list):
        return []
    names: list[str] = []
    for row in archives:
        if not isinstance(row, dict):
            continue
        label = str(row.get("draft_name") or row.get("draft_id") or "").strip()
        if label:
            names.append(label)
    return names


def _load_authenticated_migration_cloud_blobs(app_id: str, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Every full_session blob on migration cloud keys — all user_ids, not only the signed-in row."""
    try:
        from suite_storage_config import cloud_storage_enabled

        if not cloud_storage_enabled():
            return []
    except ImportError:
        return []
    try:
        import suite_storage_supabase as storage
    except ImportError:
        return []

    blobs: list[dict[str, Any]] = []
    seen_sigs: set[tuple[str, str, int]] = set()
    for _ws, cloud_key in _cloud_app_keys_to_scan_for_migration(app_id, session):
        try:
            candidates = storage.load_all_full_session_migration_candidates(cloud_key)
        except Exception:
            continue
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            blob = cand.get("blob")
            if not isinstance(blob, dict) or not blob:
                continue
            sig = (
                cloud_key,
                str(cand.get("user_id") or "null"),
                int(cand.get("draft_count") or 0),
            )
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            blobs.append(blob)
    return blobs


def discover_workflow_migration_sources(
    session: dict[str, Any],
    app_id: str = "baseball",
) -> dict[str, Any]:
    """
    Read-only scan: where saved drafts may live (cloud rows by user_id, disk paths).

    Used by the persistence probe and ``scripts/probe_daniel_draft_archive_sources.py``.
    """
    current_uid = str(session.get("_suite_auth_user_id") or "").strip()
    sources: list[dict[str, Any]] = []
    cloud_enabled = False
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = cloud_storage_enabled()
    except ImportError:
        pass

    if cloud_enabled:
        try:
            import suite_storage_supabase as storage

            for ws, cloud_key in _cloud_app_keys_to_scan_for_migration(app_id, session):
                for cand in storage.load_all_full_session_migration_candidates(cloud_key):
                    if not isinstance(cand, dict):
                        continue
                    blob = cand.get("blob") if isinstance(cand.get("blob"), dict) else {}
                    sources.append(
                        {
                            "source_type": "cloud",
                            "workspace_id": ws,
                            "cloud_app_key": cloud_key,
                            "user_id": cand.get("user_id"),
                            "updated_at": cand.get("updated_at"),
                            "draft_count": int(cand.get("draft_count") or 0),
                            "draft_ids": list(cand.get("draft_ids") or []),
                            "draft_names": list(cand.get("draft_names") or _draft_names_from_workflow_blob(blob)),
                        }
                    )
        except Exception as exc:
            sources.append({"source_type": "cloud", "error": str(exc)})

    try:
        from suite_user_persistence import legacy_state_file_path, state_file_path
    except ImportError:
        legacy_state_file_path = None  # type: ignore[assignment]
        state_file_path = None  # type: ignore[assignment]

    for ws in _disk_migration_candidate_workspace_ids(session):
        disk_state = _load_disk_workflow_at_workspace(app_id, ws)
        summary = summarize_cloud_workflow_blob(disk_state if isinstance(disk_state, dict) else None)
        path_str = ""
        if state_file_path is not None:
            try:
                path_str = str(state_file_path(app_id, ws))
            except Exception:
                path_str = ""
        sources.append(
            {
                "source_type": "disk",
                "workspace_id": ws,
                "path": path_str,
                "draft_count": int(summary.get("draft_archive_count") or 0),
                "draft_ids": list(summary.get("draft_ids") or []),
                "draft_names": _draft_names_from_workflow_blob(disk_state),
            }
        )

    if legacy_state_file_path is not None:
        try:
            leg_path = legacy_state_file_path(app_id)
            if leg_path.is_file():
                from suite_user_persistence import _read_json

                raw = _read_json(leg_path)
                leg_state = raw.get("state") if isinstance(raw, dict) and isinstance(raw.get("state"), dict) else {}
                summary = summarize_cloud_workflow_blob(leg_state if isinstance(leg_state, dict) else None)
                sources.append(
                    {
                        "source_type": "disk_legacy_flat",
                        "workspace_id": "legacy",
                        "path": str(leg_path),
                        "draft_count": int(summary.get("draft_archive_count") or 0),
                        "draft_ids": list(summary.get("draft_ids") or []),
                        "draft_names": _draft_names_from_workflow_blob(leg_state),
                    }
                )
        except Exception:
            pass

    historical_suite_users: list[dict[str, Any]] = []
    try:
        import suite_storage_supabase as storage
        from suite_auth import is_authenticated, resolve_auth_external_id

        ext_ids = ["daniel", "daniel_cohen11", "daniel.cohen11"]
        if is_authenticated(session):
            ext = str(resolve_auth_external_id(session) or "").strip()
            if ext and ext not in ext_ids:
                ext_ids.append(ext)
        historical_suite_users = storage.list_suite_users_by_external_ids(*ext_ids)
    except Exception:
        pass

    recoverable = max((int(s.get("draft_count") or 0) for s in sources), default=0)
    best_source = None
    if sources:
        best_source = max(sources, key=lambda s: int(s.get("draft_count") or 0))

    return {
        "current_auth_user_id": current_uid or None,
        "cloud_enabled": cloud_enabled,
        "sources": sources,
        "recoverable_draft_count": recoverable,
        "best_source": best_source,
        "historical_suite_users": historical_suite_users,
    }


def _load_legacy_null_migration_blob(app_id: str) -> dict[str, Any]:
    """Legacy pre-auth cloud drafts on unscoped Daniel baseball key (user_id IS NULL)."""
    try:
        import suite_storage_supabase as storage

        return storage.load_legacy_null_full_session_for_app(app_id)
    except Exception:
        return {}


def _merge_richer_workflow_into_state(
    out: dict[str, Any],
    incoming: dict[str, Any],
    *,
    allow_page_restore: bool = True,
) -> dict[str, Any]:
    """Union-merge protected workflow keys when incoming is richer than out."""
    if not isinstance(incoming, dict) or not incoming:
        return out
    for key in PROTECTED_WORKFLOW_PERSIST_KEYS:
        primary_score = workflow_richness(key, out.get(key))
        incoming_score = workflow_richness(key, incoming.get(key))
        if incoming_score > primary_score:
            out[key] = copy.deepcopy(incoming[key])
    if allow_page_restore:
        primary_page = str(out.get("active_page") or "").strip()
        incoming_page = str(incoming.get("active_page") or "").strip()
        if (
            (not primary_page or primary_page in _DEFAULT_STARTUP_PAGES)
            and incoming_page
            and incoming_page not in _DEFAULT_STARTUP_PAGES
            and workflow_richness(DRAFT_ARCHIVE_KEY, out.get(DRAFT_ARCHIVE_KEY)) > 0
        ):
            out["active_page"] = incoming_page
            out.setdefault("main_sidebar_page", incoming_page)
    return out


def _cloud_workflow_fallback_workspace_ids(session: dict[str, Any]) -> list[str]:
    """Extra workspace profiles to scan when the active workspace cloud row is empty."""
    try:
        from suite_auth import is_auth_enabled, is_authenticated
        from suite_workspace_registry import is_admin_account

        if is_auth_enabled() and is_authenticated(session) and not is_admin_account(session_state=session):
            return []
    except ImportError:
        pass
    try:
        from suite_workspace import DEFAULT_WORKSPACE_ID, get_active_workspace_id, normalize_workspace_id

        active = normalize_workspace_id(
            get_active_workspace_id(st=type("_St", (), {"session_state": session})())
        )
    except Exception:
        active = normalize_workspace_id(str(session.get("_suite_active_workspace_id") or ""))

    fallbacks: list[str] = []
    if active and active != DEFAULT_WORKSPACE_ID:
        fallbacks.append(DEFAULT_WORKSPACE_ID)
    try:
        from suite_workspace_registry import get_owned_workspace_id

        owned = normalize_workspace_id(get_owned_workspace_id(session))
        if owned and owned not in {active, DEFAULT_WORKSPACE_ID}:
            fallbacks.append(owned)
    except ImportError:
        pass
    return fallbacks


def clear_draft_library_on_account_scope_change(session: dict[str, Any]) -> None:
    """Drop workflow library blobs when auth account scope changes; cloud restore reloads owned data."""
    from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DRAFT_ARCHIVE_KEY

    session.pop(DRAFT_ARCHIVE_KEY, None)
    session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)
    session.pop(LEAGUE_CONTEXT_STATE_KEY, None)
    session.pop("_draft_archives_repaired_from_contexts", None)
    session["_suite_workspace_force_sync"] = True


def _merge_cloud_workflow_blobs(*blobs: dict[str, Any]) -> dict[str, Any]:
    """Union-merge saved drafts and league contexts from multiple cloud full_session blobs."""
    valid = [b for b in blobs if isinstance(b, dict) and b]
    if not valid:
        return {}
    if len(valid) == 1:
        return copy.deepcopy(valid[0])
    merged_archives = _union_merge_draft_archives(*(b.get(DRAFT_ARCHIVE_KEY) for b in valid))
    merged_context = _union_merge_league_context_stores(*(b.get(LEAGUE_CONTEXT_STATE_KEY) for b in valid))
    out = copy.deepcopy(valid[0])
    if merged_archives:
        out[DRAFT_ARCHIVE_KEY] = merged_archives
    if merged_context.get("contexts"):
        out[LEAGUE_CONTEXT_STATE_KEY] = merged_context
    active_id = _resolve_active_draft_archive_id(
        session_val=None,
        incoming_val=valid[-1].get(ACTIVE_DRAFT_ARCHIVE_KEY),
        disk_val=valid[0].get(ACTIVE_DRAFT_ARCHIVE_KEY),
        cloud_val=None,
        merged_archives=merged_archives,
    )
    if active_id:
        out[ACTIVE_DRAFT_ARCHIVE_KEY] = active_id
    return out


def _load_cloud_workflow_snapshot(app_id: str, st: Any | None) -> dict[str, Any]:
    try:
        from suite_cloud_state import load_cloud_full_session
        from suite_workspace import get_active_workspace_id, normalize_workspace_id, scoped_cloud_app_id

        if st is None:
            return {}
        session = st.session_state if hasattr(st, "session_state") else {}

        if _authenticated_cloud_migration_eligible(session):
            blobs: list[dict[str, Any]] = []
            primary, _ = load_cloud_full_session(app_id)
            if isinstance(primary, dict) and primary:
                blobs.append(primary)
            for blob in _load_authenticated_migration_cloud_blobs(app_id, session):
                blobs.append(blob)
            for ws in _disk_migration_candidate_workspace_ids(session):
                disk_blob = _load_disk_workflow_at_workspace(app_id, ws)
                if disk_blob:
                    blobs.append(disk_blob)
            return _merge_cloud_workflow_blobs(*blobs)

        primary, _ = load_cloud_full_session(app_id)
        blobs: list[dict[str, Any]] = []
        if isinstance(primary, dict) and primary:
            blobs.append(primary)
        active_ws = normalize_workspace_id(
            get_active_workspace_id(st=type("_St", (), {"session_state": session})())
        )
        active_key = scoped_cloud_app_id(app_id, active_ws)
        if not count_draft_archives((primary or {}).get(DRAFT_ARCHIVE_KEY)):
            live_probe = probe_cloud_workflow_for_workspace(active_ws, max_attempts=2)
            if int(live_probe.get("draft_archive_count") or 0) > 0:
                live_blob = _full_session_blob_from_storage_app_key(active_key)
                if live_blob:
                    blobs.append(live_blob)
        for fb_ws in _cloud_workflow_fallback_workspace_ids(session):
            fb_key = scoped_cloud_app_id(app_id, fb_ws)
            if fb_key == active_key:
                continue
            fb_blob = _full_session_blob_from_storage_app_key(fb_key)
            if fb_blob:
                blobs.append(fb_blob)
        return _merge_cloud_workflow_blobs(*blobs)
    except Exception:
        pass
    return {}


def enrich_cloud_restore_state(
    app_id: str,
    st: Any,
    primary_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge workflow keys from fallback cloud rows into the primary restore blob."""
    out = copy.deepcopy(primary_state) if isinstance(primary_state, dict) else {}
    enriched = _load_cloud_workflow_snapshot(app_id, st)
    if enriched:
        out = _merge_richer_workflow_into_state(out, enriched)
    return out


def _pick_persisted_value(
    key: str,
    *,
    disk_state: dict[str, Any],
    cloud_state: dict[str, Any],
) -> tuple[Any | None, str]:
    disk_val = disk_state.get(key)
    if protected_workflow_nonempty(key, disk_val):
        return disk_val, "disk"
    cloud_val = cloud_state.get(key)
    if protected_workflow_nonempty(key, cloud_val):
        return cloud_val, "cloud"
    return None, ""


def merge_protected_workflow_into_save(
    state: dict[str, Any],
    session: dict[str, Any],
    *,
    app_id: str = "baseball",
    st: Any | None = None,
    save_reason: str = "",
) -> dict[str, Any]:
    """
    Merge saved drafts / league contexts from disk (then cloud) when a partial
    save would otherwise omit or empty them.
    """
    reason = str(save_reason or session.get("_suite_pending_save_reason") or "autosave")
    if _session_allows_workflow_clear(session, reason):
        session.pop(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, None)
        return inject_session_draft_library_into_save_state(state, session)
    if is_draft_library_mutation_save_reason(reason):
        state = inject_session_draft_library_into_save_state(state, session)

    durable_state = _load_durable_workflow_snapshot(session, app_id, st=st)
    disk_state = durable_state
    cloud_state: dict[str, Any] = {}
    merged_keys: list[str] = []
    merge_sources: dict[str, str] = {}

    for key in PROTECTED_WORKFLOW_PERSIST_KEYS:
        if _session_workflow_authoritative(session, key):
            continue
        current = state.get(key)
        if protected_workflow_nonempty(key, current):
            continue
        persisted_val, source = _pick_persisted_value(key, disk_state=disk_state, cloud_state=cloud_state)
        if persisted_val is None:
            continue
        try:
            restored = copy.deepcopy(persisted_val)
        except Exception:
            restored = persisted_val
        state[key] = restored
        session[key] = copy.deepcopy(restored)
        merged_keys.append(key)
        merge_sources[key] = source or "durable"

    if merged_keys:
        session["_suite_workflow_persist_merged_keys"] = merged_keys
        session["_suite_workflow_persist_merge_sources"] = merge_sources
        session["_suite_workflow_persist_merge_reason"] = reason
    maybe_backup_draft_archive_prewrite(session, state, app_id=app_id, st=st, save_reason=reason)
    archives = state.get(DRAFT_ARCHIVE_KEY)
    if _draft_archive_nonempty(archives):
        active_id = _resolve_active_draft_archive_id(
            session_val=session.get(ACTIVE_DRAFT_ARCHIVE_KEY),
            incoming_val=state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
            disk_val=disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
            cloud_val=cloud_state.get(ACTIVE_DRAFT_ARCHIVE_KEY) if isinstance(cloud_state, dict) else "",
            merged_archives=archives if isinstance(archives, list) else [],
        )
        if not active_id and isinstance(archives, list) and len(archives) == 1:
            active_id = str(archives[0].get("draft_id") or "").strip()
        if active_id:
            state[ACTIVE_DRAFT_ARCHIVE_KEY] = active_id
            session[ACTIVE_DRAFT_ARCHIVE_KEY] = active_id
    return state


def _archive_sort_ts(entry: dict[str, Any]) -> str:
    return str(entry.get("updated_at") or entry.get("created_at") or "")


def _deleted_draft_archive_ids(session: dict[str, Any] | None) -> set[str]:
    if not isinstance(session, dict):
        return set()
    raw = session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY)
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _merge_deleted_draft_archive_ids(*sources: Any) -> list[str]:
    merged: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        merged.update(_deleted_draft_archive_ids(source))
    return sorted(merged)


def _deleted_context_ids_from_store(store: Any) -> set[str]:
    if not isinstance(store, dict):
        return set()
    raw = store.get("deleted_context_ids")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _union_merge_draft_archives(*sources: Any, exclude_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Merge saved draft lists by draft_id — never drop drafts present on any source."""
    excluded = {str(item).strip() for item in (exclude_ids or set()) if str(item).strip()}
    by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, list):
            continue
        for raw in source:
            if not isinstance(raw, dict):
                continue
            draft_id = str(raw.get("draft_id") or "").strip()
            if not draft_id or draft_id in excluded:
                continue
            entry = copy.deepcopy(raw)
            existing = by_id.get(draft_id)
            if existing is None or _archive_sort_ts(entry) >= _archive_sort_ts(existing):
                by_id[draft_id] = entry
    return sorted(by_id.values(), key=_archive_sort_ts, reverse=True)


def _union_merge_league_context_stores(
    *sources: Any,
    exclude_context_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Merge league-context stores by league_context_id."""
    excluded = {str(item).strip() for item in (exclude_context_ids or set()) if str(item).strip()}
    deleted_context_ids: set[str] = set(excluded)
    merged: dict[str, dict[str, Any]] = {}
    active_id = ""
    schema_version = 1
    legacy_migration: dict[str, Any] | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        deleted_context_ids.update(_deleted_context_ids_from_store(source))
        schema_version = int(source.get("schema_version") or schema_version or 1)
        if isinstance(source.get("legacy_migration"), dict):
            legacy_migration = copy.deepcopy(source["legacy_migration"])
        candidate_active = str(source.get("active_league_context_id") or "").strip()
        if candidate_active and candidate_active not in deleted_context_ids:
            active_id = candidate_active
        contexts = source.get("contexts")
        if not isinstance(contexts, dict):
            continue
        for context_id, context in contexts.items():
            if not isinstance(context, dict):
                continue
            cid = str(context_id or context.get("league_context_id") or "").strip()
            if not cid or cid in deleted_context_ids:
                continue
            existing = merged.get(cid)
            if existing is None:
                merged[cid] = copy.deepcopy(context)
                continue
            existing_ts = str(existing.get("metadata", {}).get("updated_at") or "")
            incoming_ts = str(context.get("metadata", {}).get("updated_at") or "")
            if incoming_ts >= existing_ts:
                merged[cid] = copy.deepcopy(context)
    if active_id and active_id not in merged:
        active_id = next(iter(merged.keys()), "")
    out: dict[str, Any] = {
        "schema_version": schema_version,
        "contexts": merged,
        "active_league_context_id": active_id,
    }
    if deleted_context_ids:
        out["deleted_context_ids"] = sorted(deleted_context_ids)
    if legacy_migration is not None:
        out["legacy_migration"] = legacy_migration
    return out


def _resolve_active_draft_archive_id(
    *,
    session_val: Any,
    incoming_val: Any,
    disk_val: Any,
    cloud_val: Any,
    merged_archives: list[dict[str, Any]],
) -> str:
    archive_ids = {
        str(entry.get("draft_id") or "").strip()
        for entry in merged_archives
        if str(entry.get("draft_id") or "").strip()
    }
    for candidate in (
        str(session_val or "").strip(),
        str(incoming_val or "").strip(),
        str(disk_val or "").strip(),
        str(cloud_val or "").strip(),
    ):
        if candidate and candidate in archive_ids:
            return candidate
    return ""


def restore_active_draft_archive_selection(
    session: dict[str, Any],
    *,
    incoming_state: dict[str, Any] | None = None,
    cloud_state: dict[str, Any] | None = None,
    disk_state: dict[str, Any] | None = None,
    app_id: str = "baseball",
    st: Any | None = None,
    phase: str = "restore",
) -> dict[str, Any]:
    """Reconcile active_draft_archive_id after restore/hydration/sanitize."""
    incoming_state = incoming_state if isinstance(incoming_state, dict) else {}
    if cloud_state is None and st is not None:
        cloud_state = _load_cloud_workflow_snapshot(app_id, st)
    if not isinstance(cloud_state, dict):
        cloud_state = {}
    if disk_state is None:
        disk_state = _load_disk_workflow_snapshot(app_id)
    if not isinstance(disk_state, dict):
        disk_state = {}

    trace: dict[str, Any] = {
        "phase": str(phase or "restore"),
        "restore_reason": "",
        "active_source": "",
        "session_active_before": str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "cloud_active": str(cloud_state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "disk_active": str(disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "incoming_active": str(incoming_state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "visible_draft_count": 0,
        "needs_set_active_prompt": False,
    }

    try:
        from draft_archive_visibility import list_visible_draft_archives

        visible = list_visible_draft_archives(session)
    except ImportError:
        try:
            from draft_archive_state import list_draft_archives

            visible = list_draft_archives(session)
        except ImportError:
            visible = []

    visible_ids = [
        str(entry.get("draft_id") or "").strip()
        for entry in visible
        if isinstance(entry, dict) and str(entry.get("draft_id") or "").strip()
    ]
    trace["visible_draft_count"] = len(visible_ids)

    merged_archives = session.get(DRAFT_ARCHIVE_KEY)
    if not isinstance(merged_archives, list):
        merged_archives = []

    for source_name, candidate in (
        ("cloud", cloud_state.get(ACTIVE_DRAFT_ARCHIVE_KEY)),
        ("disk", disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY)),
        ("incoming", incoming_state.get(ACTIVE_DRAFT_ARCHIVE_KEY)),
        ("session", session.get(ACTIVE_DRAFT_ARCHIVE_KEY)),
    ):
        cid = str(candidate or "").strip()
        if cid and cid in visible_ids:
            session[ACTIVE_DRAFT_ARCHIVE_KEY] = cid
            trace["active_source"] = source_name
            trace["restore_reason"] = f"matched_{source_name}_active_to_visible_archive"
            trace["session_active_after"] = cid
            session.pop("_suite_active_draft_restore_prompt", None)
            session[ACTIVE_DRAFT_RESTORE_TRACE_KEY] = trace
            return trace

    resolved = _resolve_active_draft_archive_id(
        session_val=session.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        incoming_val=incoming_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        disk_val=disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        cloud_val=cloud_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        merged_archives=merged_archives,
    )
    if resolved and resolved in visible_ids:
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = resolved
        trace["active_source"] = "resolved_union"
        trace["restore_reason"] = "resolved_active_matches_visible_archive"
        trace["session_active_after"] = resolved
        session.pop("_suite_active_draft_restore_prompt", None)
        session[ACTIVE_DRAFT_RESTORE_TRACE_KEY] = trace
        return trace

    current = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    if current and current not in visible_ids:
        session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)
        trace["restore_reason"] = "cleared_stale_active_not_visible"

    if len(visible_ids) == 1:
        only_id = visible_ids[0]
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = only_id
        trace["active_source"] = "auto_single_visible"
        trace["restore_reason"] = "single_visible_draft_auto_active"
        trace["session_active_after"] = only_id
        session.pop("_suite_active_draft_restore_prompt", None)
        session[ACTIVE_DRAFT_RESTORE_TRACE_KEY] = trace
        return trace

    if len(visible_ids) > 1:
        session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)
        session["_suite_active_draft_restore_prompt"] = True
        trace["needs_set_active_prompt"] = True
        trace["restore_reason"] = "multiple_visible_drafts_no_persisted_active"
    elif not trace.get("restore_reason"):
        trace["restore_reason"] = "no_visible_saved_drafts"

    trace["session_active_after"] = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "")
    session[ACTIVE_DRAFT_RESTORE_TRACE_KEY] = trace
    return trace


def merge_protected_workflow_on_restore(
    session: dict[str, Any],
    incoming_state: dict[str, Any] | None = None,
    *,
    app_id: str = "baseball",
    st: Any | None = None,
) -> dict[str, Any]:
    """After restore, union-merge drafts/contexts from session, blob, disk, and cloud."""
    incoming_state = incoming_state if isinstance(incoming_state, dict) else {}
    disk_state = _load_disk_workflow_snapshot(app_id)
    cloud_state = _load_cloud_workflow_snapshot(app_id, st) if st is not None else {}
    try:
        from draft_archive_visibility import sanitize_workflow_blob_for_account

        disk_state = sanitize_workflow_blob_for_account(session, disk_state)
        if isinstance(incoming_state, dict) and incoming_state:
            incoming_state = sanitize_workflow_blob_for_account(session, incoming_state)
        if isinstance(cloud_state, dict) and cloud_state:
            cloud_state = sanitize_workflow_blob_for_account(session, cloud_state)
    except ImportError:
        pass
    merged_keys: list[str] = []
    merge_sources: dict[str, str] = {}

    merged_tombstones = _merge_deleted_draft_archive_ids(session, incoming_state, disk_state, cloud_state)
    if merged_tombstones:
        session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = merged_tombstones

    merged_archives = _union_merge_draft_archives(
        session.get(DRAFT_ARCHIVE_KEY),
        incoming_state.get(DRAFT_ARCHIVE_KEY),
        disk_state.get(DRAFT_ARCHIVE_KEY),
        cloud_state.get(DRAFT_ARCHIVE_KEY),
        exclude_ids=set(merged_tombstones),
    )
    if merged_archives:
        before = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
        session[DRAFT_ARCHIVE_KEY] = merged_archives
        if len(merged_archives) > before:
            merged_keys.append(DRAFT_ARCHIVE_KEY)
            merge_sources[DRAFT_ARCHIVE_KEY] = "union"

    merged_context_store = _union_merge_league_context_stores(
        session.get(LEAGUE_CONTEXT_STATE_KEY),
        incoming_state.get(LEAGUE_CONTEXT_STATE_KEY),
        disk_state.get(LEAGUE_CONTEXT_STATE_KEY),
        cloud_state.get(LEAGUE_CONTEXT_STATE_KEY),
        exclude_context_ids=_deleted_context_ids_from_store(session)
        | _deleted_context_ids_from_store(incoming_state)
        | _deleted_context_ids_from_store(disk_state)
        | _deleted_context_ids_from_store(cloud_state),
    )
    if merged_context_store.get("contexts"):
        before = count_league_contexts(session.get(LEAGUE_CONTEXT_STATE_KEY))
        session[LEAGUE_CONTEXT_STATE_KEY] = merged_context_store
        if count_league_contexts(merged_context_store) > before:
            merged_keys.append(LEAGUE_CONTEXT_STATE_KEY)
            merge_sources[LEAGUE_CONTEXT_STATE_KEY] = "union"

    active_id = _resolve_active_draft_archive_id(
        session_val=session.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        incoming_val=incoming_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        disk_val=disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        cloud_val=cloud_state.get(ACTIVE_DRAFT_ARCHIVE_KEY),
        merged_archives=merged_archives,
    )
    if active_id:
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = active_id

    if merged_keys:
        session["_suite_workflow_restore_merged_keys"] = merged_keys
        session["_suite_workflow_restore_merge_sources"] = merge_sources
    try:
        from draft_archive_visibility import sanitize_workflow_library_for_account

        sanitize_workflow_library_for_account(session, st=st, persist_cleanup=True)
    except ImportError:
        pass
    restore_active_draft_archive_selection(
        session,
        incoming_state=incoming_state,
        cloud_state=cloud_state,
        disk_state=disk_state,
        app_id=app_id,
        st=st,
        phase="merge_protected_workflow_on_restore",
    )
    return session


_DEFAULT_STARTUP_PAGES = frozenset({"Historical Explorer"})


def _maybe_restore_page_from_cloud_blob(session: dict[str, Any], cloud_state: dict[str, Any]) -> str:
    """When sync was skipped, restore a non-default cloud page instead of Historical Explorer."""
    current = str(session.get("active_page") or session.get("main_sidebar_page") or "").strip()
    if current and current not in _DEFAULT_STARTUP_PAGES:
        return ""
    cloud_page = str(cloud_state.get("active_page") or "").strip()
    if not cloud_page or cloud_page in _DEFAULT_STARTUP_PAGES:
        return ""
    session["active_page"] = cloud_page
    session["main_sidebar_page"] = cloud_page
    session["_suite_last_persisted_page"] = cloud_page
    session["_suite_page_overwrite_source"] = "cloud_workflow_hydration"
    return cloud_page


def ensure_session_workflow_hydrated(
    st: Any,
    app_id: str = "baseball",
    *,
    cloud_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hydrate saved drafts from cloud/disk when session is empty but durable storage has data.

  Runs after workspace sync (including skipped paths) so a reboot or refresh cannot leave
  an empty session that later autosaves over a non-empty cloud ``draft_archive_teams``.
    """
    session = st.session_state
    before = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    out: dict[str, Any] = {
        "hydrated": False,
        "source": "",
        "session_before": before,
        "session_after": before,
        "restored_page": "",
        "empty_startup_write_would_erase": False,
    }
    if before > 0:
        return out

    if cloud_state is None:
        cloud_state = _load_cloud_workflow_snapshot(app_id, st)
    if not isinstance(cloud_state, dict):
        cloud_state = {}

    cloud_count = count_draft_archives(cloud_state.get(DRAFT_ARCHIVE_KEY))
    disk_state = _load_disk_workflow_snapshot(app_id)
    disk_count = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))

    if cloud_count == 0 and disk_count == 0:
        return out

    out["empty_startup_write_would_erase"] = True
    session["_suite_cloud_fetch_attempted"] = True
    session["_suite_cloud_fetch_success"] = bool(cloud_count > 0 or disk_count > 0)
    merge_protected_workflow_on_restore(session, cloud_state, app_id=app_id, st=st)
    after = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    out["session_after"] = after
    if after > before:
        out["hydrated"] = True
        try:
            from draft_archive_visibility import sanitize_workflow_library_for_account

            sanitize_workflow_library_for_account(session, st=st, persist_cleanup=True)
            after = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
            out["session_after"] = after
        except ImportError:
            pass
        if cloud_count >= disk_count and cloud_count > 0:
            out["source"] = "cloud"
        elif disk_count > 0:
            out["source"] = "disk"
        else:
            out["source"] = "union"
        session["_suite_workflow_hydrated_this_run"] = True
        session["_suite_workflow_hydrate_source"] = out["source"]
        session["_suite_empty_startup_write_blocked"] = (
            "hydrated_from_cloud_before_autosave"
            if out["source"] == "cloud"
            else "hydrated_from_disk_before_autosave"
        )
        restored_page = _maybe_restore_page_from_cloud_blob(session, cloud_state)
        if restored_page:
            out["restored_page"] = restored_page
        restore_active_draft_archive_selection(
            session,
            cloud_state=cloud_state,
            disk_state=disk_state,
            app_id=app_id,
            st=st,
            phase="ensure_session_workflow_hydrated",
        )
        active_trace = session.get(ACTIVE_DRAFT_RESTORE_TRACE_KEY)
        if isinstance(active_trace, dict):
            out["active_restore_reason"] = active_trace.get("restore_reason")
            out["active_restore_source"] = active_trace.get("active_source")
    return out


def workflow_counts_from_session(session: dict[str, Any]) -> dict[str, int]:
    draft_archive_count = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    league_context_count = count_league_contexts(session.get(LEAGUE_CONTEXT_STATE_KEY))
    return {
        "draft_archive_count": draft_archive_count,
        "league_context_count": league_context_count,
        "saved_drafts": draft_archive_count,
        "league_contexts": league_context_count,
    }


def resolve_restore_source_label(session: dict[str, Any]) -> str:
    raw = str(
        session.get("_suite_persist_last_restore_source")
        or session.get("_suite_restore_pick_source")
        or ""
    ).strip().lower()
    if raw == "cloud":
        return "cloud"
    if raw == "disk":
        return "disk"
    if raw in ("none", ""):
        return "none"
    return raw


def _resolve_workspace_id_for_cloud_probe(
    workspace_id: str = "",
    *,
    session: dict[str, Any] | None = None,
) -> str:
    ws = str(workspace_id or "").strip()
    if ws:
        return ws
    ss: dict[str, Any] | None = session if isinstance(session, dict) else None
    if ss is None:
        try:
            import streamlit as st  # noqa: WPS433

            ss = st.session_state
        except Exception:
            ss = None
    if isinstance(ss, dict):
        try:
            from suite_workspace import get_active_workspace_id

            return str(get_active_workspace_id(st=type("_St", (), {"session_state": ss})()))
        except Exception:
            pass
        return str(ss.get("_suite_active_workspace_id") or ss.get("_suite_owned_workspace_id") or "daniel")
    return "daniel"


def verify_cloud_draft_library_readback(
    app_id: str = "baseball",
    *,
    min_drafts: int = 1,
    expected_draft_id: str = "",
    workspace_id: str = "",
    cloud_app_key: str = "",
    expected_draft_count: int | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fresh Supabase readback after a draft-library write — confirms drafts landed."""
    out: dict[str, Any] = {
        "ok": False,
        "draft_count": 0,
        "cloud_app_key": "",
        "workspace_id": "",
        "scope_user_id": None,
        "selected_row_user_id": None,
        "row_found": False,
        "draft_ids": [],
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
        from suite_cloud_state import invalidate_cloud_full_session_cache

        invalidate_cloud_full_session_cache(app_id)
    except Exception:
        pass
    ws = _resolve_workspace_id_for_cloud_probe(workspace_id, session=session)
    out["workspace_id"] = ws
    app_key = str(cloud_app_key or "").strip()
    if not app_key:
        try:
            from suite_workspace import scoped_cloud_app_id

            app_key = scoped_cloud_app_id(app_id, ws)
        except Exception as exc:
            out["error"] = str(exc)
            return out
    out["cloud_app_key"] = app_key
    try:
        from suite_storage_supabase import inspect_cloud_state_rows

        inspection = inspect_cloud_state_rows(app_key)
        out["row_inspection"] = inspection
        out["scope_user_id"] = inspection.get("scope_user_id")
        out["selected_row_user_id"] = inspection.get("selected_row_user_id")
    except Exception:
        pass
    try:
        from suite_cloud_state import FULL_SESSION_KEY, _import_storage

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
        summary = summarize_cloud_workflow_blob(blob if isinstance(blob, dict) else None)
        out["draft_count"] = int(summary.get("draft_archive_count") or 0)
        out["draft_ids"] = list(summary.get("draft_ids") or [])
        out["ok"] = out["draft_count"] >= max(0, int(min_drafts or 0))
        expected = str(expected_draft_id or "").strip()
        if out["ok"] and expected and expected not in set(out["draft_ids"]):
            out["ok"] = False
            out["error"] = f"expected_draft_id_missing:{expected}"
        if expected_draft_count is not None and out["draft_count"] != int(expected_draft_count):
            out["ok"] = False
            out["error"] = (
                f"readback_draft_count_mismatch:{out['draft_count']}_expected_{int(expected_draft_count)}"
            )
        if not out["ok"] and not out["error"]:
            out["error"] = f"readback_draft_count_{out['draft_count']}_lt_{min_drafts}"
    except Exception as exc:
        out["error"] = str(exc)
    return out


def record_draft_library_readback(session: dict[str, Any], readback: dict[str, Any]) -> None:
    """Store readback results on session for durability badge + save trace."""
    session["_suite_draft_library_readback_at"] = _utc_now_iso() if readback.get("ok") else ""
    session["_suite_draft_library_readback_count"] = int(readback.get("draft_count") or 0)
    session["_suite_draft_library_readback_ok"] = bool(readback.get("ok"))
    session["_suite_draft_library_readback_error"] = str(readback.get("error") or "")
    if readback.get("ok"):
        session["_suite_draft_library_cloud_verified_at"] = session.get("_suite_draft_library_readback_at")
    else:
        session.pop("_suite_draft_library_cloud_verified_at", None)


def evaluate_cloud_durability_status(session: dict[str, Any]) -> dict[str, Any]:
    """Whether saved drafts are verified durable in cloud (readback required)."""
    cloud_enabled = False
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = bool(cloud_storage_enabled())
    except ImportError:
        pass
    if not cloud_enabled:
        return {
            "cloud_enabled": False,
            "durable_persistence": False,
            "cloud_write_verified": False,
            "durability_label": "Temporary local session only — data will be lost after app reboot",
            "durability_warning": (
                "Temporary local session only — app data will be lost after reboot. "
                "Cloud storage is not configured in this deployment."
            ),
        }

    auth_enabled = False
    authenticated = False
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        auth_enabled = bool(is_auth_enabled())
        authenticated = bool(is_authenticated(session))
    except ImportError:
        pass
    local_demo = bool(auth_enabled and not authenticated)

    cloud_probe: dict[str, Any] = {}
    try:
        from suite_workspace import get_active_workspace_id

        ws = str(get_active_workspace_id(st=type("_St", (), {"session_state": session})()))
        cloud_probe = probe_cloud_workflow_for_workspace(ws)
    except Exception:
        pass
    row_found = bool(cloud_probe.get("row_found"))
    cloud_drafts = int(cloud_probe.get("draft_archive_count") or 0)
    session_drafts = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    readback_ok = bool(session.get("_suite_draft_library_readback_ok"))
    readback_count = int(session.get("_suite_draft_library_readback_count") or 0)

    # Durable ONLY when cloud readback confirms drafts exist now — never from payload bytes
    # or a generic cloud write flag alone (those can succeed while draft_archive_teams is empty).
    cloud_write_verified = cloud_drafts > 0

    if local_demo:
        if cloud_drafts > 0:
            return {
                "cloud_enabled": True,
                "durable_persistence": False,
                "cloud_write_verified": False,
                "cloud_row_found": row_found,
                "cloud_saved_draft_count": cloud_drafts,
                "durability_label": (
                    "Demo mode — drafts may be in cloud (null user_id row). "
                    "Sign in for account-scoped durability."
                ),
                "durability_warning": (
                    "You are not signed in. Phone/demo saves use a separate Supabase row "
                    "(user_id null) from your signed-in account on other devices. "
                    "Sign in to scope saved drafts to your account."
                ),
            }
        return {
            "cloud_enabled": True,
            "durable_persistence": False,
            "cloud_write_verified": False,
            "cloud_row_found": row_found,
            "cloud_saved_draft_count": cloud_drafts,
            "durability_label": "Not durable — sign in for account-scoped saved drafts",
            "durability_warning": (
                "Local/demo mode does not scope saves to your account. "
                "Sign in so saved drafts restore on every device after reboot."
            ),
        }

    if cloud_write_verified:
        label = "Durable — saved drafts verified in cloud (survives app reboot)"
        if readback_ok and readback_count > 0:
            label = (
                f"Durable — {readback_count} saved draft(s) verified in cloud "
                "(survives app reboot)"
            )
        return {
            "cloud_enabled": True,
            "durable_persistence": True,
            "cloud_write_verified": True,
            "cloud_row_found": row_found,
            "cloud_saved_draft_count": cloud_drafts,
            "session_saved_draft_count": session_drafts,
            "durability_label": label,
            "durability_warning": "",
        }

    last_error = str(
        session.get("_suite_draft_library_readback_error")
        or session.get("_suite_persist_last_cloud_error")
        or session.get("_draft_archive_persist_error")
        or session.get("_suite_autosave_cloud_blocked_reason")
        or ""
    ).strip()
    payload_bytes = session.get("_suite_last_cloud_payload_bytes")
    warning = (
        "Cloud storage is configured, but no saved drafts are present in the cloud blob. "
        "A large cloud write (page state) does not mean drafts were saved — use Save Draft "
        "and confirm cloud readback shows draft count > 0."
    )
    if payload_bytes:
        warning += f" Last payload was {payload_bytes} bytes."
    if last_error:
        warning += f" Last error: `{last_error}`"
    return {
        "cloud_enabled": True,
        "durable_persistence": False,
        "cloud_write_verified": False,
        "cloud_row_found": row_found,
        "cloud_saved_draft_count": cloud_drafts,
        "session_saved_draft_count": session_drafts,
        "durability_label": "Not durable yet — no saved drafts verified in cloud",
        "durability_warning": warning,
    }


def build_saved_draft_library_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Read-only diagnostics for Saved Draft Library header."""
    counts = workflow_counts_from_session(session)
    restore_source = resolve_restore_source_label(session)
    restore_label = {
        "cloud": "Loaded from **cloud**",
        "disk": "Loaded from **disk**",
        "none": "No workspace restore yet this session",
    }.get(restore_source, f"Restore source: `{restore_source}`")

    account_email = ""
    account_external_id = ""
    account_user_id = ""
    auth_enabled = False
    authenticated = False
    try:
        from suite_auth import (
            auth_session_complete,
            current_auth_email,
            is_auth_enabled,
            is_authenticated,
            resolve_auth_external_id,
        )

        auth_enabled = is_auth_enabled()
        authenticated = bool(auth_session_complete(session))
        account_email = current_auth_email(session) if is_authenticated(session) else ""
        account_external_id = resolve_auth_external_id(session) if is_authenticated(session) else ""
    except ImportError:
        pass
    try:
        if authenticated:
            from suite_user import get_account_user_id

            account_user_id = get_account_user_id()
            auth_jwt_user_id = str(session.get("_suite_auth_user_id") or "").strip()
            cloud_suite_user_id = str(session.get("_suite_cloud_user_id") or account_user_id or "").strip()
            if auth_jwt_user_id and cloud_suite_user_id and auth_jwt_user_id != cloud_suite_user_id:
                account_user_id = cloud_suite_user_id
        else:
            account_user_id = str(session.get("_suite_auth_user_id") or "")
    except ImportError:
        account_user_id = str(session.get("_suite_auth_user_id") or "")
    auth_jwt_user_id = str(session.get("_suite_auth_user_id") or "").strip()
    cloud_suite_user_id = str(session.get("_suite_cloud_user_id") or account_user_id or "").strip()
    auth_diag: dict[str, Any] = {}
    try:
        from suite_auth import build_auth_session_diagnostics

        auth_diag = build_auth_session_diagnostics(session)
    except ImportError:
        pass
    expected_cloud_user_id = ""
    if authenticated:
        try:
            from suite_user import get_account_user_id

            expected_cloud_user_id = str(get_account_user_id() or "").strip()
        except ImportError:
            expected_cloud_user_id = cloud_suite_user_id
    cloud_identity_mismatch = bool(
        authenticated
        and expected_cloud_user_id
        and cloud_suite_user_id
        and expected_cloud_user_id != cloud_suite_user_id
    )

    workspace_id = ""
    workspace_label = ""
    owned_workspace_id = ""
    cloud_app_key = ""
    local_state_path = ""
    try:
        from suite_workspace import get_active_workspace_id, workspace_label as ws_label, workspace_persistence_meta

        workspace_id = str(get_active_workspace_id(type("_St", (), {"session_state": session})()))
        workspace_label = ws_label(workspace_id)
        meta = workspace_persistence_meta("baseball", st=type("_St", (), {"session_state": session})())
        cloud_app_key = str(meta.get("cloud_app_key") or "")
        local_state_path = str(meta.get("local_state_path") or "")
    except Exception:
        workspace_id = str(session.get("_suite_active_workspace_id") or session.get("_suite_owned_workspace_id") or "")
    try:
        from suite_workspace_registry import get_owned_workspace_id, resolve_owned_workspace_id

        owned_workspace_id = str(get_owned_workspace_id(session) or "")
        if not owned_workspace_id:
            owned_workspace_id = str(resolve_owned_workspace_id(session) or "")
        if not owned_workspace_id:
            try:
                from suite_auth import account_scoped_workspace_target

                owned_workspace_id = str(account_scoped_workspace_target(session) or "")
            except ImportError:
                pass
    except ImportError:
        owned_workspace_id = str(session.get("_suite_owned_workspace_id") or "")

    restore_at = str(session.get("_suite_persist_last_restore_at") or "")
    merged_keys = list(session.get("_suite_workflow_persist_merged_keys") or [])
    merge_sources = dict(session.get("_suite_workflow_persist_merge_sources") or {})
    restore_merged = list(session.get("_suite_workflow_restore_merged_keys") or [])
    restore_merge_sources = dict(session.get("_suite_workflow_restore_merge_sources") or {})

    cloud_enabled = False
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = cloud_storage_enabled()
    except ImportError:
        pass

    disk_snapshot = _load_disk_workflow_snapshot("baseball")
    disk_summary = summarize_cloud_workflow_blob(disk_snapshot if isinstance(disk_snapshot, dict) else None)

    cloud_probe_active: dict[str, Any] = {}
    cloud_probe_owned: dict[str, Any] = {}
    cloud_probe_legacy: dict[str, Any] = {}
    if cloud_enabled:
        try:
            cloud_probe_active = probe_cloud_workflow_for_workspace(workspace_id or "daniel")
        except Exception:
            pass
        if owned_workspace_id and owned_workspace_id != workspace_id:
            try:
                cloud_probe_owned = probe_cloud_workflow_for_workspace(owned_workspace_id)
            except Exception:
                pass
        try:
            from suite_workspace import DEFAULT_WORKSPACE_ID, normalize_workspace_id

            if normalize_workspace_id(workspace_id) != DEFAULT_WORKSPACE_ID:
                cloud_probe_legacy = probe_cloud_workflow_for_workspace(DEFAULT_WORKSPACE_ID)
        except Exception:
            pass

    save_diag = session.get("_draft_library_save_diag")
    nav_diag = session.get("_draft_library_nav_diag")
    durability = evaluate_cloud_durability_status(session)

    cloud_row_inspection: dict[str, Any] = {}
    cloud_row_inspection_legacy: dict[str, Any] = {}
    if cloud_enabled and cloud_app_key:
        try:
            from suite_storage_supabase import inspect_cloud_state_rows
            from suite_workspace import DEFAULT_WORKSPACE_ID, normalize_workspace_id, scoped_cloud_app_id

            cloud_row_inspection = inspect_cloud_state_rows(cloud_app_key)
            if workspace_id and normalize_workspace_id(workspace_id) != DEFAULT_WORKSPACE_ID:
                cloud_row_inspection_legacy = inspect_cloud_state_rows(
                    scoped_cloud_app_id("baseball", DEFAULT_WORKSPACE_ID),
                    include_legacy_null=True,
                )
        except Exception:
            pass

    migration_discovery = discover_workflow_migration_sources(session, app_id="baseball")

    return {
        "account_email": account_email,
        "account_external_id": account_external_id,
        "account_user_id": account_user_id,
        "auth_jwt_user_id": auth_jwt_user_id,
        "cloud_suite_user_id": cloud_suite_user_id,
        "cloud_identity_mismatch": cloud_identity_mismatch,
        "auth_enabled": auth_enabled,
        "authenticated": authenticated,
        "workspace_id": workspace_id,
        "owned_workspace_id": owned_workspace_id,
        "workspace_label": workspace_label,
        "cloud_app_key": cloud_app_key,
        "local_state_path": local_state_path,
        "disk_saved_draft_count": int(disk_summary.get("draft_archive_count") or 0),
        "cloud_saved_draft_count_active": int(cloud_probe_active.get("draft_archive_count") or 0),
        "cloud_saved_draft_count_owned": int(cloud_probe_owned.get("draft_archive_count") or 0),
        "cloud_saved_draft_count_legacy": int(cloud_probe_legacy.get("draft_archive_count") or 0),
        "cloud_probe_active": cloud_probe_active,
        "cloud_probe_owned": cloud_probe_owned,
        "cloud_probe_legacy": cloud_probe_legacy,
        "cloud_row_inspection": cloud_row_inspection,
        "cloud_row_inspection_legacy": cloud_row_inspection_legacy,
        "migration_discovery": migration_discovery,
        "migration_recoverable_draft_count": int(migration_discovery.get("recoverable_draft_count") or 0),
        "migration_best_source": migration_discovery.get("best_source"),
        "migration_sources": list(migration_discovery.get("sources") or []),
        "historical_suite_users": list(migration_discovery.get("historical_suite_users") or []),
        "ownership_filter_note": (
            "Saved Draft Library does not filter individual drafts by owner_user_id; "
            "account scoping applies to the Supabase row (user_id) and active workspace only."
        ),
        "draft_archive_count": counts["draft_archive_count"],
        "league_context_count": counts["league_context_count"],
        "saved_drafts": counts["saved_drafts"],
        "league_contexts": counts["league_contexts"],
        "restore_source": restore_source,
        "restore_source_label": restore_label,
        "restore_at": restore_at,
        "auth_mode": "signed_in" if authenticated else "local_demo",
        "cloud_write_expected": bool(cloud_enabled),
        "durable_persistence": bool(durability.get("durable_persistence")),
        "cloud_write_verified": bool(durability.get("cloud_write_verified")),
        "durability_label": str(durability.get("durability_label") or ""),
        "durability_warning": str(durability.get("durability_warning") or ""),
        "auth_enabled_but_signed_out": bool(auth_enabled and not authenticated),
        "auth_session_flag": bool(auth_diag.get("session_flag")),
        "auth_session_complete": bool(auth_diag.get("session_complete")),
        "auth_tokens_present": bool(auth_diag.get("tokens_present")),
        "auth_last_login_error": str(auth_diag.get("last_login_error") or ""),
        "auth_last_restore_error": str(auth_diag.get("last_restore_error") or ""),
        "auth_browser_storage": auth_diag.get("browser_storage") if isinstance(auth_diag.get("browser_storage"), dict) else {},
        "restore_cloud_vs_demo_note": (
            "Sign in with your Real Account to restore authenticated cloud drafts. "
            "Unsigned sessions use the legacy demo profile and may show 0 saved drafts "
            "even when your signed-in cloud row still has data."
            if auth_enabled and not authenticated
            else (
            "Restore source is cloud, but you are in local/demo mode — empty cloud can overwrite "
            "disk saves unless workflow protection is active."
            if restore_source == "cloud" and not authenticated
            else ""
            )
        ),
        "workflow_merge_keys": merged_keys,
        "workflow_merge_sources": merge_sources,
        "workflow_restore_merged_keys": restore_merged,
        "workflow_restore_merge_sources": restore_merge_sources,
        "cloud_enabled": cloud_enabled,
        "save_diag": save_diag if isinstance(save_diag, dict) else {},
        "nav_diag": nav_diag if isinstance(nav_diag, dict) else {},
    }


_PERSISTENCE_VERDICT_LABELS = {
    "A_persistence_failed_or_never_saved": "A — not persisted (or wiped before reboot)",
    "B_restore_failed": "B — restore failed (storage has drafts, session empty)",
    "ok": "OK — session matches storage",
}


def _resolve_probe_deploy_commit() -> str:
    try:
        from suite_deploy_marker import resolve_git_commit_short

        return str(resolve_git_commit_short() or "unknown")
    except ImportError:
        return "unknown"


def _resolve_probe_auth_labels(session: dict[str, Any], diag: dict[str, Any]) -> dict[str, str]:
    """Align signed-in display with the cloud identity actually used for restore."""
    auth_enabled = bool(diag.get("auth_enabled"))
    authenticated = bool(diag.get("authenticated"))
    session_flag = bool(diag.get("auth_session_flag"))
    session_complete = bool(diag.get("auth_session_complete"))
    account_email = str(diag.get("account_email") or diag.get("account_external_id") or "").strip()
    account_user_id = str(diag.get("account_user_id") or "").strip()
    cloud_app_key = str(diag.get("cloud_app_key") or "").strip()
    workspace_id = str(diag.get("workspace_id") or "").strip() or "daniel"

    if not auth_enabled:
        return {
            "signed_in_label": "n/a (auth disabled)",
            "auth_scope_label": f"Local/demo mode · workspace `{workspace_id}`",
            "account_email_display": account_email or "—",
            "user_id_display": account_user_id or "—",
        }

    if authenticated:
        auth_jwt = str(diag.get("auth_jwt_user_id") or "").strip()
        cloud_uid = str(diag.get("cloud_suite_user_id") or account_user_id or "").strip()
        user_display = cloud_uid or account_user_id or "—"
        if auth_jwt and cloud_uid and auth_jwt != cloud_uid:
            user_display = f"{cloud_uid} (auth jwt `{auth_jwt}`)"
        return {
            "signed_in_label": "yes",
            "auth_scope_label": f"Signed in · cloud key `{cloud_app_key or '—'}`",
            "account_email_display": account_email or "—",
            "user_id_display": user_display,
        }

    if account_user_id and not account_user_id.startswith("local:"):
        scope = (
            f"Not signed in this session · cloud restore used workspace `{workspace_id}` "
            f"and user row `{account_user_id}`"
        )
        email_display = account_email or "— (sign in to refresh email)"
    else:
        scope = f"Not signed in · local/demo workspace `{workspace_id}`"
        email_display = account_email or "—"

    if session_flag and not session_complete:
        scope = (
            f"Incomplete auth session (flag set but tokens/user id missing) · workspace `{workspace_id}`"
        )
        last_err = str(diag.get("auth_last_login_error") or diag.get("auth_last_restore_error") or "").strip()
        if last_err:
            scope = f"{scope} · last error: {last_err[:120]}"

    return {
        "signed_in_label": "no",
        "auth_scope_label": scope,
        "account_email_display": email_display,
        "user_id_display": account_user_id or "—",
    }


def _resolve_cloud_restore_probe_labels(
    session: dict[str, Any],
    *,
    restore_pick_source: str,
    restore_applied: bool,
    restore_skip: str,
    session_draft_count: int,
    workflow_hydrate_source: str,
) -> tuple[bool, str, str]:
    """Consistent cloud-restore attempted/applied labels for the probe panel."""
    fetch_attempted = bool(session.get("_suite_cloud_fetch_attempted"))
    fetch_success = bool(session.get("_suite_cloud_fetch_success"))
    hydrated = bool(session.get("_suite_workflow_hydrated_this_run"))
    cloud_workspace_restored = bool(
        session.get("_cloud_workspace_restored") or session.get("_cloud_workspace_restored_this_run")
    )
    source_cloud = restore_pick_source == "cloud"
    effective = bool(
        fetch_attempted
        or hydrated
        or cloud_workspace_restored
        or (restore_applied and source_cloud)
        or (source_cloud and session_draft_count > 0)
    )

    if restore_applied and source_cloud:
        detail = "Yes — cloud blob applied on startup"
        label = "yes — workspace restore applied"
    elif hydrated:
        detail = f"Yes — drafts hydrated from {workflow_hydrate_source or 'cloud'} before autosave"
        label = f"yes — workflow hydrated ({workflow_hydrate_source or 'cloud'})"
    elif cloud_workspace_restored or (source_cloud and session_draft_count > 0):
        detail = "Yes — session drafts match cloud restore source"
        label = "yes — cloud restore source"
    elif fetch_attempted and fetch_success:
        detail = "Yes — cloud row read this session"
        label = "yes — cloud row read"
    elif fetch_attempted:
        detail = "Attempted — cloud fetch ran but returned no usable blob"
        label = "attempted — no blob"
    elif restore_skip:
        detail = f"No — restore skipped ({restore_skip})"
        label = "no"
        effective = False
    elif source_cloud:
        detail = "Yes — restore source is cloud"
        label = "yes — restore source cloud"
        effective = True
    else:
        detail = "No — no cloud restore evidence this session"
        label = "no"
        effective = False

    return effective, label, detail


def _resolve_persistence_verdict(session: dict[str, Any], startup: dict[str, Any], diag: dict[str, Any]) -> str:
    verdict = str(startup.get("persistence_verdict") or "").strip()
    if verdict:
        return verdict
    restore_applied = str(session.get("_suite_restore_decision") or "") == "applied"
    restore_skip = str(
        session.get("_suite_restore_skip_reason")
        or session.get("_suite_persist_restore_skip_reason")
        or ""
    )
    cloud_count = max(
        int(startup.get("cloud_saved_draft_count") or 0),
        int(diag.get("cloud_saved_draft_count_active") or 0),
        int(diag.get("cloud_saved_draft_count_owned") or 0),
        int(diag.get("cloud_saved_draft_count_legacy") or 0),
        int(diag.get("migration_recoverable_draft_count") or 0),
    )
    disk_count = max(
        int(startup.get("disk_saved_draft_count") or 0),
        int(diag.get("disk_saved_draft_count") or 0),
    )
    session_count = int(diag.get("draft_archive_count") or 0)
    cloud_tracked = int(startup.get("cloud_tracked_player_count") or 0)
    session_tracked = tracked_player_count_from_blob(session)
    return infer_restore_persistence_verdict(
        cloud_draft_count=cloud_count,
        disk_draft_count=disk_count,
        session_draft_count=session_count,
        cloud_tracked_count=cloud_tracked,
        session_tracked_count=session_tracked,
        restore_applied=restore_applied,
        restore_skip_reason=restore_skip,
    )


def build_persistence_probe_panel(session: dict[str, Any], *, st: Any | None = None) -> dict[str, Any]:
    """Single read-only probe for post-reboot saved-draft persistence diagnosis."""
    diag = build_saved_draft_library_diagnostics(session)
    startup = session.get("_suite_startup_restore_snapshot")
    if not isinstance(startup, dict):
        startup = {}

    active_draft_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    active_draft_name = ""
    try:
        from draft_archive_state import get_active_draft_archive

        active_entry = get_active_draft_archive(session)
        if isinstance(active_entry, dict):
            active_draft_id = active_draft_id or str(active_entry.get("draft_id") or "").strip()
            active_draft_name = str(active_entry.get("draft_name") or "").strip()
    except ImportError:
        pass

    session_draft_count = int(diag.get("draft_archive_count") or 0)
    cloud_draft_count = int(diag.get("cloud_saved_draft_count_active") or 0)
    disk_draft_count = int(diag.get("disk_saved_draft_count") or 0)
    cloud_owned_count = int(diag.get("cloud_saved_draft_count_owned") or 0)
    cloud_legacy_count = int(diag.get("cloud_saved_draft_count_legacy") or 0)
    migration_recoverable = int(diag.get("migration_recoverable_draft_count") or 0)
    cloud_any_count = max(cloud_draft_count, cloud_owned_count, cloud_legacy_count, migration_recoverable)

    verdict = _resolve_persistence_verdict(session, startup, diag)
    verdict_label = _PERSISTENCE_VERDICT_LABELS.get(verdict, verdict or "—")

    workspace_id = str(diag.get("workspace_id") or "").strip()
    owned_workspace_id = str(diag.get("owned_workspace_id") or "").strip()
    if not owned_workspace_id and bool(diag.get("authenticated")):
        try:
            from suite_workspace_registry import resolve_owned_workspace_id

            owned_workspace_id = str(resolve_owned_workspace_id(session) or "").strip()
        except ImportError:
            pass
    restored_workspace_id = str(startup.get("restored_workspace_id") or workspace_id).strip()

    restore_pick_source = str(
        session.get("_suite_restore_pick_source")
        or session.get("_suite_persist_last_restore_source")
        or diag.get("restore_source")
        or "none"
    ).strip().lower()
    restore_applied = str(session.get("_suite_restore_decision") or "") == "applied"
    restore_skip = str(
        session.get("_suite_restore_skip_reason")
        or session.get("_suite_persist_restore_skip_reason")
        or startup.get("restore_skip_reason")
        or ""
    ).strip()

    startup_cloud_drafts = int(startup.get("cloud_saved_draft_count") or cloud_draft_count)
    startup_disk_drafts = int(startup.get("disk_saved_draft_count") or disk_draft_count)

    if workspace_id and owned_workspace_id and workspace_id != owned_workspace_id:
        different_workspace = f"Yes — active `{workspace_id}` ≠ owned `{owned_workspace_id}`"
    elif restored_workspace_id and owned_workspace_id and restored_workspace_id != owned_workspace_id:
        different_workspace = f"Yes — restored `{restored_workspace_id}` ≠ owned `{owned_workspace_id}`"
    elif workspace_id and owned_workspace_id:
        different_workspace = f"No — active and owned both `{workspace_id}`"
    else:
        different_workspace = "Unknown — owned workspace not resolved"

    workflow_hydrated = bool(session.get("_suite_workflow_hydrated_this_run"))
    workflow_hydrate_source = str(session.get("_suite_workflow_hydrate_source") or "").strip()
    cloud_restore_effective, cloud_restore_attempted_label, cloud_restore_ran = (
        _resolve_cloud_restore_probe_labels(
            session,
            restore_pick_source=restore_pick_source,
            restore_applied=restore_applied,
            restore_skip=restore_skip,
            session_draft_count=session_draft_count,
            workflow_hydrate_source=workflow_hydrate_source,
        )
    )

    cloud_zero = startup_cloud_drafts <= 0
    disk_zero = startup_disk_drafts <= 0

    readback_ok = bool(session.get("_suite_draft_library_readback_ok"))
    readback_count = int(session.get("_suite_draft_library_readback_count") or 0)
    readback_error = str(session.get("_suite_draft_library_readback_error") or "").strip()
    save_readback = session.get("_suite_last_draft_save_readback")
    save_readback_count = readback_count
    save_readback_key = ""
    if isinstance(save_readback, dict):
        save_readback_count = int(
            save_readback.get("draft_count")
            or save_readback.get("draft_archive_count")
            or readback_count
        )
        save_readback_key = str(save_readback.get("cloud_app_key") or "").strip()

    cloud_restore_error = str(session.get("_suite_cloud_fetch_error") or "").strip()
    cloud_fetch_app_key = str(session.get("_suite_cloud_fetch_app_key") or "").strip()

    # Cloud write telemetry (recorded during force save / library save).
    last_save_reason = str(session.get("_suite_persist_last_save_reason") or "").strip()
    cloud_write_attempted = bool(
        session.get("_suite_persist_last_save_at")
        or session.get("_suite_last_cloud_app_key")
        or session.get(AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY)
        or isinstance(save_readback, dict)
    )
    cloud_write_ok = bool(session.get("_suite_persist_last_save_cloud"))
    cloud_write_error = str(
        session.get("_suite_persist_last_cloud_error")
        or session.get("_suite_autosave_cloud_blocked_reason")
        or readback_error
        or ""
    ).strip()
    cloud_write_app_key = str(
        session.get("_suite_last_cloud_app_key")
        or save_readback_key
        or cloud_fetch_app_key
        or diag.get("cloud_app_key")
        or ""
    ).strip()
    local_state_path = str(diag.get("local_state_path") or "").strip()
    migration_recoverable = int(diag.get("migration_recoverable_draft_count") or 0)
    migration_best = diag.get("migration_best_source")
    migration_sources = list(diag.get("migration_sources") or [])

    if cloud_any_count > 0 or disk_draft_count > 0:
        ever_persisted = (
            f"Yes — storage has drafts (cloud active {cloud_draft_count}, "
            f"owned {cloud_owned_count}, legacy {cloud_legacy_count}, "
            f"migration scan {migration_recoverable}, disk {disk_draft_count})"
        )
    elif readback_ok or save_readback_count > 0:
        ever_persisted = "Yes — save readback confirmed drafts this session"
    elif bool(diag.get("cloud_enabled")):
        ever_persisted = "No evidence — cloud and disk both show 0 saved drafts"
    else:
        ever_persisted = "Unknown — cloud storage not configured; disk-only"

    account_email = str(diag.get("account_email") or diag.get("account_external_id") or "—")
    account_user_id = str(diag.get("account_user_id") or "—")
    account_external_id = str(diag.get("account_external_id") or "—")
    allowed_workspaces: tuple[str, ...] = ()
    try:
        from suite_auth import allowed_workspaces_for_session, auth_session_complete, is_auth_enabled

        if is_auth_enabled() and auth_session_complete(session):
            allowed_workspaces = tuple(allowed_workspaces_for_session(session))
    except ImportError:
        pass
    auth_labels = _resolve_probe_auth_labels(session, diag)
    if st is not None:
        try:
            from suite_auth import build_auth_session_diagnostics

            auth_diag = build_auth_session_diagnostics(session, st=st)
            diag = dict(diag)
            diag["auth_session_flag"] = bool(auth_diag.get("session_flag"))
            diag["auth_session_complete"] = bool(auth_diag.get("session_complete"))
            diag["auth_tokens_present"] = bool(auth_diag.get("tokens_present"))
            diag["auth_last_login_error"] = str(auth_diag.get("last_login_error") or "")
            diag["auth_last_restore_error"] = str(auth_diag.get("last_restore_error") or "")
            diag["auth_browser_storage"] = (
                auth_diag.get("browser_storage")
                if isinstance(auth_diag.get("browser_storage"), dict)
                else {}
            )
            auth_labels = _resolve_probe_auth_labels(session, diag)
        except ImportError:
            pass
    persistence_key_path = (
        f"session[{DRAFT_ARCHIVE_KEY}] → disk[{DRAFT_ARCHIVE_KEY}] → "
        f"cloud metrics.full_session.{DRAFT_ARCHIVE_KEY}"
    )
    session_has_archive_key = DRAFT_ARCHIVE_KEY in session
    session_archive_len = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    empty_startup_write_blocked = str(session.get("_suite_empty_startup_write_blocked") or "").strip()

    return {
        "signed_in": bool(diag.get("authenticated")),
        "signed_in_label": auth_labels["signed_in_label"],
        "auth_scope_label": auth_labels["auth_scope_label"],
        "account_email": auth_labels["account_email_display"],
        "user_id": auth_labels["user_id_display"],
        "workspace_id": workspace_id or "—",
        "owned_workspace_id": owned_workspace_id or "—",
        "account_external_id": account_external_id or "—",
        "allowed_workspaces": allowed_workspaces,
        "cloud_identity_mismatch": bool(diag.get("cloud_identity_mismatch")),
        "auth_jwt_user_id": str(diag.get("auth_jwt_user_id") or ""),
        "cloud_suite_user_id": str(diag.get("cloud_suite_user_id") or ""),
        "cloud_app_key": str(diag.get("cloud_app_key") or cloud_write_app_key or "—"),
        "session_draft_count": session_draft_count,
        "cloud_draft_count": cloud_draft_count,
        "disk_draft_count": disk_draft_count,
        "active_draft_id": active_draft_id or "—",
        "active_draft_name": active_draft_name or "—",
        "active_restore_source": str(
            active_trace.get("active_source") or startup.get("active_restore_source") or ""
        ) or "—",
        "active_restore_reason": str(
            active_trace.get("restore_reason") or startup.get("active_restore_reason") or ""
        ) or "—",
        "active_restore_needs_prompt": bool(
            session.get("_suite_active_draft_restore_prompt")
            or active_trace.get("needs_set_active_prompt")
            or startup.get("active_restore_needs_prompt")
        ),
        "cloud_active_draft_id": str(startup.get("cloud_active_draft_id") or diag.get("cloud_active_draft_id") or "—"),
        "disk_active_draft_id": str(startup.get("disk_active_draft_id") or diag.get("disk_active_draft_id") or "—"),
        "restore_source": restore_pick_source or "none",
        "persistence_verdict": verdict,
        "persistence_verdict_label": verdict_label,
        "cloud_restore_attempted": cloud_restore_effective,
        "cloud_restore_attempted_label": cloud_restore_attempted_label,
        "cloud_restore_error": cloud_restore_error or "—",
        "cloud_write_attempted": cloud_write_attempted,
        "cloud_write_attempted_label": "yes" if cloud_write_attempted else "no",
        "cloud_write_ok": cloud_write_ok,
        "cloud_write_error": cloud_write_error or "—",
        "cloud_write_readback_count": readback_count,
        "cloud_write_readback_ok": readback_ok,
        "cloud_write_readback_error": readback_error or "—",
        "persistence_key_path": persistence_key_path,
        "persist_canonical_session_key": DRAFT_ARCHIVE_KEY,
        "session_has_draft_archive_teams": session_has_archive_key,
        "session_draft_archive_teams_len": session_archive_len,
        "empty_startup_write_blocked": empty_startup_write_blocked or "—",
        "workflow_hydrated_from_cloud": workflow_hydrated,
        "workflow_hydrate_source": workflow_hydrate_source or "—",
        "last_save_reason": last_save_reason or "—",
        "local_state_path": local_state_path or "—",
        "auth_signed_out_warning": str(diag.get("restore_cloud_vs_demo_note") or ""),
        "auth_enabled": bool(diag.get("auth_enabled")),
        "auth_enabled_but_signed_out": bool(diag.get("auth_enabled_but_signed_out")),
        "auth_session_flag": bool(diag.get("auth_session_flag")),
        "auth_session_complete": bool(diag.get("auth_session_complete")),
        "auth_tokens_present": bool(diag.get("auth_tokens_present")),
        "auth_last_login_error": str(diag.get("auth_last_login_error") or ""),
        "auth_last_restore_error": str(diag.get("auth_last_restore_error") or ""),
        "auth_browser_storage": diag.get("auth_browser_storage") if isinstance(diag.get("auth_browser_storage"), dict) else {},
        "diagnosis": {
            "Did the reboot load a different workspace?": different_workspace,
            "Did cloud restore run?": cloud_restore_ran,
            "Did cloud restore return zero drafts?": "Yes" if cloud_zero else f"No ({startup_cloud_drafts} in cloud blob)",
            "Did disk restore return zero drafts?": "Yes" if disk_zero else f"No ({startup_disk_drafts} on disk)",
            "Were my drafts ever successfully persisted?": ever_persisted,
            "Migration scan (all cloud user_ids + disk paths)": (
                f"Found **{migration_recoverable}** recoverable draft(s) across {len(migration_sources)} source(s)"
                if migration_recoverable > 0
                else f"No recoverable drafts in migration scan ({len(migration_sources)} source(s) checked)"
            ),
        },
        "cloud_draft_count_owned": cloud_owned_count,
        "cloud_draft_count_legacy": cloud_legacy_count,
        "migration_recoverable_draft_count": migration_recoverable,
        "migration_best_source": migration_best if isinstance(migration_best, dict) else None,
        "migration_sources": migration_sources,
        "historical_suite_users": list(diag.get("historical_suite_users") or []),
        "deploy_commit": _resolve_probe_deploy_commit(),
        "restore_skip_reason": restore_skip or None,
        "restore_applied": restore_applied,
        "migration_writeback_attempted": bool(session.get(AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY)),
        "migration_writeback_ok": bool(session.get(AUTH_MIGRATION_WRITEBACK_OK_KEY)),
        "migration_writeback_trace": (
            session.get(AUTH_MIGRATION_WRITEBACK_TRACE_KEY)
            if isinstance(session.get(AUTH_MIGRATION_WRITEBACK_TRACE_KEY), dict)
            else None
        ),
        "stranded_disk_reconcile": (
            session.get("_suite_stranded_disk_reconcile")
            if isinstance(session.get("_suite_stranded_disk_reconcile"), dict)
            else None
        ),
        "pending_league_invites": list(session.get("_suite_pending_league_invites") or []),
    }


AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY = "_suite_auth_migration_writeback_attempted"
AUTH_MIGRATION_WRITEBACK_OK_KEY = "_suite_auth_migration_writeback_ok"
AUTH_MIGRATION_WRITEBACK_TRACE_KEY = "_suite_auth_migration_writeback_trace"
AUTH_MIGRATION_WRITEBACK_FORCE_KEY = "_suite_auth_migration_writeback_force"


def _authenticated_migration_writeback_eligible(
    session: dict[str, Any],
    *,
    app_id: str = "baseball",
    st: Any | None = None,
) -> tuple[bool, str]:
    try:
        from suite_auth import auth_session_complete, is_auth_enabled
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return False, "auth_unavailable"
    if not is_auth_enabled():
        return False, "auth_disabled"
    if not auth_session_complete(session):
        return False, "not_signed_in"
    if not cloud_storage_enabled():
        return False, "cloud_disabled"
    if session.get(AUTH_MIGRATION_WRITEBACK_OK_KEY):
        return False, "already_writeback_ok"
    if session.get(AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY) and not session.get(
        AUTH_MIGRATION_WRITEBACK_FORCE_KEY
    ):
        return False, "already_attempted"

    session_drafts = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    disk_state = _load_disk_workflow_snapshot(app_id, session)
    disk_drafts = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
    visible_disk_drafts = disk_drafts
    try:
        from draft_archive_visibility import count_visible_draft_archives_in_blob

        visible_disk_drafts = count_visible_draft_archives_in_blob(session, disk_state)
    except ImportError:
        pass
    discovery = discover_workflow_migration_sources(session, app_id=app_id)
    migration_recoverable = int(discovery.get("recoverable_draft_count") or 0)
    local_drafts = max(session_drafts, visible_disk_drafts, migration_recoverable)
    if local_drafts <= 0:
        if disk_drafts > 0 and visible_disk_drafts <= 0:
            return False, "foreign_shared_league_on_disk_not_member"
        return False, "no_local_drafts"

    if st is None:
        return False, "streamlit_unavailable"
    try:
        from suite_workspace import get_active_workspace_id, normalize_workspace_id

        ws = normalize_workspace_id(get_active_workspace_id(st=st))
        cloud_probe = probe_cloud_workflow_for_workspace(ws)
        cloud_drafts = int(cloud_probe.get("draft_archive_count") or 0)
    except Exception:
        return False, "cloud_probe_failed"
    if cloud_drafts > 0:
        return False, "cloud_already_has_drafts"
    return True, ""


def maybe_authenticated_workflow_cloud_writeback(
    st: Any,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """
    When signed in with recoverable disk/session drafts but empty authenticated cloud row,
    merge local workflow state and force-save draft_archive_teams to cloud, then read back.
    """
    session = st.session_state
    trace: dict[str, Any] = {
        "attempted": False,
        "ok": False,
        "skipped": "",
        "session_draft_count_before": count_draft_archives(session.get(DRAFT_ARCHIVE_KEY)),
        "session_draft_count_after": 0,
        "disk_draft_count": 0,
        "cloud_readback_count": 0,
        "cloud_readback_ok": False,
        "cloud_readback_error": "",
        "persist_ok": False,
        "cloud_app_key": "",
        "reason": "authenticated_migration_writeback",
        "persistence_key_path": (
            f"session[{DRAFT_ARCHIVE_KEY}] → disk[{DRAFT_ARCHIVE_KEY}] → "
            f"cloud metrics.full_session.{DRAFT_ARCHIVE_KEY}"
        ),
    }

    eligible, skip = _authenticated_migration_writeback_eligible(session, app_id=app_id, st=st)
    if not eligible:
        trace["skipped"] = skip
        session[AUTH_MIGRATION_WRITEBACK_TRACE_KEY] = trace
        return trace

    session[AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY] = True
    trace["attempted"] = True
    session.pop(AUTH_MIGRATION_WRITEBACK_FORCE_KEY, None)

    try:
        merge_protected_workflow_on_restore(session, st=st, app_id=app_id)
    except Exception as exc:
        trace["merge_error"] = f"{type(exc).__name__}: {exc}"

    draft_count = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    trace["session_draft_count_before"] = draft_count
    if draft_count <= 0:
        disk_raw = int(trace.get("disk_draft_count") or 0)
        try:
            from draft_archive_visibility import count_visible_draft_archives_in_blob

            disk_state = _load_disk_workflow_snapshot(app_id, session)
            visible_disk = count_visible_draft_archives_in_blob(session, disk_state)
        except ImportError:
            visible_disk = disk_raw
        if disk_raw > 0 and visible_disk <= 0:
            trace["skipped"] = "foreign_shared_league_not_member"
            try:
                from fantasy_league_invites import reconcile_stranded_foreign_disk_drafts

                trace["stranded_reconcile"] = reconcile_stranded_foreign_disk_drafts(st, app_id)
            except Exception as exc:
                trace["stranded_reconcile_error"] = f"{type(exc).__name__}: {exc}"
        else:
            trace["skipped"] = "no_drafts_in_session_after_merge"
        session[AUTH_MIGRATION_WRITEBACK_TRACE_KEY] = trace
        return trace

    mark_workflow_persist_authoritative(session)

    try:
        from suite_user_persistence import clear_workspace_autosave_block

        clear_workspace_autosave_block(st, app_id)
    except ImportError:
        session.pop(f"_suite_autosave_fp::{app_id}", None)
        session.pop(f"_suite_restored_fp::{app_id}", None)

    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["persist_ok"] = bool(
            force_save_baseball_state(st, reason="authenticated_migration_writeback")
        )
    except Exception as exc:
        trace["persist_error"] = f"{type(exc).__name__}: {exc}"
        trace["persist_ok"] = False

    trace["session_draft_count_after"] = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    trace["cloud_app_key"] = str(session.get("_suite_last_cloud_app_key") or "")
    trace["cloud_write_ok"] = bool(session.get("_suite_persist_last_save_cloud"))
    trace["cloud_write_error"] = str(session.get("_suite_persist_last_cloud_error") or "")

    try:
        disk_state = _load_disk_workflow_snapshot(app_id)
        trace["disk_draft_count"] = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
    except Exception:
        pass

    readback: dict[str, Any] = {}
    try:
        from suite_workspace import get_active_workspace_id, scoped_cloud_app_id

        ws = str(get_active_workspace_id(st=st))
        app_key = scoped_cloud_app_id(app_id, ws)
        readback = verify_cloud_draft_library_readback(
            app_id,
            min_drafts=1,
            workspace_id=ws,
            cloud_app_key=app_key,
            expected_draft_count=int(trace["session_draft_count_after"] or 0),
            session=session,
        )
        record_draft_library_readback(session, readback)
        session["_suite_last_draft_save_readback"] = {
            "cloud_app_key": app_key,
            "workspace_id": ws,
            "scope_user_id": readback.get("scope_user_id"),
            "selected_row_user_id": readback.get("selected_row_user_id"),
            "draft_count": readback.get("draft_count"),
            "draft_ids": list(readback.get("draft_ids") or []),
            "expected_draft_count": trace["session_draft_count_after"],
            "authenticated_migration_writeback": True,
        }
    except Exception as exc:
        readback = {"ok": False, "error": str(exc), "draft_count": 0}
        record_draft_library_readback(session, readback)

    trace["cloud_readback_count"] = int(readback.get("draft_count") or 0)
    trace["cloud_readback_ok"] = bool(readback.get("ok"))
    trace["cloud_readback_error"] = str(readback.get("error") or "")
    trace["readback"] = readback
    trace["ok"] = bool(
        trace.get("persist_ok")
        and trace.get("cloud_readback_ok")
        and int(trace.get("session_draft_count_after") or 0) > 0
    )
    if trace["ok"]:
        session[AUTH_MIGRATION_WRITEBACK_OK_KEY] = True
    session[AUTH_MIGRATION_WRITEBACK_TRACE_KEY] = trace
    return trace


def save_probe_test_draft(st: Any, session: dict[str, Any]) -> dict[str, Any]:
    """Create one known minimal draft, persist, and read back cloud/disk counts."""
    trace: dict[str, Any] = {
        "ok": False,
        "draft_id": "",
        "draft_name": "Probe Test Draft",
        "session_draft_count_before": count_draft_archives(session.get(DRAFT_ARCHIVE_KEY)),
        "session_draft_count_after": 0,
        "disk_draft_count": 0,
        "cloud_readback_count": 0,
        "cloud_readback_ok": False,
        "cloud_readback_error": "",
        "persist_ok": False,
        "cloud_app_key": "",
        "persistence_key_path": (
            f"session[{DRAFT_ARCHIVE_KEY}] → disk[{DRAFT_ARCHIVE_KEY}] → "
            f"cloud metrics.full_session.{DRAFT_ARCHIVE_KEY}"
        ),
    }
    try:
        from draft_archive_state import save_draft_archive

        entry = save_draft_archive(
            session,
            draft_type="simulator",
            draft_name="Probe Test Draft",
            team_name="Probe Team",
            roster_rows=[{"Player": "Aaron Judge", "Position": "OF", "Team": "NYY"}],
        )
        trace["draft_id"] = str(entry.get("draft_id") or "")
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
        return trace

    try:
        from suite_user_persistence import clear_workspace_autosave_block

        clear_workspace_autosave_block(st, "baseball")
    except ImportError:
        session.pop("_suite_autosave_fp::baseball", None)
        session.pop("_suite_restored_fp::baseball", None)
    session.pop("_suite_autosave_fp::baseball", None)
    session.pop("_suite_restored_fp::baseball", None)

    try:
        from baseball_persistent_state import force_save_baseball_state

        trace["persist_ok"] = bool(force_save_baseball_state(st, reason="probe_test_draft_saved"))
    except Exception as exc:
        trace["persist_error"] = f"{type(exc).__name__}: {exc}"
        trace["persist_ok"] = False

    trace["session_draft_count_after"] = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    trace["cloud_app_key"] = str(session.get("_suite_last_cloud_app_key") or "")
    trace["cloud_write_ok"] = bool(session.get("_suite_persist_last_save_cloud"))
    trace["cloud_write_error"] = str(session.get("_suite_persist_last_cloud_error") or "")

    try:
        disk_state = _load_disk_workflow_snapshot("baseball")
        trace["disk_draft_count"] = count_draft_archives(disk_state.get(DRAFT_ARCHIVE_KEY))
    except Exception:
        pass

    readback: dict[str, Any] = {}
    try:
        from suite_workspace import get_active_workspace_id, scoped_cloud_app_id

        ws = str(get_active_workspace_id(st=st))
        app_key = scoped_cloud_app_id("baseball", ws)
        readback = verify_cloud_draft_library_readback(
            "baseball",
            min_drafts=1,
            expected_draft_id=trace["draft_id"],
            workspace_id=ws,
            cloud_app_key=app_key,
            expected_draft_count=int(trace["session_draft_count_after"] or 0),
            session=session,
        )
        record_draft_library_readback(session, readback)
        session["_suite_last_draft_save_readback"] = {
            "cloud_app_key": app_key,
            "workspace_id": ws,
            "scope_user_id": readback.get("scope_user_id"),
            "selected_row_user_id": readback.get("selected_row_user_id"),
            "draft_count": readback.get("draft_count"),
            "draft_ids": list(readback.get("draft_ids") or []),
            "expected_draft_count": trace["session_draft_count_after"],
            "expected_draft_id": trace["draft_id"],
            "probe_test_draft": True,
        }
    except Exception as exc:
        readback = {"ok": False, "error": str(exc), "draft_count": 0}
        record_draft_library_readback(session, readback)

    trace["cloud_readback_count"] = int(readback.get("draft_count") or 0)
    trace["cloud_readback_ok"] = bool(readback.get("ok"))
    trace["cloud_readback_error"] = str(readback.get("error") or "")
    trace["readback"] = readback
    trace["ok"] = bool(
        trace.get("draft_id")
        and int(trace.get("session_draft_count_after") or 0) > int(trace.get("session_draft_count_before") or 0)
        and trace.get("persist_ok")
        and trace.get("cloud_readback_ok")
    )
    session["_probe_test_draft_trace"] = trace
    return trace


def tracked_player_count_from_blob(blob: dict[str, Any] | None) -> int:
    if not isinstance(blob, dict):
        return 0
    rv = blob.get("workflow_recently_viewed")
    return len(rv) if isinstance(rv, list) else 0


def summarize_cloud_workflow_blob(blob: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(blob, dict):
        return {
            "draft_archive_count": 0,
            "league_context_count": 0,
            "has_draft_archive_teams": False,
            "has_fantasy_league_context_state": False,
            "active_draft_archive_id": "",
            "active_page": "",
            "tracked_player_count": 0,
            "state_key_count": 0,
            "draft_ids": [],
        }
    archives = blob.get(DRAFT_ARCHIVE_KEY)
    flc = blob.get(LEAGUE_CONTEXT_STATE_KEY)
    draft_ids: list[str] = []
    if isinstance(archives, list):
        draft_ids = [
            str(row.get("draft_id") or "").strip()
            for row in archives
            if isinstance(row, dict) and str(row.get("draft_id") or "").strip()
        ]
    return {
        "draft_archive_count": count_draft_archives(archives),
        "league_context_count": count_league_contexts(flc),
        "has_draft_archive_teams": _draft_archive_nonempty(archives),
        "has_fantasy_league_context_state": _league_context_store_nonempty(flc),
        "active_draft_archive_id": str(blob.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "active_page": str(blob.get("active_page") or ""),
        "tracked_player_count": tracked_player_count_from_blob(blob),
        "state_key_count": len(blob),
        "draft_ids": draft_ids,
    }


def infer_restore_persistence_verdict(
    *,
    cloud_draft_count: int = 0,
    disk_draft_count: int = 0,
    session_draft_count: int = 0,
    cloud_tracked_count: int = 0,
    session_tracked_count: int = 0,
    restore_applied: bool = False,
    restore_skip_reason: str = "",
) -> str:
    """Classify cold-start outcome: persistence failed (A) vs restore failed (B)."""
    skip = str(restore_skip_reason or "").strip().lower()
    cloud_rich = cloud_draft_count > 0 or cloud_tracked_count > 0
    disk_rich = disk_draft_count > 0
    session_empty = session_draft_count == 0 and session_tracked_count == 0
    if cloud_rich and session_empty:
        if restore_applied:
            return "B_restore_failed"
        if skip in ("no workspace blob", "empty"):
            return "A_persistence_failed_or_never_saved"
        return "B_restore_failed"
    if disk_rich and session_empty and not cloud_rich:
        return "B_restore_failed"
    if not cloud_rich and not disk_rich and session_empty:
        return "A_persistence_failed_or_never_saved"
    return "ok"


def build_startup_restore_snapshot(
    session: dict[str, Any],
    *,
    cloud_state: dict[str, Any] | None = None,
    disk_state: dict[str, Any] | None = None,
    phase: str = "post_apply",
) -> dict[str, Any]:
    """Read-only startup restore snapshot for A vs B persistence diagnosis."""
    counts = workflow_counts_from_session(session)
    session_tracked = tracked_player_count_from_blob(session)
    cloud_summary = summarize_cloud_workflow_blob(cloud_state if isinstance(cloud_state, dict) else None)
    disk_summary = summarize_cloud_workflow_blob(disk_state if isinstance(disk_state, dict) else None)

    workspace_id = ""
    cloud_app_key = ""
    try:
        from suite_workspace import get_active_workspace_id, scoped_cloud_app_id

        workspace_id = str(get_active_workspace_id(st=type("_St", (), {"session_state": session})()))
        cloud_app_key = scoped_cloud_app_id("baseball", workspace_id)
    except Exception:
        workspace_id = str(
            session.get("_suite_active_workspace_id")
            or session.get("_suite_owned_workspace_id")
            or ""
        )

    restore_applied = str(session.get("_suite_restore_decision") or "") == "applied"
    restore_skip = str(
        session.get("_suite_restore_skip_reason")
        or session.get("_suite_persist_restore_skip_reason")
        or ""
    )
    restored_page = str(session.get("active_page") or session.get("main_sidebar_page") or "")

    verdict = infer_restore_persistence_verdict(
        cloud_draft_count=int(cloud_summary.get("draft_archive_count") or 0),
        disk_draft_count=int(disk_summary.get("draft_archive_count") or 0),
        session_draft_count=int(counts.get("draft_archive_count") or 0),
        cloud_tracked_count=int(cloud_summary.get("tracked_player_count") or 0),
        session_tracked_count=session_tracked,
        restore_applied=restore_applied,
        restore_skip_reason=restore_skip,
    )
    active_trace = session.get(ACTIVE_DRAFT_RESTORE_TRACE_KEY)
    if not isinstance(active_trace, dict):
        active_trace = {}

    return {
        "phase": phase,
        "restored_workspace_id": workspace_id,
        "cloud_app_key": cloud_app_key,
        "restored_active_page": restored_page,
        "session_saved_draft_count": int(counts.get("draft_archive_count") or 0),
        "session_active_draft_id": str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "session_tracked_player_count": session_tracked,
        "cloud_saved_draft_count": int(cloud_summary.get("draft_archive_count") or 0),
        "cloud_active_draft_id": str(cloud_summary.get("active_draft_archive_id") or ""),
        "cloud_active_page": str(cloud_summary.get("active_page") or ""),
        "cloud_tracked_player_count": int(cloud_summary.get("tracked_player_count") or 0),
        "disk_saved_draft_count": int(disk_summary.get("draft_archive_count") or 0),
        "disk_active_draft_id": str(disk_summary.get("active_draft_archive_id") or ""),
        "disk_active_page": str(disk_summary.get("active_page") or ""),
        "disk_tracked_player_count": int(disk_summary.get("tracked_player_count") or 0),
        "active_restore_source": str(active_trace.get("active_source") or ""),
        "active_restore_reason": str(active_trace.get("restore_reason") or ""),
        "active_restore_needs_prompt": bool(active_trace.get("needs_set_active_prompt")),
        "restore_decision": session.get("_suite_restore_decision"),
        "restore_pick_source": session.get("_suite_restore_pick_source")
        or session.get("_suite_persist_last_restore_source"),
        "restore_skip_reason": restore_skip or None,
        "persistence_verdict": verdict,
    }


def record_startup_restore_snapshot(
    st: Any,
    *,
    cloud_state: dict[str, Any] | None = None,
    disk_state: dict[str, Any] | None = None,
    phase: str = "during_sync",
) -> dict[str, Any]:
    """Store startup restore snapshot on session for dev panels and Saved Draft Library."""
    ss = st.session_state
    snapshot = build_startup_restore_snapshot(
        ss,
        cloud_state=cloud_state,
        disk_state=disk_state,
        phase=phase,
    )
    ss["_suite_startup_restore_snapshot"] = snapshot
    for key, value in snapshot.items():
        ss[f"_suite_startup_{key}"] = value
    return snapshot


def hydrate_session_workflow_from_disk(
    session: dict[str, Any],
    *,
    draft_id: str = "",
) -> dict[str, Any]:
    """Restore workflow archives/context from disk when session lost them after persist."""
    out: dict[str, Any] = {"hydrated": False, "draft_archive_count": 0, "merged_keys": []}
    try:
        from suite_user_persistence import _load_raw
    except ImportError:
        return out
    try:
        disk_state, _, _ = _load_raw("baseball")
    except Exception:
        return out
    if not isinstance(disk_state, dict):
        return out

    target = str(draft_id or "").strip()
    merged: list[str] = []

    disk_archives = disk_state.get(DRAFT_ARCHIVE_KEY)
    session_archives = session.get(DRAFT_ARCHIVE_KEY)
    need_archives = not _draft_archive_nonempty(session_archives)
    if target and isinstance(session_archives, list):
        need_archives = need_archives or not any(
            str(row.get("draft_id") or "") == target for row in session_archives if isinstance(row, dict)
        )
    if need_archives and _draft_archive_nonempty(disk_archives):
        session[DRAFT_ARCHIVE_KEY] = copy.deepcopy(disk_archives)
        merged.append(DRAFT_ARCHIVE_KEY)

    disk_active = str(disk_state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    session_active = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    archive_ids = {
        str(entry.get("draft_id") or "").strip()
        for entry in (session.get(DRAFT_ARCHIVE_KEY) or [])
        if isinstance(entry, dict) and str(entry.get("draft_id") or "").strip()
    }
    if not session_active and disk_active and disk_active in archive_ids:
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = disk_active
        merged.append(ACTIVE_DRAFT_ARCHIVE_KEY)

    disk_flc = disk_state.get(LEAGUE_CONTEXT_STATE_KEY)
    session_flc = session.get(LEAGUE_CONTEXT_STATE_KEY)
    if not _league_context_store_nonempty(session_flc) and _league_context_store_nonempty(disk_flc):
        session[LEAGUE_CONTEXT_STATE_KEY] = copy.deepcopy(disk_flc)
        merged.append(LEAGUE_CONTEXT_STATE_KEY)

    out["hydrated"] = bool(merged)
    out["merged_keys"] = merged
    out["draft_archive_count"] = count_draft_archives(session.get(DRAFT_ARCHIVE_KEY))
    return out


def probe_cloud_workflow_for_app_key(
    cloud_app_key: str,
    *,
    workspace_id: str = "",
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Read-only cloud probe for one exact Supabase ``app`` row key."""
    app_key = str(cloud_app_key or "").strip()
    ws = str(workspace_id or "").strip()
    out: dict[str, Any] = {
        "workspace_id": ws,
        "cloud_app_key": app_key,
        "cloud_enabled": False,
        "scope_user_id": None,
        "selected_row_user_id": None,
        "row_found": False,
        "updated_at": None,
        "row_inspection": {},
        "error": None,
    }
    if not app_key:
        out["error"] = "missing_cloud_app_key"
        return out
    try:
        from suite_storage_config import cloud_storage_enabled

        out["cloud_enabled"] = cloud_storage_enabled()
    except ImportError as exc:
        out["error"] = str(exc)
        return out
    if not out["cloud_enabled"]:
        out["error"] = "cloud_storage_disabled"
        return out
    try:
        from suite_storage_supabase import inspect_cloud_state_rows

        inspection = inspect_cloud_state_rows(app_key)
        out["row_inspection"] = inspection
        out["scope_user_id"] = inspection.get("scope_user_id")
        out["selected_row_user_id"] = inspection.get("selected_row_user_id")
    except Exception:
        pass
    import time

    attempts = max(1, int(max_attempts or 1))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            import suite_storage_supabase as storage

            row = storage.load_current_state_for_app(app_key)
            if not isinstance(row, dict) or not row:
                return out
            out["row_found"] = True
            out["updated_at"] = str(row.get("updated_at") or "") or None
            if out.get("selected_row_user_id") is None:
                out["selected_row_user_id"] = row.get("user_id")
            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            blob = metrics.get("full_session") if isinstance(metrics, dict) else None
            out.update(summarize_cloud_workflow_blob(blob if isinstance(blob, dict) else None))
            out.pop("error", None)
            return out
        except Exception as exc:
            last_exc = exc
            try:
                from suite_storage_supabase import is_transient_supabase_error

                transient = is_transient_supabase_error(exc)
            except ImportError:
                transient = "503" in str(exc) or "PGRST002" in str(exc)
            if attempt + 1 >= attempts or not transient:
                out["error"] = str(exc)
                return out
            time.sleep(0.5 * (2**attempt))
    if last_exc is not None:
        out["error"] = str(last_exc)
    return out


def probe_cloud_workflow_for_workspace(
    workspace_id: str,
    *,
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Read-only cloud probe for one workspace profile (production diagnostics)."""
    from suite_workspace import scoped_cloud_app_id

    ws = str(workspace_id or "daniel").strip()
    cloud_app_key = scoped_cloud_app_id("baseball", ws)
    return probe_cloud_workflow_for_app_key(
        cloud_app_key,
        workspace_id=ws,
        max_attempts=max_attempts,
    )
