"""Season calendar setup and scoring-period labels for the Lineup page."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fantasy_season_ledger import (
    PERIOD_ACTIVE,
    PERIOD_FINALIZED,
    PERIOD_LOCKED,
    PERIOD_UPCOMING,
    configure_season_calendar,
    get_period,
    get_season_ledger,
    league_today,
    list_periods,
    period_date_label,
    period_status,
)

STATUS_LABELS = {
    PERIOD_UPCOMING: "Upcoming",
    PERIOD_ACTIVE: "In progress",
    PERIOD_LOCKED: "Ended — awaiting finalization",
    PERIOD_FINALIZED: "Final",
}


def period_option_label(context: dict[str, Any] | None, number: int) -> str:
    """'Week 3 · Apr 20 – Apr 26, 2026 · Final' — or 'Week 3' for a legacy league."""
    period = get_period(context, number)
    if not period:
        return f"Week {int(number)}"
    parts = [str(period.get("label") or f"Week {int(number)}"), period_date_label(period)]
    parts.append(STATUS_LABELS.get(period_status(period), ""))
    return " · ".join(p for p in parts if p)


def period_week_options(context: dict[str, Any] | None) -> list[int] | None:
    periods = list_periods(context)
    return [int(p["number"]) for p in periods] if periods else None


def _default_first_day() -> date:
    today = league_today()
    return today - timedelta(days=today.weekday())  # Monday of this week


def render_season_calendar_setup(st: Any, session: dict[str, Any], context: dict[str, Any], *, is_commissioner: bool) -> bool:
    """Commissioner sets the scoring periods once. Returns True when the league has a calendar."""
    if get_season_ledger(context) and list_periods(context):
        return True
    if not is_commissioner:
        st.info(
            "The commissioner has not set this league's season calendar yet. Lineups still save, "
            "but official weekly results start once the calendar exists."
        )
        return False
    with st.expander("Set the season calendar (official weekly scoring)", expanded=False):
        st.caption(
            "Official standings add up finalized scoring periods. Each period has fixed dates; "
            "a finalized period never changes, even after later drops or trades."
        )
        # A form: editing the date must not rerun the page (which folded the expander away).
        with st.form("season_calendar_form", border=False):
            first_day = st.date_input("First day of Week 1", value=_default_first_day(), key="season_calendar_first_day")
            count = st.number_input("Number of weeks", min_value=1, max_value=30, value=26, step=1, key="season_calendar_count")
            submitted = st.form_submit_button("Create season calendar", type="primary")
        if submitted:
            ok, err = configure_season_calendar(context, first_day=first_day, period_count=int(count))
            if not ok:
                st.error(err)
                return False
            try:
                from fantasy_league_context import upsert_league_context

                upsert_league_context(session, context)
                import streamlit as _st
                from baseball_persistent_state import force_save_baseball_state

                force_save_baseball_state(_st, reason="season_calendar_created")
            except Exception:
                pass
            st.rerun()
    return False


def period_editability(
    context: dict[str, Any] | None,
    number: int,
    *,
    lineup_locked: bool,
    is_commissioner: bool,
) -> tuple[bool, str]:
    """(locked, message) for a team's lineup in a scoring period.

    A saved lineup stays locked (existing rule). An unsaved lineup is editable before the
    period starts; after that only the commissioner may set it, marked as set after the lock.
    """
    period = get_period(context, number)
    if not period:
        return lineup_locked, ""
    label = str(period.get("label") or f"Week {int(number)}")
    status = period_status(period)
    if status == PERIOD_FINALIZED:
        return True, f"{label} is final. Its results can no longer change."
    if lineup_locked:
        return True, f"{label} lineup is saved and locked."
    if status == PERIOD_UPCOMING:
        return False, f"Set your {label} lineup before it starts on {period.get('start')}."
    if is_commissioner:
        return False, (
            f"{label} has started. As commissioner you can still set this lineup; "
            "it will be recorded as set after the lock."
        )
    return True, f"{label} has started, so lineups are locked. Ask the commissioner to set a missing lineup."
