"""Active League Context display + fantasy context source controls."""

from __future__ import annotations

from typing import Any

from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
    SOURCE_GENERIC,
    fantasy_context_source_badge_text,
    fantasy_context_using_caption,
    fantasy_context_using_html,
    fantasy_context_using_markdown,
    live_draft_context_available,
    live_draft_sync_enabled,
    simulator_board_context_available,
    simulator_board_sync_enabled,
)

# Persisted session key (legacy name retained for cloud/disk compatibility).
FANTASY_RESEARCH_SYNC_KEY = "use_active_league_context_waiver_filter"

FANTASY_RESEARCH_SYNC_LABEL = "Research Mode — treat drafted players as unavailable"
FANTASY_RESEARCH_SYNC_HELP = (
    "When enabled, broader research pages treat players already drafted in the active fantasy "
    "context as **unavailable** and recalculate rankings using only remaining players. "
    "Also enables Draft Assistant Simulator for Saved Active Draft and Simulator override "
    "contexts. Source follows your **Fantasy Source** priority (Live Draft, Simulator "
    "board, or Saved Draft Library Active Draft)."
)

USE_LIVE_DRAFT_CONTEXT_LABEL = "Live Draft Room override"
USE_LIVE_DRAFT_CONTEXT_HELP = (
    "Temporarily use your current Live Draft Room board instead of your Active Draft. "
    "Does not save a draft or change your Active Draft."
)

USE_SIMULATOR_BOARD_CONTEXT_LABEL = "Draft Room Simulator override"
USE_SIMULATOR_BOARD_CONTEXT_HELP = (
    "Temporarily use your Draft Room Simulator board instead of your Active Draft. "
    "Does not save a draft or change your Active Draft."
)

FANTASY_CONTEXT_INTRO = (
    "Your Active Draft is the normal source for your fantasy tools.\n\n"
    "Practicing? Turn on an override to temporarily use your Live Draft Room or "
    "Draft Room Simulator board instead."
)

FANTASY_CONTEXT_OVERRIDE_FOOTER = "Turn the override off to go back to your Active Draft."

RESEARCH_SYNC_INTRO = (
    "Research Mode Sync removes players from your current draft context on research pages too, "
    "so recommendations recalculate without already-drafted players."
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


# Separate widget keys from the persisted source-of-truth keys. Streamlit garbage
# collects widget-owned session keys when the widget is not rendered (e.g. after
# navigating to another page). Persisted keys live in the workspace blob; checkbox
# widgets receive value= from persisted state and never get session_state writes
# after render (which raises StreamlitAPIException).
_LIVE_CONTEXT_TOGGLE_WIDGET_KEY = "_fcs_live_context_toggle_widget"
_SIM_CONTEXT_TOGGLE_WIDGET_KEY = "_fcs_sim_context_toggle_widget"
_RESEARCH_SYNC_TOGGLE_WIDGET_KEY = "_fcs_research_sync_toggle_widget"


def _sync_persisted_context_toggles_from_widgets(session: dict[str, Any]) -> None:
    """Copy widget display state into persisted source-of-truth keys (on_change only)."""
    if _LIVE_CONTEXT_TOGGLE_WIDGET_KEY in session:
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = bool(
            session.get(_LIVE_CONTEXT_TOGGLE_WIDGET_KEY)
        )
    if _SIM_CONTEXT_TOGGLE_WIDGET_KEY in session:
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = bool(
            session.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY)
        )
    if _RESEARCH_SYNC_TOGGLE_WIDGET_KEY in session:
        session[FANTASY_RESEARCH_SYNC_KEY] = bool(
            session.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY)
        )


def _persist_context_settings(*, lightweight: bool = True) -> None:
    try:
        import streamlit as st
    except Exception:
        return
    session = st.session_state
    try:
        from account_fantasy_preferences import write_account_fantasy_preferences

        write_account_fantasy_preferences(session, reason="fantasy_context_toggle")
    except ImportError:
        pass
    if lightweight:
        try:
            from suite_user_persistence import _local_dirty_key

            st.session_state[_local_dirty_key("baseball")] = True
        except Exception:
            pass
        return
    try:
        from suite_user_persistence import _local_dirty_key

        st.session_state[_local_dirty_key("baseball")] = True
    except Exception:
        pass
    try:
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="fantasy_context_source_changed")
    except Exception:
        pass


