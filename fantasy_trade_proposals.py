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
    save_draft_archive_with_league_context,
    upsert_league_context,
)
from fantasy_league_identity import ensure_league_identity, resolve_canonical_league_id
from fantasy_league_team_ownership import (
    TRADES_DISABLED_MESSAGE,
    owner_display_for_team,
    owner_user_id_for_team,
    owned_team_for_user,
    trades_enabled,
)

WORKFLOW_KEY_TRADE_PROPOSALS = "trade_proposals"
WORKFLOW_KEY_TRADE_ALERTS_SEEN = "trade_alerts_seen"
TRADE_PROPOSAL_STATUS_PENDING = "pending"
TRADE_PROPOSAL_STATUS_ACCEPTED = "accepted"
TRADE_PROPOSAL_STATUS_DECLINED = "declined"
TRADE_PROPOSAL_STATUS_CANCELED = "canceled"
TRADE_PROPOSAL_STATUS_COUNTERED = "countered"
TRADE_PROPOSAL_STATUS_EXPIRED = "expired"
TRADE_PROPOSAL_STATUS_STALE = "stale"
TRADE_HANDOFF_SESSION_KEY = "_fantasy_trade_proposal_handoff"
TRADE_OFFER_INBOX_DISMISSALS_KEY = "trade_offer_inbox_dismissals"
LINEUP_ASSISTANT_PAGE = "Fantasy Lineup Assistant"
TRADE_PHASE1_SIMPLE = False
STALE_TRADE_MESSAGE = (
    "Trade can no longer be completed because one or more players are no longer on the expected roster."
)
TRADE_SUBMIT_TRACE_KEY = "_suite_last_trade_submit_trace"
TRADE_RESPONSE_TRACE_KEY = "_suite_last_trade_response_trace"


