"""Trade Plan chips for Fantasy Lineup Assistant."""

from __future__ import annotations

from typing import Any, Callable

from fantasy_league_context import (
    TRADE_MODE_ACQUIRE,
    TRADE_MODE_TRADE_AWAY,
    get_active_league_context,
    get_active_workflow_targets,
    remove_workflow_target,
    workflow_target_player_names,
)


def render_trade_plan_section(
    st: Any,
    session: dict[str, Any],
    *,
    persist_fn: Callable[..., None] | None = None,
    key_prefix: str = "trade_plan",
) -> tuple[list[str], list[str]]:
    """Render Your Trade Plan chips. Returns (trade_candidate_names, acquire_target_names)."""
    active = get_active_league_context(session)
    if not active:
        st.caption("No active league context. Set one in **Saved Draft Library** to persist trade targets.")
        return [], []

    league_context_id = str(active.get("league_context_id") or "").strip()
    display_name = str(active.get("display_name") or active.get("league_name") or "League").strip()

    st.markdown("##### Your Trade Plan")
    st.caption(f"Active league context: **{display_name}**")

    trade_targets = get_active_workflow_targets(session, TRADE_MODE_TRADE_AWAY)
    acquire_targets = get_active_workflow_targets(session, TRADE_MODE_ACQUIRE)

    if not trade_targets and not acquire_targets:
        st.caption("No trade targets yet. Use **Trade / Acquire** from a player page to add candidates.")

    if trade_targets:
        st.markdown("**Trade Candidates** (my team)")
        cols = st.columns(min(len(trade_targets), 4) or 1)
        for idx, target in enumerate(trade_targets):
            name = str(target.get("player_name") or "").strip()
            if not name:
                continue
            col = cols[idx % len(cols)]
            with col:
                if st.button(f"✕ {name}", key=f"{key_prefix}_remove_trade_{idx}_{target.get('player_key', idx)}"):
                    remove_workflow_target(session, league_context_id, TRADE_MODE_TRADE_AWAY, name)
                    if persist_fn:
                        persist_fn(session, st, reason="trade_candidate_removed")
                    st.rerun()

    if acquire_targets:
        st.markdown("**Acquire Targets** (rivals)")
        cols = st.columns(min(len(acquire_targets), 4) or 1)
        for idx, target in enumerate(acquire_targets):
            name = str(target.get("player_name") or "").strip()
            owner = str(target.get("owner_team") or "").strip()
            label = f"✕ {name}" + (f" ({owner})" if owner else "")
            col = cols[idx % len(cols)]
            with col:
                if st.button(label, key=f"{key_prefix}_remove_acquire_{idx}_{target.get('player_key', idx)}"):
                    remove_workflow_target(session, league_context_id, TRADE_MODE_ACQUIRE, name)
                    if persist_fn:
                        persist_fn(session, st, reason="acquire_target_removed")
                    st.rerun()

    return (
        workflow_target_player_names(active, TRADE_MODE_TRADE_AWAY),
        workflow_target_player_names(active, TRADE_MODE_ACQUIRE),
    )
