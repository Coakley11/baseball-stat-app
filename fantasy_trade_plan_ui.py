"""Trade Plan chips for Fantasy Lineup Assistant."""

from __future__ import annotations

import re
from typing import Any, Callable

from fantasy_league_context import (
    TRADE_MODE_ACQUIRE,
    TRADE_MODE_TRADE_AWAY,
    get_active_league_context,
    get_active_workflow_targets,
    normalize_player_key,
    remove_workflow_target,
    workflow_target_player_names,
)


def _is_ephemeral_session_key(key: str) -> bool:
    try:
        from page_state import _is_ephemeral_widget_key

        return _is_ephemeral_widget_key(key)
    except ImportError:
        k = str(key or "")
        return "_remove_trade_" in k or "_remove_acquire_" in k


def trade_plan_button_key_prefixes(key_prefix: str) -> tuple[str, str]:
    return (f"{key_prefix}_remove_trade_", f"{key_prefix}_remove_acquire_")


def strip_trade_plan_button_keys(session: dict[str, Any], key_prefix: str) -> None:
    """Drop Streamlit-owned button keys — never persist or pre-assign them."""
    prefixes = trade_plan_button_key_prefixes(key_prefix)
    for key in list(session.keys()):
        if not isinstance(key, str):
            continue
        if any(key.startswith(prefix) for prefix in prefixes) or _is_ephemeral_session_key(key):
            session.pop(key, None)


def stable_trade_plan_button_key(key_prefix: str, *, action: str, player_key: str) -> str:
    """Stable widget key based on player identity, not list index."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(player_key or "").strip()) or "unknown"
    return f"{key_prefix}_{action}_{slug}"


def pending_remove_key(key_prefix: str, mode: str) -> str:
    if mode == TRADE_MODE_TRADE_AWAY:
        return f"{key_prefix}_pending_remove_trade"
    return f"{key_prefix}_pending_remove_acquire"


def _process_pending_removals(
    session: dict[str, Any],
    st: Any,
    *,
    league_context_id: str,
    key_prefix: str,
    persist_fn: Callable[..., None] | None,
) -> bool:
    changed = False
    for mode, reason in (
        (TRADE_MODE_TRADE_AWAY, "trade_candidate_removed"),
        (TRADE_MODE_ACQUIRE, "acquire_target_removed"),
    ):
        payload = session.pop(pending_remove_key(key_prefix, mode), None)
        if not payload or not league_context_id:
            continue
        if isinstance(payload, dict):
            name = str(payload.get("player_name") or "").strip()
        else:
            name = str(payload or "").strip()
        if not name:
            continue
        remove_workflow_target(session, league_context_id, mode, name)
        if persist_fn:
            persist_fn(session, st, reason=reason)
        changed = True
    return changed


def render_trade_plan_section(
    st: Any,
    session: dict[str, Any],
    *,
    persist_fn: Callable[..., None] | None = None,
    key_prefix: str = "trade_plan",
) -> tuple[list[str], list[str]]:
    """Render Your Trade Plan chips. Returns (trade_candidate_names, acquire_target_names)."""
    strip_trade_plan_button_keys(session, key_prefix)

    active = get_active_league_context(session)
    if not active:
        st.caption("No active league context. Set one in **Saved Draft Library** to persist trade targets.")
        return [], []

    league_context_id = str(active.get("league_context_id") or "").strip()
    display_name = str(active.get("display_name") or active.get("league_name") or "League").strip()

    if _process_pending_removals(
        session,
        st,
        league_context_id=league_context_id,
        key_prefix=key_prefix,
        persist_fn=persist_fn,
    ):
        st.rerun()

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
            player_key = str(target.get("player_key") or normalize_player_key(name)).strip()
            col = cols[idx % len(cols)]
            with col:
                btn_key = stable_trade_plan_button_key(
                    key_prefix,
                    action="remove_trade",
                    player_key=player_key,
                )
                if st.button(f"✕ {name}", key=btn_key):
                    session[pending_remove_key(key_prefix, TRADE_MODE_TRADE_AWAY)] = {
                        "player_name": name,
                        "player_key": player_key,
                    }
                    st.rerun()

    if acquire_targets:
        st.markdown("**Acquire Targets** (rivals)")
        cols = st.columns(min(len(acquire_targets), 4) or 1)
        for idx, target in enumerate(acquire_targets):
            name = str(target.get("player_name") or "").strip()
            owner = str(target.get("owner_team") or "").strip()
            label = f"✕ {name}" + (f" ({owner})" if owner else "")
            player_key = str(target.get("player_key") or normalize_player_key(name)).strip()
            col = cols[idx % len(cols)]
            with col:
                btn_key = stable_trade_plan_button_key(
                    key_prefix,
                    action="remove_acquire",
                    player_key=player_key,
                )
                if st.button(label, key=btn_key):
                    session[pending_remove_key(key_prefix, TRADE_MODE_ACQUIRE)] = {
                        "player_name": name,
                        "player_key": player_key,
                    }
                    st.rerun()

    return (
        workflow_target_player_names(active, TRADE_MODE_TRADE_AWAY),
        workflow_target_player_names(active, TRADE_MODE_ACQUIRE),
    )
