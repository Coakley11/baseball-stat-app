"""Sidebar trade notification badges and deep-link actions."""

from __future__ import annotations

from typing import Any

from fantasy_league_context import get_active_league_context
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_PENDING,
    get_display_status,
    get_trade_notifications,
    navigate_to_trade_proposal,
    pending_incoming_count,
)


def _active_team_name(session: dict[str, Any]) -> str:
    context = get_active_league_context(session)
    if context:
        my_team = str(context.get("my_team_name") or "").strip()
        if my_team:
            return my_team
    return str(session.get("room_your_team") or "").strip()


def render_trade_notification_sidebar(st: Any, session: dict[str, Any]) -> None:
    """League trade alerts in the workflow sidebar — scoped to active league/team."""
    context = get_active_league_context(session)
    if not context:
        return

    team = _active_team_name(session)
    if not team:
        return

    alerts = get_trade_notifications(session, team)
    pending_n = pending_incoming_count(session, team)
    if not alerts and pending_n == 0:
        return

    st.sidebar.markdown("### League Trade Alerts")
    league_label = str(context.get("display_name") or context.get("league_name") or "Active League")
    st.sidebar.caption(f"{league_label} · **{team}**")

    if pending_n and not any(a.get("kind") == "incoming" for a in alerts):
        st.sidebar.warning(
            f"**{pending_n}** incoming trade offer{'s' if pending_n != 1 else ''}"
        )

    for alert in alerts[:8]:
        msg = str(alert.get("message") or "Trade update")
        pid = str(alert.get("proposal_id") or "")
        key = str(alert.get("alert_key") or pid)
        kind = str(alert.get("kind") or "")
        if kind in ("incoming", "counteroffer"):
            st.sidebar.error(msg)
        elif kind in ("accepted",):
            st.sidebar.success(msg)
        elif kind in ("declined", "canceled", "countered", "expired"):
            st.sidebar.warning(msg)
        else:
            st.sidebar.info(msg)

        if st.sidebar.button("Open in Trade Analyzer", key=f"trade_alert_open_{key}"):
            navigate_to_trade_proposal(
                session,
                proposal_id=pid,
                view_as_team=str(alert.get("view_as_team") or team),
                alert_key=key,
            )
            st.rerun()
