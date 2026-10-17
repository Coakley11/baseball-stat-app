"""Home: what can I do in Baseball Explorer? Task entry points + a compact league summary.

Not a dashboard: four task cards, the user's league in two lines (place, gap, this week, the
next thing to do), and a pointer to the question box. Every league number comes from the
season ledger / official standings (``fantasy_season_results.official_standings``); nothing is
computed here beyond rank arithmetic on that table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

HOME_PAGE = "Home"

# (icon, title, one line, button, page key)
TASKS: tuple[tuple[str, str, str, str, str], ...] = (
    ("🔎", "Explore Players", "Look up any player's seasons and careers, back to 1871.", "Find a player", "Historical Explorer"),
    ("📈", "Compare Players", "Put two or three players side by side.", "Compare players", "Comparison Tool"),
    ("📝", "Prepare for a Draft", "Draft live with your league, practice on your own, or review saved drafts.", "Start a mock draft", "Draft Assistant Simulator"),
    ("🏆", "Manage My League", "Standings, lineups, waivers and trades.", "Open my league", "Fantasy Standings Tracker"),
)


@dataclass(frozen=True)
class LeagueSummary:
    league_name: str
    my_team: str
    team_count: int
    place: int | None = None
    tied: bool = False
    points: float | None = None
    gap_text: str = ""
    weeks_final: int = 0
    week_text: str = ""
    next_action: str = ""
    next_page: str = "Fantasy Lineup Assistant"
    is_commissioner: bool = False
    leaderboard: tuple[tuple[int, str, float], ...] = field(default_factory=tuple)


def _fmt_pts(value: float) -> str:
    return f"{value:g}" if float(value) != int(value) else str(int(value))


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def league_summary(context: dict[str, Any] | None, my_team: str, *, is_commissioner: bool = False,
                   now=None) -> LeagueSummary | None:
    """Place, gap to the team ahead/behind, this week's status and the next action."""
    if not isinstance(context, dict) or not (context.get("league_rosters") or {}):
        return None
    from fantasy_season_ledger import (
        PERIOD_FINALIZED,
        PERIOD_LOCKED,
        current_period_number,
        get_period,
        get_period_lineup,
        ledger_initialized,
        list_periods,
        period_date_label,
        period_status,
    )
    from fantasy_season_results import official_standings

    name = str(context.get("league_name") or context.get("display_name") or context.get("draft_name") or "My league")
    teams = [str(t) for t in context.get("league_rosters") or {}]
    base = dict(league_name=name, my_team=my_team, team_count=len(teams), is_commissioner=is_commissioner)
    if not ledger_initialized(context):
        action = ("Set the season calendar" if is_commissioner
                  else "Your commissioner hasn't set the season calendar yet")
        return LeagueSummary(**base, week_text="No season calendar yet", next_action=action)

    table, weeks = official_standings(context)
    place = points = None
    tied = False
    gap_text = ""
    board: list[tuple[int, str, float]] = []
    if not table.empty:
        board = [(int(r["Rank"]), str(r["Team"]), float(r["Total Points"])) for _, r in table.iterrows()]
        mine = [b for b in board if b[1] == my_team]
        if mine:
            place, _, points = mine[0]
            tied = sum(1 for b in board if b[0] == place) > 1
            if place == 1:
                others = [b[2] for b in board if b[1] != my_team]
                lead = points - max(others) if others else 0.0
                gap_text = "tied for 1st" if lead == 0 else f"{_fmt_pts(lead)} point{'s' if lead != 1 else ''} ahead of 2nd"
            else:
                leader_pts = max(b[2] for b in board)
                gap = leader_pts - points
                gap_text = f"{_fmt_pts(gap)} point{'s' if gap != 1 else ''} behind 1st"

    number = current_period_number(context, now=now) if callable(current_period_number) else None
    period = get_period(context, number) if number else None
    if not period:
        finals = [p for p in list_periods(context) if period_status(p, now=now) == PERIOD_FINALIZED]
        return LeagueSummary(**base, place=place, tied=tied, points=points, gap_text=gap_text,
                             weeks_final=len(finals), week_text="Season complete", next_action="See final standings",
                             next_page="Fantasy Standings Tracker", leaderboard=tuple(board))
    status = period_status(period, now=now)
    label = str(period.get("label") or f"Week {number}")
    dates = period_date_label(period)
    if status == PERIOD_LOCKED:
        week_text = f"{label} ({dates}) has ended"
        action = f"Finalize {label}" if is_commissioner else f"{label} is waiting for the commissioner to finalize it"
    else:
        lineup = get_period_lineup(context, int(number), my_team) if my_team else None
        week_text = f"{label} · {dates} · {'in progress' if status == 'active' else 'upcoming'}"
        action = f"Your {label} lineup is set" if lineup else f"Set your {label} lineup"
    return LeagueSummary(**base, place=place, tied=tied, points=points, gap_text=gap_text, weeks_final=len(weeks),
                         week_text=week_text, next_action=action, leaderboard=tuple(board))


