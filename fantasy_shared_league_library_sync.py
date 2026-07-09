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


def sync_uploaded_league_contexts_on_library_render(session: dict[str, Any]) -> dict[str, Any]:
    """
    Pull canonical team_ownership from baseball_shared_leagues for library leagues.

    Runs once per Saved Draft Library render so commissioners see invitee claims
    without requiring Set Active first.
    """
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