def record_trade_submit_trace(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Persist trade propose-button diagnostics across reruns."""
    trace = dict(session.get(TRADE_SUBMIT_TRACE_KEY) or {})
    trace.update({k: v for k, v in fields.items() if v is not None or k.endswith("_error")})
    trace["updated_at"] = _utc_now_iso()
    session[TRADE_SUBMIT_TRACE_KEY] = trace
    return trace


def build_trade_submit_trace_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Latest trade propose form trace for diagnostic panels."""
    trace = dict(session.get(TRADE_SUBMIT_TRACE_KEY) or {})
    return {
        "button_clicked": bool(trace.get("button_clicked")),
        "propose_trade_called": bool(trace.get("propose_trade_called")),
        "proposer_team": trace.get("proposer_team"),
        "recipient_team": trace.get("recipient_team"),
        "give_players": trace.get("give_players"),
        "receive_players": trace.get("receive_players"),
        "trade_id": trace.get("trade_id"),
        "validation_error": trace.get("validation_error"),
        "create_error": trace.get("create_error"),
        "save_shared_league_ok": trace.get("save_shared_league_ok"),
        "save_shared_league_error": trace.get("save_shared_league_error"),
        "pending_trade_count_before": trace.get("pending_trade_count_before"),
        "pending_trade_count_after": trace.get("pending_trade_count_after"),
        "outgoing_count_before": trace.get("outgoing_count_before"),
        "outgoing_count_after": trace.get("outgoing_count_after"),
        "league_context_id": trace.get("league_context_id"),
        "league_id": trace.get("league_id"),
        "updated_at": trace.get("updated_at"),
    }


def record_trade_response_trace(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Persist trade accept/decline button diagnostics across reruns."""
    trace = dict(session.get(TRADE_RESPONSE_TRACE_KEY) or {})
    trace.update({k: v for k, v in fields.items() if v is not None or k.endswith("_error")})
    trace["updated_at"] = _utc_now_iso()
    session[TRADE_RESPONSE_TRACE_KEY] = trace
    return trace


def build_trade_response_trace_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Latest trade accept/decline trace for diagnostic panels."""
    trace = dict(session.get(TRADE_RESPONSE_TRACE_KEY) or {})
    return {
        "button_clicked": bool(trace.get("button_clicked")),
        "action": trace.get("action"),
        "respond_trade_called": bool(trace.get("respond_trade_called")),
        "trade_id": trace.get("trade_id"),
        "validation_error": trace.get("validation_error"),
        "update_error": trace.get("update_error"),
        "save_shared_league_ok": trace.get("save_shared_league_ok"),
        "save_shared_league_error": trace.get("save_shared_league_error"),
        "status_before": trace.get("status_before"),
        "status_after": trace.get("status_after"),
        "roster_mutation_attempted": trace.get("roster_mutation_attempted"),
        "roster_mutation_ok": trace.get("roster_mutation_ok"),
        "roster_mutation_error": trace.get("roster_mutation_error"),
        "pending_count_before": trace.get("pending_count_before"),
        "pending_count_after": trace.get("pending_count_after"),
        "accepted_count_before": trace.get("accepted_count_before"),
        "accepted_count_after": trace.get("accepted_count_after"),
        "recipient_team": trace.get("recipient_team"),
        "my_owned_team": trace.get("my_owned_team"),
        "league_context_id": trace.get("league_context_id"),
        "league_id": trace.get("league_id"),
        "updated_at": trace.get("updated_at"),
    }


def count_pending_trade_proposals(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    return sum(
        1
        for proposal in get_trade_proposals(context)
        if get_display_status(context, proposal) == TRADE_PROPOSAL_STATUS_PENDING
    )


def count_accepted_trade_proposals(context: dict[str, Any] | None) -> int:
    if not context:
        return 0
    return sum(
        1
        for proposal in get_trade_proposals(context)
        if str(proposal.get("status") or "") == TRADE_PROPOSAL_STATUS_ACCEPTED
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_utc_datetime(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _player_ids_from_refs(players: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for player in players:
        if not isinstance(player, dict):
            continue
        key = str(player.get("player_key") or normalize_player_key(player.get("player_name"))).strip()
        if key:
            ids.append(key)
    return ids


def _load_mutable_context(session: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context in Saved Draft Library before trading."
    league_context_id = str(context.get("league_context_id") or "").strip()
    if not league_context_id:
        return None, "Active league context is missing an id."
    try:
        from fantasy_shared_league_store import sync_context_with_shared_store

        context = sync_context_with_shared_store(session, context)
    except ImportError:
        context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."
    return context, ""


def finalize_accepted_trade(
    session: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], bool | None, str | None]:
    """Persist roster swap to local context, archive, and shared league document."""
    context = ensure_league_identity(context)
    context["ownership_map"] = build_ownership_map(context)
    meta = context.get("metadata") or {}
    draft_id = str(meta.get("source_draft_id") or meta.get("draft_id") or "").strip()
    league_context_id = str(context.get("league_context_id") or "").strip()
    if draft_id:
        save_draft_archive_with_league_context(
            session,
            draft_id=draft_id,
            league_rosters=context.get("league_rosters") or {},
            league_context_id=league_context_id,
        )
    try:
        from fantasy_trade_roster_sync import finalize_trade_roster_persistence

        finalize_trade_roster_persistence(session, context)
    except ImportError:
        pass
    saved = upsert_league_context(session, context, mark_persist_authoritative=False)
    save_shared_ok: bool | None = None
    save_shared_error: str | None = None
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        pushed = push_league_context_to_shared(session, saved)
        save_shared_ok = pushed is not None
        if not save_shared_ok:
            save_shared_error = "push_league_context_to_shared returned None"
    except ImportError:
        save_shared_ok = None
    except Exception as exc:
        save_shared_ok = False
        save_shared_error = str(exc)
    return saved, save_shared_ok, save_shared_error


def get_trade_history(context: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    pending: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    declined: list[dict[str, Any]] = []
    activity: list[dict[str, Any]] = []
    if not context:
        return {"pending": pending, "accepted": accepted, "declined": declined, "activity": activity}
    league_id = resolve_canonical_league_id(context)
    for proposal in get_trade_proposals(context):
        status = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING).strip()
        display = get_display_status(context, proposal)
        row = copy.deepcopy(proposal)
        if league_id:
            row["league_id"] = league_id
        if display == TRADE_PROPOSAL_STATUS_PENDING:
            pending.append(row)
        elif status == TRADE_PROPOSAL_STATUS_ACCEPTED:
            accepted.append(row)
        elif status == TRADE_PROPOSAL_STATUS_DECLINED:
            declined.append(row)
    workflow = context.get("workflow") or {}
    for raw in workflow.get("league_activity") or []:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action") or "")
        if not action.startswith("trade_"):
            continue
        entry = copy.deepcopy(raw)
        if league_id:
            entry["league_id"] = league_id
        activity.append(entry)
    activity.sort(key=lambda row: str(row.get("recorded_at") or ""), reverse=True)
    return {"pending": pending, "accepted": accepted, "declined": declined, "activity": activity}


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


def _format_player_list(players: list[dict[str, Any]]) -> str:
    names = [str(p.get("player_name") or "").strip() for p in players if str(p.get("player_name") or "").strip()]
    return ", ".join(names) if names else "—"


def _trade_summary(proposal: dict[str, Any]) -> str:
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    gives_fmt = _format_player_list(proposal.get("proposer_gives") or [])
    receives_fmt = _format_player_list(proposal.get("proposer_receives") or [])
    return f"{proposer} traded {gives_fmt} to {recipient} for {receives_fmt}."


def _record_trade_activity(context: dict[str, Any], proposal: dict[str, Any], action: str) -> None:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    proposer = str(proposal.get("proposer_team") or "").strip()
    recipient = str(proposal.get("recipient_team") or "").strip()
    gives_fmt = _format_player_list(proposal.get("proposer_gives") or [])
    receives_fmt = _format_player_list(proposal.get("proposer_receives") or [])
    action_norm = str(action or "").strip()
    labels = {
        TRADE_PROPOSAL_STATUS_ACCEPTED: _trade_summary(proposal),
        TRADE_PROPOSAL_STATUS_DECLINED: f"{recipient} declined {proposer}'s trade offer: {gives_fmt} for {receives_fmt}.",
        TRADE_PROPOSAL_STATUS_CANCELED: f"{proposer} canceled trade offer to {recipient}: {gives_fmt} for {receives_fmt}.",
        TRADE_PROPOSAL_STATUS_COUNTERED: f"{recipient} countered {proposer}'s trade offer.",
        TRADE_PROPOSAL_STATUS_EXPIRED: f"Trade offer from {proposer} to {recipient} expired: {gives_fmt} for {receives_fmt}.",
    }
    league_id = resolve_canonical_league_id(context)
    activity = list(workflow.get("league_activity") or [])
    activity.append(
        {
            "team_name": proposer,
            "action": f"trade_{action_norm}",
            "player_name": gives_fmt,
            "counterparty": recipient,
            "summary": labels.get(action_norm, _trade_summary(proposal)),
            "proposal_id": str(proposal.get("proposal_id") or ""),
            "league_id": league_id,
            "recorded_at": _utc_now_iso(),
        }
    )
    workflow["league_activity"] = activity[-100:]
    context["workflow"] = workflow


def is_trade_proposal_expired(proposal: dict[str, Any], *, now: datetime | None = None) -> bool:
    if str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING) != TRADE_PROPOSAL_STATUS_PENDING:
        return False
    expires_at = _parse_utc_datetime(str(proposal.get("expires_at") or ""))
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) >= expires_at


def _alert_key(proposal_id: str, kind: str) -> str:
    return f"{proposal_id}:{kind}"


def _ensure_alerts_seen(context: dict[str, Any]) -> dict[str, list[str]]:
    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        workflow = {}
        context["workflow"] = workflow
    raw = workflow.get(WORKFLOW_KEY_TRADE_ALERTS_SEEN)
    if not isinstance(raw, dict):
        raw = {}
        workflow[WORKFLOW_KEY_TRADE_ALERTS_SEEN] = raw
    return raw


def get_alerts_seen_for_team(context: dict[str, Any] | None, team_name: str) -> set[str]:
    if not context:
        return set()
    team = str(team_name or "").strip()
    seen = _ensure_alerts_seen(context).get(team) or []
    if not isinstance(seen, list):
        return set()
    return {str(x).strip() for x in seen if str(x).strip()}


def mark_trade_notification_seen(
    session: dict[str, Any],
    *,
    team_name: str,
    alert_key: str,
) -> None:
    context = get_active_league_context(session)
    if not context:
        return
    league_context_id = str(context.get("league_context_id") or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return
    team = str(team_name or "").strip()
    key = str(alert_key or "").strip()
    if not team or not key:
        return
    seen_map = _ensure_alerts_seen(context)
    seen_list = [str(x).strip() for x in (seen_map.get(team) or []) if str(x).strip()]
    if key not in seen_list:
        seen_list.append(key)
    seen_map[team] = seen_list[-200:]
    upsert_league_context(session, context, mark_persist_authoritative=False)


def get_display_status(context: dict[str, Any], proposal: dict[str, Any]) -> str:
    status = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING).strip()
    if status != TRADE_PROPOSAL_STATUS_PENDING:
        return status
    if is_trade_proposal_expired(proposal):
        return TRADE_PROPOSAL_STATUS_EXPIRED
    ok, _ = validate_proposal_for_acceptance(context, proposal)
    if not ok:
        return TRADE_PROPOSAL_STATUS_STALE
    return TRADE_PROPOSAL_STATUS_PENDING


def is_proposal_actionable(context: dict[str, Any], proposal: dict[str, Any], *, as_team: str) -> bool:
    display = get_display_status(context, proposal)
    if display != TRADE_PROPOSAL_STATUS_PENDING:
        return False
    team = str(as_team or "").strip()
    if team == str(proposal.get("recipient_team") or "").strip():
        return True
    if team == str(proposal.get("proposer_team") or "").strip():
        return True
    return False


def get_trade_notifications(
    session: dict[str, Any],
    team_name: str,
) -> list[dict[str, Any]]:
    """Build unread trade alerts for the active league and team."""
    context = get_active_league_context(session)
    team = str(team_name or "").strip()
    if not context or not team:
        return []
    seen = get_alerts_seen_for_team(context, team)
    alerts: list[dict[str, Any]] = []

    for proposal in get_incoming_trade_proposals(session, team):
        pid = str(proposal.get("proposal_id") or "")
        display = get_display_status(context, proposal)
        if display == TRADE_PROPOSAL_STATUS_PENDING:
            key = _alert_key(pid, "incoming")
            if key not in seen:
                proposer = str(proposal.get("proposer_team") or "")
                proposer_label = str(
                    proposal.get("from_user_display")
                    or owner_display_for_team(context, proposer)
                    or proposer
                ).strip()
                is_counter = bool(str(proposal.get("countered_from_proposal_id") or "").strip())
                if TRADE_PHASE1_SIMPLE:
                    message = f"New trade offer from {proposer_label}."
                elif is_counter:
                    message = f"Counteroffer from {proposer_label}"
                else:
                    message = f"1 incoming trade offer from {proposer_label}"
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "counteroffer" if is_counter else "incoming",
                        "message": message,
                        "view_as_team": team,
                    }
                )
        elif display == TRADE_PROPOSAL_STATUS_CANCELED:
            key = _alert_key(pid, "canceled_in")
            if key not in seen:
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "canceled",
                        "message": f"Trade offer from {proposal.get('proposer_team')} was canceled",
                        "view_as_team": team,
                    }
                )

    for proposal in get_outgoing_trade_proposals(session, team):
        pid = str(proposal.get("proposal_id") or "")
        status = str(proposal.get("status") or "")
        recipient = str(proposal.get("recipient_team") or "")
        if status == TRADE_PROPOSAL_STATUS_ACCEPTED:
            key = _alert_key(pid, "accepted")
            if key not in seen:
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "accepted",
                        "message": f"Trade accepted by {recipient}",
                        "view_as_team": team,
                    }
                )
        elif status == TRADE_PROPOSAL_STATUS_DECLINED:
            key = _alert_key(pid, "declined")
            if key not in seen:
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "declined",
                        "message": f"Trade declined by {recipient}",
                        "view_as_team": team,
                    }
                )
        elif status == TRADE_PROPOSAL_STATUS_COUNTERED:
            key = _alert_key(pid, "countered")
            if key not in seen:
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "countered",
                        "message": f"Trade countered by {recipient}",
                        "view_as_team": team,
                    }
                )
        elif status == TRADE_PROPOSAL_STATUS_EXPIRED:
            key = _alert_key(pid, "expired")
            if key not in seen:
                alerts.append(
                    {
                        "alert_key": key,
                        "proposal_id": pid,
                        "kind": "expired",
                        "message": f"Trade offer to {recipient} expired",
                        "view_as_team": team,
                    }
                )

    return alerts


