"""UI for Fantasy Trade Proposal inbox, outgoing offers, and propose/accept/decline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fantasy_league_context import get_active_league_context
from fantasy_league_team_ownership import (
    TEAM_ASSIGNMENT_PROMPT,
    TRADES_DISABLED_MESSAGE,
    assign_my_team,
    needs_team_assignment,
    owned_team_for_user,
    resolve_trade_team_for_session,
    trades_enabled,
)
from fantasy_trade_proposals import (
    TRADE_PHASE1_SIMPLE,
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    TRADE_PROPOSAL_STATUS_CANCELED,
    TRADE_PROPOSAL_STATUS_COUNTERED,
    TRADE_PROPOSAL_STATUS_DECLINED,
    TRADE_PROPOSAL_STATUS_EXPIRED,
    TRADE_PROPOSAL_STATUS_PENDING,
    TRADE_PROPOSAL_STATUS_STALE,
    accept_trade_proposal,
    build_trade_response_trace_snapshot,
    build_trade_submit_trace_snapshot,
    cancel_trade_proposal,
    count_accepted_trade_proposals,
    count_pending_trade_proposals,
    counter_trade_proposal,
    create_trade_proposal,
    decline_trade_proposal,
    get_display_status,
    get_incoming_trade_proposals,
    get_outgoing_trade_proposals,
    get_trade_history,
    is_proposal_actionable,
    navigate_to_trade_proposal,
    pending_incoming_count,
    record_trade_response_trace,
    record_trade_submit_trace,
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


def _render_trade_submit_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Always show last trade propose submit trace."""
    snap = build_trade_submit_trace_snapshot(session)
    with st.expander("Trade submit diagnostic", expanded=bool(snap.get("updated_at") and not snap.get("trade_id"))):
        st.caption("Explains the last **Propose this trade** click — button, create, shared save, and inbox counts.")
        if not snap.get("updated_at"):
            st.caption("No trade submit recorded yet. Click **Propose this trade** below.")
        st.markdown(
            f"- **button_clicked:** {snap.get('button_clicked') if snap.get('updated_at') else '—'}  \n"
            f"- **propose_trade_called:** {snap.get('propose_trade_called') if snap.get('updated_at') else '—'}  \n"
            f"- **proposer → recipient:** `{snap.get('proposer_team') or '—'}` → `{snap.get('recipient_team') or '—'}`  \n"
            f"- **trade_id:** `{snap.get('trade_id') or '—'}`  \n"
            f"- **validation_error:** {snap.get('validation_error') or '—'}  \n"
            f"- **create_error:** {snap.get('create_error') or '—'}  \n"
            f"- **save_shared_league_ok:** "
            f"{snap.get('save_shared_league_ok') if snap.get('updated_at') else '—'}  \n"
            f"- **save_shared_league_error:** `{snap.get('save_shared_league_error') or '—'}`  \n"
            f"- **pending_trade_count:** "
            f"{snap.get('pending_trade_count_before') if snap.get('updated_at') else '—'}"
            f" → {snap.get('pending_trade_count_after') if snap.get('updated_at') else '—'}  \n"
            f"- **outgoing_count:** "
            f"{snap.get('outgoing_count_before') if snap.get('updated_at') else '—'}"
            f" → {snap.get('outgoing_count_after') if snap.get('updated_at') else '—'}"
        )
        if snap.get("updated_at"):
            with st.expander("Trade submit trace (full)", expanded=False):
                st.json(snap)


