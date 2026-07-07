"""Streamlit UI for weekly lineup management (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_weekly_lineup import (
    ROTO_STARTER_CATEGORIES,
    build_lineup_summary,
    compute_weekly_starter_totals,
    eligible_players_for_slot,
    get_saved_weekly_lineup,
    list_week_options,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    slot_display_name,
    validate_weekly_lineup,
    waiver_filter_for_slot_label,
)


def _slot_widget_keys(slots: list[str]) -> list[tuple[str, str]]:
    """Return (widget_key, display_label) for each lineup slot."""
    counts: dict[str, int] = {}
    keys: list[tuple[str, str]] = []
    for slot in slots:
        base = str(slot or "").strip().upper()
        count = counts.get(base, 0) + 1
        counts[base] = count
        key = base if count == 1 else f"{base}_{count}"
        if count == 1:
            label = slot_display_name(base)
        elif base == "UTIL":
            label = f"Utility ({count})"
        else:
            label = f"{slot_display_name(base)} ({count})"
        keys.append((key, label))
    return keys


def _read_slot_assignments(
    session: dict[str, Any],
    slot_keys: list[tuple[str, str]],
    *,
    prefix: str,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, _label in slot_keys:
        widget_key = f"{prefix}_{key}"
        out[key] = str(session.get(widget_key) or "").strip()
    return out


def render_weekly_lineup_section(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: pd.DataFrame,
    lineup_team: str,
    on_open_waiver_wire: Callable[[str], None] | None = None,
) -> None:
    """Weekly lineup builder for the active team only."""
    context = get_active_league_context(session)
    if not context:
        st.info("Set an **Active Draft** to manage weekly lineups.")
        return

    my_team = str(context.get("my_team_name") or "").strip()
    active_team = str(lineup_team or my_team or "").strip()
    if my_team and active_team and my_team != active_team:
        st.info(f"Weekly lineups are available for your active team (**{my_team}**) only.")
        return

    if team_roster is None or team_roster.empty:
        st.warning("Load roster stats to assign a weekly lineup.")
        return

    slots = resolve_weekly_lineup_slots(context)
    slot_keys = _slot_widget_keys(slots)
    week_options = list_week_options()
    prefix = "weekly_lineup"

    st.markdown("##### Weekly Lineup Management")
    save_flash = session.pop("weekly_lineup_save_flash", None)
    if isinstance(save_flash, dict):
        st.success(
            "✅ **Weekly Lineup Saved**\n\n"
            f"Saved for:\n"
            f"- **Team:** {save_flash.get('team') or active_team or '—'}\n"
            f"- **Week:** {save_flash.get('week') or '—'}\n"
            f"- **Time:** {save_flash.get('time') or '—'}"
        )
    st.caption(
        "Assign your active-team starters by week. Saved lineups persist to your **Active Draft**, "
        "league context, cloud, and disk — and restore after refresh or reboot."
    )

    week_cols = st.columns([2, 3])
    with week_cols[0]:
        selected_week = st.selectbox(
            "Fantasy week",
            week_options,
            format_func=week_label,
            key=f"{prefix}_selected_week",
        )
    with week_cols[1]:
        st.caption(
            f"**Slots:** {', '.join(label for _k, label in slot_keys)} · "
            f"**Team:** {active_team or '—'}"
        )

    saved = get_saved_weekly_lineup(context, int(selected_week))
    if saved and saved.get("assignments"):
        saved_assignments = dict(saved.get("assignments") or {})
        for key, _label in slot_keys:
            widget_key = f"{prefix}_{key}"
            if widget_key not in session and key in saved_assignments:
                session[widget_key] = saved_assignments.get(key) or ""

    assignment_cols = st.columns(2)
    midpoint = (len(slot_keys) + 1) // 2
    for col_idx, chunk in enumerate((slot_keys[:midpoint], slot_keys[midpoint:])):
        with assignment_cols[col_idx]:
            for key, label in chunk:
                base_slot = key.split("_", 1)[0]
                options = [""] + eligible_players_for_slot(team_roster, base_slot)
                st.selectbox(
                    label,
                    options,
                    key=f"{prefix}_{key}",
                    format_func=lambda name, slot_label=label: f"Select {slot_label}…" if not name else name,
                )

    assignments = _read_slot_assignments(session, slot_keys, prefix=prefix)
    validation = validate_weekly_lineup(slots, assignments, team_roster)
    summary = build_lineup_summary(slots, assignments, team_roster)

    if validation.get("messages"):
        for message in validation.get("messages") or []:
            lower = str(message).lower()
            if "empty" in lower or "not eligible" in lower or "twice" in lower:
                st.warning(message)
            else:
                st.info(message)

    open_slots = list(summary.get("open_slots") or [])
    if open_slots and on_open_waiver_wire is not None:
        waiver_cols = st.columns(min(3, len(open_slots)))
        for idx, slot_label in enumerate(open_slots[:3]):
            with waiver_cols[idx % len(waiver_cols)]:
                st.button(
                    f"Open Waiver Wire for {slot_label}",
                    key=f"{prefix}_waiver_open_{slot_label}_{selected_week}_{idx}",
                    on_click=on_open_waiver_wire,
                    args=(slot_label,),
                )

    st.markdown("**Team summary**")
    summary_cols = st.columns(3)
    with summary_cols[0]:
        st.caption("**Starting lineup**")
        starters = summary.get("starters") or []
        if starters:
            for line in starters:
                st.write(line)
        else:
            st.caption("No starters assigned yet.")
    with summary_cols[1]:
        st.caption("**Bench**")
        bench = summary.get("bench") or []
        if bench:
            st.caption(", ".join(bench))
        else:
            st.caption("All roster players are starting.")
    with summary_cols[2]:
        st.caption("**Open slots**")
        if open_slots:
            st.caption(", ".join(open_slots))
        else:
            st.caption("All lineup slots filled.")

    totals = compute_weekly_starter_totals(team_roster, assignments)
    starter_rows = totals.get("starters") or []
    if starter_rows:
        st.markdown("**Current starter production (season-to-date)**")
        st.dataframe(pd.DataFrame(starter_rows), use_container_width=True, hide_index=True)
        total_bits = []
        for cat in ROTO_STARTER_CATEGORIES:
            val = (totals.get("totals") or {}).get(cat)
            if val is None:
                continue
            if cat == "AVG":
                total_bits.append(f"**{cat}** {val:.3f}")
            else:
                total_bits.append(f"**{cat}** {val:g}")
        if total_bits:
            st.caption("Starter totals · " + " · ".join(total_bits))

    save_col, status_col = st.columns([1, 2])
    with save_col:
        if st.button("Save Weekly Lineup", key=f"{prefix}_save_btn", type="primary"):
            save_result = save_weekly_lineup(
                session,
                week=int(selected_week),
                slots=slots,
                assignments=assignments,
                my_team=active_team,
                roster_df=team_roster,
            )
            if save_result.get("ok"):
                now = datetime.now().astimezone()
                session["weekly_lineup_save_flash"] = {
                    "team": active_team,
                    "week": int(selected_week),
                    "time": now.strftime("%I:%M %p").lstrip("0"),
                }
                st.rerun()
            else:
                for err in save_result.get("errors") or []:
                    st.error(str(err))

    with status_col:
        if saved:
            saved_at = str(saved.get("saved_at") or "").strip()
            if saved_at:
                st.caption(f"Last saved: {saved_at[:19].replace('T', ' ')} UTC")