def pending_incoming_count(session: dict[str, Any], team_name: str) -> int:
    context = get_active_league_context(session)
    if not context:
        return 0
    return sum(
        1
        for p in get_incoming_trade_proposals(session, team_name)
        if get_display_status(context, p) == TRADE_PROPOSAL_STATUS_PENDING
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
    if len(proposer_gives) > 3 or len(proposer_receives) > 3:
        return False, "Trade proposals support up to three players on each side."
    if len(proposer_gives) + len(proposer_receives) > 5:
        return False, "Trade proposals currently support up to five total players."
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
    if is_trade_proposal_expired(proposal):
        return False, "This trade proposal has expired."
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
    expires_at: str = "",
    countered_from_proposal_id: str = "",
) -> tuple[dict[str, Any] | None, str]:
    context, load_err = _load_mutable_context(session)
    if context is None:
        record_trade_submit_trace(session, propose_trade_called=False, create_error=load_err or "No active league context")
        return None, load_err

    enabled, gate_msg = trades_enabled(context, session)
    if not enabled:
        err = gate_msg or TRADES_DISABLED_MESSAGE
        record_trade_submit_trace(session, propose_trade_called=False, create_error=err)
        return None, err

    proposer = str(proposer_team or "").strip()
    recipient = str(recipient_team or "").strip()
    my_owned = owned_team_for_user(context)
    if my_owned and proposer != my_owned:
        err = f"Your account owns {my_owned}; trades must be proposed from that team."
        record_trade_submit_trace(
            session,
            propose_trade_called=True,
            proposer_team=proposer,
            recipient_team=recipient,
            create_error=err,
        )
        return None, err

    gives = [str(x).strip() for x in proposer_gives if str(x).strip()]
    receives = [str(x).strip() for x in proposer_receives if str(x).strip()]
    ok, msg = validate_proposal_players(
        context,
        proposer_team=proposer,
        recipient_team=recipient,
        proposer_gives=gives,
        proposer_receives=receives,
    )
    if not ok:
        record_trade_submit_trace(
            session,
            propose_trade_called=True,
            proposer_team=proposer,
            recipient_team=recipient,
            give_players=gives,
            receive_players=receives,
            validation_error=msg,
            create_error=msg,
        )
        return None, msg

    give_refs = [_normalize_player_ref(n) for n in gives]
    receive_refs = [_normalize_player_ref(n) for n in receives]
    now = _utc_now_iso()
    from_user_id = owner_user_id_for_team(context, proposer) or owned_team_for_user(context)
    to_user_id = owner_user_id_for_team(context, recipient)
    if not to_user_id:
        err = f"{recipient} has no account owner assigned yet."
        record_trade_submit_trace(
            session,
            propose_trade_called=True,
            proposer_team=proposer,
            recipient_team=recipient,
            give_players=gives,
            receive_players=receives,
            create_error=err,
        )
        return None, err
    league_id = resolve_canonical_league_id(context)
    league_context_id = str(context.get("league_context_id") or "").strip()
    record_trade_submit_trace(
        session,
        propose_trade_called=True,
        proposer_team=proposer,
        recipient_team=recipient,
        give_players=gives,
        receive_players=receives,
        league_context_id=league_context_id or None,
        league_id=league_id or None,
        create_error=None,
        validation_error=None,
        trade_id=None,
    )
    proposal: dict[str, Any] = {
        "proposal_id": f"tp:{uuid.uuid4().hex[:12]}",
        "trade_id": "",
        "league_id": league_id,
        "status": TRADE_PROPOSAL_STATUS_PENDING,
        "proposer_team": proposer,
        "recipient_team": recipient,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "from_team_id": proposer,
        "to_team_id": recipient,
        "proposer_gives": give_refs,
        "proposer_receives": receive_refs,
        "give_player_ids": _player_ids_from_refs(give_refs),
        "receive_player_ids": _player_ids_from_refs(receive_refs),
        "from_user_display": owner_display_for_team(context, proposer),
        "created_at": now,
        "updated_at": now,
        "responded_at": "",
        "accepted_at": "",
        "declined_at": "",
        "expires_at": "" if TRADE_PHASE1_SIMPLE else str(expires_at or "").strip(),
        "countered_from_proposal_id": "" if TRADE_PHASE1_SIMPLE else str(countered_from_proposal_id or "").strip(),
        "verdict": str(verdict or "").strip(),
    }
    proposal["trade_id"] = str(proposal["proposal_id"])
    proposals = _ensure_trade_proposals_workflow(context)
    proposals.append(proposal)
    context = ensure_league_identity(context)
    saved = upsert_league_context(session, context, mark_persist_authoritative=False)
    reloaded = get_league_context(session, str(saved.get("league_context_id") or "")) or saved
    save_shared_ok: bool | None = None
    save_shared_error: str | None = None
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        pushed = push_league_context_to_shared(session, reloaded)
        save_shared_ok = pushed is not None
        if not save_shared_ok:
            save_shared_error = "push_league_context_to_shared returned None"
    except ImportError:
        save_shared_ok = None
    except Exception as exc:
        save_shared_ok = False
        save_shared_error = str(exc)
    proposal_id = str(proposal["proposal_id"])
    created = get_trade_proposal(reloaded, proposal_id)
    if not created:
        err = "Trade proposal saved but could not be reloaded from league context."
        record_trade_submit_trace(
            session,
            trade_id=proposal_id,
            create_error=err,
            save_shared_league_ok=save_shared_ok,
            save_shared_league_error=save_shared_error,
        )
        return None, err
    record_trade_submit_trace(
        session,
        trade_id=str(created.get("trade_id") or created.get("proposal_id") or proposal_id),
        create_error=None,
        save_shared_league_ok=save_shared_ok,
        save_shared_league_error=save_shared_error,
    )
    return created, ""


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

    return True


