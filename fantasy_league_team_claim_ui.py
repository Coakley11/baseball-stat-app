"""Team claim UI for shared imported leagues."""

from __future__ import annotations

from typing import Any, Callable

from fantasy_league_context import get_active_league_context, get_league_context
from fantasy_league_team_ownership import (
    TEAM_ASSIGNMENT_PROMPT,
    assign_my_team,
    get_team_ownership,
    needs_team_assignment,
    owner_display_for_team,
    owned_team_for_user,
)


def _team_options(context: dict[str, Any]) -> list[str]:
    return sorted((context.get("league_rosters") or {}).keys())


def render_team_claim_panel(
    st: Any,
    session: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    key_prefix: str = "team_claim",
    persist_fn: Callable[..., None] | None = None,
    title: str = "Claim your team",
) -> bool:
    """Show team list with ownership badges and claim action. Returns True after claim."""
    context = context or get_active_league_context(session, respect_source_priority=False)
    if not isinstance(context, dict):
        return False
    if str(context.get("context_type") or "") != "real_league":
        return False

    teams = _team_options(context)
    if not teams:
        return False

    st.markdown(f"##### {title}")
    ownership = get_team_ownership(context)
    for team in teams:
        record = ownership.get(team) or {}
        owner_uid = str(record.get("user_id") or "").strip()
        if owner_uid:
            badge = f"Claimed by **{owner_display_for_team(context, team)}**"
        else:
            badge = "Unclaimed"
        st.markdown(f"- **{team}** — {badge}")

    if not needs_team_assignment(context):
        owned = owned_team_for_user(context)
        if owned:
            st.success(f"Your account owns **{owned}** in this league.")
        return bool(owned)

    st.warning(TEAM_ASSIGNMENT_PROMPT)
    unclaimed = [team for team in teams if not str((ownership.get(team) or {}).get("user_id") or "").strip()]
    choices = unclaimed or teams
    pick = st.selectbox("Choose your team", choices, key=f"{key_prefix}_team_pick")
    if st.button("Claim team", key=f"{key_prefix}_claim_btn"):
        saved, err = assign_my_team(session, pick)
        if err:
            st.error(err)
            return False
        if persist_fn:
            persist_fn(session, st, reason="team_claimed")
        st.success(f"Claimed **{pick}** — roster saved to your library.")
        st.rerun()
    return False


def render_active_league_team_claim(st: Any, session: dict[str, Any], **kwargs: Any) -> bool:
    """Claim panel for the persisted Active Draft / league context."""
    context = get_active_league_context(session, respect_source_priority=False)
    if not isinstance(context, dict):
        return False
    league_context_id = str(context.get("league_context_id") or "").strip()
    if league_context_id:
        refreshed = get_league_context(session, league_context_id)
        if refreshed:
            context = refreshed
    return render_team_claim_panel(st, session, context=context, **kwargs)