DRAFT_TASK = "Prepare for a Draft"


def _render_draft_choices(st: Any, go: Callable[[str], Callable[[], None]]) -> None:
    """The Draft landing (U3A): four ways in, two per row, each opening the matching tool."""
    from draft_tools import HOME_DRAFT_CHOICES

    for row, pair in enumerate((HOME_DRAFT_CHOICES[:2], HOME_DRAFT_CHOICES[2:])):
        try:
            from mobile_foundation import mobile_wrap_row

            wrap = mobile_wrap_row(st, f"home-draft-row-{row}")
        except ImportError:
            wrap = st.container()
        with wrap:
            cols = st.columns(2)
        for col, (label, page) in zip(cols, pair):
            col.button(label, key=f"home_draft_{page}", on_click=go(page), use_container_width=True)


def render_home(st: Any, session: Any, *, navigate: Callable[..., Any], render_tutorial_bar: Callable[[], None] | None = None) -> None:
    import ui_hierarchy as ui

    def go(page: str) -> Callable[[], None]:
        return lambda: navigate(page, from_callback=True)

    ui.page_head(st, "What would you like to do?",
                 "Look up players, spot who's rising, prepare for your draft and run your fantasy league.")
    st.markdown('<div class="u1-label u1-home-tasks">Start here</div>', unsafe_allow_html=True)
    for row in (TASKS[:2], TASKS[2:]):
        cols = st.columns(2)
        for col, (icon, title, body, button, page) in zip(cols, row):
            with col.container(border=True):
                st.markdown(f'<div class="u1-card-title">{icon} {ui.esc(title)}</div>'
                            f'<div class="u1-card-body">{ui.esc(body)}</div>', unsafe_allow_html=True)
                if title == DRAFT_TASK:
                    _render_draft_choices(st, go)
                else:
                    st.button(button, key=f"home_task_{page}", on_click=go(page), use_container_width=True)

    _render_league_block(st, session, go)

    ui.section_label(st, "Ask a question")
    st.markdown(
        '<div class="u1-card u1-ami-slot"><div class="u1-card-title">💬 Ask AMI</div>'
        '<div class="u1-card-body">Ask a baseball question in plain English. For now, use the '
        '<strong>Baseball Insight</strong> box in the sidebar (on a phone, tap the <strong>»</strong> '
        "at the top left).</div></div>",
        unsafe_allow_html=True,
    )
    if render_tutorial_bar is not None:
        render_tutorial_bar()


def _my_team(session: Any, context: dict[str, Any]) -> str:
    try:
        from fantasy_league_team_ownership import resolve_account_fantasy_team

        owned = str(resolve_account_fantasy_team(session, context) or "").strip()
        if owned:
            return owned
    except Exception:
        pass
    return str(context.get("my_team_name") or "").strip()


def _render_league_block(st: Any, session: Any, go: Callable[[str], Callable[[], None]]) -> None:
    import ui_hierarchy as ui

    try:
        from fantasy_league_context import get_active_league_context

        context = get_active_league_context(session, respect_source_priority=False)
    except Exception:
        context = None
    ui.section_label(st, "My league")
    if not isinstance(context, dict):
        ui.answer_card(st, "You don't have a league yet",
                       "Draft one (mock or live) or import a draft board you already have.", kicker="My league")
        ui.action_row(st, [("Start or import a draft", go("Draft Room Simulator")),
                           ("Open saved drafts", go("Saved Draft Library"))], key="home_noleague")
        return
    team = _my_team(session, context)
    try:
        from fantasy_team_control import resolve_team_control

        is_comm = bool(resolve_team_control(session, context, team).is_commissioner)
    except Exception:
        is_comm = False
    summary = league_summary(context, team, is_commissioner=is_comm)
    if summary is None:
        ui.answer_card(st, "Your league has no rosters yet", "Open your saved drafts to pick or finish a league.")
        ui.action_row(st, [("Open saved drafts", go("Saved Draft Library"))], key="home_emptyleague")
        return
    if summary.place is not None:
        tie = "tied " if summary.tied else ""
        headline = f"{team}: {tie}{_ordinal(summary.place)} of {summary.team_count} · {summary.gap_text}"
        body = f"{summary.league_name} · official standings after {summary.weeks_final} completed week" + (
            "s" if summary.weeks_final != 1 else "")
    else:
        headline = f"{team or 'Your team'} · {summary.league_name}"
        body = "No completed weeks yet, so there are no official standings."
    ui.answer_card(st, headline, body, kicker="My league")
    ui.chips(st, [(summary.week_text, ""), (summary.next_action, "warn" if summary.next_action.startswith(("Set", "Finalize")) else "")])
    ui.action_row(st, [("League Standings", go("Fantasy Standings Tracker")),
                       ("Set Lineup", go("Fantasy Lineup Assistant")),
                       ("Waiver Wire", go("Waiver Wire / Add-Drop Center"))], key="home_league")
