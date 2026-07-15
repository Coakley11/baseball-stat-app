"""
Command Center activity emitters for fantasy league workflows.

Continue = actionable resume cards (trade offers, invites, locks, …).
Activity = detailed work history.
App Directory chips are derived on the Command Center side from these events.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from baseball_activity import _record


def _league_label(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(
        context.get("league_name")
        or context.get("display_name")
        or context.get("league_label")
        or ""
    ).strip()


def _league_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    try:
        from fantasy_league_context import resolve_canonical_league_id

        return str(resolve_canonical_league_id(context) or "").strip()
    except Exception:
        return str(context.get("league_id") or context.get("league_context_id") or "").strip()


def _trade_label(proposal: dict[str, Any] | None) -> str:
    if not isinstance(proposal, dict):
        return ""
    try:
        from fantasy_trade_proposals import _format_player_list

        gives = _format_player_list(proposal.get("proposer_gives") or [])
        receives = _format_player_list(proposal.get("proposer_receives") or [])
    except Exception:
        gives = ", ".join(
            str(x.get("name") if isinstance(x, dict) else x).strip()
            for x in (proposal.get("proposer_gives") or [])[:2]
            if str(x.get("name") if isinstance(x, dict) else x).strip()
        )
        receives = ", ".join(
            str(x.get("name") if isinstance(x, dict) else x).strip()
            for x in (proposal.get("proposer_receives") or [])[:2]
            if str(x.get("name") if isinstance(x, dict) else x).strip()
        )
    if gives and receives:
        return f"{gives} ⇄ {receives}"
    return ""


def _my_team(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(context.get("my_team_name") or "").strip()


def _league_context_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(context.get("league_context_id") or "").strip()


def _invalidate_resume(item_key: str) -> None:
    key = str(item_key or "").strip()
    if not key:
        return
    try:
        from suite_activity_client import invalidate_resume_item

        invalidate_resume_item("baseball", key)
    except Exception:
        pass


def _invalidate_trade_resume(proposal_id: str) -> None:
    pid = str(proposal_id or "").strip()
    if pid:
        _invalidate_resume(f"bb:trade_center:{pid}")


def _common_league_metrics(context: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    out = {
        "league_id": _league_id(context),
        "league_name": _league_label(context),
        "league_context_id": _league_context_id(context),
        "my_team": _my_team(context),
    }
    out.update({k: v for k, v in extra.items() if v not in (None, "")})
    return out


def log_trade_offer_sent(context: dict[str, Any] | None, proposal: dict[str, Any] | None) -> None:
    if not isinstance(proposal, dict):
        return
    pid = str(proposal.get("proposal_id") or "").strip()
    if not pid:
        return
    to_team = str(proposal.get("recipient_team") or "").strip()
    from_team = str(proposal.get("proposer_team") or "").strip()
    trade = _trade_label(proposal)
    _record(
        "trade_offer_sent",
        page="Trade Center",
        metrics=_common_league_metrics(
            context,
            proposal_id=pid,
            from_team=from_team,
            to_team=to_team,
            proposer_team=from_team,
            recipient_team=to_team,
            trade=trade,
            feature="Trade Center",
        ),
        summary=f"Sent trade offer to {to_team}" + (f": {trade}" if trade else ""),
        resume_key=f"bb:trade_center:{pid}",
        resume_title=f"Trade offer to {to_team}" if to_team else "Outgoing trade offer",
        resume_subtitle=trade or "Trade Center",
        workstream="baseball_fantasy",
    )


def log_trade_offer_received(context: dict[str, Any] | None, proposal: dict[str, Any] | None) -> None:
    """Emit when the current account first sees an incoming pending offer."""
    if not isinstance(proposal, dict):
        return
    pid = str(proposal.get("proposal_id") or "").strip()
    if not pid:
        return
    from_team = str(proposal.get("proposer_team") or "").strip()
    to_team = str(proposal.get("recipient_team") or "").strip()
    trade = _trade_label(proposal)
    _record(
        "trade_offer_received",
        page="Trade Center",
        metrics=_common_league_metrics(
            context,
            proposal_id=pid,
            from_team=from_team,
            to_team=to_team,
            proposer_team=from_team,
            recipient_team=to_team,
            trade=trade,
            my_team=to_team or _my_team(context),
            feature="Trade Center",
        ),
        summary=f"Received trade offer from {from_team}" + (f": {trade}" if trade else ""),
        resume_key=f"bb:trade_center:{pid}",
        resume_title=f"Trade offer from {from_team}" if from_team else "New trade offer",
        resume_subtitle=trade or "Trade Center",
        workstream="baseball_fantasy",
    )


def log_trade_terminal(
    context: dict[str, Any] | None,
    proposal: dict[str, Any] | None,
    *,
    status: str,
) -> None:
    if not isinstance(proposal, dict):
        return
    pid = str(proposal.get("proposal_id") or "").strip()
    status_norm = str(status or "").strip().lower()
    event_map = {
        "accepted": "trade_accepted",
        "declined": "trade_declined",
        "canceled": "trade_canceled",
        "cancelled": "trade_canceled",
        "expired": "trade_expired",
    }
    event = event_map.get(status_norm)
    if not event or not pid:
        return
    _invalidate_trade_resume(pid)
    from_team = str(proposal.get("proposer_team") or "").strip()
    to_team = str(proposal.get("recipient_team") or "").strip()
    trade = _trade_label(proposal)
    titles = {
        "trade_accepted": "Trade completed",
        "trade_declined": "Trade offer declined",
        "trade_canceled": "Trade offer canceled",
        "trade_expired": "Trade offer expired",
    }
    _record(
        event,
        page="Trade Center",
        metrics=_common_league_metrics(
            context,
            proposal_id=pid,
            from_team=from_team,
            to_team=to_team,
            proposer_team=from_team,
            recipient_team=to_team,
            trade=trade,
            status=status_norm,
            feature="Trade Center",
        ),
        summary=titles[event] + (f": {trade}" if trade else ""),
        resume_key=f"bb:trade_center:{pid}",
        resume_title=titles[event],
        resume_subtitle=trade or "Trade Center",
        workstream="baseball_fantasy",
    )


def log_waiver_recommendation(
    context: dict[str, Any] | None,
    *,
    add_player: str = "",
) -> None:
    """Continue-eligible pending waiver task (cleared when a waiver transaction lands)."""
    lid = _league_id(context)
    player = str(add_player or "").strip()
    title = f"Waiver pickup: {player}" if player else "Review Waiver Wire"
    rk = f"bb:waiver:{lid}" if lid else "bb:waiver"
    _record(
        "waiver_recommendation",
        page="Waiver Wire / Add-Drop Center",
        metrics=_common_league_metrics(
            context,
            player=player,
            add_player=player,
            feature="Waiver Wire",
        ),
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Waiver Wire",
        workstream="baseball_fantasy",
    )


def log_waiver_transaction(
    context: dict[str, Any] | None,
    *,
    added: list[str] | None = None,
    dropped: list[str] | None = None,
) -> None:
    """Activity-only history — clears waiver recommendation Continue cards."""
    adds = [str(x).strip() for x in (added or []) if str(x).strip()]
    drops = [str(x).strip() for x in (dropped or []) if str(x).strip()]
    if not adds and not drops:
        return
    lid = _league_id(context)
    tx_id = f"wtx:{uuid4().hex[:10]}"
    if adds and drops:
        summary = f"Dropped {', '.join(drops)} and added {', '.join(adds)}"
    elif adds:
        summary = f"Added {', '.join(adds)} from Waiver Wire"
    else:
        summary = f"Dropped {', '.join(drops)}"
    # Remove pending waiver Continuity for this league.
    if lid:
        _invalidate_resume(f"bb:waiver:{lid}")
    _invalidate_resume("bb:waiver")
    _record(
        "waiver_transaction",
        page="Waiver Wire / Add-Drop Center",
        metrics=_common_league_metrics(
            context,
            added=adds,
            dropped=drops,
            added_players=adds,
            dropped_players=drops,
            waiver_tx_id=tx_id,
            feature="Waiver Wire",
            cc_card_kind="activity",
        ),
        summary=summary,
        resume_key="",
        resume_title="",
        resume_subtitle="",
        workstream="baseball_fantasy",
        cc_card_kind="activity",
    )


def _lineup_resume_key(context: dict[str, Any] | None, week: str) -> str:
    lid = _league_id(context)
    week_s = str(week or "").strip()
    if lid and week_s:
        return f"bb:lineup:{lid}:w{week_s}"
    if week_s:
        return f"bb:lineup:w{week_s}"
    return "bb:lineup"


def log_lineup_reminder(
    context: dict[str, Any] | None,
    *,
    week: int | str,
    team: str = "",
) -> None:
    week_s = str(week).strip()
    title = f"Finish Week {week_s} lineup" if week_s else "Finish weekly lineup"
    rk = _lineup_resume_key(context, week_s)
    _record(
        "lineup_reminder",
        page="Fantasy Lineup Assistant",
        metrics=_common_league_metrics(
            context,
            week=week_s,
            team=str(team or _my_team(context) or "").strip(),
            feature="Fantasy Lineup",
        ),
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Fantasy Lineup",
        workstream="baseball_fantasy",
    )


def log_lineup_saved(
    context: dict[str, Any] | None,
    *,
    week: int | str,
    team: str = "",
) -> None:
    week_s = str(week).strip()
    title = f"Week {week_s} lineup saved" if week_s else "Lineup saved"
    rk = _lineup_resume_key(context, week_s)
    # Same resume key replaces any unfinished reminder Continuity.
    _record(
        "lineup_saved",
        page="Fantasy Lineup Assistant",
        metrics=_common_league_metrics(
            context,
            week=week_s,
            team=str(team or _my_team(context) or "").strip(),
            feature="Fantasy Lineup",
        ),
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Fantasy Lineup",
        workstream="baseball_fantasy",
    )


def log_lineup_locked(
    context: dict[str, Any] | None,
    *,
    week: int | str,
    team: str = "",
) -> None:
    week_s = str(week).strip()
    title = f"Week {week_s} lineup locked" if week_s else "Lineup locked"
    rk = _lineup_resume_key(context, week_s)
    _record(
        "lineup_locked",
        page="Fantasy Lineup Assistant",
        metrics=_common_league_metrics(
            context,
            week=week_s,
            team=str(team or _my_team(context) or "").strip(),
            feature="Fantasy Lineup",
        ),
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Fantasy Lineup",
        workstream="baseball_fantasy",
    )


def log_shared_league_created(context: dict[str, Any] | None, *, draft_id: str = "") -> None:
    lid = _league_id(context)
    league = _league_label(context)
    did = str(draft_id or "").strip()
    if not did and isinstance(context, dict):
        did = str(context.get("source_draft_id") or "").strip()
    rk = f"bb:saved_draft:{did}" if did else (f"bb:library:{lid}" if lid else "bb:library")
    title = f"{league} created successfully" if league else "Shared League created"
    _record(
        "shared_league_created",
        page="Saved Draft Library",
        metrics=_common_league_metrics(context, draft_id=did, feature="Shared Leagues"),
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Saved Draft Library",
        workstream="baseball_fantasy",
    )


def log_shared_league_invite(
    context: dict[str, Any] | None,
    invite: dict[str, Any] | None,
    *,
    as_invitee: bool = False,
) -> None:
    if not isinstance(invite, dict):
        return
    invite_id = str(invite.get("invite_id") or "").strip()
    league = str(invite.get("league_name") or _league_label(context) or "").strip()
    lid = str(invite.get("league_id") or _league_id(context) or "").strip()
    draft_id = str(invite.get("draft_id") or "").strip()
    invitee = str(invite.get("invitee_workspace_id") or invite.get("invitee_external_id") or "").strip()
    if as_invitee:
        title = f"Invited to {league}" if league else "Shared League invitation"
        _record(
            "shared_league_invite",
            page="Saved Draft Library",
            metrics=_common_league_metrics(
                context,
                invite_id=invite_id,
                league_id=lid or _league_id(context),
                league_name=league,
                draft_id=draft_id,
                as_invitee=True,
                feature="Shared Leagues",
            ),
            summary=title,
            resume_key=f"bb:invite:{invite_id}" if invite_id else (f"bb:library:{lid}" if lid else "bb:library"),
            resume_title=title,
            resume_subtitle="Claim a team",
            workstream="baseball_fantasy",
        )
        return
    # Commissioner send = Activity only (not a Continue card).
    title = f"Invited {invitee} to {league}" if invitee and league else f"Sent invite for {league or 'Shared League'}"
    _record(
        "shared_league_invite",
        page="Saved Draft Library",
        metrics=_common_league_metrics(
            context,
            invite_id=invite_id,
            league_id=lid or _league_id(context),
            league_name=league,
            draft_id=draft_id,
            invitee=invitee,
            as_invitee=False,
            feature="Shared Leagues",
            cc_card_kind="activity",
        ),
        summary=title,
        resume_key="",
        resume_title="",
        workstream="baseball_fantasy",
        cc_card_kind="activity",
    )


def log_shared_league_invite_declined(
    context: dict[str, Any] | None,
    invite: dict[str, Any] | None,
) -> None:
    """Activity-only — clears invite Continue."""
    if not isinstance(invite, dict):
        return
    invite_id = str(invite.get("invite_id") or "").strip()
    league = str(invite.get("league_name") or _league_label(context) or "").strip()
    if invite_id:
        _invalidate_resume(f"bb:invite:{invite_id}")
    _record(
        "shared_league_invite_declined",
        page="Saved Draft Library",
        metrics=_common_league_metrics(
            context,
            invite_id=invite_id,
            league_name=league,
            feature="Shared Leagues",
            cc_card_kind="activity",
        ),
        summary=f"Declined invite to {league}" if league else "Declined a Shared League invitation",
        resume_key="",
        workstream="baseball_fantasy",
        cc_card_kind="activity",
    )


def log_team_claimed(
    context: dict[str, Any] | None,
    *,
    team: str,
    invite_id: str = "",
) -> None:
    lid = _league_id(context)
    league = _league_label(context)
    team_name = str(team or "").strip()
    title = f"Claimed {team_name}" if team_name else "Team claimed"
    draft_id = ""
    if isinstance(context, dict):
        draft_id = str(context.get("source_draft_id") or "").strip()
    iid = str(invite_id or "").strip()
    if iid:
        _invalidate_resume(f"bb:invite:{iid}")
    rk = f"bb:saved_draft:{draft_id}" if draft_id else (f"bb:library:{lid}" if lid else "bb:library")
    _record(
        "team_claimed",
        page="Saved Draft Library",
        metrics=_common_league_metrics(
            context,
            team=team_name,
            claimed_team=team_name,
            invite_id=iid,
            draft_id=draft_id,
            feature="Shared Leagues",
        ),
        summary=f"{title} in {league}" if league and team_name else title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle=league or "Saved Draft Library",
        workstream="baseball_fantasy",
    )


def log_active_draft_changed(
    *,
    league_name: str = "",
    draft_id: str = "",
    league_id: str = "",
) -> None:
    league = str(league_name or "").strip()
    did = str(draft_id or "").strip()
    lid = str(league_id or "").strip()
    title = f"Active League set to {league}" if league else "Active League changed"
    rk = f"bb:saved_draft:{did}" if did else (f"bb:library:{lid}" if lid else "bb:library")
    _record(
        "active_draft_changed",
        page="Saved Draft Library",
        metrics={
            "league_name": league,
            "league_id": lid,
            "draft_id": did,
            "feature": "Shared Leagues",
        },
        summary=title,
        resume_key=rk,
        resume_title=title,
        resume_subtitle="Saved Draft Library",
        workstream="baseball_fantasy",
    )


def emit_incoming_trade_offers_once(session: dict[str, Any], context: dict[str, Any] | None, offers: list[dict[str, Any]]) -> None:
    """Idempotent Continuity emit for newly visible incoming offers on this account."""
    if not isinstance(session, dict) or not offers:
        return
    seen_key = "_cc_trade_offer_received_ids"
    seen_raw = session.get(seen_key)
    seen = set(str(x) for x in seen_raw) if isinstance(seen_raw, (list, set, tuple)) else set()
    changed = False
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        if str(offer.get("status") or "").strip().lower() not in {"", "pending"}:
            continue
        pid = str(offer.get("proposal_id") or "").strip()
        if not pid or pid in seen:
            continue
        log_trade_offer_received(context, offer)
        seen.add(pid)
        changed = True
    if changed:
        session[seen_key] = sorted(seen)[-200:]
