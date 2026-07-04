"""Fantasy Trade Proposal System — pending offers, inbox, accept/decline, roster swaps."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from fantasy_league_context import (
    build_ownership_map,
    get_active_league_context,
    get_league_context,
    normalize_player_key,
    upsert_league_context,
)

WORKFLOW_KEY_TRADE_PROPOSALS = "trade_proposals"
TRADE_PROPOSAL_STATUS_PENDING = "pending"
TRADE_PROPOSAL_STATUS_ACCEPTED = "accepted"
TRADE_PROPOSAL_STATUS_DECLINED = "declined"
TRADE_PROPOSAL_HANDOFF_KEY = "_fantasy_trade_proposal_handoff"
STALE_TRADE_MESSAGE = (
    "Trade can no longer be completed because one or more players are no longer on the expected roster."
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_player_ref(player_name: str) -> dict[str, str]:
    name = str(player_name or "").strip()
    return {"player_name": name, "player_key": normalize_player_key(name)}


def _ensure_trade_proposals_workflow(context: dict[str, Any]) -> list[dict[str, Any]]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    raw = workflow.get(WORKFLOW_KEY_TRADE_PROPOSALS)
    if not isinstance(raw, list):
        raw = []
        workflow[WORKFLOW_KEY_TRADE_PROPOSALS] = raw
    return raw


def _league_team_names(context: dict[str, Any]) -> set[str]:
    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return set()
    return {str(team).strip() for team in rosters.keys() if str(team).strip()}


def _player_owner(context: dict[str, Any], player_name: str) -> str:
    ownership = context.get("ownership_map") or build_ownership_map(context)
    rec = ownership.get(normalize_player_key(player_name)) or {}
    if isinstance(rec, dict):
        return str(rec.get("owner_team") or "").strip()
    return ""


def _find_player_on_roster(context: dict[str, Any], team_name: str, player_name: str) -> dict[str, Any] | None:
    rosters = context.get("league_rosters") or {}
    entry = rosters.get(team_name) if isinstance(rosters, dict) else None
    if not isinstance(entry, dict):
        return None
    key = normalize_player_key(player_name)
    for player in entry.get("players") or []:
        if not isinstance(player, dict):
            continue
        pkey = str(player.get("player_key") or normalize_player_key(player.get("player_name"))).strip()
        if pkey == key:
            return dict(player)
    return None


def _remove_player_from_team_roster(context: dict[str, Any], team_name: str, player_name: str) -> dict[str, Any] | None:
    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return None
    entry = rosters.get(team_name)
    if not isinstance(entry, dict):
        return None
    remove_key = normalize_player_key(player_name)
    players = [dict(p) for p in (entry.get("players") or []) if isinstance(p, dict)]
    removed: dict[str, Any] | None = None
    kept: list[dict[str, Any]] = []
    for p in players:
        pkey = str(p.get("player_key") or normalize_player_key(p.get("player_name"))).strip()
        if pkey == remove_key:
            removed = p
        else:
            kept.append(p)
    if removed is None:
        return None
    entry["players"] = kept
    rosters[team_name] = entry
    context["league_rosters"] = rosters
    return removed


def _add_player_to_team_roster(
    context: dict[str, Any],
    team_name: str,
    player_record: dict[str, Any],
) -> bool:
    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return False
    my_team = str(context.get("my_team_name") or "").strip()
    entry = rosters.setdefault(
        team_name,
        {"team_name": team_name, "is_user_team": team_name == my_team, "players": []},
    )
    players = [dict(p) for p in (entry.get("players") or []) if isinstance(p, dict)]
    player_key = str(player_record.get("player_key") or normalize_player_key(player_record.get("player_name"))).strip()
    if any(str(p.get("player_key") or "") == player_key for p in players):
        return False
    new_player = dict(player_record)
    new_player["team_name"] = team_name
    new_player.setdefault("player_key", player_key)
    players.append(new_player)
    entry["players"] = players
    rosters[team_name] = entry
    context["league_rosters"] = rosters
    return True


def recipient_view(proposal: dict[str, Any]) -> dict[str, Any]:
    """Flip proposer perspective to recipient perspective for Trade Analyzer."""
    view = copy.deepcopy(proposal)
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    view["viewer_team"] = recipient
    view["other_team"] = proposer
    view["give_players"] = [str(p.get("player_name") or "") for p in (proposal.get("proposer_receives") or []) if str(p.get("player_name") or "").strip()]
    view["receive_players"] = [str(p.get("player_name") or "") for p in (proposal.get("proposer_gives") or []) if str(p.get("player_name") or "").strip()]
    return view


def proposer_view(proposal: dict[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(proposal)
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    view["viewer_team"] = proposer
    view["other_team"] = recipient
    view["give_players"] = [str(p.get("player_name") or "") for p in (proposal.get("proposer_gives") or []) if str(p.get("player_name") or "").strip()]
    view["receive_players"] = [str(p.get("player_name") or "") for p in (proposal.get("proposer_receives") or []) if str(p.get("player_name") or "").strip()]
    return view


def get_trade_proposals(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not context:
        return []
    workflow = context.get("workflow") or {}
    raw = workflow.get(WORKFLOW_KEY_TRADE_PROPOSALS) or []
    return [dict(x) for x in raw if isinstance(x, dict)]


def get_trade_proposal(context: dict[str, Any] | None, proposal_id: str) -> dict[str, Any] | None:
    proposal_id = str(proposal_id or "").strip()
    for proposal in get_trade_proposals(context):
        if str(proposal.get("proposal_id") or "") == proposal_id:
            return copy.deepcopy(proposal)
    return None


def get_incoming_trade_proposals(session: dict[str, Any], team_name: str) -> list[dict[str, Any]]:
    context = get_active_league_context(session)
    team = str(team_name or "").strip()
    if not context or not team:
        return []
    return [
        copy.deepcopy(p)
        for p in get_trade_proposals(context)
        if str(p.get("recipient_team") or "").strip() == team
    ]


def get_outgoing_trade_proposals(session: dict[str, Any], team_name: str) -> list[dict[str, Any]]:
    context = get_active_league_context(session)
    team = str(team_name or "").strip()
    if not context or not team:
        return []
    return [
        copy.deepcopy(p)
        for p in get_trade_proposals(context)
        if str(p.get("proposer_team") or "").strip() == team
    ]


def pending_incoming_count(session: dict[str, Any], team_name: str) -> int:
    return sum(
        1
        for p in get_incoming_trade_proposals(session, team_name)
        if str(p.get("status") or "") == TRADE_PROPOSAL_STATUS_PENDING
    )


def validate_proposal_players(
    context: dict[str, Any],
    *,
    proposer_team: str,
    recipient_team: str,
    proposer_gives: list[str],
    proposer_receives: list[str],
) -> tuple[bool, str]:
    teams = _league_team_names(context)
    proposer = str(proposer_team or "").strip()
    recipient = str(recipient_team or "").strip()
    if proposer not in teams:
        return False, f"Proposer team '{proposer}' is not in this league."
    if recipient not in teams:
        return False, f"Recipient team '{recipient}' is not in this league."
    if proposer == recipient:
        return False, "Proposer and recipient must be different teams."
    if not proposer_gives or not proposer_receives:
        return False, "Trade must include at least one player on each side."
    for name in proposer_gives:
        owner = _player_owner(context, name)
        if owner != proposer:
            return False, f"{name} is not on {proposer}'s roster."
    for name in proposer_receives:
        owner = _player_owner(context, name)
        if owner != recipient:
            return False, f"{name} is not on {recipient}'s roster."
    return True, ""


def validate_proposal_for_acceptance(context: dict[str, Any], proposal: dict[str, Any]) -> tuple[bool, str]:
    if str(proposal.get("status") or "") != TRADE_PROPOSAL_STATUS_PENDING:
        return False, "This trade is no longer pending."
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    teams = _league_team_names(context)
    if proposer not in teams or recipient not in teams:
        return False, STALE_TRADE_MESSAGE
    gives = [str(p.get("player_name") or "") for p in (proposal.get("proposer_gives") or []) if str(p.get("player_name") or "").strip()]
    receives = [str(p.get("player_name") or "") for p in (proposal.get("proposer_receives") or []) if str(p.get("player_name") or "").strip()]
    ok, msg = validate_proposal_players(context, proposer_team=proposer, recipient_team=recipient, proposer_gives=gives, proposer_receives=receives)
    if not ok:
        return False, STALE_TRADE_MESSAGE if "not on" in msg else msg
    return True, ""


def create_trade_proposal(
    session: dict[str, Any],
    *,
    proposer_team: str,
    recipient_team: str,
    proposer_gives: list[str],
    proposer_receives: list[str],
    verdict: str = "",
) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context in Saved Draft Library before proposing a trade."
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        return None, "Active league context is missing an id."
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."

    gives = [str(x).strip() for x in proposer_gives if str(x).strip()]
    receives = [str(x).strip() for x in proposer_receives if str(x).strip()]
    ok, msg = validate_proposal_players(
        context,
        proposer_team=proposer_team,
        recipient_team=recipient_team,
        proposer_gives=gives,
        proposer_receives=receives,
    )
    if not ok:
        return None, msg

    now = _utc_now_iso()
    proposal: dict[str, Any] = {
        "proposal_id": f"tp:{uuid.uuid4().hex[:12]}",
        "status": TRADE_PROPOSAL_STATUS_PENDING,
        "proposer_team": str(proposer_team or "").strip(),
        "recipient_team": str(recipient_team or "").strip(),
        "proposer_gives": [_normalize_player_ref(n) for n in gives],
        "proposer_receives": [_normalize_player_ref(n) for n in receives],
        "created_at": now,
        "updated_at": now,
        "responded_at": "",
        "verdict": str(verdict or "").strip(),
    }
    proposals = _ensure_trade_proposals_workflow(context)
    proposals.append(proposal)
    upsert_league_context(session, context)
    return copy.deepcopy(proposal), ""


def _execute_roster_swap(context: dict[str, Any], proposal: dict[str, Any]) -> bool:
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    gives = [str(p.get("player_name") or "") for p in (proposal.get("proposer_gives") or []) if str(p.get("player_name") or "").strip()]
    receives = [str(p.get("player_name") or "") for p in (proposal.get("proposer_receives") or []) if str(p.get("player_name") or "").strip()]

    removed_from_proposer: list[tuple[str, dict[str, Any]]] = []
    removed_from_recipient: list[tuple[str, dict[str, Any]]] = []

    for name in gives:
        rec = _remove_player_from_team_roster(context, proposer, name)
        if rec is None:
            return False
        removed_from_proposer.append((name, rec))

    for name in receives:
        rec = _remove_player_from_team_roster(context, recipient, name)
        if rec is None:
            for _, prior in removed_from_proposer:
                _add_player_to_team_roster(context, proposer, prior)
            return False
        removed_from_recipient.append((name, rec))

    for _, rec in removed_from_proposer:
        if not _add_player_to_team_roster(context, recipient, rec):
            for _, prior in removed_from_recipient:
                _add_player_to_team_roster(context, recipient, prior)
            for _, prior in removed_from_proposer:
                _add_player_to_team_roster(context, proposer, prior)
            return False

    for _, rec in removed_from_recipient:
        if not _add_player_to_team_roster(context, proposer, rec):
            return False

    workflow = context.setdefault("workflow", {})
    activity = list(workflow.get("league_activity") or [])
    for name in gives:
        activity.append(
            {
                "team_name": proposer,
                "action": "trade_away",
                "player_name": name,
                "counterparty": recipient,
                "recorded_at": _utc_now_iso(),
            }
        )
    for name in receives:
        activity.append(
            {
                "team_name": recipient,
                "action": "trade_away",
                "player_name": name,
                "counterparty": proposer,
                "recorded_at": _utc_now_iso(),
            }
        )
    workflow["league_activity"] = activity[-50:]
    context["workflow"] = workflow
    return True


def accept_trade_proposal(session: dict[str, Any], proposal_id: str) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context before accepting a trade."
    league_context_id = str(context.get("league_context_id") or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."

    proposal_id = str(proposal_id or "").strip()
    proposals = _ensure_trade_proposals_workflow(context)
    target_idx = -1
    proposal: dict[str, Any] | None = None
    for idx, existing in enumerate(proposals):
        if str(existing.get("proposal_id") or "") == proposal_id:
            target_idx = idx
            proposal = dict(existing)
            break
    if proposal is None:
        return None, "Trade proposal not found."

    ok, msg = validate_proposal_for_acceptance(context, proposal)
    if not ok:
        return None, msg

    if not _execute_roster_swap(context, proposal):
        return None, STALE_TRADE_MESSAGE

    now = _utc_now_iso()
    proposal["status"] = TRADE_PROPOSAL_STATUS_ACCEPTED
    proposal["updated_at"] = now
    proposal["responded_at"] = now
    proposals[target_idx] = proposal
    saved = upsert_league_context(session, context)
    return get_trade_proposal(saved, proposal_id), ""


def decline_trade_proposal(session: dict[str, Any], proposal_id: str) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context before declining a trade."
    league_context_id = str(context.get("league_context_id") or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."

    proposal_id = str(proposal_id or "").strip()
    proposals = _ensure_trade_proposals_workflow(context)
    target_idx = -1
    proposal: dict[str, Any] | None = None
    for idx, existing in enumerate(proposals):
        if str(existing.get("proposal_id") or "") == proposal_id:
            target_idx = idx
            proposal = dict(existing)
            break
    if proposal is None:
        return None, "Trade proposal not found."
    if str(proposal.get("status") or "") != TRADE_PROPOSAL_STATUS_PENDING:
        return None, "This trade is no longer pending."

    now = _utc_now_iso()
    proposal["status"] = TRADE_PROPOSAL_STATUS_DECLINED
    proposal["updated_at"] = now
    proposal["responded_at"] = now
    proposals[target_idx] = proposal
    saved = upsert_league_context(session, context)
    return get_trade_proposal(saved, proposal_id), ""


def set_trade_proposal_handoff(
    session: dict[str, Any],
    *,
    proposal_id: str,
    view_as_team: str,
) -> None:
    session[TRADE_PROPOSAL_HANDOFF_KEY] = {
        "proposal_id": str(proposal_id or "").strip(),
        "view_as_team": str(view_as_team or "").strip(),
    }
    session["_lineup_focus_trade_analyzer"] = True


def consume_trade_proposal_handoff(session: dict[str, Any]) -> dict[str, Any] | None:
    handoff = session.pop(TRADE_PROPOSAL_HANDOFF_KEY, None)
    if not isinstance(handoff, dict):
        return None
    proposal_id = str(handoff.get("proposal_id") or "").strip()
    view_as_team = str(handoff.get("view_as_team") or "").strip()
    if not proposal_id:
        return None
    context = get_active_league_context(session)
    proposal = get_trade_proposal(context, proposal_id)
    if not proposal:
        return None
    if view_as_team == str(proposal.get("recipient_team") or "").strip():
        view = recipient_view(proposal)
    else:
        view = proposer_view(proposal)
    other_team = str(view.get("other_team") or "").strip()
    give_players = list(view.get("give_players") or [])
    receive_players = list(view.get("receive_players") or [])
    if other_team:
        session["lineup_trade_other_team"] = other_team
    if give_players:
        session["lineup_trade_give_players"] = give_players
    if receive_players:
        session["lineup_trade_get_players"] = receive_players
    session["_lineup_focus_trade_analyzer"] = True
    return view