def accept_trade_proposal(session: dict[str, Any], proposal_id: str) -> tuple[dict[str, Any] | None, str]:
    proposal_id = str(proposal_id or "").strip()
    record_trade_response_trace(
        session,
        respond_trade_called=True,
        action="accept",
        trade_id=proposal_id or None,
    )
    context, load_err = _load_mutable_context(session)
    if context is None:
        record_trade_response_trace(session, update_error=load_err or "No active league context")
        return None, load_err

    league_context_id = str(context.get("league_context_id") or "").strip()
    league_id = resolve_canonical_league_id(context)
    record_trade_response_trace(
        session,
        league_context_id=league_context_id or None,
        league_id=league_id or None,
    )

    enabled, gate_msg = trades_enabled(context, session)
    if not enabled:
        err = gate_msg or TRADES_DISABLED_MESSAGE
        record_trade_response_trace(session, update_error=err)
        return None, err

    proposals = _ensure_trade_proposals_workflow(context)
    target_idx = -1
    proposal: dict[str, Any] | None = None
    for idx, existing in enumerate(proposals):
        if str(existing.get("proposal_id") or "") == proposal_id:
            target_idx = idx
            proposal = dict(existing)
            break
    if proposal is None:
        err = "Trade proposal not found."
        record_trade_response_trace(session, update_error=err)
        return None, err

    status_before = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING).strip()
    record_trade_response_trace(session, status_before=status_before)

    if status_before == TRADE_PROPOSAL_STATUS_ACCEPTED:
        try:
            from fantasy_trade_roster_sync import (
                accepted_trade_rosters_applied,
                finalize_trade_roster_persistence,
            )

            if accepted_trade_rosters_applied(context, proposal):
                return get_trade_proposal(context, proposal_id), ""
            if _execute_roster_swap(context, proposal):
                finalize_trade_roster_persistence(session, context)
                saved, save_shared_ok, save_shared_error = finalize_accepted_trade(session, context)
                record_trade_response_trace(
                    session,
                    roster_mutation_attempted=True,
                    roster_mutation_ok=True,
                    status_after=TRADE_PROPOSAL_STATUS_ACCEPTED,
                    save_shared_league_ok=save_shared_ok,
                    save_shared_league_error=save_shared_error,
                    update_error=None,
                )
                return get_trade_proposal(saved, proposal_id), ""
        except ImportError:
            pass
        err = "This trade is no longer pending."
        record_trade_response_trace(session, update_error=err, status_after=status_before)
        return None, err

    if status_before != TRADE_PROPOSAL_STATUS_PENDING:
        err = "This trade is no longer pending."
        record_trade_response_trace(session, update_error=err, status_after=status_before)
        return None, err

    ok, msg = validate_proposal_for_acceptance(context, proposal)
    if not ok:
        if msg == "This trade proposal has expired.":
            proposal["status"] = TRADE_PROPOSAL_STATUS_EXPIRED
            proposal["updated_at"] = _utc_now_iso()
            proposal["responded_at"] = proposal["updated_at"]
            proposals[target_idx] = proposal
            _record_trade_activity(context, proposal, TRADE_PROPOSAL_STATUS_EXPIRED)
            upsert_league_context(session, context, mark_persist_authoritative=False)
            record_trade_response_trace(
                session,
                validation_error=msg,
                update_error=msg,
                status_after=TRADE_PROPOSAL_STATUS_EXPIRED,
            )
            return None, msg
        if msg == STALE_TRADE_MESSAGE:
            proposal["status"] = TRADE_PROPOSAL_STATUS_STALE
            proposal["updated_at"] = _utc_now_iso()
            proposals[target_idx] = proposal
            upsert_league_context(session, context, mark_persist_authoritative=False)
        record_trade_response_trace(
            session,
            validation_error=msg,
            update_error=msg,
            status_after=str(proposal.get("status") or status_before),
        )
        return None, msg

    recipient = str(proposal.get("recipient_team") or "").strip()
    my_owned = owned_team_for_user(context)
    record_trade_response_trace(session, recipient_team=recipient, my_owned_team=my_owned or None)
    if my_owned and recipient != my_owned:
        err = f"Only the owner of {recipient} can accept this trade."
        record_trade_response_trace(session, validation_error=err, update_error=err)
        return None, err

    record_trade_response_trace(session, roster_mutation_attempted=True)
    if not _execute_roster_swap(context, proposal):
        record_trade_response_trace(
            session,
            roster_mutation_ok=False,
            roster_mutation_error=STALE_TRADE_MESSAGE,
            update_error=STALE_TRADE_MESSAGE,
        )
        return None, STALE_TRADE_MESSAGE
    record_trade_response_trace(session, roster_mutation_ok=True, roster_mutation_error=None)

    now = _utc_now_iso()
    proposal["status"] = TRADE_PROPOSAL_STATUS_ACCEPTED
    proposal["updated_at"] = now
    proposal["responded_at"] = now
    proposal["accepted_at"] = now
    proposals[target_idx] = proposal
    _record_trade_activity(context, proposal, TRADE_PROPOSAL_STATUS_ACCEPTED)
    saved, save_shared_ok, save_shared_error = finalize_accepted_trade(session, context)
    record_trade_response_trace(
        session,
        status_after=TRADE_PROPOSAL_STATUS_ACCEPTED,
        save_shared_league_ok=save_shared_ok,
        save_shared_league_error=save_shared_error,
        update_error=None,
    )
    return get_trade_proposal(saved, proposal_id), ""


