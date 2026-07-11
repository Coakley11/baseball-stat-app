"""Streamlit UI for weekly lineup management — roster board redesign."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_lineup_ui import (
    build_slot_key_labels,
    build_team_header_model,
    emit_html_block,
    inject_lineup_board_styles,
    render_action_metrics_html,
    render_roster_board_html,
    render_team_header_html,
    slot_key_labels_as_tuples,
)
from fantasy_weekly_lineup import (
    ROTO_STARTER_CATEGORIES,
    build_lineup_summary,
    compute_weekly_starter_totals,
    eligible_players_for_slot,
    get_saved_weekly_lineup,
    list_week_options,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
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
    slot_validation_styles,
)


def _slot_widget_keys(slots: list[str]) -> list[tuple[str, str]]:
    return slot_key_labels_as_tuples(build_slot_key_labels(slots))


def canonical_week_key(prefix: str, week: int) -> str:
    """Session key holding the single canonical assignment dict for a week."""
    return f"{prefix}_canon_{int(week)}"


def assignment_signature(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Order-independent, normalized signature used to detect real changes."""
    return tuple(
        (key, str((assignments or {}).get(key) or "").strip()) for key, _label in slot_keys
    )


def _normalize_assignments(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
) -> dict[str, str]:
    return {key: str((assignments or {}).get(key) or "").strip() for key, _label in slot_keys}


def ensure_canonical_assignments(
    session: dict[str, Any],
    *,
    canon_key: str,
    slot_keys: list[tuple[str, str]],
    saved_assignments: dict[str, str],
) -> dict[str, str]:
    """Return the canonical per-week assignments, hydrating from saved on first use."""
    current = session.get(canon_key)
    if not isinstance(current, dict):
        session[canon_key] = _normalize_assignments(saved_assignments, slot_keys)
    else:
        for key, _label in slot_keys:
            current.setdefault(key, "")
    return dict(session[canon_key])


def reconcile_editor_assignments(
    session: dict[str, Any],
    *,
    canon_key: str,
    slot_keys: list[tuple[str, str]],
    new_assignments: dict[str, str],
) -> bool:
    """Persist editor output to canonical state. Return True when it changed.

    Comparing normalized signatures keeps a guarded, single rerun (no loop):
    once canonical equals the editor output, subsequent runs are no-ops.
    """
    current = session.get(canon_key) or {}
    if assignment_signature(new_assignments, slot_keys) != assignment_signature(current, slot_keys):
        session[canon_key] = _normalize_assignments(new_assignments, slot_keys)
        return True
    return False


def _render_roster_board(
    st: Any,
    *,
    slot_labels: list,
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
    scored_roster: pd.DataFrame | None,
    validation_styles: dict[str, str] | None = None,
) -> None:
    emit_html_block(
        st,
        render_roster_board_html(
            slot_labels,
            assignments,
            team_roster,
            scored_roster=scored_roster,
            validation_styles=validation_styles,
        ),
    )


def _render_classic_dropdown_builder(
    st: Any,
    session: dict[str, Any],
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    team_roster: pd.DataFrame,
    selected_week: int,
    assignments: dict[str, str],
) -> dict[str, str]:
    st.caption("Assign starters using dropdowns — same lineup data as drag-and-drop.")
    assignment_cols = st.columns(2)
    midpoint = (len(slot_keys) + 1) // 2
    new_assignments: dict[str, str] = {}
    for col_idx, chunk in enumerate((slot_keys[:midpoint], slot_keys[midpoint:])):
        with assignment_cols[col_idx]:
            for key, label in chunk:
                base_slot = key.split("_", 1)[0]
                options = [""] + eligible_players_for_slot(team_roster, base_slot)
                # Dropdown widgets use their own per-week keys so they never
                # clobber the canonical assignment state. Seed once from canonical.
                widget_key = f"{prefix}_dd_{int(selected_week)}_{key}"
                if widget_key not in session:
                    seed = str(assignments.get(key) or "").strip()
                    session[widget_key] = seed if seed in options else ""
                chosen = st.selectbox(
                    label,
                    options,
                    key=widget_key,
                    format_func=lambda name, slot_label=label: f"Select {slot_label}…" if not name else name,
                )
                new_assignments[key] = str(chosen or "").strip()
    return new_assignments


