"""One-shot admin repair: rebuild draft_archive_teams from shared league context."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

DEFAULT_REPAIR_LEAGUE_ID = "league:0bcf703881121de10c2dd439"
DEFAULT_REPAIR_WORKSPACES: tuple[str, ...] = ("daniel", "coakley11")

_WORKFLOW_KEYS = (
    "draft_archive_teams",
    "active_draft_archive_id",
    "fantasy_league_context_state",
    "_deleted_draft_archive_ids",
)

_AUTH_BOOTSTRAP_KEYS = (
    "_suite_auth_user_id",
    "_suite_auth_external_id",
    "_suite_auth_user_email",
    "_suite_auth_session",
    "_suite_cloud_user_id",
    "_suite_owned_workspace_id",
    "_suite_owned_workspace_label",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def registry_record_for_workspace(workspace_id: str) -> dict[str, Any] | None:
    """Return the newest ownership-registry row for a workspace slug."""
    from suite_workspace import normalize_workspace_id
    from suite_workspace_registry import _read_registry

    wid = normalize_workspace_id(workspace_id)
    if not wid:
        return None
    rows: list[dict[str, Any]] = []
    for row in (_read_registry().get("by_owner") or {}).values():
        if not isinstance(row, dict):
            continue
        if normalize_workspace_id(str(row.get("workspace_id") or "")) == wid:
            rows.append(dict(row))
    if not rows:
        return None
    rows.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    return rows[0]


def find_league_context_by_league_id(session: dict[str, Any], league_id: str) -> dict[str, Any] | None:
    """Locate a saved league context matching canonical league_id."""
    from fantasy_league_context import ensure_fantasy_league_context_state
    from fantasy_league_identity import resolve_canonical_league_id

    target = str(league_id or "").strip()
    if not target:
        return None
    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if not isinstance(contexts, dict):
        return None
    for ctx in contexts.values():
        if not isinstance(ctx, dict):
            continue
        if resolve_canonical_league_id(ctx) == target:
            return copy.deepcopy(ctx)
    return None


def _owned_team_for_owner_id(shared_doc: dict[str, Any], owner_user_id: str) -> str:
    from fantasy_league_team_ownership import account_user_ids_match

    ownership = shared_doc.get("team_ownership") or {}
    if not isinstance(ownership, dict):
        return ""
    uid = str(owner_user_id or "").strip()
    for team, record in ownership.items():
        if not isinstance(record, dict):
            continue
        stored = str(record.get("user_id") or "").strip()
        if stored and account_user_ids_match(stored, uid):
            return str(team or "").strip()
    return ""


def build_context_from_shared_for_workspace(
    shared_doc: dict[str, Any],
    *,
    owner_user_id: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed or refresh a workspace league context from canonical shared league doc."""
    from fantasy_league_context import (
        CONTEXT_TYPE_REAL_LEAGUE,
        SOURCE_IMPORTED_DRAFT,
        context_id_for_archive,
    )
    from fantasy_league_identity import ensure_league_identity
    from fantasy_shared_league_store import merge_shared_into_context

    shared = copy.deepcopy(shared_doc)
    draft_id = str(shared.get("draft_id") or "").strip()
    league_id = str(shared.get("league_id") or "").strip()
    my_team = _owned_team_for_owner_id(shared, owner_user_id)
    base = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    if not base:
        league_context_id = context_id_for_archive(draft_id) if draft_id else ""
        base = {
            "league_context_id": league_context_id,
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "source": SOURCE_IMPORTED_DRAFT,
            "display_name": str(shared.get("league_name") or "Shared League").strip(),
            "league_name": str(shared.get("league_name") or "").strip(),
            "my_team_name": my_team,
            "league_rosters": copy.deepcopy(shared.get("league_rosters") or {}),
            "metadata": {
                "source_draft_id": draft_id,
                "league_id": league_id,
                "draft_fingerprint": str(shared.get("draft_fingerprint") or "").strip(),
                "commissioner_user_id": str(shared.get("commissioner_user_id") or "").strip(),
            },
        }
    elif my_team and not str(base.get("my_team_name") or "").strip():
        base["my_team_name"] = my_team
    merged = merge_shared_into_context(base, shared)
    return ensure_league_identity(merged)