def decline_trade_proposal(session: dict[str, Any], proposal_id: str) -> tuple[dict[str, Any] | None, str]:
    context, load_err = _load_mutable_context(session)
    if context is None:
        return None, load_err

    enabled, gate_msg = trades_enabled(context, session)
    if not enabled:
        return None, gate_msg or TRADES_DISABLED_MESSAGE

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
    proposal["declined_at"] = now
    proposals[target_idx] = proposal
    _record_trade_activity(context, proposal, TRADE_PROPOSAL_STATUS_DECLINED)
    saved = upsert_league_context(session, context)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, saved)
    except ImportError:
        pass
    return get_trade_proposal(saved, proposal_id), ""


def cancel_trade_proposal(
    session: dict[str, Any],
    proposal_id: str,
    *,
    canceled_by_team: str = "",
) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context before canceling a trade."
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
        return None, "Only pending trades can be canceled."
    proposer = str(proposal.get("proposer_team") or "").strip()
    team = str(canceled_by_team or proposer).strip()
    if team != proposer:
        return None, "Only the proposing team can cancel this offer."

    now = _utc_now_iso()
    proposal["status"] = TRADE_PROPOSAL_STATUS_CANCELED
    proposal["updated_at"] = now
    proposal["responded_at"] = now
    proposals[target_idx] = proposal
    _record_trade_activity(context, proposal, TRADE_PROPOSAL_STATUS_CANCELED)
    saved = upsert_league_context(session, context)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, saved)
    except ImportError:
        pass
    return get_trade_proposal(saved, proposal_id), ""


