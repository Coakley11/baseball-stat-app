"""Commissioner UI for league lineup format setup."""

from __future__ import annotations

from typing import Any

from fantasy_league_lineup_format import (
    PICKABLE_POSITIONS,
    clear_saved_lineup_assignments_for_format_change,
    configuration_source_for_context,
    detect_roster_size_hint,
    expand_position_picks,
    is_lineup_format_commissioner,
    lineup_format_block,
    needs_lineup_format_setup,
    resolve_lineup_page_context,
    save_league_lineup_format,
)
from fantasy_lineup_ui import build_slot_key_labels, emit_html_block, inject_lineup_board_styles


def _preview_circle_html(slots: list[str]) -> str:
    labels = build_slot_key_labels(slots)
    circles = "".join(
        f'<div class="fl-slot-circle fl-slot-empty" style="margin:6px;">'
        f'<span class="fl-slot-label">{label.label}</span></div>'
        for label in labels
    )
    return f'<div class="fl-lineup-board" style="justify-content:center;flex-wrap:wrap;">{circles}</div>'


def render_lineup_format_setup(
    st: Any,
    session: dict[str, Any],
    *,
    team_roster: Any,
    editing: bool = False,
) -> bool:
    """Render commissioner setup. Return True when format is ready (saved or already set)."""
    from fantasy_league_context import get_active_league_context

    context = resolve_lineup_page_context(session)
    if not context:
        return False

    if not editing and not needs_lineup_format_setup(context):
        return True

    if not is_lineup_format_commissioner(session, context):
        block = lineup_format_block(context)
        if block:
            slots = list(block.get("lineup_slots") or [])
            st.caption("League lineup format (commissioner configured).")
            inject_lineup_board_styles(st)
            emit_html_block(st, _preview_circle_html(slots))
        else:
            st.info("The league commissioner must choose starting positions before lineups are available.")
        return False

    suggested, team_counts = detect_roster_size_hint(context, team_roster)
    st.subheader("Choose Lineup Positions")
    st.markdown("Choose the starting positions every team must fill.")

    if team_counts:
        parts = [f"**{name}**: {count} players" for name, count in sorted(team_counts.items())]
        st.caption("Detected roster sizes — " + " · ".join(parts))
    st.markdown(f"**Detected roster size:** {suggested} players per team")
    st.caption(
        "Required starting positions cannot exceed the drafted roster size. "
        "Extra drafted players remain on the bench. Roster corrections use Waiver Wire — not a second draft."
    )

    pick_labels = [label for _code, label in PICKABLE_POSITIONS]
    pick_codes = {label: code for code, label in PICKABLE_POSITIONS}

    default_count = max(1, min(int(suggested), int(suggested)))
    slot_count = st.number_input(
        "Number of starting positions",
        min_value=1,
        max_value=max(1, int(suggested)),
        value=default_count,
        step=1,
        key="lineup_format_slot_count",
    )

    include_util = st.checkbox("Include Utility", value=False, key="lineup_format_include_util")

    selected_labels: list[str] = []
    of_qty = 0
    for idx in range(int(slot_count)):
        options = list(pick_labels)
        if not include_util:
            options = [o for o in options if o != "Utility"]
        choice = st.selectbox(
            f"Position {idx + 1}",
            options,
            key=f"lineup_format_pick_{idx}",
        )
        selected_labels.append(choice)
        if choice == "Outfield":
            of_qty = max(of_qty, sum(1 for x in selected_labels if x == "Outfield"))

    picks = [pick_codes[label] for label in selected_labels]
    lineup_slots = expand_position_picks(picks, of_count=of_qty)

    st.markdown("**Preview**")
    inject_lineup_board_styles(st)
    emit_html_block(st, _preview_circle_html(lineup_slots))

    if st.button("Save League Lineup Format", type="primary", key="lineup_format_save_btn"):
        try:
            from fantasy_roster_validation import (
                no_expansion_draft_allowed,
                validate_commissioner_lineup_slot_count,
            )

            count_check = validate_commissioner_lineup_slot_count(
                starter_count=len(lineup_slots),
                drafted_roster_size=int(suggested),
            )
            if not count_check.get("ok"):
                st.error(str(count_check.get("error") or "Invalid lineup format."))
                return False
            # Product rule: never spawn an expansion draft after position setup.
            _ = no_expansion_draft_allowed(context)
        except ImportError:
            pass
        result = save_league_lineup_format(
            session,
            lineup_slots=lineup_slots,
            roster_capacity=int(suggested),
            configured_by=str(session.get("user_email") or session.get("username") or "commissioner"),
            configuration_source=configuration_source_for_context(context),
        )
        if result.get("ok"):
            if editing:
                clear_saved_lineup_assignments_for_format_change(session)
            session["lineup_format_saved_flash"] = True
            session.pop("lineup_format_editing", None)
            st.rerun()
        else:
            for err in result.get("errors") or []:
                st.error(err)
    return False


def render_edit_lineup_format_action(st: Any, session: dict[str, Any]) -> None:
    from fantasy_league_context import get_active_league_context

    context = get_active_league_context(session)
    if not context or needs_lineup_format_setup(context):
        return
    if not is_lineup_format_commissioner(session, context):
        return
    if st.button("Edit Lineup Format", key="lineup_format_edit_btn"):
        session["lineup_format_editing"] = True
        st.rerun()
    if session.get("lineup_format_editing"):
        st.warning("Changing the lineup format will reset saved lineup assignments for future weeks.")
