"""Active League Context display + research-page sync toggle (Saved Draft Library)."""

from __future__ import annotations

from typing import Any

# Persisted session key (legacy name retained for cloud/disk compatibility).
FANTASY_RESEARCH_SYNC_KEY = "use_active_league_context_waiver_filter"

FANTASY_RESEARCH_SYNC_LABEL = "Research Mode — treat drafted players as unavailable"
FANTASY_RESEARCH_SYNC_HELP = (
    "When enabled, research pages treat players already drafted in the active draft "
    "as **unavailable** and recalculate rankings and recommendations using only the "
    "remaining available players. Source of truth is your **Active League** when one "
    "is selected, otherwise the **Draft Assistant Simulator**."
)

RESEARCH_SYNC_PAGES: tuple[str, ...] = (
    "Comparison Tool",
    "Trend Value",
    "Valuation",
    "Fantasy Sleepers & Busts",
    "Draft Assistant Simulator",
    "Rankings",
    "Leaderboards",
    "Player Search",
)


def research_league_sync_enabled(session: dict[str, Any]) -> bool:
    """True when research pages should use Active League Context for league-aware filtering."""
    return bool(session.get(FANTASY_RESEARCH_SYNC_KEY))


# Backward-compatible aliases
def fantasy_context_sync_enabled(session: dict[str, Any]) -> bool:
    return research_league_sync_enabled(session)


def _on_sync_changed(*_args, **_kwargs) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="fantasy_context_sync_changed")
    except Exception:
        pass


def render_fantasy_context_sync_control(
    st: Any,
    session: dict[str, Any],
    *,
    key: str = "library_fantasy_context_sync",
) -> None:
    """Research-page sync toggle — Saved Draft Library only."""
    st.markdown("##### Fantasy Context Sync")
    st.checkbox(
        FANTASY_RESEARCH_SYNC_LABEL,
        key=FANTASY_RESEARCH_SYNC_KEY,
        help=FANTASY_RESEARCH_SYNC_HELP,
        on_change=_on_sync_changed,
    )
    st.caption(
        "Affected pages: "
        + ", ".join(RESEARCH_SYNC_PAGES)
        + ". When enabled, **recommendation tables and rankings** exclude drafted players and "
        "re-rank the remaining pool. **Player lookup** (Comparison charts, trend dashboards, "
        "valuation insight picker) still allows viewing any player you search for."
    )
    st.caption(
        "**Not affected:** Fantasy Standings, Lineup Assistant, Waiver Wire, Trade tools — "
        "those always use your **Active Draft** when one is set. Draft Lab stays independent."
    )


def active_league_context_badge_text(session: dict[str, Any]) -> str:
    """Fantasy workflow pages — sync checkbox is irrelevant here."""
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session)
    except ImportError:
        ctx = None
    if isinstance(ctx, dict):
        name = str(ctx.get("display_name") or ctx.get("my_team_name") or "Active Draft").strip()
        return f"Active Draft: **{name}** · ✓ Active"
    return "Active Draft: **Not set** — choose one in Saved Draft Library"


def research_sync_badge_text(session: dict[str, Any]) -> str:
    """Research pages — show whether Research Mode is on and its active source."""
    if not research_league_sync_enabled(session):
        return "Research mode: **General MLB** (off)"
    try:
        from active_team_context import (
            SOURCE_LEAGUE,
            SOURCE_SIMULATOR,
            resolve_active_team_context,
        )

        ctx = resolve_active_team_context(session)
    except Exception:
        ctx = None
    if ctx is not None and getattr(ctx, "source", None) == SOURCE_LEAGUE:
        return f"Research mode: **On** · Active League — {ctx.active_team} (drafted players hidden & re-ranked)"
    if ctx is not None and getattr(ctx, "source", None) == SOURCE_SIMULATOR:
        return f"Research mode: **On** · Draft Simulator — {ctx.active_team} (drafted players hidden & re-ranked)"
    return "Research mode: **On** (no active draft — start a simulator draft or select an Active League)"


def render_active_league_context_badge(st: Any, session: dict[str, Any]) -> None:
    st.caption(active_league_context_badge_text(session))


def render_research_sync_badge(st: Any, session: dict[str, Any]) -> None:
    st.caption(research_sync_badge_text(session))


def render_fantasy_context_badge(st: Any, session: dict[str, Any]) -> None:
    """Default badge for in-season fantasy pages."""
    render_active_league_context_badge(st, session)


# Backward-compatible alias for tests and callers.
fantasy_context_badge_text = active_league_context_badge_text


def render_fantasy_context_library_block(
    st: Any,
    session: dict[str, Any],
    *,
    active_context: dict[str, Any] | None,
) -> None:
    """Legacy wrapper — sync control only (Active Draft section lives in draft_archive_ui)."""
    render_fantasy_context_sync_control(st, session)
