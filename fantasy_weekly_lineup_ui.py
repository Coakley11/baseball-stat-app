"""Streamlit UI for weekly lineup management — circular face-to-circle board."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from fantasy_league_context import get_active_league_context
from fantasy_lineup_interactive_board import (
    apply_drop_event,
    build_interactive_board_payload,
    parse_board_drop_result,
    render_interactive_lineup_board,
)
from fantasy_lineup_ui import (
    SlotKeyLabel,
    build_slot_key_labels,
    build_team_header_model,
    emit_html_block,
    inject_lineup_board_styles,
    render_team_header_html,
    slot_key_labels_as_tuples,
)
from fantasy_league_lineup_format import hydrate_lineup_format_from_shared
from fantasy_league_lineup_format_ui import (
    render_edit_lineup_format_action,
    render_lineup_format_setup,
)
from fantasy_weekly_lineup import (
    _lineup_storage_context,
    get_saved_weekly_lineup,
    is_lineup_locked,
    list_week_options,
    persist_weekly_lineup_draft,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    slot_display_name,
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
    saved_norm = _normalize_assignments(saved_assignments, slot_keys)
    current = session.get(canon_key)
    if not isinstance(current, dict):
        session[canon_key] = dict(saved_norm)
    else:
        current_norm = _normalize_assignments(current, slot_keys)
        if any(saved_norm.values()) and not any(current_norm.values()):
            session[canon_key] = dict(saved_norm)
        else:
            for key, _label in slot_keys:
                current_norm.setdefault(key, "")
            session[canon_key] = current_norm
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


def _waiver_slot_label_for_open_prompt(slot_label: SlotKeyLabel) -> str:
    """Display label passed to Waiver Wire position filter."""
    if slot_label.base_slot == "OF":
        return "Outfield"
    return slot_display_name(slot_label.base_slot)


def build_open_slot_prompts(
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
) -> list[dict[str, str]]:
    """Compact open-slot rows from current canonical assignments only."""
    open_slots = [
        label
        for label in slot_labels
        if not str(assignments.get(label.key) or "").strip()
    ]
    if not open_slots:
        return []

    rows: list[dict[str, str]] = []
    of_labels = [label for label in open_slots if label.base_slot == "OF"]
    other_labels = [label for label in open_slots if label.base_slot != "OF"]

    for label in other_labels:
        rows.append(
            {
                "text": f"{label.label} is empty",
                "waiver_label": _waiver_slot_label_for_open_prompt(label),
            }
        )

    if len(of_labels) == 1:
        rows.append({"text": f"{of_labels[0].label} is empty", "waiver_label": "Outfield"})
    elif len(of_labels) > 1:
        rows.append(
            {
                "text": f"{len(of_labels)} Outfield spots are empty",
                "waiver_label": "Outfield",
            }
        )
    return rows


def _inject_open_slots_styles(st: Any) -> None:
    emit_html_block(
        st,
        """
