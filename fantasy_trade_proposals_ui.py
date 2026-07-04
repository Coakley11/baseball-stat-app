"""UI for Fantasy Trade Proposal inbox, outgoing offers, and propose/accept/decline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fantasy_league_context import get_active_league_context
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_CANCELED,
    TRADE_PROPOSAL_STATUS_COUNTERED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_EXPIRED,
    TRADE_PROPOSAL_STATUS_PENDING,
    TRADE_PROPOSAL_STATUS_STALE,
    accept_trade_proposal,
    cancel_trade_proposal,
    counter_trade_proposal,
    create_trade_proposal,
    decline_trade_proposal,
    get_display_status,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    is_proposal_actionable,
    navigate_to_trade_proposal,
    pending_incoming_count,
)


def _format_players(players: list[dict[str, Any]]) -> str:
    names = [str(p.get("player_name") or "").strip() for p in players if str(p.get("player_name") or "").strip()]
    return ", ".join(names) if names else "—"


def _format_time(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except ValueError:
        return text[:16]


def _format_deadline(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "No deadline"
    return f"Expires {_format_time(text)}"


def _deadline_for_choice(choice: str) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    mapping = {
        "24 hours": now + timedelta(hours=24),
        "48 hours": now + timedelta(hours=48),
        "7 days": now + timedelta(days=7),
    }
    deadline = mapping.get(str(choice or "").strip())
    return deadline.isoformat() if deadline else ""


def _trade_shape(give_players: list[str], get_players: list[str]) -> str:
    if not give_players or not get_players:
        return "Select players on both sides."
    return f"{len(give_players)}-for-{len(get_players)}"


def _validate_ui_trade_shape(give_players: list[str], get_players: list[str]) -> str:
    if not give_players or not get_players:
        return "Select players on both sides."
    if len(give_players) > 3 or len(get_players) > 3:
        return "Use up to three players on each side."
    if len(give_players) + len(get_players) > 5:
        return "Use up to five total players for this phase."
    return ""


def _status_badge(status: str) -> str:
    labels = {
        TRADE_PROPOSAL_STATUS_PENDING: "Pending",
        TRADE_PROPOSAL_STATUS_ACCEPTED: "Trade Accepted",
        TRADE_PROPOSAL_STATUS_DECLINED: "Trade Declined",
        TRADE_PROPOSAL_STATUS_CANCELED: "Canceled",
        TRADE_PROPOSAL_STATUS_COUNTERED: "Countered",
        TRADE_PROPOSAL_STATUS_EXPIRED: "Expired",
        TRADE_PROPOSAL_STATUS_STALE: "Cannot Complete",
    }
    return labels.get(status, status or "Pending")


def _render_proposal_card(
    st: Any,
    session: dict[str, Any],
    *,
    proposal: dict[str, Any],
    context: dict[str, Any],
    my_team_name: str,
    direction: str,
    persist_fn: Callable[..., None] | None,
    key_prefix: str,
    current_give_players: list[str],
    current_get_players: list[str],
    verdict: str,
    expires_at: str,
) -> None:
    pid = str(proposal.get("proposal_id") or "")
    display_status = get_display_status(context, proposal)
    proposer = str(proposal.get("proposer_team") or "")
    recipient = str(proposal.get("recipient_team") or "")
    created = _format_time(str(proposal.get("created_at") or ""))
    responded = _format_time(str(proposal.get("responded_at") or ""))
    deadline = _format_deadline(str(proposal.get("expires_at") or ""))

    if direction == "incoming":
        header = f"From **{proposer}** → **{my_team_name}**"
        you_give = _format_players(proposal.get("proposer_receives") or [])
        you_receive = _format_players(proposal.get("proposer_gives") or [])
    else:
        header = f"**{my_team_name}** → To **{recipient}**"
        you_give = _format_players(proposal.get("proposer_gives") or [])
        you_receive = _format_players(proposal.get("proposer_receives") or [])

    st.markdown(
        f'<div style="border:1px solid rgba(128,128,128,0.3);border-radius:0.5rem;padding:0.75rem;margin-bottom:0.5rem;">'
        f"{header}<br>"
        f'<span style="font-size:0.85rem;opacity:0.9;"><strong>{_status_badge(display_status)}</strong>'
        f" · Created {created}"
        f"{f' · Responded {responded}' if responded != '—' else ''}"
        f" · {deadline}"
        f"</span><br>"
        f"<strong>You give:</strong> {you_give}<br>"
        f"<strong>You receive:</strong> {you_receive}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if display_status == TRADE_PROPOSAL_STATUS_STALE:
        st.caption("This trade can no longer be completed.")
        return

    if not is_proposal_actionable(context, proposal, as_team=my_team_name):
        return

    if direction == "incoming" and display_status == TRADE_PROPOSAL_STATUS_PENDING:
        btn_analyze, btn_counter, btn_accept, btn_decline = st.columns(4)
        with btn_analyze:
            if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_in_{pid}"):
                navigate_to_trade_proposal(session, proposal_id=pid, view_as_team=my_team_name)
                st.rerun()
        with btn_counter:
            counter_shape_error = _validate_ui_trade_shape(current_give_players, current_get_players)
            if st.button(
                "Counter Offer",
                key=f"{key_prefix}_counter_{pid}",
                disabled=bool(counter_shape_error),
            ):
                countered, err = counter_trade_proposal(
                    session,
                    pid,
                    countered_by_team=my_team_name,
                    counter_gives=current_give_players,
                    counter_receives=current_get_players,
                    verdict=verdict,
                    expires_at=expires_at,
                )
                if err:
                    st.error(err)
                else:
                    if persist_fn:
                        persist_fn(session, st, reason="trade_proposal_countered")
                    st.success("Counteroffer sent.")
                    st.rerun()
        with btn_accept:
            if st.button("Accept Trade", key=f"{key_prefix}_accept_{pid}", type="primary"):
                accepted, err = accept_trade_proposal(session, pid)
                if err:
                    st.error(err)
                else:
                    if persist_fn:
                        persist_fn(session, st, reason="trade_proposal_accepted")
                    st.success("Trade Accepted")
                    st.rerun()
        with btn_decline:
            if st.button("Decline Trade", key=f"{key_prefix}_decline_{pid}"):
                declined, err = decline_trade_proposal(session, pid)
                if err:
                    st.error(err)
                else:
                    if persist_fn:
                        persist_fn(session, st, reason="trade_proposal_declined")
                    st.warning("Trade Declined")
                    st.rerun()
        if _validate_ui_trade_shape(current_give_players, current_get_players):
            st.caption("To counter, select the players you would give and receive in the analyzer above.")
    elif direction == "outgoing" and display_status == TRADE_PROPOSAL_STATUS_PENDING:
        btn_analyze, btn_cancel = st.columns(2)
        with btn_analyze:
            if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_out_{pid}"):
                navigate_to_trade_proposal(session, proposal_id=pid, view_as_team=my_team_name)
                st.rerun()
        with btn_cancel:
            if st.button("Cancel Offer", key=f"{key_prefix}_cancel_{pid}"):
                canceled, err = cancel_trade_proposal(session, pid, canceled_by_team=my_team_name)
                if err:
                    st.error(err)
                else:
                    if persist_fn:
                        persist_fn(session, st, reason="trade_proposal_canceled")
                    st.info("Offer canceled.")
                    st.rerun()
    elif direction == "outgoing":
        if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_out_done_{pid}"):
            navigate_to_trade_proposal(session, proposal_id=pid, view_as_team=my_team_name)
            st.rerun()


def render_trade_proposals_section(
    st: Any,
    session: dict[str, Any],
    *,
    my_team: str,
    other_team: str,
    give_players: list[str],
    get_players: list[str],
    verdict: str = "",
    persist_fn: Callable[..., None] | None = None,
    key_prefix: str = "trade_proposals",
) -> None:
    """Incoming/outgoing inbox plus Propose Trade action."""
    context = get_active_league_context(session)
    if not context:
        st.caption("Set an **Active League Context** in Saved Draft Library to propose league trades.")
        return

    my_team_name = str(my_team or context.get("my_team_name") or "").strip()
    incoming = get_incoming_trade_proposals(session, my_team_name)
    outgoing = get_outgoing_trade_proposals(session, my_team_name)
    pending_n = pending_incoming_count(session, my_team_name)
    expiry_choice = st.selectbox(
        "New offer/counter deadline",
        ["No deadline", "24 hours", "48 hours", "7 days"],
        key=f"{key_prefix}_expiry_choice",
    )
    expires_at = _deadline_for_choice(expiry_choice)

    st.markdown("##### League Trade Offers")
    if pending_n:
        st.info(f"**{pending_n}** incoming trade offer{'s' if pending_n != 1 else ''} waiting for your review.")

    col_in, col_out = st.columns(2)
    with col_in:
        st.markdown("**Incoming Trade Offers**")
        if not incoming:
            st.caption("No incoming offers yet.")
        for proposal in incoming:
            _render_proposal_card(
                st,
                session,
                proposal=proposal,
                context=context,
                my_team_name=my_team_name,
                direction="incoming",
                persist_fn=persist_fn,
                key_prefix=key_prefix,
                current_give_players=give_players,
                current_get_players=get_players,
                verdict=verdict,
                expires_at=expires_at,
            )

    with col_out:
        st.markdown("**Outgoing Trade Offers**")
        if not outgoing:
            st.caption("No outgoing offers yet.")
        for proposal in outgoing:
            _render_proposal_card(
                st,
                session,
                proposal=proposal,
                context=context,
                my_team_name=my_team_name,
                direction="outgoing",
                persist_fn=persist_fn,
                key_prefix=key_prefix,
                current_give_players=give_players,
                current_get_players=get_players,
                verdict=verdict,
                expires_at=expires_at,
            )

    st.markdown("##### Propose Trade")
    st.caption("Supports 1-for-1, 2-for-1, 2-for-2, and 3-for-2 style offers. The analyzer evaluates; accepting the proposal is what mutates rosters.")
    shape_error = _validate_ui_trade_shape(give_players, get_players)
    if give_players or get_players:
        st.caption(f"Current deal shape: **{_trade_shape(give_players, get_players)}**")
    if shape_error and (give_players or get_players):
        st.warning(shape_error)
    if give_players and get_players and other_team:
        if st.button("Propose this trade", key=f"{key_prefix}_propose_btn", type="primary", disabled=bool(shape_error)):
            proposal, err = create_trade_proposal(
                session,
                proposer_team=my_team_name,
                recipient_team=other_team,
                proposer_gives=give_players,
                proposer_receives=get_players,
                verdict=verdict,
                expires_at=expires_at,
            )
            if err:
                st.error(err)
            elif proposal:
                if persist_fn:
                    persist_fn(session, st, reason="trade_proposal_created")
                st.success(f"Trade proposed to **{other_team}**.")
                st.rerun()
    else:
        st.caption("Select players you give up and receive above, then click **Propose this trade**.")
