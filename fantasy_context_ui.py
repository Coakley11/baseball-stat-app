"""Fantasy league context sync UI — Saved Draft Library + page badges."""

from __future__ import annotations

from typing import Any, Callable

from fantasy_waiver_wire import GLOBAL_WAIVER_FILTER_KEY

FANTASY_CONTEXT_SYNC_LABEL = "Sync fantasy pages to this league"
FANTASY_CONTEXT_SYNC_HELP = (
    "When enabled, Standings, Lineup Assistant, Waiver Wire, Trade Analyzer, and "
    "Fantasy Assistant use your **Active League Context** (rosters, team, category ranks)."
)

_SYNC_PAGES = (
    "Fantasy Standings Tracker",
    "Fantasy Lineup Assistant",
    "Waiver Wire / Add-Drop Center",
)


def fantasy_context_sync_enabled(session: dict[str, Any]) -> bool:
    return bool(session.get(GLOBAL_WAIVER_FILTER_KEY))


def _on_sync_changed(st: Any) -> None:
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="fantasy_context_sync_changed")
    except Exception:
        pass


def render_fantasy_context_sync_control(st: Any, session: dict[str, Any], *, key: str = "library_fantasy_context_sync") -> None:
    """Primary control — belongs on Saved Draft Library, not Waiver Wire."""
    st.markdown("##### Fantasy Context Sync")
    st.checkbox(
        FANTASY_CONTEXT_SYNC_LABEL,
        key=GLOBAL_WAIVER_FILTER_KEY,
        help=FANTASY_CONTEXT_SYNC_HELP,
        on_change=_on_sync_changed,
    )
    st.caption(
        "Affected pages: Fantasy Standings Tracker, Fantasy Lineup Assistant, "
        "Waiver Wire / Add-Drop Center, Trade Analyzer, Fantasy Assistant."
    )


def fantasy_context_badge_text(session: dict[str, Any]) -> str:
    synced = fantasy_context_sync_enabled(session)
    try:
        from fantasy_league_context import get_active_league_context

        ctx = get_active_league_context(session)
    except ImportError:
        ctx = None
    if synced and isinstance(ctx, dict):
        name = str(ctx.get("display_name") or ctx.get("my_team_name") or "Active League").strip()
        return f"Fantasy Context: **{name}** (Synced)"
    if synced:
        return "Fantasy Context: **Active League** (Synced)"
    return "Fantasy Context: **General MLB Mode**"


def render_fantasy_context_badge(st: Any, session: dict[str, Any]) -> None:
    st.caption(fantasy_context_badge_text(session))


def render_fantasy_context_library_block(
    st: Any,
    session: dict[str, Any],
    *,
    active_context: dict[str, Any] | None,
) -> None:
    """Show active league summary + sync toggle on Saved Draft Library."""
    if active_context:
        st.markdown(
            f"**Active League:** {active_context.get('display_name', 'League')} · "
            f"My team: **{active_context.get('my_team_name', '—')}**"
        )
    else:
        st.info("No **Active League Context** selected. Set one from a saved draft below.")
    render_fantasy_context_sync_control(st, session)