<style>
.fl-open-slots-wrap { margin: 2px 0 6px 0; }
.fl-open-slots-wrap [data-testid="column"] { padding-top: 0.15rem; padding-bottom: 0.15rem; }
.fl-open-slots-wrap p { margin: 0; line-height: 1.35; font-size: 0.92rem; }
</style>
<div class="fl-open-slots-wrap"></div>
""",
    )


def _render_open_slots_and_validation(
    st: Any,
    *,
    slots: list[str],
    slot_labels: list[SlotKeyLabel],
    assignments: dict[str, str],
    team_roster: pd.DataFrame,
    on_open_waiver_wire: Callable[[str], None] | None,
    prefix: str,
    selected_week: int,
) -> dict[str, Any]:
    validation = validate_weekly_lineup(slots, assignments, team_roster)

    # Show only non-empty-slot issues from validate (duplicate, ineligible, roster).
    for message in validation.get("messages") or []:
        lower = str(message).lower()
        if " is empty" in lower:
            continue
        if "need eligible" in lower and "waiver wire" in lower:
            continue
        if "empty" in lower or "not eligible" in lower or "twice" in lower:
            st.warning(message)
        else:
            st.info(message)

    open_rows = build_open_slot_prompts(slot_labels, assignments)
    if open_rows:
        _inject_open_slots_styles(st)
        for idx, row in enumerate(open_rows):
            text_col, btn_col = st.columns([5, 2], gap="small")
            with text_col:
                st.markdown(f"**{row['text']}**")
            with btn_col:
                if on_open_waiver_wire is not None:
                    st.button(
                        "Open Waiver Wire",
                        key=f"{prefix}_waiver_{row['waiver_label']}_{idx}_{int(selected_week)}",
                        on_click=on_open_waiver_wire,
                        args=(row["waiver_label"],),
                    )

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
    del scored_roster

    context = get_active_league_context(session)
    if not context:
        st.info("Set an **Active Draft** to manage your weekly lineup.")
        return

    storage_context = _lineup_storage_context(session) or context
    try:
        from fantasy_league_identity import resolve_canonical_league_id
        from fantasy_shared_league_store import sync_context_with_shared_store

        if resolve_canonical_league_id(storage_context):
            storage_context = sync_context_with_shared_store(session, storage_context)
            hydrate_lineup_format_from_shared(session, storage_context)
            context = get_active_league_context(session) or storage_context
    except ImportError:
        pass

    my_team = str(context.get("my_team_name") or "").strip()
    active_team = str(lineup_team or my_team or "").strip()
    if my_team and active_team and my_team != active_team:
        st.info(f"Weekly lineups are available for your team (**{my_team}**) only.")
        return

    if team_roster is None or team_roster.empty:
        st.warning("Load roster stats to set your weekly lineup.")
        return

    if session.pop("lineup_format_saved_flash", None):
        st.success("League lineup format saved.")

    editing_format = bool(session.get("lineup_format_editing"))
    if editing_format:
        render_lineup_format_setup(st, session, team_roster=team_roster, editing=True)
        return
    if not render_lineup_format_setup(st, session, team_roster=team_roster):
        return

    render_edit_lineup_format_action(st, session)

    inject_lineup_board_styles(st)

    slots = resolve_weekly_lineup_slots(context)
    if not slots:
        st.info("League starting positions are not configured yet.")
        return
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

    saved = get_saved_weekly_lineup(context, int(selected_week), team=active_team, session=session)
    saved_assignments = dict((saved or {}).get("assignments") or {})
    lineup_locked = is_lineup_locked(context, int(selected_week), team=active_team, session=session)
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

    if lineup_locked:
        st.info(f"Lineup locked for {week_label(int(selected_week))}")

    board_payload = build_interactive_board_payload(
        slot_labels,
        assignments,
        team_roster,
        editable=not lineup_locked,
    )
    board_nonce_key = f"{prefix}_board_nonce_{int(selected_week)}"
    board_nonce = int(session.get(board_nonce_key, 0))
    component_key = f"{prefix}_circle_board_{int(selected_week)}_{board_nonce}"
    board_result = render_interactive_lineup_board(
        st,
        payload=board_payload,
        component_key=component_key,
    )
    drop_event = parse_board_drop_result(board_result)
    if drop_event and not lineup_locked:
        new_assignments = apply_drop_event(
            assignments,
            slot_keys,
            drop_event,
            roster_df=team_roster,
        )
        if new_assignments is not None and reconcile_editor_assignments(
            session,
            canon_key=canon_key,
            slot_keys=slot_keys,
            new_assignments=new_assignments,
        ):
            persist_weekly_lineup_draft(
                session,
                week=int(selected_week),
                slots=slots,
                assignments=new_assignments,
                my_team=active_team,
                roster_df=team_roster,
            )
            session[board_nonce_key] = board_nonce + 1
            st.rerun()
        elif new_assignments is not None:
            assignments = new_assignments

    validation = _render_open_slots_and_validation(
        st,
        slots=slots,
        slot_labels=slot_labels,
        assignments=assignments,
        team_roster=team_roster,
        on_open_waiver_wire=on_open_waiver_wire if not lineup_locked else None,
        prefix=prefix,
        selected_week=int(selected_week),
    )

    if lineup_locked:
        return

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
            session[board_nonce_key] = board_nonce + 1
            st.rerun()
