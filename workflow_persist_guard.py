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


def _archive_sort_ts(entry: dict[str, Any]) -> str:
    return str(entry.get("updated_at") or entry.get("created_at") or "")


def _union_merge_draft_archives(*sources: Any) -> list[dict[str, Any]]:
    """Merge saved draft lists by draft_id — never drop drafts present on any source."""
    by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, list):
            continue
        for raw in source:
            if not isinstance(raw, dict):
                continue
            draft_id = str(raw.get("draft_id") or "").strip()
            if not draft_id:
                continue
            entry = copy.deepcopy(raw)
            existing = by_id.get(draft_id)
            if existing is None or _archive_sort_ts(entry) >= _archive_sort_ts(existing):
                by_id[draft_id] = entry
    return sorted(by_id.values(), key=_archive_sort_ts, reverse=True)


def _union_merge_league_context_stores(*sources: Any) -> dict[str, Any]:
    """Merge league-context stores by league_context_id."""
    merged: dict[str, dict[str, Any]] = {}
    active_id = ""
    schema_version = 1
    legacy_migration: dict[str, Any] | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        schema_version = int(source.get("schema_version") or schema_version or 1)
        if isinstance(source.get("legacy_migration"), dict):
            legacy_migration = copy.deepcopy(source["legacy_migration"])
        candidate_active = str(source.get("active_league_context_id") or "").strip()
        if candidate_active:
            active_id = candidate_active
        contexts = source.get("contexts")
        if not isinstance(contexts, dict):
            continue
        for context_id, context in contexts.items():
            if not isinstance(context, dict):
                continue
            cid = str(context_id or context.get("league_context_id") or "").strip()
            if not cid:
                continue
            existing = merged.get(cid)
            if existing is None:
                merged[cid] = copy.deepcopy(context)
                continue
            existing_ts = str(existing.get("metadata", {}).get("updated_at") or "")
            incoming_ts = str(context.get("metadata", {}).get("updated_at") or "")
            if incoming_ts >= existing_ts:
                merged[cid] = copy.deepcopy(context)
    out: dict[str, Any] = {
        "schema_version": schema_version,
        "contexts": merged,
        "active_league_context_id": active_id,
    }
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
    merged_keys: list[str] = []
    merge_sources: dict[str, str] = {}

    merged_archives = _union_merge_draft_archives(
        session.get(DRAFT_ARCHIVE_KEY),
        incoming_state.get(DRAFT_ARCHIVE_KEY),
        disk_state.get(DRAFT_ARCHIVE_KEY),
        cloud_state.get(DRAFT_ARCHIVE_KEY),
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
    return session


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


def evaluate_cloud_durability_status(session: dict[str, Any]) -> dict[str, Any]:
    """Whether this session has verified durable cloud persistence (not just config)."""
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

    last_cloud_save = bool(session.get("_suite_persist_last_save_cloud"))
    cloud_probe: dict[str, Any] = {}
    try:
        from suite_workspace import get_active_workspace_id

        ws = str(get_active_workspace_id(st=type("_St", (), {"session_state": session})()))
        cloud_probe = probe_cloud_workflow_for_workspace(ws)
    except Exception:
        pass
    row_found = bool(cloud_probe.get("row_found"))
    cloud_drafts = int(cloud_probe.get("draft_archive_count") or 0)
    cloud_write_verified = last_cloud_save or (row_found and cloud_drafts > 0)

    if cloud_write_verified:
        return {
            "cloud_enabled": True,
            "durable_persistence": True,
            "cloud_write_verified": True,
            "cloud_row_found": row_found,
            "cloud_saved_draft_count": cloud_drafts,
            "durability_label": "Durable — saved to cloud (survives app reboot)",
            "durability_warning": "",
        }

    last_error = str(
        session.get("_suite_persist_last_cloud_error")
        or session.get("_draft_archive_persist_error")
        or session.get("_suite_autosave_cloud_blocked_reason")
        or ""
    ).strip()
    warning = (
        "Cloud storage is configured, but no draft has been verified in cloud yet. "
        "Saves are only durable after a successful cloud write and readback. "
        "Disk-only saves will not survive Streamlit Cloud reboot."
    )
    if last_error:
        warning += f" Last cloud error: `{last_error}`"
    return {
        "cloud_enabled": True,
        "durable_persistence": False,
        "cloud_write_verified": False,
        "cloud_row_found": row_found,
        "cloud_saved_draft_count": cloud_drafts,
        "durability_label": "Not durable yet — cloud write not verified",
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
    restore_merged = list(session.get("_suite_workflow_restore_merged_keys") or [])
    restore_merge_sources = dict(session.get("_suite_workflow_restore_merge_sources") or {})

    cloud_enabled = False
    try:
        from suite_storage_config import cloud_storage_enabled

        cloud_enabled = cloud_storage_enabled()
    except ImportError:
        pass

    save_diag = session.get("_draft_library_save_diag")
    nav_diag = session.get("_draft_library_nav_diag")
    durability = evaluate_cloud_durability_status(session)

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
        "auth_mode": "signed_in" if authenticated else "local_demo",
        "cloud_write_expected": bool(cloud_enabled),
        "durable_persistence": bool(durability.get("durable_persistence")),
        "cloud_write_verified": bool(durability.get("cloud_write_verified")),
        "durability_label": str(durability.get("durability_label") or ""),
        "durability_warning": str(durability.get("durability_warning") or ""),
        "auth_enabled_but_signed_out": bool(auth_enabled and not authenticated),
        "restore_cloud_vs_demo_note": (
            "Restore source is cloud, but you are in local/demo mode — empty cloud can overwrite "
            "disk saves unless workflow protection is active."
            if restore_source == "cloud" and not authenticated
            else ""
        ),
        "workflow_merge_keys": merged_keys,
        "workflow_merge_sources": merge_sources,
        "workflow_restore_merged_keys": restore_merged,
        "workflow_restore_merge_sources": restore_merge_sources,
        "cloud_enabled": cloud_enabled,
        "save_diag": save_diag if isinstance(save_diag, dict) else {},
        "nav_diag": nav_diag if isinstance(nav_diag, dict) else {},
    }


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
