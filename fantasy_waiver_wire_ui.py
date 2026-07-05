"""Streamlit UI for Waiver Wire / Add-Drop Center — current-season stats driven."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from fantasy_league_context import (
    build_roster_stats_from_league_context,
    get_active_league_context,
    has_full_league_rosters,
    league_context_coverage_badge,
    league_context_type_badge,
)
from fantasy_waiver_wire import (
    WAIVER_PLANNER_ADD_KEY,
    WAIVER_PLANNER_DROP_KEY,
    add_pending_move_pair,
    analyze_current_team_needs,
    build_category_standings_table,
    build_waiver_pool,
    build_weakness_narrative,
    compute_add_drop_category_impact,
    filter_waiver_names_by_search,
    format_current_stat_line,
    format_league_rank_lines,
    get_pending_move_pairs,
    my_team_roster_dataframe,
    recommend_adds_current,
    recommend_drops_current,
    remove_pending_move_pair,
    waiver_categories_for_context,
    waiver_display_stat_columns,
)


def _player_names(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []
    for col in ("Player", "fullName", "player_name"):
        if col in df.columns:
            return sorted(df[col].dropna().astype(str).unique().tolist())
    return []


def _row_for_player(df: pd.DataFrame, name: str) -> pd.Series | None:
    if df is None or df.empty or not name:
        return None
    for col in ("Player", "fullName", "player_name"):
        if col not in df.columns:
            continue
        match = df[df[col].astype(str).str.strip() == str(name).strip()]
        if not match.empty:
            return match.iloc[0]
    return None


def _photo_helpers(st: Any) -> tuple[bool, Any, Any]:
    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_rec_card_photo_html

        inject_player_photo_styles(st)
        return True, get_player_photo_info, render_rec_card_photo_html
    except ImportError:
        return False, None, None


def _render_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
    button_label: str,
    on_click,
    subtitle: str = "",
) -> None:
    use_photos, get_photo, render_photo = _photo_helpers(st)
    name = str(row.get("Player") or row.get("fullName") or "")
    team = str(row.get("MLB Team") or row.get("Team") or "—")
    pos = str(row.get("Primary Position") or row.get("Position") or "—")

    with st.container(border=True):
        c_photo, c_body, c_action = st.columns([1, 3, 1])
        with c_photo:
            if use_photos and get_photo and render_photo:
                photo_info = get_photo(full_name=name, row=row, use_api=True)
                st.markdown(render_photo(photo_info, alt=name), unsafe_allow_html=True)
        with c_body:
            st.markdown(f"**{name}**")
            st.caption(f"{team} · {pos}")
            st.caption(format_current_stat_line(row))
            if subtitle:
                st.caption(subtitle)
        with c_action:
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
            if st.button(button_label, key=f"{key_prefix}_{safe_key}", use_container_width=True):
                on_click(name)
                st.rerun()


def _render_add_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
    on_plan_add,
) -> None:
    why = str(row.get("Why Add") or "")
    _render_player_card(
        st,
        row,
        key_prefix=key_prefix,
        button_label="Plan Add",
        on_click=on_plan_add,
        subtitle=why,
    )


def _on_waiver_filter_changed() -> None:
    """Persist waiver global filter toggle to baseball workspace state."""
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_filter_changed")
    except Exception:
        pass


def _on_planner_pick_changed() -> None:
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="waiver_planner_pick")
    except Exception:
        pass


def render_waiver_wire_page(
    st: Any,
    session: dict[str, Any],
    *,
    current_stats_pool: pd.DataFrame,
    league_roster_stats: pd.DataFrame | None = None,
    normalize_name_fn=None,
    page_label_fn=None,
) -> None:
    context = get_active_league_context(session)
    if not context:
        st.warning(
            "No **Active League Context**. Open **Saved Draft Library**, pick a saved draft, "
            "and click **Set Active League Context**."
        )
        return

    st.caption(
        f"**{context.get('display_name', 'Active League')}** · "
        f"{league_context_coverage_badge(context)} · "
        f"{league_context_type_badge(context)} · "
        f"My team: **{context.get('my_team_name', '—')}**"
    )
    try:
        from fantasy_context_ui import render_fantasy_context_badge, render_fantasy_context_sync_required

        render_fantasy_context_badge(st, session)
        if not render_fantasy_context_sync_required(st, session, page_name="Waiver Wire / Add-Drop Center"):
            return
    except ImportError:
        pass

    stats_pool = current_stats_pool.copy() if current_stats_pool is not None else pd.DataFrame()
    if stats_pool.empty:
        st.warning(
            "**Current 2026 stats not loaded yet.** Open **Fantasy Standings Tracker**, "
            "load MLB API or CSV current-season stats, then return here."
        )
        return

    st.caption(
        "Waiver analysis uses **current-season MLB stats** and your **Active League Context** — "
        "not projections, ADP, Fantasy Edge, or draft-risk metrics."
    )

    try:
        from fantasy_in_season_state import prepare_fantasy_in_season_hydration

        prepare_fantasy_in_season_hydration(session)
    except ImportError:
        pass

    league_df = league_roster_stats.copy() if league_roster_stats is not None and not league_roster_stats.empty else pd.DataFrame()
    if league_df.empty and normalize_name_fn is not None:
        cached = stats_pool
        if isinstance(cached, pd.DataFrame) and not cached.empty and has_full_league_rosters(context):
            league_df = build_roster_stats_from_league_context(
                context,
                cached,
                normalize_name_fn=normalize_name_fn,
            )

    my_team = str(context.get("my_team_name") or "").strip()
    if not league_df.empty and my_team and "Team" in league_df.columns:
        my_roster = league_df[league_df["Team"].astype(str) == my_team].copy()
    else:
        my_roster = my_team_roster_dataframe(context)
        if not my_roster.empty and not league_df.empty:
            name_col = "Player" if "Player" in league_df.columns else None
            if name_col:
                names = set(my_roster.get("Player", my_roster.get("fullName", pd.Series())).astype(str))
                my_roster = league_df[league_df[name_col].astype(str).isin(names)].copy()

    waiver_pool = build_waiver_pool(stats_pool, context)
    waiver_cats = waiver_categories_for_context(context)
    needs = analyze_current_team_needs(my_roster, league_df, categories=waiver_cats)
    _has_slots = context_has_roster_slots(context)
    open_slots = resolve_context_open_position_needs(context, my_roster) if _has_slots else []

    st.markdown("##### League snapshot")
    rank_lines = format_league_rank_lines(needs, categories=waiver_cats)
    if rank_lines:
        st.caption(" · ".join(rank_lines))
    cat_table = build_category_standings_table(needs, categories=waiver_cats)
    if not cat_table.empty:
        with st.expander("Category ranks", expanded=False):
            st.dataframe(cat_table, use_container_width=True, hide_index=True)
    for line in build_weakness_narrative(needs)[:2]:
        st.caption(line)

    st.markdown("##### 1. Top Recommended Adds")
    adds = recommend_adds_current(waiver_pool, needs, limit=15)
    if adds.empty:
        st.info("No waiver recommendations yet — load current-season stats and check your league context.")
    else:
        def _plan_add(name: str) -> None:
            session[WAIVER_PLANNER_ADD_KEY] = name
            _on_planner_pick_changed()

        for i, (_, row) in enumerate(adds.head(15).iterrows()):
            _render_add_player_card(st, row, key_prefix=f"waiver_rec_{i}", on_plan_add=_plan_add)

    st.markdown("##### 2. Recommended Drops")
    drops = recommend_drops_current(my_roster, limit=15, categories=waiver_cats)
    if drops.empty:
        st.info("No drop candidates on your roster yet.")
    else:
        selected_drop = str(session.get(WAIVER_PLANNER_DROP_KEY) or "").strip()

        def _select_drop(name: str) -> None:
            session[WAIVER_PLANNER_DROP_KEY] = name
            _on_planner_pick_changed()

        for i, (_, row) in enumerate(drops.head(15).iterrows()):
            name = str(row.get("Player") or row.get("fullName") or "")
            label = "Selected To Drop" if name == selected_drop else "Plan Drop"
            _render_player_card(
                st,
                row,
                key_prefix=f"waiver_drop_{i}",
                button_label=label,
                on_click=_select_drop,
                subtitle=str(row.get("Why Drop") or ""),
            )

    st.markdown("##### 3. Available Player Pool")
    st.caption(f"{len(waiver_pool)} waiver-eligible players. Search and sort in the table — use **Plan Add** cards above or the planner below.")
    search_query = st.text_input(
        "Search available players",
        key="waiver_pool_search",
        placeholder="Type a player name…",
    )
    if waiver_pool.empty:
        st.info("Waiver pool is empty for this context.")
    else:
        pool_view = waiver_pool.copy()
        if search_query:
            names = _player_names(pool_view)
            keep = set(filter_waiver_names_by_search(names, search_query))
            name_col = "Player" if "Player" in pool_view.columns else "fullName"
            if name_col in pool_view.columns:
                pool_view = pool_view[pool_view[name_col].astype(str).isin(keep)]
        disp_cols = [c for c in waiver_display_stat_columns(pool_view) if c in pool_view.columns]
        extra_cols = [c for c in ("Team", "Primary Position", "Position", "MLB Team") if c in pool_view.columns]
        for c in extra_cols:
            if c not in disp_cols:
                disp_cols.insert(0, c)
        st.dataframe(pool_view[disp_cols].head(150), use_container_width=True, hide_index=True)

    st.markdown("##### 4. Manual Add / Drop Actions")
    st.caption("Select an add target and a drop from your roster, then save as a pending move.")
    planner_add = str(session.get(WAIVER_PLANNER_ADD_KEY) or "").strip()
    planner_drop = str(session.get(WAIVER_PLANNER_DROP_KEY) or "").strip()
    if planner_add:
        add_row = _row_for_player(waiver_pool, planner_add)
        if add_row is not None:
            st.markdown("**Add target**")

            def _clear_add(_name: str) -> None:
                session.pop(WAIVER_PLANNER_ADD_KEY, None)
                _on_planner_pick_changed()

            _render_player_card(
                st,
                add_row,
                key_prefix="waiver_planner_add",
                button_label="Clear Add",
                on_click=_clear_add,
            )
    if planner_drop:
        drop_row = _row_for_player(my_roster, planner_drop)
        if drop_row is not None:
            st.markdown("**Drop candidate**")

            def _clear_drop(_name: str) -> None:
                session.pop(WAIVER_PLANNER_DROP_KEY, None)
                _on_planner_pick_changed()

            _render_player_card(
                st,
                drop_row,
                key_prefix="waiver_planner_drop",
                button_label="Clear Drop",
                on_click=_clear_drop,
            )
    add_row = _row_for_player(waiver_pool, planner_add) if planner_add else None
    drop_row = _row_for_player(my_roster, planner_drop) if planner_drop else None
    impact = compute_add_drop_category_impact(
        add_row,
        drop_row,
        categories=list(needs.get("available_categories") or waiver_cats),
    )
    if impact:
        st.caption(f"**Category impact:** {', '.join(impact)}")
    if st.button("Add to Pending Moves", key="waiver_save_pair_btn", type="primary"):
        if not planner_add or not planner_drop:
            st.warning("Select both an add target and a drop player.")
        elif add_pending_move_pair(
            session,
            add_player=planner_add,
            drop_player=planner_drop,
            category_impact=impact,
        ):
            session.pop(WAIVER_PLANNER_ADD_KEY, None)
            session.pop(WAIVER_PLANNER_DROP_KEY, None)
            st.rerun()

    st.markdown("##### Pending Add/Drop Moves")
    pairs = get_pending_move_pairs(session)
    if not pairs:
        st.caption("No pending add/drop pairs yet.")
    else:
        for i, pair in enumerate(pairs):
            add_name = str(pair.get("add_player") or "")
            drop_name = str(pair.get("drop_player") or "")
            impact_txt = ", ".join(pair.get("category_impact") or []) or "—"
            st.markdown(f"**Add:** {add_name}  ·  **Drop:** {drop_name}")
            st.caption(f"Category impact: {impact_txt}")
            if st.button("Remove pair", key=f"waiver_rm_pair_{i}_btn"):
                remove_pending_move_pair(session, i)
                st.rerun()
