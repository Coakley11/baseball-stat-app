"""Auto-sync uploaded/shared leagues on Saved Draft Library render."""

from __future__ import annotations

import copy
from typing import Any

from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context_for_archive
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import get_team_ownership
from fantasy_shared_league_store import (
    build_team_ownership_sync_diagnostics,
    sync_context_with_shared_store,
)

_LIBRARY_SYNC_TRACE_KEY = "_suite_shared_league_library_sync_trace"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _real_league_contexts_for_library(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Distinct real_league contexts linked to visible Saved Draft Library cards."""
    try:
        from draft_archive_visibility import list_visible_draft_archives
    except ImportError:
        return []

    seen: set[str] = set()
    contexts: list[dict[str, Any]] = []
    for entry in list_visible_draft_archives(session):
        if not isinstance(entry, dict):
            continue
        ctx = get_league_context_for_archive(session, entry)
        if not isinstance(ctx, dict):
            continue
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        ctx_id = str(ctx.get("league_context_id") or "").strip()
        if not ctx_id or ctx_id in seen:
            continue
        seen.add(ctx_id)
        contexts.append(ctx)
    return contexts


def materialize_owned_shared_leagues_for_session(session: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure account-local library/context rows exist for canonical shared leagues this user owns.

    Deduplicates by canonical league_id — never creates a second shared league document.
    """
    from fantasy_admin_draft_archive_repair import (
        build_context_from_shared_for_workspace,
        find_league_context_by_league_id,
    )
    from fantasy_league_context import upsert_league_context
    from fantasy_shared_league_startup_sync import (
        apply_workspace_member_identity_from_shared,
        discover_shared_league_memberships_for_session,
        finalize_repaired_archives_for_membership,
    )
    from fantasy_shared_league_store import load_shared_league
    from fantasy_workspace_team_identity import session_account_identity

    uid, external, workspace, _, _ = session_account_identity(session)
    trace: dict[str, Any] = {
        "updated_at": _utc_now_iso(),
        "memberships_checked": 0,
        "materialized": [],
        "errors": [],
    }
    if not uid and not external and not workspace:
        trace["reason"] = "identity_unresolved"
        session[_LIBRARY_SYNC_TRACE_KEY] = trace
        return trace

    for row in discover_shared_league_memberships_for_session(session):
        trace["memberships_checked"] += 1
        league_id = str(row.get("league_id") or "").strip()
        if not league_id:
            continue
        shared_doc = load_shared_league(league_id)
        if not isinstance(shared_doc, dict):
            trace["errors"].append(f"{league_id}:shared_doc_not_found")
            continue
        try:
            existing = find_league_context_by_league_id(session, league_id)
            context = build_context_from_shared_for_workspace(
                shared_doc,
                owner_user_id=uid,
                owner_external_id=external,
                workspace_id=workspace,
                existing=existing,
            )
            context = apply_workspace_member_identity_from_shared(session, context, shared_doc)
            upsert_league_context(session, context, mark_persist_authoritative=False)
            finalize_trace = finalize_repaired_archives_for_membership(session, shared_doc=shared_doc)
            trace["materialized"].append(
                {
                    "league_id": league_id,
                    "draft_id": str(shared_doc.get("draft_id") or "").strip(),
                    "owned_teams": list(row.get("owned_teams") or []),
                    "finalize_trace": finalize_trace,
                }
            )
        except Exception as exc:
            trace["errors"].append(f"{league_id}:{type(exc).__name__}:{exc}")

    session[_LIBRARY_SYNC_TRACE_KEY] = trace
    return trace


def sync_uploaded_league_contexts_on_library_render(session: dict[str, Any]) -> dict[str, Any]:
    """
    Pull canonical team_ownership from baseball_shared_leagues for library leagues.

    Runs once per Saved Draft Library render so commissioners see invitee claims
    without requiring Set Active first.
    """
    materialize_owned_shared_leagues_for_session(session)
    results: list[dict[str, Any]] = []
    leagues_synced = 0

    for ctx in _real_league_contexts_for_library(session):
        league_id = str(resolve_canonical_league_id(ctx) or "").strip()
        league_context_id = str(ctx.get("league_context_id") or "").strip()
        before_diag = build_team_ownership_sync_diagnostics(ctx)
        comparison = dict(before_diag.get("comparison") or {})
        shared_found = bool(before_diag.get("shared_doc_found"))

        if not league_id:
            results.append(
                {
                    "league_id": "",
                    "league_context_id": league_context_id,
                    "draft_name": str(ctx.get("display_name") or ctx.get("league_name") or "").strip(),
                    "shared_doc_found": False,
                    "auto_synced": False,
                    "reason": "missing_league_id",
                }
            )
            continue

        if not shared_found:
            results.append(
                {
                    "league_id": league_id,
                    "league_context_id": league_context_id,
                    "draft_name": str(ctx.get("display_name") or ctx.get("league_name") or "").strip(),
                    "shared_doc_found": False,
                    "auto_synced": False,
                    "reason": "shared_doc_not_found",
                    "ownership_sync": before_diag,
                }
            )
            continue

        if not comparison.get("local_stale_vs_shared"):
            results.append(
                {
                    "league_id": league_id,
                    "league_context_id": league_context_id,
                    "draft_name": str(ctx.get("display_name") or ctx.get("league_name") or "").strip(),
                    "shared_doc_found": True,
                    "auto_synced": False,
                    "reason": "already_in_sync",
                    "ownership_sync": before_diag,
                }
            )
            continue

        ownership_before = copy.deepcopy(get_team_ownership(ctx))
        synced = sync_context_with_shared_store(session, ctx)
        ownership_after = copy.deepcopy(get_team_ownership(synced))
        changed = ownership_before != ownership_after
        if changed:
            leagues_synced += 1
        after_diag = build_team_ownership_sync_diagnostics(synced)
        results.append(
            {
                "league_id": league_id,
                "league_context_id": league_context_id,
                "draft_name": str(ctx.get("display_name") or ctx.get("league_name") or "").strip(),
                "shared_doc_found": True,
                "auto_synced": changed,
                "reason": "merged_from_shared_store" if changed else "sync_no_local_change",
                "teams_merged_from_shared": list(comparison.get("teams_only_in_shared") or []),
                "ownership_before": ownership_before,
                "ownership_after": ownership_after,
                "ownership_sync": after_diag,
            }
        )

    trace = {
        "updated_at": _utc_now_iso(),
        "leagues_checked": len(results),
        "leagues_synced": leagues_synced,
        "results": results,
    }
    session[_LIBRARY_SYNC_TRACE_KEY] = trace
    return trace


def get_library_sync_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(_LIBRARY_SYNC_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def summarize_library_sync_for_banner(trace: dict[str, Any]) -> str | None:
    """One-line user message when library auto-sync merged remote team claims."""
    if not isinstance(trace, dict):
        return None
    merged: list[str] = []
    for row in trace.get("results") or []:
        if not isinstance(row, dict) or not row.get("auto_synced"):
            continue
        league = str(row.get("draft_name") or row.get("league_id") or "Shared league").strip()
        teams = [str(t) for t in (row.get("teams_merged_from_shared") or []) if str(t).strip()]
        if teams:
            merged.append(f"**{league}**: {', '.join(teams)}")
        else:
            merged.append(f"**{league}**")
    if not merged:
        return None
    return (
        "Synced team ownership from the canonical shared league document: "
        + "; ".join(merged)
        + "."
    )