def counter_trade_proposal(
    session: dict[str, Any],
    proposal_id: str,
    *,
    countered_by_team: str,
    counter_gives: list[str],
    counter_receives: list[str],
    verdict: str = "",
    expires_at: str = "",
) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context before countering a trade."
    league_context_id = str(context.get("league_context_id") or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."

    proposal_id = str(proposal_id or "").strip()
    proposals = _ensure_trade_proposals_workflow(context)
    target_idx = -1
    original: dict[str, Any] | None = None
    for idx, existing in enumerate(proposals):
        if str(existing.get("proposal_id") or "") == proposal_id:
            target_idx = idx
            original = dict(existing)
            break
    if original is None:
        return None, "Trade proposal not found."
    if str(original.get("status") or "") != TRADE_PROPOSAL_STATUS_PENDING:
        return None, "Only pending trades can be countered."
    if is_trade_proposal_expired(original):
        original["status"] = TRADE_PROPOSAL_STATUS_EXPIRED
        original["updated_at"] = _utc_now_iso()
        original["responded_at"] = original["updated_at"]
        proposals[target_idx] = original
        _record_trade_activity(context, original, TRADE_PROPOSAL_STATUS_EXPIRED)
        upsert_league_context(session, context, mark_persist_authoritative=False)
        return None, "This trade proposal has expired."

    proposer = str(original.get("proposer_team") or "").strip()
    recipient = str(original.get("recipient_team") or "").strip()
    team = str(countered_by_team or "").strip()
    if team != recipient:
        return None, "Only the receiving team can counter this offer."

    gives = [str(x).strip() for x in counter_gives if str(x).strip()]
    receives = [str(x).strip() for x in counter_receives if str(x).strip()]
    ok, msg = validate_proposal_players(
        context,
        proposer_team=recipient,
        recipient_team=proposer,
        proposer_gives=gives,
        proposer_receives=receives,
    )
    if not ok:
        return None, msg

    now = _utc_now_iso()
    original["status"] = TRADE_PROPOSAL_STATUS_COUNTERED
    original["updated_at"] = now
    original["responded_at"] = now
    proposals[target_idx] = original
    _record_trade_activity(context, original, TRADE_PROPOSAL_STATUS_COUNTERED)

    counter: dict[str, Any] = {
        "proposal_id": f"tp:{uuid.uuid4().hex[:12]}",
        "status": TRADE_PROPOSAL_STATUS_PENDING,
        "proposer_team": recipient,
        "recipient_team": proposer,
        "proposer_gives": [_normalize_player_ref(n) for n in gives],
        "proposer_receives": [_normalize_player_ref(n) for n in receives],
        "created_at": now,
        "updated_at": now,
        "responded_at": "",
        "expires_at": str(expires_at or "").strip(),
        "countered_from_proposal_id": proposal_id,
        "verdict": str(verdict or "").strip(),
    }
    proposals.append(counter)
    saved = upsert_league_context(session, context)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, saved)
    except ImportError:
        pass
    return get_trade_proposal(saved, str(counter["proposal_id"])), ""