def bootstrap_session_for_workspace(
    workspace_id: str,
    *,
    cloud_blob: dict[str, Any] | None = None,
    disk_blob: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a repair session with workspace/auth identity and workflow keys."""
    from suite_workspace import normalize_workspace_id

    ws = normalize_workspace_id(workspace_id)
    session: dict[str, Any] = {"_suite_active_workspace_id": ws}
    for source in (cloud_blob, disk_blob):
        if not isinstance(source, dict):
            continue
        for key in _WORKFLOW_KEYS + _AUTH_BOOTSTRAP_KEYS:
            if key in source and key not in session:
                try:
                    session[key] = copy.deepcopy(source[key])
                except Exception:
                    session[key] = source[key]
    record = registry_record_for_workspace(ws)
    if record:
        owner_uid = str(record.get("owner_user_id") or "").strip()
        external = str(record.get("owner_external_id") or "").strip()
        if owner_uid:
            session.setdefault("_suite_auth_user_id", owner_uid)
            session.setdefault("_suite_cloud_user_id", owner_uid)
        if external:
            session.setdefault("_suite_auth_external_id", external.lower())
        session.setdefault("_suite_owned_workspace_id", ws)
        session.setdefault("_suite_auth_session", True)
    session.setdefault("_suite_pending_save_reason", "admin_draft_archive_repair")
    return session


def archive_metrics(session: dict[str, Any]) -> dict[str, Any]:
    """Snapshot raw/visible archive counts and active draft id."""
    from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, list_draft_archives
    from draft_archive_visibility import list_visible_draft_archives

    raw = list_draft_archives(session)
    visible = list_visible_draft_archives(session)
    return {
        "raw_archive_count": len(raw),
        "visible_archive_count": len(visible),
        "active_draft_archive_id": str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip() or None,
        "draft_ids": [str(e.get("draft_id") or "").strip() for e in raw if isinstance(e, dict)],
        "visible_draft_ids": [str(e.get("draft_id") or "").strip() for e in visible if isinstance(e, dict)],
    }


def _trade_proposal_count(context: dict[str, Any] | None) -> int:
    if not isinstance(context, dict):
        return 0
    workflow = context.get("workflow") or {}
    proposals = workflow.get("trade_proposals") or []
    return len(proposals) if isinstance(proposals, list) else 0


def _ownership_snapshot(context: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(context, dict):
        return {}
    try:
        from fantasy_shared_league_store import get_team_ownership_from_context
    except ImportError:
        return {}
    ownership = get_team_ownership_from_context(context)
    out: dict[str, str] = {}
    if isinstance(ownership, dict):
        for team, record in ownership.items():
            if isinstance(record, dict):
                out[str(team)] = str(record.get("user_id") or "").strip()
    return out


def _normalize_repaired_archive_types(session: dict[str, Any]) -> int:
    """Ensure imported shared-league archives carry imported_draft type after stub repair."""
    from draft_archive_state import DRAFT_ARCHIVE_KEY, DRAFT_TYPE_IMPORTED, list_draft_archives
    from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context_for_archive

    fixed = 0
    entries = list_draft_archives(session)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ctx = get_league_context_for_archive(session, entry)
        if not isinstance(ctx, dict):
            continue
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        if str(entry.get("draft_type") or "").strip() == DRAFT_TYPE_IMPORTED:
            continue
        entry["draft_type"] = DRAFT_TYPE_IMPORTED
        fixed += 1
    if fixed:
        session[DRAFT_ARCHIVE_KEY] = entries
    return fixed


def repair_workspace_session_for_league(
    session: dict[str, Any],
    *,
    league_id: str,
    shared_doc: dict[str, Any],
    cloud_blob: dict[str, Any] | None = None,
    disk_blob: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair one in-memory session; idempotent and preserves ownership/trades via merge."""
    from draft_archive_state import list_draft_archives
    from fantasy_league_context import (
        FANTASY_LEAGUE_CONTEXT_STATE_KEY,
        repair_missing_draft_archives_from_contexts,
        upsert_league_context,
    )
    from workflow_persist_guard import restore_active_draft_archive_selection

    trace: dict[str, Any] = {
        "league_id": league_id,
        "before": archive_metrics(session),
        "context_found": False,
        "context_created": False,
        "archives_repaired": 0,
        "archive_types_normalized": 0,
        "trade_proposals_before": 0,
        "trade_proposals_after": 0,
        "ownership_before": {},
        "ownership_after": {},
        "active_restore_trace": {},
        "errors": [],
        "skipped_duplicate": False,
        "changed": False,
    }

    shared = copy.deepcopy(shared_doc)
    if str(shared.get("league_id") or "").strip() != str(league_id or "").strip():
        trace["errors"].append("shared_doc_league_id_mismatch")
        return trace

    owner_uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    context = find_league_context_by_league_id(session, league_id)
    trace["context_found"] = bool(context)
    if context:
        trace["trade_proposals_before"] = _trade_proposal_count(context)
        trace["ownership_before"] = _ownership_snapshot(context)
    else:
        trace["context_created"] = True

    try:
        context = build_context_from_shared_for_workspace(
            shared,
            owner_user_id=owner_uid,
            existing=context,
        )
        upsert_league_context(session, context, mark_persist_authoritative=False)
        store = session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY) or {}
        active_ctx_id = str(store.get("active_league_context_id") or "").strip()
        ctx_id = str(context.get("league_context_id") or "").strip()
        if not active_ctx_id and ctx_id:
            store["active_league_context_id"] = ctx_id
            session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = store
    except Exception as exc:
        trace["errors"].append(f"context_sync_failed:{type(exc).__name__}:{exc}")
        return trace

    refreshed = find_league_context_by_league_id(session, league_id) or context
    trace["trade_proposals_after"] = _trade_proposal_count(refreshed)
    trace["ownership_after"] = _ownership_snapshot(refreshed)

    target_draft_id = str(shared.get("draft_id") or "").strip()
    existing_ids = {
        str(e.get("draft_id") or "").strip()
        for e in list_draft_archives(session)
        if isinstance(e, dict) and str(e.get("draft_id") or "").strip()
    }
    if target_draft_id and target_draft_id in existing_ids:
        trace["skipped_duplicate"] = True

    try:
        trace["archives_repaired"] = int(
            repair_missing_draft_archives_from_contexts(session, require_visibility=False) or 0
        )
        trace["archive_types_normalized"] = _normalize_repaired_archive_types(session)
        restore_trace = restore_active_draft_archive_selection(
            session,
            cloud_state=cloud_blob if isinstance(cloud_blob, dict) else {},
            disk_state=disk_blob if isinstance(disk_blob, dict) else {},
            phase="admin_repair",
        )
        trace["active_restore_trace"] = restore_trace if isinstance(restore_trace, dict) else {}
    except Exception as exc:
        trace["errors"].append(f"archive_repair_failed:{type(exc).__name__}:{exc}")

    after = archive_metrics(session)
    trace["after"] = after
    trace["changed"] = (
        after.get("raw_archive_count", 0) != trace["before"].get("raw_archive_count", 0)
        or after.get("active_draft_archive_id") != trace["before"].get("active_draft_archive_id")
        or trace["archives_repaired"] > 0
        or trace["archive_types_normalized"] > 0
    )
    return trace


