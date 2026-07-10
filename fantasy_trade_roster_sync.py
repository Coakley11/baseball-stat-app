"""Reconcile accepted trades with league rosters and invalidate stale roster view caches."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    WORKFLOW_KEY_TRADE_PROPOSALS,
    _execute_roster_swap,
    _player_owner,
    get_trade_proposals,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def roster_content_fingerprint(context: dict[str, Any] | None) -> str:
    """Player-level fingerprint for league_rosters (swap-safe vs count-only sigs)."""
    if not isinstance(context, dict):
        return ""
    try:
        from fantasy_shared_league_store import _roster_content_fingerprint

        return _roster_content_fingerprint(context.get("league_rosters"))
    except ImportError:
        rosters = context.get("league_rosters") or {}
        if not isinstance(rosters, dict):
            return ""
        parts: list[str] = []
        for team in sorted(rosters.keys()):
            entry = rosters.get(team)
            if not isinstance(entry, dict):
                continue
            names = sorted(
                str(p.get("player_key") or p.get("player_name") or "").strip().lower()
                for p in (entry.get("players") or [])
                if isinstance(p, dict)
                if str(p.get("player_key") or p.get("player_name") or "").strip()
            )
            parts.append(f"{team}:{','.join(names)}")
        return "|".join(parts)


def invalidate_fantasy_roster_view_caches(
    session: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> None:
    """Drop persisted roster/standings view caches so lineup rebuilds from league context."""
    session.pop("fantasy_current_roster_stats", None)
    session.pop("fantasy_current_standings", None)
    blob = session.get("fantasy_in_season_state")
    if isinstance(blob, dict):
        cleaned = dict(blob)
        cleaned.pop("roster_stats_records", None)
        cleaned.pop("standings_records", None)
        if isinstance(context, dict):
            cleaned["league_rosters_view_sig"] = roster_content_fingerprint(context)
        cleaned["updated_at"] = _utc_now_iso()
        cleaned["reason"] = "accepted_trade_roster_sync"
        session["fantasy_in_season_state"] = cleaned


def sync_all_archives_league_rosters(session: dict[str, Any], context: dict[str, Any]) -> int:
    """Refresh league_rosters, team players, and snapshot on every archive for this league."""
    from draft_archive_state import _archive_list, _build_archive_snapshot, _set_archive_list

    league_context_id = str(context.get("league_context_id") or "").strip()
    meta = context.get("metadata") or {}
    source_draft_id = str(meta.get("source_draft_id") or meta.get("draft_id") or "").strip()
    league_rosters = context.get("league_rosters") or {}
    if not isinstance(league_rosters, dict) or not league_rosters:
        return 0
    entries = _archive_list(session)
    changed = 0
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_ctx = str(entry.get("league_context_id") or "").strip()
        entry_draft = str(entry.get("draft_id") or "").strip()
        linked = entry_ctx == league_context_id if league_context_id else False
        if not linked and source_draft_id and entry_draft == source_draft_id:
            linked = True
        if not linked:
            continue
        updated = copy.deepcopy(entry)
        updated["league_rosters"] = copy.deepcopy(league_rosters)
        if league_context_id:
            updated["league_context_id"] = league_context_id
        team_name = str(updated.get("team_name") or "").strip()
        team_entry = league_rosters.get(team_name) if team_name else None
        if isinstance(team_entry, dict):
            updated["players"] = copy.deepcopy(team_entry.get("players") or [])
        updated["snapshot"] = _build_archive_snapshot(updated, league_rosters=league_rosters)
        updated["updated_at"] = _utc_now_iso()
        if updated != entry:
            entries[idx] = updated
            changed += 1
    if changed:
        _set_archive_list(session, entries)
    return changed


def accepted_trade_rosters_applied(context: dict[str, Any], proposal: dict[str, Any]) -> bool:
    """True when accepted trade players already sit on post-trade teams."""
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    gives = [
        str(p.get("player_name") or "").strip()
        for p in (proposal.get("proposer_gives") or [])
        if str(p.get("player_name") or "").strip()
    ]
    receives = [
        str(p.get("player_name") or "").strip()
        for p in (proposal.get("proposer_receives") or [])
        if str(p.get("player_name") or "").strip()
    ]
    for name in gives:
        if _player_owner(context, name) != recipient:
            return False
    for name in receives:
        if _player_owner(context, name) != proposer:
            return False
    return True


def _pre_trade_positions_valid(context: dict[str, Any], proposal: dict[str, Any]) -> bool:
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    gives = [
        str(p.get("player_name") or "").strip()
        for p in (proposal.get("proposer_gives") or [])
        if str(p.get("player_name") or "").strip()
    ]
    receives = [
        str(p.get("player_name") or "").strip()
        for p in (proposal.get("proposer_receives") or [])
        if str(p.get("player_name") or "").strip()
    ]
    for name in gives:
        if _player_owner(context, name) != proposer:
            return False
    for name in receives:
        if _player_owner(context, name) != recipient:
            return False
    return True


def reconcile_accepted_trades_in_context(
    context: dict[str, Any],
) -> tuple[dict[str, Any], bool, list[str]]:
    """Idempotently apply roster swaps for accepted trades that were not yet applied."""
    out = copy.deepcopy(context)
    out["ownership_map"] = out.get("ownership_map") or {}
    try:
        from fantasy_league_context import build_ownership_map

        out["ownership_map"] = build_ownership_map(out)
    except ImportError:
        pass
    changed = False
    traces: list[str] = []
    workflow = out.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        out["workflow"] = workflow
    proposals = workflow.get(WORKFLOW_KEY_TRADE_PROPOSALS)
    if not isinstance(proposals, list):
        proposals = []
    for idx, raw in enumerate(proposals):
        if not isinstance(raw, dict):
            continue
        proposal = dict(raw)
        status = str(proposal.get("status") or "").strip()
        if status != TRADE_PROPOSAL_STATUS_ACCEPTED:
            continue
        if accepted_trade_rosters_applied(out, proposal):
            continue
        proposal_id = str(proposal.get("proposal_id") or proposal.get("trade_id") or idx)
        if not _pre_trade_positions_valid(out, proposal):
            traces.append(f"accepted trade {proposal_id} cannot auto-reconcile (players moved)")
            continue
        if not _execute_roster_swap(out, proposal):
            traces.append(f"accepted trade {proposal_id} roster swap failed")
            continue
        proposals[idx] = proposal
        changed = True
        traces.append(f"reconciled accepted trade {proposal_id}")
    if changed:
        try:
            from fantasy_league_context import build_ownership_map

            out["ownership_map"] = build_ownership_map(out)
        except ImportError:
            pass
    return out, changed, traces


def roster_stats_cache_stale(
    session: dict[str, Any],
    context: dict[str, Any],
    roster_stats: pd.DataFrame | None,
) -> bool:
    """True when cached roster stats disagree with active league context rosters."""
    if roster_stats is None or getattr(roster_stats, "empty", True):
        return False
    current_sig = roster_content_fingerprint(context)
    if not current_sig:
        return False
    blob = session.get("fantasy_in_season_state")
    stored_sig = ""
    if isinstance(blob, dict):
        stored_sig = str(blob.get("league_rosters_view_sig") or "").strip()
    if stored_sig and stored_sig != current_sig:
        return True
    my_team = str(context.get("my_team_name") or "").strip()
    if not my_team:
        return False
    rosters = context.get("league_rosters") or {}
    team_entry = rosters.get(my_team) if isinstance(rosters, dict) else None
    if not isinstance(team_entry, dict):
        return False
    expected = {
        str(p.get("player_name") or "").strip().lower()
        for p in (team_entry.get("players") or [])
        if isinstance(p, dict)
        if str(p.get("player_name") or "").strip()
    }
    team_col = "Team" if "Team" in roster_stats.columns else None
    player_col = "Player" if "Player" in roster_stats.columns else None
    if not team_col or not player_col:
        return False
    cached = {
        str(row.get(player_col) or "").strip().lower()
        for _, row in roster_stats.iterrows()
        if str(row.get(team_col) or "").strip() == my_team
        if str(row.get(player_col) or "").strip()
    }
    return expected != cached


def finalize_trade_roster_persistence(
    session: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Archive sync + roster view cache invalidation after accepted trade or reconcile."""
    sync_all_archives_league_rosters(session, context)
    try:
        from fantasy_admin_draft_archive_repair import _sync_archives_to_workspace_team

        _sync_archives_to_workspace_team(session, context)
    except ImportError:
        pass
    invalidate_fantasy_roster_view_caches(session, context=context)
    return context