def set_trade_proposal_handoff(
    session: dict[str, Any],
    *,
    proposal_id: str,
    view_as_team: str,
) -> None:
    session[TRADE_HANDOFF_SESSION_KEY] = {
        "proposal_id": str(proposal_id or "").strip(),
        "view_as_team": str(view_as_team or "").strip(),
    }
    session["_lineup_focus_trade_center"] = True


def navigate_to_trade_proposal(
    session: dict[str, Any],
    *,
    proposal_id: str,
    view_as_team: str,
    alert_key: str = "",
) -> None:
    """Deep-link to Fantasy Lineup Assistant Trade Analyzer with proposal loaded."""
    set_trade_proposal_handoff(session, proposal_id=proposal_id, view_as_team=view_as_team)
    session["_navigate_to_page"] = LINEUP_ASSISTANT_PAGE
    session["_skip_page_restore_for"] = LINEUP_ASSISTANT_PAGE
    if alert_key:
        mark_trade_notification_seen(session, team_name=view_as_team, alert_key=alert_key)


def archived_offer_ids(session: dict[str, Any], league_id: str) -> set[str]:
    """Return proposal IDs cleared from this user's active Offers inbox."""
    scope = _resolve_offer_dismissal_scope(session, league_id=league_id)
    if not scope.get("league_id"):
        return set()
    store = _ensure_offer_dismissal_store(session)
    records = store.get("records") if isinstance(store.get("records"), dict) else {}
    out: set[str] = set()
    for rec in records.values():
        if not isinstance(rec, dict):
            continue
        if not _offer_dismissal_record_matches_scope(rec, scope):
            continue
        pid = str(rec.get("proposal_id") or "").strip()
        if pid:
            out.add(pid)
    return out


