"""UI for Fantasy Trade Proposal inbox, outgoing offers, and propose/accept/decline."""

from __future__ import annotations

from typing import Any, Callable

from fantasy_league_context import get_active_league_context
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_PENDING,
    accept_trade_proposal,
    create_trade_proposal,
    decline_trade_proposal,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    pending_incoming_count,
    set_trade_proposal_handoff,
)


def _format_players(players: list[dict[str, Any]]) -> str:
    names = [str(p.get("player_name") or "").strip() for p in players if str(p.get("player_name") or "").strip()]
    return ", ".join(names) if names else "—"


def _status_label(status: str) -> str:
    if status == TRADE_PROPOSAL_STATUS_ACCEPTED:
        return "Trade Accepted"
    if status == TRADE_PROPOSAL_STATUS_DECLINED:
        return "Trade Declined"
    return "Pending"


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

    st.markdown("##### League Trade Offers")
    if pending_n:
        st.info(f"**{pending_n}** incoming trade offer{'s' if pending_n != 1 else ''} waiting for your review.")

    col_in, col_out = st.columns(2)
    with col_in:
        st.markdown("**Incoming Trade Offers**")
        if not incoming:
            st.caption("No incoming offers yet.")
        for proposal in incoming:
            pid = str(proposal.get("proposal_id") or "")
            status = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING)
            proposer = str(proposal.get("proposer_team") or "")
            st.markdown(
                f"**From {proposer}** · {_status_label(status)}  \n"
                f"You give: {_format_players(proposal.get('proposer_receives') or [])}  \n"
                f"You receive: {_format_players(proposal.get('proposer_gives') or [])}"
            )
            if status == TRADE_PROPOSAL_STATUS_PENDING:
                btn_analyze, btn_accept, btn_decline = st.columns(3)
                with btn_analyze:
                    if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_in_{pid}"):
                        set_trade_proposal_handoff(session, proposal_id=pid, view_as_team=my_team_name)
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

    with col_out:
        st.markdown("**Outgoing Trade Offers**")
        if not outgoing:
            st.caption("No outgoing offers yet.")
        for proposal in outgoing:
            pid = str(proposal.get("proposal_id") or "")
            status = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING)
            recipient = str(proposal.get("recipient_team") or "")
            st.markdown(
                f"**To {recipient}** · {_status_label(status)}  \n"
                f"You give: {_format_players(proposal.get('proposer_gives') or [])}  \n"
                f"You receive: {_format_players(proposal.get('proposer_receives') or [])}"
            )
            if status == TRADE_PROPOSAL_STATUS_PENDING:
                if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_out_{pid}"):
                    set_trade_proposal_handoff(session, proposal_id=pid, view_as_team=my_team_name)
                    st.rerun()

    st.markdown("##### Propose Trade")
    if give_players and get_players and other_team:
        if st.button("Propose this trade", key=f"{key_prefix}_propose_btn", type="primary"):
            proposal, err = create_trade_proposal(
                session,
                proposer_team=my_team_name,
                recipient_team=other_team,
                proposer_gives=give_players,
                proposer_receives=get_players,
                verdict=verdict,
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