def _render_drag_drop_builder(
    st: Any,
    *,
    prefix: str,
    slot_keys: list[tuple[str, str]],
    team_roster: pd.DataFrame,
    selected_week: int,
    assignments: dict[str, str],
) -> dict[str, str]:
    try:
        from streamlit_sortables import sort_items
    except ImportError:
        st.warning(
            "Drag-and-drop requires **streamlit-sortables**. Install it or switch to **Classic Dropdowns**."
        )
        return assignments

    containers = build_sortable_containers(slot_keys, assignments, team_roster)
    sort_key = f"{prefix}_sortable_{int(selected_week)}"
    st.caption(
        "Drag players between **lineup slots** and **Bench** — on phones, "
        "**touch-and-hold** a card for a moment, then drag. The roster board "
        "above refreshes after each change."
    )
    sorted_containers = sort_items(
        containers,
        multi_containers=True,
        direction="vertical",
        custom_style=dnd_custom_style(),
        key=sort_key,
    )
    new_assignments = assignments_from_sortable_containers(sorted_containers, slot_keys, team_roster)

    styles = slot_validation_styles(slot_keys, new_assignments, team_roster)
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

    emit_html_block(st, render_action_metrics_html(validation=validation, summary=summary))

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

    totals = compute_weekly_starter_totals(team_roster, assignments)
    starter_rows = totals.get("starters") or []
    if starter_rows:
        with st.expander("Current starter production (season-to-date)", expanded=False):
            st.dataframe(pd.DataFrame(starter_rows), width="stretch", hide_index=True)
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

    inject_lineup_board_styles(st)

    slots = resolve_weekly_lineup_slots(context)
    slot_labels = build_slot_key_labels(slots)
    slot_keys = slot_key_labels_as_tuples(slot_labels)
    week_options = list_week_options()
    prefix = "weekly_lineup"

    save_flash = session.pop("weekly_lineup_save_flash", None)
    if isinstance(save_flash, dict):
        st.success(
            "✅ **Weekly Lineup Saved**\n\n"
            f"Saved for:\n"
            f"- **Team:** {save_flash.get('team') or active_team or '—'}\n"
            f"- **Week:** {save_flash.get('week') or '—'}\n"
            f"- **Time:** {save_flash.get('time') or '—'}"
        )

    if f"{prefix}_selected_week" not in session:
        session[f"{prefix}_selected_week"] = week_options[0]

    st.markdown("### Weekly Lineup Management")
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
            "Saved lineups persist to your active draft, league context, cloud, and disk."
        )

    saved = get_saved_weekly_lineup(context, int(selected_week))
    saved_assignments = dict((saved or {}).get("assignments") or {})
    canon_key = canonical_week_key(prefix, int(selected_week))
    assignments = ensure_canonical_assignments(
        session,
        canon_key=canon_key,
        slot_keys=slot_keys,
        saved_assignments=saved_assignments,
    )

    header_model = build_team_header_model(
        context=context,
        team_name=active_team,
        week=int(selected_week),
        roster_df=team_roster,
        slot_labels=slot_labels,
        assignments=assignments,
        saved=saved,
    )
    emit_html_block(st, render_team_header_html(header_model))

    validation_styles = slot_validation_styles(slot_keys, assignments, team_roster)
    _render_roster_board(
        st,
        slot_labels=slot_labels,
        assignments=assignments,
        team_roster=team_roster,
        scored_roster=scored_roster,
        validation_styles=validation_styles,
    )

    st.markdown("#### Edit lineup")
    st.caption("Use the editor below to change starters. The roster board above updates after each edit.")

    if f"{prefix}_editor_mode" not in session:
        session[f"{prefix}_editor_mode"] = DEFAULT_WEEKLY_LINEUP_EDITOR_MODE

    editor_mode = st.radio(
        "Lineup editor mode",
        list(WEEKLY_LINEUP_EDITOR_MODES),
        horizontal=True,
        key=f"{prefix}_editor_mode",
        help="Drag & Drop works on desktop and touch devices. Classic Dropdowns is a reliable fallback.",
    )

    if editor_mode == "Drag & Drop":
        new_assignments = _render_drag_drop_builder(
            st,
            prefix=prefix,
            slot_keys=slot_keys,
            team_roster=team_roster,
            selected_week=int(selected_week),
            assignments=assignments,
        )
        st.caption(
            "Drag-and-drop not working on your device? Switch to **Classic Dropdowns** above."
        )
    else:
        new_assignments = _render_classic_dropdown_builder(
            st,
            session,
            prefix=prefix,
            slot_keys=slot_keys,
            team_roster=team_roster,
            selected_week=int(selected_week),
            assignments=assignments,
        )

    # Persist editor output to the single canonical per-week state and refresh the
    # board above via one guarded rerun (no loop: signatures match after update).
    if reconcile_editor_assignments(
        session,
        canon_key=canon_key,
        slot_keys=slot_keys,
        new_assignments=new_assignments,
    ):
        st.rerun()
    assignments = _normalize_assignments(new_assignments, slot_keys)

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
        if st.button("Reset unsaved changes", key=f"{prefix}_reset_btn"):
            session[canon_key] = _normalize_assignments(saved_assignments, slot_keys)
            for key, _label in slot_keys:
                session.pop(f"{prefix}_dd_{int(selected_week)}_{key}", None)
            st.rerun()

    with status_col:
        if saved:
            saved_at = str(saved.get("saved_at") or "").strip()
            if saved_at:
                st.caption(f"Last saved: {saved_at[:19].replace('T', ' ')} UTC")
