"""Streamlit UI for weekly lineup management (Phase 1 + Phase 2 drag-and-drop)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_weekly_lineup import (
    ROTO_STARTER_CATEGORIES,
    _player_name_col,
    build_lineup_summary,
    compute_weekly_starter_totals,
    eligible_players_for_slot,
    get_saved_weekly_lineup,
    list_week_options,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    slot_display_name,
    validate_weekly_lineup,
    week_label,
    waiver_filter_for_slot_label,
)
from fantasy_weekly_lineup_dnd import (
    DEFAULT_WEEKLY_LINEUP_EDITOR_MODE,
    WEEKLY_LINEUP_EDITOR_MODES,
    assignments_from_sortable_containers,
    build_sortable_containers,
    dnd_custom_style,
    player_card_caption,
    recommendation_lookup,
    slot_validation_styles,
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


def _hydrate_assignments_from_saved(
    session: dict[str, Any],
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    saved_assignments: dict[str, str],
) -> None:
    for key, _label in slot_keys:
        widget_key = f"{prefix}_{key}"
        if widget_key not in session and key in saved_assignments:
            session[widget_key] = saved_assignments.get(key) or ""


def _sync_dropdown_assignments_to_session(
    session: dict[str, Any],
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    assignments: dict[str, str],
) -> None:
    for key, _label in slot_keys:
        session[f"{prefix}_{key}"] = assignments.get(key) or ""


def _render_player_headshots(
    st: Any,
    roster_df: pd.DataFrame,
    player_names: list[str],
    *,
    key_prefix: str,
) -> None:
    if not player_names:
        return
    try:
        from player_photos import get_player_photo_info, inject_player_photo_styles, render_rec_card_photo_html

        inject_player_photo_styles(st)
        name_col = _player_name_col(roster_df)
        lookup = {
            str(row[name_col]).strip(): row
            for _, row in roster_df.iterrows()
            if str(row.get(name_col) or "").strip()
        }
        cells: list[str] = []
        for name in player_names[:12]:
            row = lookup.get(name)
            photo_info = get_player_photo_info(full_name=name, row=row, use_api=True)
            photo_html = render_rec_card_photo_html(photo_info, alt=name)
            cells.append(
                f'<div style="text-align:center;min-width:56px;">{photo_html}'
                f'<div style="font-size:0.68rem;font-weight:600;">{name.split()[-1] if name else ""}</div></div>'
            )
        if cells:
            st.markdown(
                f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 10px;">{"".join(cells)}</div>',
                unsafe_allow_html=True,
            )
    except ImportError:
        pass


def _render_classic_dropdown_builder(
    st: Any,
    session: dict[str, Any],
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    team_roster: pd.DataFrame,
) -> dict[str, str]:
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
    return _read_slot_assignments(session, slot_keys, prefix=prefix)


def _render_drag_drop_builder(
    st: Any,
    session: dict[str, Any],
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    team_roster: pd.DataFrame,
    selected_week: int,
    assignments: dict[str, str],
    scored_roster: pd.DataFrame | None,
) -> dict[str, str]:
    try:
        from streamlit_sortables import sort_items
    except ImportError:
        st.warning(
            "Drag-and-drop requires **streamlit-sortables**. Install it or switch to **Classic Dropdowns**."
        )
        return assignments

    rec_map = recommendation_lookup(scored_roster)
    name_col = _player_name_col(team_roster)
    row_lookup = {
        str(row[name_col]).strip(): row for _, row in team_roster.iterrows() if str(row.get(name_col) or "").strip()
    }

    starter_names = [assignments.get(key) for key, _ in slot_keys if assignments.get(key)]
    if starter_names:
        st.caption("**Starting lineup headshots**")
        _render_player_headshots(st, team_roster, starter_names, key_prefix=f"{prefix}_starters")

    containers = build_sortable_containers(slot_keys, assignments, team_roster)
    sort_key = f"{prefix}_sortable_{selected_week}"
    sorted_containers = sort_items(
        containers,
        multi_containers=True,
        custom_style=dnd_custom_style(),
        key=sort_key,
    )
    new_assignments = assignments_from_sortable_containers(sorted_containers, slot_keys, team_roster)
    _sync_dropdown_assignments_to_session(
        session,
        prefix=prefix,
        slot_keys=slot_keys,
        assignments=new_assignments,
    )

    styles = slot_validation_styles(slot_keys, new_assignments, team_roster)
    st.caption("Drag players between **lineup slots** and **Bench**. Each player can start in one slot only.")
    status_bits = []
    for key, label in slot_keys:
        state = styles.get(key, "empty")
        player = new_assignments.get(key) or "—"
        if state == "valid":
            status_bits.append(f"🟢 **{label}:** {player}")
        elif state == "invalid":
            status_bits.append(f"🔴 **{label}:** {player}")
        else:
            status_bits.append(f"⚪ **{label}:** empty")
    if status_bits:
        st.markdown(" · ".join(status_bits))

    bench_names = [
        name
        for name in sorted(row_lookup.keys())
        if name not in {new_assignments.get(k) for k, _ in slot_keys if new_assignments.get(k)}
    ]
    if bench_names:
        st.markdown("##### Bench / Available Players")
        _render_player_headshots(st, team_roster, bench_names[:9], key_prefix=f"{prefix}_bench")
        for name in bench_names:
            row = row_lookup.get(name)
            if row is None:
                continue
            st.markdown(f"**{name}** — {player_card_caption(row, recommendation=rec_map.get(name, ''))}")

    return new_assignments


def _render_validation_and_summary(
    st: Any,
    *,
    slots: list[str],
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
    on_open_waiver_wire: Callable[[str], None] | None,
    prefix: str,
    selected_week: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validation = validate_weekly_lineup(slots, assignments, team_roster)
    summary = build_lineup_summary(slots, assignments, team_roster)

    if validation.get("messages"):
        st.markdown("**Validation**")
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

    return validation, summary


def render_weekly_lineup_section(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: pd.DataFrame,
    lineup_team: str,
    on_open_waiver_wire: Callable[[str], None] | None = None,
    scored_roster: pd.DataFrame | None = None,
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

    if f"{prefix}_editor_mode" not in session:
        session[f"{prefix}_editor_mode"] = DEFAULT_WEEKLY_LINEUP_EDITOR_MODE

    editor_mode = st.radio(
        "Lineup editor mode",
        list(WEEKLY_LINEUP_EDITOR_MODES),
        horizontal=True,
        key=f"{prefix}_editor_mode",
        help="Drag & Drop on desktop; Classic Dropdowns works better on mobile.",
    )

    saved = get_saved_weekly_lineup(context, int(selected_week))
    saved_assignments = dict((saved or {}).get("assignments") or {})
    hydrate_key = f"{prefix}_hydrated_week"
    if session.get(hydrate_key) != selected_week:
        if saved_assignments:
            _hydrate_assignments_from_saved(
                session,
                prefix=prefix,
                slot_keys=slot_keys,
                saved_assignments=saved_assignments,
            )
        session[hydrate_key] = selected_week

    assignments = _read_slot_assignments(session, slot_keys, prefix=prefix)

    if editor_mode == "Drag & Drop":
        st.markdown("**Starting Lineup** — drag players into slots")
        assignments = _render_drag_drop_builder(
            st,
            session,
            prefix=prefix,
            slot_keys=slot_keys,
            team_roster=team_roster,
            selected_week=int(selected_week),
            assignments=assignments,
            scored_roster=scored_roster,
        )
        with st.expander("Mobile / fallback: Classic Dropdowns", expanded=False):
            st.caption("Use dropdowns if drag-and-drop is awkward on your device.")
            dropdown_assignments = _render_classic_dropdown_builder(
                st,
                session,
                prefix=prefix,
                slot_keys=slot_keys,
                team_roster=team_roster,
            )
            if any(dropdown_assignments.values()):
                assignments = dropdown_assignments
    else:
        assignments = _render_classic_dropdown_builder(
            st,
            session,
            prefix=prefix,
            slot_keys=slot_keys,
            team_roster=team_roster,
        )

    validation, _summary = _render_validation_and_summary(
        st,
        slots=slots,
        assignments=assignments,
        team_roster=team_roster,
        on_open_waiver_wire=on_open_waiver_wire,
        prefix=prefix,
        selected_week=int(selected_week),
    )

    save_col, status_col = st.columns([1, 2])
    with save_col:
        save_disabled = not validation.get("ok")
        if st.button(
            "Save Weekly Lineup",
            key=f"{prefix}_save_btn",
            type="primary",
            disabled=bool(save_disabled),
        ):
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
        if save_disabled:
            st.caption("Fix validation issues above before saving.")

    with status_col:
        if saved:
            saved_at = str(saved.get("saved_at") or "").strip()
            if saved_at:
                st.caption(f"Last saved: {saved_at[:19].replace('T', ' ')} UTC")