def _render_trade_response_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Always show last trade accept/decline submit trace."""
    snap = build_trade_response_trace_snapshot(session)
    with st.expander(
        "Last trade response",
        expanded=bool(
            snap.get("updated_at")
            and snap.get("button_clicked")
            and (snap.get("update_error") or snap.get("validation_error") or not snap.get("status_after"))
        ),
    ):
        st.caption("Explains the last **Accept Trade** click — validation, roster swap, shared save, and inbox counts.")
        if not snap.get("updated_at"):
            st.caption("No trade response recorded yet. Click **Accept Trade** on an incoming offer.")
        st.markdown(
            f"- **button_clicked:** {snap.get('button_clicked') if snap.get('updated_at') else '—'}  \n"
            f"- **action:** `{snap.get('action') or '—'}`  \n"
            f"- **respond_trade_called:** {snap.get('respond_trade_called') if snap.get('updated_at') else '—'}  \n"
            f"- **trade_id:** `{snap.get('trade_id') or '—'}`  \n"
            f"- **validation_error:** {snap.get('validation_error') or '—'}  \n"
            f"- **update_error:** {snap.get('update_error') or '—'}  \n"
            f"- **save_shared_league_ok:** "
            f"{snap.get('save_shared_league_ok') if snap.get('updated_at') else '—'}  \n"
            f"- **save_shared_league_error:** `{snap.get('save_shared_league_error') or '—'}`  \n"
            f"- **status:** "
            f"{snap.get('status_before') if snap.get('updated_at') else '—'}"
            f" → {snap.get('status_after') if snap.get('updated_at') else '—'}  \n"
            f"- **roster_mutation_attempted:** "
            f"{snap.get('roster_mutation_attempted') if snap.get('updated_at') else '—'}  \n"
            f"- **roster_mutation_ok:** {snap.get('roster_mutation_ok') if snap.get('updated_at') else '—'}  \n"
            f"- **roster_mutation_error:** {snap.get('roster_mutation_error') or '—'}  \n"
            f"- **pending_count:** "
            f"{snap.get('pending_count_before') if snap.get('updated_at') else '—'}"
            f" → {snap.get('pending_count_after') if snap.get('updated_at') else '—'}  \n"
            f"- **accepted_count:** "
            f"{snap.get('accepted_count_before') if snap.get('updated_at') else '—'}"
            f" → {snap.get('accepted_count_after') if snap.get('updated_at') else '—'}  \n"
            f"- **recipient_team / my_owned_team:** "
            f"`{snap.get('recipient_team') or '—'}` / `{snap.get('my_owned_team') or '—'}`"
        )
        if snap.get("updated_at"):
            with st.expander("Trade response trace (full)", expanded=False):
                st.json(snap)


def _process_incoming_accept_forms(
    st: Any,
    session: dict[str, Any],
    *,
    context: dict[str, Any],
    my_team_name: str,
    persist_fn: Callable[..., None] | None,
    key_prefix: str,
) -> None:
    """Handle Accept Trade form submits before inbox lists render (same-run visibility)."""
    incoming = get_incoming_trade_proposals(session, my_team_name)
    for proposal in incoming:
        if get_display_status(context, proposal) != TRADE_PROPOSAL_STATUS_PENDING:
            continue
        if not is_proposal_actionable(context, proposal, as_team=my_team_name):
            continue
        pid = str(proposal.get("proposal_id") or "").strip()
        if not pid:
            continue
        proposer = str(proposal.get("proposer_team") or "")
        gives = _format_players(proposal.get("proposer_gives") or [])
        receives = _format_players(proposal.get("proposer_receives") or [])
        with st.form(f"{key_prefix}_accept_form_{pid}", clear_on_submit=False):
            st.caption(
                f"**Accept incoming trade** from **{proposer}**: you give {receives}, you receive {gives}"
            )
            submitted = st.form_submit_button("Accept Trade", type="primary")
        if not submitted:
            continue
        active_ctx = get_active_league_context(session)
        pending_before = count_pending_trade_proposals(active_ctx)
        accepted_before = count_accepted_trade_proposals(active_ctx)
        status_before = str(proposal.get("status") or TRADE_PROPOSAL_STATUS_PENDING)
        record_trade_response_trace(
            session,
            button_clicked=True,
            action="accept",
            trade_id=pid,
            respond_trade_called=False,
            status_before=status_before,
            pending_count_before=pending_before,
            accepted_count_before=accepted_before,
            validation_error=None,
            update_error=None,
            roster_mutation_attempted=None,
            roster_mutation_ok=None,
            roster_mutation_error=None,
            status_after=None,
            save_shared_league_ok=None,
            save_shared_league_error=None,
        )
        accepted, err = accept_trade_proposal(session, pid)
        refreshed_ctx = get_active_league_context(session)
        pending_after = count_pending_trade_proposals(refreshed_ctx)
        accepted_after = count_accepted_trade_proposals(refreshed_ctx)
        record_trade_response_trace(
            session,
            pending_count_after=pending_after,
            accepted_count_after=accepted_after,
        )
        if err:
            session["_last_trade_response_submit_error"] = err
            session.pop("_last_trade_response_submit_ok", None)
            st.error(err)
        elif accepted:
            session.pop("_last_trade_response_submit_error", None)
            session["_last_trade_response_submit_ok"] = {
                "trade_id": pid,
                "proposer_team": proposer,
                "status": TRADE_PROPOSAL_STATUS_ACCEPTED,
            }
            if persist_fn:
                persist_fn(session, st, reason="trade_proposal_accepted")
            st.success("Trade Accepted")
        else:
            msg = "Accept trade returned no proposal and no error."
            session["_last_trade_response_submit_error"] = msg
            record_trade_response_trace(session, update_error=msg)
            st.error(msg)


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
    skip_accept_button: bool = False,
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
        if TRADE_PHASE1_SIMPLE:
            btn_analyze, btn_accept, btn_decline = st.columns(3)
        else:
            btn_analyze, btn_counter, btn_accept, btn_decline = st.columns(4)
        with btn_analyze:
            if st.button("Analyze This Trade", key=f"{key_prefix}_analyze_in_{pid}"):
                navigate_to_trade_proposal(session, proposal_id=pid, view_as_team=my_team_name)
                st.rerun()
        if not TRADE_PHASE1_SIMPLE:
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
            if not skip_accept_button:
                st.caption("Use **Accept Trade** above the offer list.")
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
        if not TRADE_PHASE1_SIMPLE and _validate_ui_trade_shape(current_give_players, current_get_players):
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


def _render_trade_history(st: Any, context: dict[str, Any], *, key_prefix: str) -> None:
    history = get_trade_history(context)
    st.markdown("##### Trade History")
    sections = (
        ("Pending Trades", history.get("pending") or []),
        ("Accepted Trades", history.get("accepted") or []),
        ("Declined Trades", history.get("declined") or []),
    )
    for title, proposals in sections:
        st.markdown(f"**{title}**")
        if not proposals:
            st.caption("None")
            continue
        for proposal in proposals[:12]:
            pid = str(proposal.get("proposal_id") or "")
            status = get_display_status(context, proposal)
            proposer = str(proposal.get("proposer_team") or "")
            recipient = str(proposal.get("recipient_team") or "")
            gives = _format_players(proposal.get("proposer_gives") or [])
            receives = _format_players(proposal.get("proposer_receives") or [])
            st.caption(
                f"{_status_badge(status)} · {proposer} → {recipient}: {gives} for {receives} "
                f"({_format_time(str(proposal.get('created_at') or ''))})"
            )
    activity_rows = history.get("activity") or []
    if activity_rows:
        st.markdown("**League activity**")
        for row in activity_rows[:12]:
            st.caption(
                f"{str(row.get('summary') or row.get('action') or 'Trade event')} "
                f"({_format_time(str(row.get('recorded_at') or ''))})"
            )


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
        st.caption("Set an **Active Draft** in Saved Draft Library to propose league trades.")
        return

    my_team_name = str(my_team or resolve_trade_team_for_session(context, session) or context.get("my_team_name") or "").strip()
    proposer_team = resolve_trade_team_for_session(context, session) or my_team_name
    owned_team = owned_team_for_user(context)
    if owned_team and my_team_name and my_team_name != owned_team:
        st.warning(
            f"Trade analyzer selected **{my_team_name}**, but your claimed team is **{owned_team}**. "
            f"Proposals will use **{owned_team}**."
        )
        my_team_name = owned_team
        proposer_team = owned_team
    team_names = sorted((context.get("league_rosters") or {}).keys())

    if needs_team_assignment(context):
        st.warning(TEAM_ASSIGNMENT_PROMPT)
        if team_names:
            pick = st.selectbox("Which team is yours?", team_names, key=f"{key_prefix}_assign_team")
            if st.button("Save my team", key=f"{key_prefix}_assign_team_btn"):
                saved, err = assign_my_team(session, pick)
                if err:
                    st.error(err)
                else:
                    if persist_fn:
                        persist_fn(session, st, reason="team_ownership_assigned")
                    st.success(f"Assigned **{pick}** to your account.")
                    st.rerun()

    enabled, gate_msg = trades_enabled(context, session)
    if not enabled:
        st.info(gate_msg or TRADES_DISABLED_MESSAGE)
        _render_trade_submit_diagnostics(st, session)
        _render_trade_response_diagnostics(st, session)
        _render_trade_history(st, context, key_prefix=key_prefix)
        return

    _render_trade_submit_diagnostics(st, session)
    _render_trade_response_diagnostics(st, session)
    submit_err = str(session.get("_last_trade_proposal_submit_error") or "").strip()
    if submit_err:
        st.error(submit_err)
    last_ok = session.get("_last_trade_proposal_submit_ok")
    if isinstance(last_ok, dict) and str(last_ok.get("trade_id") or "").strip():
        st.success(
            f"Trade proposed to **{last_ok.get('recipient_team') or '—'}** · "
            f"id `{last_ok.get('trade_id') or '—'}`"
        )

    response_err = str(session.get("_last_trade_response_submit_error") or "").strip()
    if response_err:
        st.error(response_err)
    last_accept = session.get("_last_trade_response_submit_ok")
    if isinstance(last_accept, dict) and str(last_accept.get("trade_id") or "").strip():
        st.success(
            f"Trade accepted from **{last_accept.get('proposer_team') or '—'}** · "
            f"id `{last_accept.get('trade_id') or '—'}`"
        )

    expires_at = ""
    if not TRADE_PHASE1_SIMPLE:
        expiry_choice = st.selectbox(
            "New offer/counter deadline",
            ["No deadline", "24 hours", "48 hours", "7 days"],
            key=f"{key_prefix}_expiry_choice",
        )
        expires_at = _deadline_for_choice(expiry_choice)

    st.markdown("##### Propose Trade")
    st.caption("Supports 1-for-1, 2-for-1, 2-for-2, and 3-for-2 style offers. The analyzer evaluates; accepting the proposal is what mutates rosters.")
    shape_error = _validate_ui_trade_shape(give_players, get_players)
    if give_players or get_players:
        st.caption(f"Current deal shape: **{_trade_shape(give_players, get_players)}**")
    if shape_error and (give_players or get_players):
        st.warning(shape_error)

    can_propose = bool(give_players and get_players and other_team)
    if not can_propose:
        st.caption("Select players you give up and receive above, then click **Propose this trade**.")
    else:
        with st.form(f"{key_prefix}_propose_form", clear_on_submit=False):
            st.caption(
                f"Propose from **{proposer_team or my_team_name}** to **{other_team}**: "
                f"{', '.join(give_players)} → {', '.join(get_players)}"
            )
            submitted = st.form_submit_button(
                "Propose this trade",
                type="primary",
                disabled=bool(shape_error),
            )

        if submitted:
            active_ctx = get_active_league_context(session)
            pending_before = count_pending_trade_proposals(active_ctx)
            outgoing_before = len(get_outgoing_trade_proposals(session, my_team_name))
            record_trade_submit_trace(
                session,
                button_clicked=True,
                proposer_team=proposer_team or my_team_name,
                recipient_team=other_team,
                give_players=list(give_players),
                receive_players=list(get_players),
                pending_trade_count_before=pending_before,
                outgoing_count_before=outgoing_before,
                propose_trade_called=False,
                validation_error=shape_error or None,
                create_error=None,
                trade_id=None,
            )
            if shape_error:
                session["_last_trade_proposal_submit_error"] = shape_error
                record_trade_submit_trace(session, validation_error=shape_error, create_error=shape_error)
            else:
                proposal, err = create_trade_proposal(
                    session,
                    proposer_team=proposer_team or my_team_name,
                    recipient_team=other_team,
                    proposer_gives=give_players,
                    proposer_receives=get_players,
                    verdict=verdict,
                    expires_at=expires_at,
                )
                refreshed_ctx = get_active_league_context(session)
                pending_after = count_pending_trade_proposals(refreshed_ctx)
                outgoing_after = len(get_outgoing_trade_proposals(session, my_team_name))
                record_trade_submit_trace(
                    session,
                    pending_trade_count_after=pending_after,
                    outgoing_count_after=outgoing_after,
                )
                if err:
                    session["_last_trade_proposal_submit_error"] = err
                    session.pop("_last_trade_proposal_submit_ok", None)
                    st.error(err)
                elif proposal:
                    session.pop("_last_trade_proposal_submit_error", None)
                    session["_last_trade_proposal_submit_ok"] = {
                        "trade_id": str(proposal.get("trade_id") or proposal.get("proposal_id") or ""),
                        "recipient_team": other_team,
                    }
                    if persist_fn:
                        persist_fn(session, st, reason="trade_proposal_created")
                    st.success(f"Trade proposed to **{other_team}**.")
                else:
                    msg = "Propose trade returned no proposal and no error."
                    session["_last_trade_proposal_submit_error"] = msg
                    record_trade_submit_trace(session, create_error=msg)
                    st.error(msg)

    context = get_active_league_context(session) or context
    incoming_preview = get_incoming_trade_proposals(session, my_team_name)
    pending_actionable = [
        p
        for p in incoming_preview
        if get_display_status(context, p) == TRADE_PROPOSAL_STATUS_PENDING
        and is_proposal_actionable(context, p, as_team=my_team_name)
    ]
    if pending_actionable:
        st.markdown("##### Respond to incoming offers")
    _process_incoming_accept_forms(
        st,
        session,
        context=context,
        my_team_name=my_team_name,
        persist_fn=persist_fn,
        key_prefix=key_prefix,
    )

    context = get_active_league_context(session) or context
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
                skip_accept_button=True,
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

    _render_trade_history(st, context, key_prefix=key_prefix)
