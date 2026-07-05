"""Protect saved drafts / league contexts from accidental partial-save overwrites."""

from __future__ import annotations

import copy
from typing import Any

DRAFT_ARCHIVE_KEY = "draft_archive_teams"
LEAGUE_CONTEXT_STATE_KEY = "fantasy_league_context_state"
ACTIVE_DRAFT_ARCHIVE_KEY = "active_draft_archive_id"

PROTECTED_WORKFLOW_PERSIST_KEYS: tuple[str, ...] = (
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    ACTIVE_DRAFT_ARCHIVE_KEY,
)

WORKFLOW_PERSIST_ALLOW_CLEAR_KEY = "_suite_allow_workflow_persist_clear"

_EXPLICIT_WORKFLOW_CLEAR_REASONS = frozenset(
    {
        "draft_archive_cleared",
        "draft_archive_deleted",
        "league_context_deleted",
        "suite_reset",
        "reset_user_state",
        "user_reset",
    }
)


def mark_workflow_persist_authoritative(session: dict[str, Any]) -> None:
    """Call after intentional draft archive or league-context mutations."""
    session[WORKFLOW_PERSIST_ALLOW_CLEAR_KEY] = True


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


def _session_allows_workflow_clear(session: dict[str, Any], save_reason: str) -> bool:
    if session.get(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY):
        return True
    return str(save_reason or "").strip() in _EXPLICIT_WORKFLOW_CLEAR_REASONS


def _session_workflow_authoritative(session: dict[str, Any], key: str) -> bool:
    """True when the live session intentionally owns this workflow key."""
    if key not in session:
        return False
    if key == DRAFT_ARCHIVE_KEY:
        return True
    if key == LEAGUE_CONTEXT_STATE_KEY:
        return _league_context_store_nonempty(session.get(key))
    return True


def _load_disk_workflow_snapshot(app_id: str) -> dict[str, Any]:
    try:
        from suite_user_persistence import _load_raw

        state, _, _ = _load_raw(app_id)
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    return {}


def _load_cloud_workflow_snapshot(app_id: str, st: Any | None) -> dict[str, Any]:
    try:
        from suite_cloud_state import load_cloud_full_session

        if st is None:
            return {}
        blob, _ = load_cloud_full_session(app_id)
        if isinstance(blob, dict):
            return blob
    except Exception:
        pass
    return {}


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
        return state

    disk_state = _load_disk_workflow_snapshot(app_id)
    cloud_state = _load_cloud_workflow_snapshot(app_id, st) if st is not None else {}
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
        merge_sources[key] = source

    if merged_keys:
        session["_suite_workflow_persist_merged_keys"] = merged_keys
        session["_suite_workflow_persist_merge_sources"] = merge_sources
        session["_suite_workflow_persist_merge_reason"] = reason
    return state


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
            current_auth_email,
            is_auth_enabled,
            is_authenticated,
            resolve_auth_external_id,
        )

        auth_enabled = is_auth_enabled()
        authenticated = is_authenticated(session)
        account_email = current_auth_email(session)
        account_external_id = resolve_auth_external_id(session)
    except ImportError:
        pass
    try:
        from suite_user import get_account_user_id

        account_user_id = get_account_user_id()
    except ImportError:
        account_user_id = str(session.get("_suite_auth_user_id") or "")

    workspace_id = ""
    workspace_label = ""
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

    restore_at = str(session.get("_suite_persist_last_restore_at") or "")
    merged_keys = list(session.get("_suite_workflow_persist_merged_keys") or [])
    merge_sources = dict(session.get("_suite_workflow_persist_merge_sources") or {})

    cloud_enabled = False
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = cloud_storage_enabled()
    except ImportError:
        pass

    return {
        "account_email": account_email,
        "account_external_id": account_external_id,
        "account_user_id": account_user_id,
        "auth_enabled": auth_enabled,
        "authenticated": authenticated,
        "workspace_id": workspace_id,
        "workspace_label": workspace_label,
        "cloud_app_key": cloud_app_key,
        "local_state_path": local_state_path,
        "draft_archive_count": counts["draft_archive_count"],
        "league_context_count": counts["league_context_count"],
        "saved_drafts": counts["saved_drafts"],
        "league_contexts": counts["league_contexts"],
        "restore_source": restore_source,
        "restore_source_label": restore_label,
        "restore_at": restore_at,
        "workflow_merge_keys": merged_keys,
        "workflow_merge_sources": merge_sources,
        "cloud_enabled": cloud_enabled,
    }


def summarize_cloud_workflow_blob(blob: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(blob, dict):
        return {
            "draft_archive_count": 0,
            "league_context_count": 0,
            "has_draft_archive_teams": False,
            "has_fantasy_league_context_state": False,
            "active_draft_archive_id": "",
            "state_key_count": 0,
        }
    archives = blob.get(DRAFT_ARCHIVE_KEY)
    flc = blob.get(LEAGUE_CONTEXT_STATE_KEY)
    return {
        "draft_archive_count": count_draft_archives(archives),
        "league_context_count": count_league_contexts(flc),
        "has_draft_archive_teams": _draft_archive_nonempty(archives),
        "has_fantasy_league_context_state": _league_context_store_nonempty(flc),
        "active_draft_archive_id": str(blob.get(ACTIVE_DRAFT_ARCHIVE_KEY) or ""),
        "state_key_count": len(blob),
    }


def probe_cloud_workflow_for_workspace(workspace_id: str) -> dict[str, Any]:
    """Read-only cloud probe for one workspace profile (production diagnostics)."""
    from suite_workspace import scoped_cloud_app_id

    ws = str(workspace_id or "daniel").strip()
    cloud_app_key = scoped_cloud_app_id("baseball", ws)
    out: dict[str, Any] = {
        "workspace_id": ws,
        "cloud_app_key": cloud_app_key,
        "cloud_enabled": False,
        "row_found": False,
        "updated_at": None,
        "error": None,
    }
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
        import suite_storage_supabase as storage

        row = storage.load_current_state_for_app(cloud_app_key)
        if not isinstance(row, dict) or not row:
            return out
        out["row_found"] = True
        out["updated_at"] = str(row.get("updated_at") or "") or None
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        blob = metrics.get("full_session") if isinstance(metrics, dict) else None
        out.update(summarize_cloud_workflow_blob(blob if isinstance(blob, dict) else None))
    except Exception as exc:
        out["error"] = str(exc)
    return out
