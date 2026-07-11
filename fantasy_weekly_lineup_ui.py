"""Streamlit UI for weekly lineup management — circular face-to-circle board."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_lineup_interactive_board import (
    apply_board_drop,
    build_interactive_board_payload,
    parse_board_drop_result,
    render_interactive_lineup_board,
)
from fantasy_lineup_ui import (
    build_slot_key_labels,
    build_team_header_model,
    emit_html_block,
    inject_lineup_board_styles,
    render_team_header_html,
    slot_key_labels_as_tuples,
)
from fantasy_weekly_lineup import (
    get_saved_weekly_lineup,
    list_week_options,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    validate_weekly_lineup,
    week_label,
)


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
    """Persist editor output to canonical state. Return True when it changed."""
    current = session.get(canon_key) or {}
    if assignment_signature(new_assignments, slot_keys) != assignment_signature(current, slot_keys):
        session[canon_key] = _normalize_assignments(new_assignments, slot_keys)
        return True
    return False


def _render_simple_validation(
    st: Any,
    *,
    slots: list[str],
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
) -> dict[str, Any]:
    validation = validate_weekly_lineup(slots, assignments, team_roster)
    if validation.get("messages"):
        for message in validation.get("messages") or []:
            lower = str(message).lower()
            if "empty" in lower or "not eligible" in lower or "twice" in lower:
                st.warning(message)
            else:
                st.info(message)
    return validation


def render_weekly_lineup_section(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: pd.DataFrame,
    lineup_team: str,
    on_open_waiver_wire: Callable[[str], None] | None = None,
    scored_roster: pd.DataFrame | None = None,
) -> None:
    """Weekly lineup builder — one circular face-to-circle interaction."""
    del on_open_waiver_wire, scored_roster  # board-only UI; persistence unchanged

    context = get_active_league_context(session)
    if not context:
        st.info("Set an **Active Draft** to manage your weekly lineup.")
        return

    my_team = str(context.get("my_team_name") or "").strip()
    active_team = str(lineup_team or my_team or "").strip()
    if my_team and active_team and my_team != active_team:
        st.info(f"Weekly lineups are available for your team (**{my_team}**) only.")
        return

    if team_roster is None or team_roster.empty:
        st.warning("Load roster stats to set your weekly lineup.")
        return

    inject_lineup_board_styles(st)

    slots = resolve_weekly_lineup_slots(context)
    slot_labels = build_slot_key_labels(slots)
    slot_keys = slot_key_labels_as_tuples(slot_labels)
    week_options = list_week_options()
    prefix = "weekly_lineup"

    save_flash = session.pop("weekly_lineup_save_flash", None)
    if isinstance(save_flash, dict):
        st.success("Lineup saved.")

    if f"{prefix}_selected_week" not in session:
        session[f"{prefix}_selected_week"] = week_options[0]

    week_cols = st.columns([2, 3])
    with week_cols[0]:
        selected_week = st.selectbox(
            "Week",
            week_options,
            format_func=week_label,
            key=f"{prefix}_selected_week",
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

    board_payload = build_interactive_board_payload(slot_labels, assignments, team_roster)
    board_result = render_interactive_lineup_board(
        st,
        payload=board_payload,
        component_key=f"{prefix}_circle_board_{int(selected_week)}",
    )
    drop_event = parse_board_drop_result(board_result)
    if drop_event:
        player = str(drop_event.get("player") or "").strip()
        target = str(drop_event.get("target") or "").strip()
        new_assignments = apply_board_drop(
            assignments,
            slot_keys,
            player=player,
            target=target,
            roster_df=team_roster,
        )
        if reconcile_editor_assignments(
            session,
            canon_key=canon_key,
            slot_keys=slot_keys,
            new_assignments=new_assignments,
        ):
            st.rerun()
        assignments = new_assignments

    validation = _render_simple_validation(
        st,
        slots=slots,
        assignments=assignments,
        team_roster=team_roster,
    )

    save_col, _reset_col = st.columns(2)
    with save_col:
        save_disabled = not validation.get("ok")
        if st.button(
            "Save Lineup",
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
                session["weekly_lineup_save_flash"] = {"team": active_team, "week": int(selected_week)}
                st.rerun()
            else:
                st.error("Couldn't save changes. Try again.")
        elif save_disabled:
            st.caption("Complete your lineup before saving.")
    with _reset_col:
        if st.button("Reset", key=f"{prefix}_reset_btn"):
            session[canon_key] = _normalize_assignments(saved_assignments, slot_keys)
            st.rerun()