def merge_repaired_workflow_into_blob(blob: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Patch workflow keys onto an existing full_session blob without dropping unrelated state."""
    out = copy.deepcopy(blob) if isinstance(blob, dict) else {}
    for key in _WORKFLOW_KEYS:
        if key in session:
            try:
                out[key] = copy.deepcopy(session[key])
            except Exception:
                out[key] = session[key]
    return out


def load_cloud_workflow_blob(workspace_id: str) -> tuple[dict[str, Any], str]:
    """Load metrics.full_session for a scoped workspace cloud row."""
    from suite_workspace import scoped_cloud_app_id
    from workflow_persist_guard import _full_session_blob_from_storage_app_key

    ws = str(workspace_id or "").strip()
    app_key = scoped_cloud_app_id("baseball", ws)
    blob = _full_session_blob_from_storage_app_key(app_key)
    return (blob if isinstance(blob, dict) else {}, app_key)


def save_cloud_workflow_blob(
    workspace_id: str,
    blob: dict[str, Any],
    *,
    summary: str = "Admin draft archive repair",
) -> tuple[bool, str, str]:
    """Write full_session directly to a scoped workspace cloud row."""
    from suite_cloud_state import FULL_SESSION_KEY
    from suite_workspace import scoped_cloud_app_id

    ws = str(workspace_id or "").strip()
    app_key = scoped_cloud_app_id("baseball", ws)
    try:
        from suite_storage_config import cloud_storage_enabled
    except ImportError:
        return False, "cloud_storage_config_unavailable", app_key
    if not cloud_storage_enabled():
        return False, "cloud_storage_disabled", app_key
    try:
        from suite_storage_supabase import save_current_state_with_result

        result = save_current_state_with_result(
            app_key,
            page="Saved Draft Library",
            summary=summary,
            metrics={FULL_SESSION_KEY: copy.deepcopy(blob)},
            skip_metrics_merge=True,
            direct_upsert=True,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            err = str((result or {}).get("error") or "cloud_save_failed")
            return False, err, app_key
        return True, "", app_key
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", app_key


def verify_cloud_workflow_readback(workspace_id: str) -> dict[str, Any]:
    """Fresh readback probe after repair write."""
    from workflow_persist_guard import probe_cloud_workflow_for_workspace

    probe = probe_cloud_workflow_for_workspace(workspace_id, max_attempts=2)
    return {
        "workspace_id": workspace_id,
        "cloud_enabled": bool(probe.get("cloud_enabled")),
        "cloud_app_key": probe.get("cloud_app_key"),
        "draft_archive_count": int(probe.get("draft_archive_count") or 0),
        "league_context_count": int(probe.get("league_context_count") or 0),
        "active_draft_archive_id": probe.get("active_draft_archive_id"),
        "cloud_load_error": probe.get("cloud_load_error"),
    }


def repair_workspace_for_league(
    workspace_id: str,
    *,
    league_id: str,
    shared_doc: dict[str, Any],
    dry_run: bool = False,
    write_disk: bool = True,
) -> dict[str, Any]:
    """End-to-end repair for one workspace: load cloud, repair session, write cloud, verify."""
    from suite_user_persistence import _load_raw, save_user_state

    ws = str(workspace_id or "").strip()
    row: dict[str, Any] = {
        "workspace_id": ws,
        "dry_run": dry_run,
        "cloud_app_key": "",
        "shared_doc_found": isinstance(shared_doc, dict),
        "errors": [],
        "repair_trace": {},
        "cloud_write_ok": False,
        "cloud_write_error": "",
        "disk_write_ok": False,
        "readback": {},
        "readback_verified": False,
    }

    cloud_blob, app_key = load_cloud_workflow_blob(ws)
    row["cloud_app_key"] = app_key
    disk_blob, _, _ = _load_raw("baseball", ws)

    session = bootstrap_session_for_workspace(ws, cloud_blob=cloud_blob, disk_blob=disk_blob)
    repair_trace = repair_workspace_session_for_league(
        session,
        league_id=league_id,
        shared_doc=shared_doc,
        cloud_blob=cloud_blob,
        disk_blob=disk_blob,
    )
    row["repair_trace"] = repair_trace
    row["errors"].extend(list(repair_trace.get("errors") or []))

    after_count = int((repair_trace.get("after") or {}).get("raw_archive_count") or 0)
    if after_count <= 0:
        row["errors"].append("repair_session_archive_count_zero")

    outbound = merge_repaired_workflow_into_blob(cloud_blob, session)
    if dry_run:
        row["readback_verified"] = after_count > 0
        return row

    ok, err, _ = save_cloud_workflow_blob(ws, outbound)
    row["cloud_write_ok"] = ok
    row["cloud_write_error"] = err
    if not ok:
        row["errors"].append(f"cloud_write_failed:{err}")
        return row

    if write_disk:
        row["disk_write_ok"] = bool(save_user_state("baseball", outbound, workspace_id=ws))

    readback = verify_cloud_workflow_readback(ws)
    row["readback"] = readback
    row["readback_verified"] = int(readback.get("draft_archive_count") or 0) > 0
    if not row["readback_verified"]:
        row["errors"].append("readback_archive_count_zero")
    return row


def run_league_draft_archive_repair(
    league_id: str = DEFAULT_REPAIR_LEAGUE_ID,
    workspaces: tuple[str, ...] | list[str] = DEFAULT_REPAIR_WORKSPACES,
    *,
    dry_run: bool = False,
    write_disk: bool = True,
) -> dict[str, Any]:
    """Repair draft archives for all target workspaces from canonical shared league doc."""
    from fantasy_shared_league_store import load_shared_league

    target_league = str(league_id or "").strip()
    trace: dict[str, Any] = {
        "repair_id": f"admin_draft_archive_repair::{target_league}",
        "started_at": _utc_now_iso(),
        "league_id": target_league,
        "workspaces": list(workspaces),
        "dry_run": dry_run,
        "shared_doc_found": False,
        "shared_doc_revision": None,
        "shared_trade_proposal_count": 0,
        "workspace_results": [],
        "ok": False,
        "errors": [],
    }

    shared = load_shared_league(target_league)
    if not isinstance(shared, dict):
        trace["errors"].append("shared_league_not_found")
        trace["finished_at"] = _utc_now_iso()
        return trace

    trace["shared_doc_found"] = True
    trace["shared_doc_revision"] = shared.get("revision")
    proposals = shared.get("trade_proposals") or []
    trace["shared_trade_proposal_count"] = len(proposals) if isinstance(proposals, list) else 0

    results: list[dict[str, Any]] = []
    all_ok = True
    for ws in workspaces:
        result = repair_workspace_for_league(
            ws,
            league_id=target_league,
            shared_doc=shared,
            dry_run=dry_run,
            write_disk=write_disk,
        )
        results.append(result)
        if result.get("errors"):
            all_ok = False
        if not dry_run and not result.get("readback_verified"):
            all_ok = False
        if dry_run and int((result.get("repair_trace") or {}).get("after", {}).get("raw_archive_count") or 0) <= 0:
            all_ok = False

    trace["workspace_results"] = results
    trace["ok"] = all_ok and not trace["errors"]
    trace["finished_at"] = _utc_now_iso()
    return trace