def _on_context_setting_changed(*_args, **_kwargs) -> None:
    """Persist fantasy context toggles immediately on change (Research Mode toggle)."""
    _persist_context_settings()


def _on_research_sync_toggle_changed() -> None:
    try:
        import streamlit as st
    except Exception:
        return
    st.session_state[FANTASY_RESEARCH_SYNC_KEY] = bool(
        st.session_state.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY)
    )
    _persist_context_settings()


def _on_live_context_toggle_changed() -> None:
    try:
        import streamlit as st
    except Exception:
        return
    st.session_state[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = bool(
        st.session_state.get(_LIVE_CONTEXT_TOGGLE_WIDGET_KEY)
    )
    _persist_context_settings()


def _on_sim_context_toggle_changed() -> None:
    try:
        import streamlit as st
    except Exception:
        return
    st.session_state[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = bool(
        st.session_state.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY)
    )
    _persist_context_settings()


def _prepare_context_checkbox_widget(
    session: dict[str, Any],
    *,
    persisted_key: str,
    widget_key: str,
) -> None:
    """Seed widget key from persisted state only before first render — never after."""
    session.setdefault(persisted_key, False)
    persisted = bool(session.get(persisted_key))
    if widget_key in session and bool(session.get(widget_key)) != persisted:
        session.pop(widget_key, None)
    if widget_key not in session:
        session[widget_key] = persisted


def _render_persisted_context_checkbox(
    st: Any,
    session: dict[str, Any],
    *,
    label: str,
    persisted_key: str,
    widget_key: str,
    help: str,
    on_change,
) -> None:
    """Checkbox backed by a persisted key — widget seeded once, synced back on change only."""
    _prepare_context_checkbox_widget(session, persisted_key=persisted_key, widget_key=widget_key)
    st.checkbox(
        label,
        key=widget_key,
        help=help,
        on_change=on_change,
    )


def render_fantasy_context_source_controls(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "fantasy_context_source",
) -> None:
    """Temporary workspace overrides — do not create saved leagues or replace Active Draft."""
    st.markdown("##### Fantasy Source")
    st.markdown(FANTASY_CONTEXT_INTRO)
    from fantasy_context_source import prepare_fantasy_context_source_defaults, resolve_fantasy_context_source

    prepare_fantasy_context_source_defaults(session)

    effective = resolve_fantasy_context_source(session)
    live_available = live_draft_context_available(session)
    sim_available = simulator_board_context_available(session)

    _render_persisted_context_checkbox(
        st,
        session,
        label=USE_LIVE_DRAFT_CONTEXT_LABEL,
        persisted_key=USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
        widget_key=_LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
        help=USE_LIVE_DRAFT_CONTEXT_HELP,
        on_change=_on_live_context_toggle_changed,
    )
    if live_draft_sync_enabled(session):
        if effective.kind == "live_draft":
            st.caption("✓ Live Draft Room is currently driving fantasy context.")
        elif not live_available:
            st.caption("Override is on, but no Live Draft Room picks are available yet.")
    elif not live_available:
        st.caption("No Live Draft Room board with picks yet.")

    _render_persisted_context_checkbox(
        st,
        session,
        label=USE_SIMULATOR_BOARD_CONTEXT_LABEL,
        persisted_key=USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
        widget_key=_SIM_CONTEXT_TOGGLE_WIDGET_KEY,
        help=USE_SIMULATOR_BOARD_CONTEXT_HELP,
        on_change=_on_sim_context_toggle_changed,
    )
    if simulator_board_sync_enabled(session):
        if effective.kind == "simulator_board":
            st.caption("✓ Draft Room Simulator is currently driving fantasy context.")
        elif not sim_available:
            st.caption("Override is on, but the simulator board has no picks yet.")
    elif not sim_available:
        st.caption("No simulator board with picks yet.")

    st.caption(FANTASY_CONTEXT_OVERRIDE_FOOTER)
    effective = resolve_fantasy_context_source(session)
    st.caption(f"Effective source: {fantasy_context_using_caption(session)}")
    if effective.kind == SOURCE_GENERIC:
        try:
            from workflow_persist_guard import DRAFT_ARCHIVE_KEY, count_draft_archives

            if count_draft_archives(session.get(DRAFT_ARCHIVE_KEY)) > 0:
                st.info(
                    "**Next step:** choose a saved draft in **Saved Draft Library** below and click "
                    "**Set Active** to feed Standings, Lineup, Waiver Wire, and Trades."
                )
        except ImportError:
            pass


def render_fantasy_context_sync_control(
    st: Any,
    session: dict[str, Any],
    *,
    key: str = "library_fantasy_context_sync",
) -> None:
    """Research-page sync toggle + temporary workspace overrides."""
    render_fantasy_context_source_controls(st, session, key_prefix=key)
    st.markdown("##### Research Mode Sync")
    st.caption(RESEARCH_SYNC_INTRO)
    _render_persisted_context_checkbox(
        st,
        session,
        label=FANTASY_RESEARCH_SYNC_LABEL,
        persisted_key=FANTASY_RESEARCH_SYNC_KEY,
        widget_key=_RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
        help=FANTASY_RESEARCH_SYNC_HELP,
        on_change=_on_research_sync_toggle_changed,
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
    st.caption(fantasy_context_source_badge_text(session))


def render_fantasy_using_caption(st: Any, session: dict[str, Any]) -> None:
    """Polished league-card header naming the effective fantasy source."""
    try:
        from fantasy_context_source import fantasy_workflow_using_html

        st.markdown(fantasy_workflow_using_html(session), unsafe_allow_html=True)
    except ImportError:
        st.markdown(fantasy_context_using_html(session), unsafe_allow_html=True)


def render_fantasy_workflow_page_header(
    st: Any,
    session: dict[str, Any],
    *,
    active_page: str,
    key_prefix: str = "fantasy_nav",
    page_label_fn=None,
) -> None:
    """Fantasy workflow pages: one context line + nav (no duplicate source blocks)."""
    render_fantasy_using_caption(st, session)
    try:
        from draft_archive_ui import render_fantasy_page_navigation

        render_fantasy_page_navigation(
            st,
            session,
            active_page=active_page,
            key_prefix=key_prefix,
            page_label_fn=page_label_fn,
        )
    except ImportError:
        pass


# Backward-compatible alias for tests and callers.
fantasy_context_badge_text = fantasy_context_source_badge_text


def render_fantasy_context_activation_prompt(
    st: Any,
    session: dict[str, Any],
    *,
    key_prefix: str = "fantasy_activate",
    page_label_fn=None,
) -> bool:
    """Prompt user to activate a league/draft when none is selected. Returns True when active."""
    try:
        from draft_archive_state import get_active_draft_archive
        from fantasy_league_context import get_active_league_context
        from fantasy_context_terminology import no_active_context_message
        from draft_archive_ui import (
            DRAFT_SIMULATOR_PAGE,
            SAVED_DRAFT_LIBRARY_PAGE,
            _nav_label,
            _on_click_navigate_to_page,
        )
    except ImportError:
        return False

    active_archive = get_active_draft_archive(session)
    active_context = get_active_league_context(session, respect_source_priority=False)
    if active_archive or active_context:
        return True

    st.info(no_active_context_message())
    nav1, nav2 = st.columns(2)
    with nav1:
        st.button(
            _nav_label(DRAFT_SIMULATOR_PAGE, "Draft Room Simulator", page_label_fn),
            key=f"{key_prefix}__go_draft_simulator_btn",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(DRAFT_SIMULATOR_PAGE, f"{key_prefix}__go_draft_simulator_btn", "draft_room_simulator"),
        )
    with nav2:
        st.button(
            _nav_label(SAVED_DRAFT_LIBRARY_PAGE, "Saved Draft Library", page_label_fn),
            key=f"{key_prefix}__go_saved_library_btn",
            use_container_width=True,
            on_click=_on_click_navigate_to_page,
            args=(SAVED_DRAFT_LIBRARY_PAGE, f"{key_prefix}__go_saved_library_btn", "saved_draft_library"),
        )
    return False


def render_fantasy_context_library_block(
    st: Any,
    session: dict[str, Any],
    *,
    active_context: dict[str, Any] | None,
) -> None:
    """Legacy wrapper — sync control only (Active Draft section lives in draft_archive_ui)."""
    render_fantasy_context_sync_control(st, session)
