"""Active League Context display + fantasy context source controls."""

from __future__ import annotations

from typing import Any

from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    fantasy_context_source_badge_text,
    live_draft_context_available,
    simulator_board_context_available,
)

# Persisted session key (legacy name retained for cloud/disk compatibility).
FANTASY_RESEARCH_SYNC_KEY = "use_active_league_context_waiver_filter"

FANTASY_RESEARCH_SYNC_LABEL = "Research Mode — treat drafted players as unavailable"
FANTASY_RESEARCH_SYNC_HELP = (
    "When enabled, research pages treat players already drafted in the active fantasy "
    "context as **unavailable** and recalculate rankings using only remaining players. "
    "Source follows your **Fantasy Context Source** priority (Live Draft, Simulator "
    "board, or Saved Draft Library Active Draft)."
)

USE_LIVE_DRAFT_CONTEXT_LABEL = "Use Live Draft Room as active fantasy context"
USE_LIVE_DRAFT_CONTEXT_HELP = (
    "When enabled and a live draft is in progress, the Live Draft Room feeds Draft "
    "Assistant, research pages, waiver wire, lineup, standings, and trades. Turn off "
    "to keep using your Saved Draft Library Active Draft during a live draft."
)

USE_SIMULATOR_BOARD_CONTEXT_LABEL = "Use Draft Room Simulator board as active fantasy context"
USE_SIMULATOR_BOARD_CONTEXT_HELP = (
    "When enabled and the simulator draft board has picks, that board feeds fantasy "
    "and research pages. Turn off if you uploaded a board for reference but want your "
    "Saved Draft Library Active Draft to control the app."
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

FANTASY_CONTEXT_PAGES: tuple[str, ...] = (
    "Draft Assistant Simulator",
    "Research Mode",
    "Comparison Tool",
    "Trend Value",
    "Valuation",
    "Fantasy Sleepers & Busts",
    "Waiver Wire",
    "Fantasy Lineup Assistant",
    "Fantasy Standings Tracker",
    "Trades",
)


def research_league_sync_enabled(session: dict[str, Any]) -> bool:
    """True when research pages should use fantasy context for league-aware filtering."""
    return bool(session.get(FANTASY_RESEARCH_SYNC_KEY))


# Backward-compatible aliases
def fantasy_context_sync_enabled(session: dict[str, Any]) -> bool:
    return research_league_sync_enabled(session)


def _on_context_setting_changed(*_args, **_kwargs) -> None:
    """Persist fantasy context toggles immediately on change."""
    try:
        import streamlit as st
    except Exception:
        return
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="fantasy_context_source_changed")
    except Exception:
        pass


def render_fantasy_context_source_controls(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "fantasy_context_source",
) -> None:
    """User toggles for which draft source feeds fantasy/research pages."""
    st.markdown("##### Fantasy Context Source")
    st.caption(
        "Default priority: **Live Draft Room** → **Draft Room Simulator board** → "
        "**Saved Draft Library Active Draft** → generic simulator defaults."
    )
    live_available = live_draft_context_available(session)
    sim_available = simulator_board_context_available(session)
    st.checkbox(
        USE_LIVE_DRAFT_CONTEXT_LABEL,
        key=USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
        help=USE_LIVE_DRAFT_CONTEXT_HELP,
        disabled=not live_available,
        on_change=_on_context_setting_changed,
    )
    if not live_available:
        st.caption("No active Live Draft Room detected.")
    st.checkbox(
        USE_SIMULATOR_BOARD_CONTEXT_LABEL,
        key=USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
        help=USE_SIMULATOR_BOARD_CONTEXT_HELP,
        disabled=not sim_available,
        on_change=_on_context_setting_changed,
    )
    if not sim_available:
        st.caption("Draft Room Simulator board is empty.")
    st.caption(
        "When both overrides are off (or unavailable), **Saved Draft Library Active Draft** "
        "controls fantasy pages."
    )
    st.caption("Affected: " + ", ".join(FANTASY_CONTEXT_PAGES) + ".")


def render_fantasy_context_sync_control(
    st: Any,
    session: dict[str, Any],
    *,
    key: str = "library_fantasy_context_sync",
) -> None:
    """Research-page sync toggle + context source controls."""
    render_fantasy_context_source_controls(st, session, key_prefix=key)
    st.markdown("##### Research Mode Sync")
    st.checkbox(
        FANTASY_RESEARCH_SYNC_LABEL,
        key=FANTASY_RESEARCH_SYNC_KEY,
        help=FANTASY_RESEARCH_SYNC_HELP,
        on_change=_on_context_setting_changed,
    )
    st.caption(
        "Affected research pages: "
        + ", ".join(RESEARCH_SYNC_PAGES)
        + ". When enabled, recommendation tables exclude drafted players and re-rank the "
        "remaining pool. Player lookup still allows viewing any player you search for."
    )


def active_league_context_badge_text(session: dict[str, Any]) -> str:
    """Backward-compatible alias — unified fantasy context source badge."""
    return fantasy_context_source_badge_text(session)


def research_sync_badge_text(session: dict[str, Any]) -> str:
    """Research pages — show whether Research Mode is on and its active source."""
    source_badge = fantasy_context_source_badge_text(session)
    if not research_league_sync_enabled(session):
        return f"Research mode: **General MLB** (off) · {source_badge}"
    try:
        from active_team_context import (
            SOURCE_LEAGUE,
            SOURCE_LIVE_DRAFT,
            SOURCE_SIMULATOR,
            resolve_active_team_context,
        )

        ctx = resolve_active_team_context(session)
    except Exception:
        ctx = None
    if ctx is not None and getattr(ctx, "source", None) == SOURCE_LEAGUE:
        return (
            f"Research mode: **On** · {source_badge} — {ctx.active_team} "
            "(drafted players hidden & re-ranked)"
        )
    if ctx is not None and getattr(ctx, "source", None) in (SOURCE_SIMULATOR, SOURCE_LIVE_DRAFT):
        return (
            f"Research mode: **On** · {source_badge} — {ctx.active_team} "
            "(drafted players hidden & re-ranked)"
        )
    return f"Research mode: **On** · {source_badge} (no drafted pool to filter)"


def render_active_league_context_badge(st: Any, session: dict[str, Any]) -> None:
    st.caption(active_league_context_badge_text(session))


def render_research_sync_badge(st: Any, session: dict[str, Any]) -> None:
    st.caption(research_sync_badge_text(session))


def render_fantasy_context_badge(st: Any, session: dict[str, Any]) -> None:
    """Default badge for in-season fantasy pages."""
    render_active_league_context_badge(st, session)


# Backward-compatible alias for tests and callers.
fantasy_context_badge_text = fantasy_context_source_badge_text


def render_fantasy_context_library_block(
    st: Any,
    session: dict[str, Any],
    *,
    active_context: dict[str, Any] | None,
) -> None:
    """Legacy wrapper — sync control only (Active Draft section lives in draft_archive_ui)."""
    render_fantasy_context_sync_control(st, session)
