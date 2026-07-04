"""Streamlit UI for Waiver Wire / Add-Drop Center — current-season stats driven."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from fantasy_league_context import (
    build_roster_stats_from_league_context,
    context_has_roster_slots,
    get_active_league_context,
    has_full_league_rosters,
    league_context_coverage_badge,
    league_context_type_badge,
    resolve_context_open_position_needs,
)
from fantasy_waiver_wire import (
    GLOBAL_WAIVER_FILTER_KEY,
    WAIVER_PLANNER_ADD_KEY,
    WAIVER_PLANNER_DROP_KEY,
    add_pending_move_pair,
    analyze_current_team_needs,
    build_category_standings_table,
    build_waiver_pool,
    build_weakness_narrative,
    compute_add_drop_category_impact,
    get_pending_move_pairs,
    my_team_roster_dataframe,
    recommend_adds_current,
    recommend_drops_current,
    remove_pending_move_pair,
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


def _format_current_stat_line(row: pd.Series) -> str:
    parts: list[str] = []
    for label, cols in (
        ("HR", ("HR",)),
        ("RBI", ("RBI",)),
        ("R", ("R",)),
        ("SB", ("SB",)),
        ("AVG", ("BA", "AVG")),
        ("OPS", ("OPS",)),
    ):
        for col in cols:
            if col in row.index and pd.notna(row.get(col)):
                val = row.get(col)
                if label == "AVG":
                    parts.append(f"AVG {float(val):.3f}")
                elif isinstance(val, float):
                    parts.append(f"{label} {val:.0f}" if label != "OPS" else f"OPS {val:.3f}")
                break
    return " · ".join(parts) if parts else "Current stats loaded"


def _render_add_player_card(
    st: Any,
    row: pd.Series,
    *,
    key_prefix: str,
    on_plan_add,
) -> None:
    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_rec_card_photo_html

        inject_player_photo_styles(st)
        use_photos = True
    except ImportError:
        use_photos = False

    name = str(row.get("Player") or row.get("fullName") or "")
    team = str(row.get("MLB Team") or row.get("Team") or "—")
    pos = str(row.get("Primary Position") or row.get("Position") or "—")
    why = str(row.get("Why Add") or "")
    helped = str(row.get("Categories Helped") or "")

    with st.container(border=True):
        c_photo, c_body, c_action = st.columns([1, 3, 1])
        with c_photo:
            if use_photos:
                photo_info = get_player_photo_info(full_name=name, row=row, use_api=True)
                st.markdown(render_rec_card_photo_html(photo_info, alt=name), unsafe_allow_html=True)
        with c_body:
            st.markdown(f"**{name}**")
            st.caption(f"{team} · {pos}")
            st.caption(_format_current_stat_line(row))
            if helped:
                st.caption(f"Categories helped: **{helped}**")
            if why:
                st.caption(why)
        with c_action:
            if st.button("Plan Add", key=f"{key_prefix}_plan_{name}", use_container_width=True):
                on_plan_add(name)
                st.rerun()


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

    st.checkbox(
        "Use Active League Context Across Draft Pages",
        key=GLOBAL_WAIVER_FILTER_KEY,
        help=(
            "When enabled, draft tools exclude players already rostered in the active league context. "
            "Turn off to analyze the full player universe."
        ),
    )

    league_df = league_roster_stats.copy() if league_roster_stats is not None and not league_roster_stats.empty else pd.DataFrame()
    if league_df.empty and normalize_name_fn is not None:
        cached = session.get("_fantasy_current_hitter_stats")
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
    needs = analyze_current_team_needs(my_roster, league_df)
    _has_slots = context_has_roster_slots(context)
    open_slots = resolve_context_open_position_needs(context, my_roster) if _has_slots else []

    st.markdown("##### 1. League / Category Standings Summary")
    if _has_slots and open_slots:
        slot_counts = Counter(open_slots)
        slot_parts = []
        for pos in ("C", "1B", "2B", "3B", "SS", "OF", "UTIL", "DH", "P", "BN"):
            if pos not in slot_counts:
                continue
            n = slot_counts[pos]
            slot_parts.append(f"**{pos}**" + (f" (×{n})" if n > 1 else ""))
        st.caption(
            "**Open roster slots (active league context):** "
            + (", ".join(slot_parts) if slot_parts else ", ".join(open_slots))
        )
    elif not _has_slots:
        st.info(
            "This mock draft was saved without roster-slot settings, so waiver analysis focuses "
            "on current stats and category balance rather than missing lineup positions."
        )

    cat_table = build_category_standings_table(needs)
    if not cat_table.empty:
        st.dataframe(cat_table, use_container_width=True, hide_index=True)
    else:
        st.caption("Category ranks will appear after league rosters are merged with current-season stats.")

    sum_cols = st.columns(3)
    with sum_cols[0]:
        st.markdown("**Strongest categories**")
        st.write(", ".join(needs.get("strengths") or []) or "—")
    with sum_cols[1]:
        st.markdown("**Weakest categories**")
        st.write(", ".join(needs.get("weaknesses") or []) or "—")
    with sum_cols[2]:
        st.markdown("**Biggest opportunities**")
        st.write(", ".join(needs.get("targets") or []) or "—")

    st.markdown("##### 2. Team Weakness Analysis")
    for line in build_weakness_narrative(needs):
        st.markdown(line)

    st.markdown("##### 3. Recommended Adds")
    adds = recommend_adds_current(waiver_pool, needs)
    if adds.empty:
        st.info("No waiver recommendations yet — widen the player pool or load more current-season stats.")
    else:
        def _plan_add(name: str) -> None:
            session[WAIVER_PLANNER_ADD_KEY] = name

        for i, (_, row) in enumerate(adds.head(6).iterrows()):
            _render_add_player_card(st, row, key_prefix=f"waiver_rec_{i}", on_plan_add=_plan_add)

        if session.get(WAIVER_PLANNER_ADD_KEY):
            st.success(f"**{session[WAIVER_PLANNER_ADD_KEY]}** is queued in the Add/Drop planner below.")

    st.markdown("##### 4. More Available Players")
    st.caption(f"{len(waiver_pool)} waiver-eligible players (current pool minus active league rosters).")
    if waiver_pool.empty:
        st.info("Waiver pool is empty for this context.")
    else:
        extra = waiver_pool.copy()
        targets = list(needs.get("targets") or [])
        from fantasy_waiver_wire import categories_helped_by_player

        extra["Categories Helped"] = [
            ", ".join(categories_helped_by_player(row, targets)) or "Balance"
            for _, row in extra.iterrows()
        ]
        extra["Status"] = "Available"
        disp_cols = waiver_display_stat_columns(extra)
        if "Categories Helped" in extra.columns:
            disp_cols.append("Categories Helped")
        if "Status" in extra.columns:
            disp_cols.append("Status")
        table_df = extra[disp_cols].head(40)
        st.dataframe(table_df, use_container_width=True, hide_index=True)
        for i, (_, row) in enumerate(extra.head(10).iterrows()):
            pname = str(row.get("Player") or row.get("fullName") or "")
            if st.button(f"Plan Add: {pname}", key=f"waiver_table_plan_{i}"):
                session[WAIVER_PLANNER_ADD_KEY] = pname
                st.rerun()

    st.markdown("##### 5. Player Selector")
    pool_names = _player_names(waiver_pool)
    roster_names = _player_names(my_roster)
    default_add = str(session.get(WAIVER_PLANNER_ADD_KEY) or "")
    add_options = [""] + pool_names
    add_index = add_options.index(default_add) if default_add in add_options else 0
    selected_add = st.selectbox(
        "Select any available waiver player",
        add_options,
        index=add_index,
        key="waiver_any_add_pick",
    )
    if selected_add:
        session[WAIVER_PLANNER_ADD_KEY] = selected_add

    st.markdown("##### 6. Add / Drop Planner")
    st.caption("Select an add target and a drop from your roster, then save as a pending move.")
    planner_add = str(session.get(WAIVER_PLANNER_ADD_KEY) or selected_add or "").strip()
    drop_options = [""] + roster_names
    selected_drop = st.selectbox(
        "Drop from my roster",
        drop_options,
        key=WAIVER_PLANNER_DROP_KEY,
    )
    if planner_add:
        st.caption(f"**Add target:** {planner_add}")
    add_row = _row_for_player(waiver_pool, planner_add) if planner_add else None
    drop_row = _row_for_player(my_roster, selected_drop) if selected_drop else None
    impact = compute_add_drop_category_impact(add_row, drop_row, categories=list(needs.get("targets") or []))
    if impact:
        st.caption(f"**Category impact:** {', '.join(impact)}")
    if st.button("Add to Pending Moves", key="waiver_save_pair_btn", type="primary"):
        if not planner_add or not selected_drop:
            st.warning("Select both an add target and a drop player.")
        elif add_pending_move_pair(
            session,
            add_player=planner_add,
            drop_player=selected_drop,
            category_impact=impact,
        ):
            session.pop(WAIVER_PLANNER_ADD_KEY, None)
            st.rerun()

    st.markdown("##### 7. Pending Add/Drop Moves")
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
            if st.button("Remove pair", key=f"waiver_rm_pair_{i}"):
                remove_pending_move_pair(session, i)
                st.rerun()

    st.markdown("##### 8. Drop Candidates (current-season)")
    drops = recommend_drops_current(my_roster)
    if drops.empty:
        st.info("No drop candidates on your roster yet.")
    else:
        drop_cols = waiver_display_stat_columns(drops)
        if "Why Drop" in drops.columns:
            drop_cols.append("Why Drop")
        st.dataframe(drops[drop_cols], use_container_width=True, hide_index=True)
