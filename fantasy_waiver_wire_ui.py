"""Streamlit UI for Waiver Wire / Add-Drop Center."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from fantasy_league_context import (
    context_has_roster_slots,
    get_active_league_context,
    league_context_coverage_badge,
    league_context_type_badge,
    league_context_roster_dataframe,
    resolve_context_open_position_needs,
)
from fantasy_waiver_wire import (
    GLOBAL_WAIVER_FILTER_KEY,
    TRADE_MODE_ADD,
    TRADE_MODE_DROP,
    WAIVER_WIRE_PAGE,
    add_pending_move,
    analyze_team_needs,
    build_waiver_pool,
    get_league_activity,
    get_pending_add_targets,
    get_pending_drop_candidates,
    my_team_roster_dataframe,
    recommend_adds,
    recommend_drops,
    record_league_activity,
    remove_pending_move,
)


def _display_cols(df: pd.DataFrame, extra: list[str] | None = None) -> list[str]:
    cols = ["Player", "Primary Position", "proj_OPS", "proj_HR", "proj_RBI", "proj_SB", "proj_BA"]
    if extra:
        cols.extend(extra)
    return [c for c in cols if c in df.columns]


def render_waiver_wire_page(
    st: Any,
    session: dict[str, Any],
    *,
    player_pool: pd.DataFrame,
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

    st.checkbox(
        "Use Active League Context Across Draft Pages",
        key=GLOBAL_WAIVER_FILTER_KEY,
        help=(
            "When enabled, draft tools exclude players already rostered in the active league context. "
            "Turn off to analyze the full player universe."
        ),
    )
    st.caption(
        "When enabled, Draft Assistant, Sleepers, Trends, Valuation, and Comparison "
        "hide players rostered in this active league context."
    )

    my_roster = my_team_roster_dataframe(context)
    league_df = league_context_roster_dataframe(context)
    waiver_pool = build_waiver_pool(player_pool, context)
    fantasy_format = str(context.get("fantasy_format") or session.get("room_format") or "5x5 Roto")
    needs = analyze_team_needs(my_roster, league_df, fantasy_format=fantasy_format)
    _has_slots = context_has_roster_slots(context)
    open_slots = resolve_context_open_position_needs(context, my_roster) if _has_slots else []

    st.markdown("##### 1. Team Needs")
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
            "This mock draft was saved without roster-slot settings, so analysis focuses "
            "on player value, category balance, and team strengths rather than missing "
            "lineup positions."
        )
    need_cols = st.columns(3)
    with need_cols[0]:
        st.markdown("**Strengths**")
        if needs.get("strengths"):
            st.write(", ".join(needs["strengths"]))
        else:
            st.caption("No clear strengths yet.")
    with need_cols[1]:
        st.markdown("**Weaknesses**")
        if needs.get("weaknesses"):
            st.write(", ".join(needs["weaknesses"]))
        else:
            st.caption("Balanced roster profile.")
    with need_cols[2]:
        st.markdown("**Categories to target**")
        if needs.get("targets"):
            st.write(", ".join(needs["targets"]))
        else:
            st.caption("Best available upgrades.")

    st.markdown("##### 2. Recommended Adds")
    adds = recommend_adds(waiver_pool, needs)
    if adds.empty:
        st.info("No waiver recommendations — load player projections or widen the player pool.")
    else:
        st.dataframe(adds[_display_cols(adds, ["Why Add"])], use_container_width=True, hide_index=True)

    st.markdown("##### 3. Recommended Drops")
    drops = recommend_drops(my_roster)
    if drops.empty:
        st.info("No drop candidates on your roster yet.")
    else:
        st.dataframe(drops[_display_cols(drops, ["Why Drop"])], use_container_width=True, hide_index=True)

    st.markdown("##### 4. Available Players")
    st.caption(f"{len(waiver_pool)} waiver-eligible players (pool minus active league rosters).")
    if waiver_pool.empty:
        st.info("Waiver pool is empty for this context.")
    else:
        st.dataframe(
            waiver_pool[_display_cols(waiver_pool)].head(40),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("##### 5. Pending Moves")
    add_targets = get_pending_add_targets(session)
    drop_targets = get_pending_drop_candidates(session)
    if add_targets or drop_targets:
        for target in add_targets:
            name = str(target.get("player_name") or "")
            if st.button(f"Remove add: {name}", key=f"waiver_rm_add_{name}"):
                remove_pending_move(session, TRADE_MODE_ADD, name)
                st.rerun()
        for target in drop_targets:
            name = str(target.get("player_name") or "")
            if st.button(f"Remove drop: {name}", key=f"waiver_rm_drop_{name}"):
                remove_pending_move(session, TRADE_MODE_DROP, name)
                st.rerun()
    else:
        st.caption("No pending add/drop candidates yet.")

    plan_col1, plan_col2 = st.columns(2)
    with plan_col1:
        add_pick = st.selectbox(
            "Add candidate",
            [""] + sorted(waiver_pool.get("Player", waiver_pool.get("fullName", pd.Series())).astype(str).tolist())
            if not waiver_pool.empty
            else [""],
            key="waiver_add_pick",
        )
        if st.button("Add to weekly plan", key="waiver_add_btn") and add_pick:
            add_pending_move(session, TRADE_MODE_ADD, add_pick)
            st.rerun()
    with plan_col2:
        drop_pick = st.selectbox(
            "Drop candidate",
            [""] + sorted(my_roster.get("Player", my_roster.get("fullName", pd.Series())).astype(str).tolist())
            if not my_roster.empty
            else [""],
            key="waiver_drop_pick",
        )
        if st.button("Drop from weekly plan", key="waiver_drop_btn") and drop_pick:
            add_pending_move(session, TRADE_MODE_DROP, drop_pick)
            st.rerun()

    st.markdown("##### 6. League Activity")
    st.caption("Simulate league-wide adds and drops — dropped players return to the waiver pool.")
    teams = sorted(
        {
            str(entry.get("team_name") or team)
            for team, entry in (context.get("league_rosters") or {}).items()
            if isinstance(entry, dict)
        }
    )
    act_col1, act_col2, act_col3 = st.columns(3)
    with act_col1:
        act_team = st.selectbox("Team", teams or [""], key="waiver_activity_team")
    with act_col2:
        act_action = st.selectbox("Action", ["drop", "add"], key="waiver_activity_action")
    with act_col3:
        player_options = (
            sorted(waiver_pool.get("Player", waiver_pool.get("fullName", pd.Series())).astype(str).tolist())
            if act_action == "add" and not waiver_pool.empty
            else sorted(my_roster.get("Player", my_roster.get("fullName", pd.Series())).astype(str).tolist())
            if not my_roster.empty
            else []
        )
        act_player = st.selectbox("Player", [""] + player_options, key="waiver_activity_player")
    if st.button("Record league transaction", key="waiver_activity_btn") and act_team and act_player:
        record_league_activity(session, team_name=act_team, action=act_action, player_name=act_player)
        try:
            from baseball_persistent_state import force_save_baseball_state

            force_save_baseball_state(st, reason="waiver_league_activity")
        except Exception:
            pass
        st.rerun()

    activity = get_league_activity(get_active_league_context(session))
    if activity:
        st.dataframe(pd.DataFrame(activity), use_container_width=True, hide_index=True)
    else:
        st.caption("No league transactions recorded yet.")