def archive_offer_from_inbox(session: dict[str, Any], proposal_id: str, *, league_id: str) -> None:
    """Persistently hide a completed offer from this account's Offers inbox."""
    pid = str(proposal_id or "").strip()
    scope = _resolve_offer_dismissal_scope(session, league_id=league_id)
    lid = str(scope.get("league_id") or "").strip()
    if not pid or not lid:
        return
    store = _ensure_offer_dismissal_store(session)
    records = store.setdefault("records", {})
    if not isinstance(records, dict):
        records = {}
        store["records"] = records
    key = _offer_dismissal_record_key(scope, pid)
    records[key] = {
        "user_id": scope.get("user_id") or "",
        "workspace_id": scope.get("workspace_id") or "",
        "league_id": lid,
        "proposal_id": pid,
        "dismissed_at": _utc_now_iso(),
    }
    session[TRADE_OFFER_INBOX_DISMISSALS_KEY] = store
    _persist_trade_inbox_dismissals(session)


def is_offer_archived(session: dict[str, Any], proposal_id: str, *, league_id: str) -> bool:
    return str(proposal_id or "").strip() in archived_offer_ids(session, league_id)


def _session_state_stub(session: dict[str, Any]) -> Any:
    return type("_SessionStateStub", (), {"session_state": session})()


def _resolve_offer_dismissal_scope(session: dict[str, Any], *, league_id: str = "") -> dict[str, str]:
    user_id = str(
        session.get("_suite_auth_user_id")
        or session.get("_suite_cloud_user_id")
        or ""
    ).strip()
    if not user_id:
        try:
            from fantasy_league_team_ownership import _resolve_user_id

            user_id = str(_resolve_user_id() or "").strip()
        except ImportError:
            pass
    workspace_id = ""
    try:
        from suite_workspace import get_active_workspace_id

        workspace_id = str(get_active_workspace_id(_session_state_stub(session)) or "").strip()
    except ImportError:
        workspace_id = str(
            session.get("_suite_owned_workspace_id")
            or session.get("_suite_active_workspace_id")
            or ""
        ).strip()
    lid = str(league_id or "").strip()
    if not lid:
        try:
            from fantasy_league_identity import resolve_canonical_league_id

            context = get_active_league_context(session)
            lid = str(resolve_canonical_league_id(context) or "").strip()
        except ImportError:
            pass
    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "league_id": lid,
    }


def _offer_dismissal_record_key(scope: dict[str, str], proposal_id: str) -> str:
    return "|".join(
        [
            str(scope.get("user_id") or "").strip(),
            str(scope.get("workspace_id") or "").strip(),
            str(scope.get("league_id") or "").strip(),
            str(proposal_id or "").strip(),
        ]
    )


def _offer_dismissal_record_matches_scope(record: dict[str, Any], scope: dict[str, str]) -> bool:
    if str(record.get("league_id") or "").strip() != str(scope.get("league_id") or "").strip():
        return False
    rec_user = str(record.get("user_id") or "").strip()
    rec_ws = str(record.get("workspace_id") or "").strip()
    scope_user = str(scope.get("user_id") or "").strip()
    scope_ws = str(scope.get("workspace_id") or "").strip()
    if scope_user and rec_user and rec_user != scope_user:
        return False
    if scope_ws and rec_ws and rec_ws != scope_ws:
        return False
    return True


def _ensure_offer_dismissal_store(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(TRADE_OFFER_INBOX_DISMISSALS_KEY)
    if isinstance(raw, dict):
        store = dict(raw)
    else:
        store = {"records": {}}
    records = store.get("records")
    if not isinstance(records, dict):
        store["records"] = {}
    return store


def _persist_trade_inbox_dismissals(session: dict[str, Any]) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state
    except ImportError:
        return
    try:
        force_save_baseball_state(_session_state_stub(session), reason="trade_offer_inbox_dismissal")
    except Exception:
        pass


def consume_trade_proposal_handoff(session: dict[str, Any]) -> dict[str, Any] | None:
    handoff = session.pop(TRADE_HANDOFF_SESSION_KEY, None)
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
    session["_lineup_focus_trade_center"] = True
    session["_trade_center_handoff"] = {
        "proposal_id": proposal_id,
        "give_players": give_players,
        "receive_players": receive_players,
        "other_team": other_team,
        "source_offer_id": proposal_id,
        "auto_analyze": True,
    }
    return view
