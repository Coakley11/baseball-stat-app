"""Read-only fantasy interface for AMI and other consumers.

One import surface over the authoritative modules. Nothing here computes a statistic of its
own: every number comes from the module named in each function's docstring. Nothing here
writes the session, fetches data, or changes a league.

Contracts in brief (details per function; see docs/FANTASY_SHARED_INTERFACES.md):

* ``active_league(session)`` — which league/team the fantasy pages show.
* ``official_standings_view(session)`` — THE standings: sum of finalized weeks.
* ``current_roster_standings_view(roster_stats, fmt)`` — today's rosters on season-to-date
  stats. Analysis only; always labeled "not official standings".
* ``loaded_roster_stats(session)`` — the roster stats a page already loaded (never fetches).
* ``team_access(session, team)`` — may this user act for / see private data of a team.
* ``evaluate_trade_for_team(...)`` — trade value + legality, only for a team the user manages.
* ``lineup_report(...)``, ``explain_slot_eligibility(...)``, ``check_lineup(...)`` — lineup
  scoring, recommended starters, diagnosis and eligibility explanations.
* ``player_owner(session, player)`` — who rosters a player (the check waiver adds and trade
  proposals use).
* ``week_lineup_status(session, team, week)`` — Not saved / Draft / Saved and locked, with the
  Lineup page's own answer.
* ``waiver_recommendations_view(session, team, position)`` / ``loaded_player_pool(session)`` —
  the Waiver Wire's ranked adds, drops and reasons; the unrostered pool already loaded.
* ``pending_trade_draft(session, team)`` — the trade being built in Trade Center (read only).
* ``week_view(session, number, team)`` — one scoring period from the season ledger.

Every result says which kind of data it is (``kind`` / ``label``) so an assistant can never
present a snapshot as the official standings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fantasy_league_peek import isolated_session_view, peek_active_league_context, peek_resolved_fantasy_context
from fantasy_standings_snapshot import SNAPSHOT_KIND, SNAPSHOT_LABEL

OFFICIAL_KIND = "official"
OFFICIAL_LABEL = "League Standings (official)"
OFFICIAL_BASIS = (
    "Sum of finalized weeks. Each week counts the lineup used that week; later drops and trades never change "
    "a completed week. Tied teams split category points."
)
SNAPSHOT_BASIS = (
    "Season-to-date stats of the players on each roster today. A player counts for whoever owns him now, "
    "whenever he played. Not the league standings."
)
ELIGIBILITY_RULE = (
    "Eligible at his primary position and at any position with at least 10 games this season or last season "
    "(LF/CF/RF count as OF; UTIL takes any hitter)."
)


@dataclass(frozen=True)
class LeagueSummary:
    league_context_id: str
    league_name: str
    my_team: str
    team_names: tuple[str, ...]
    scoring_format: str
    lineup_slots: tuple[str, ...]
    has_season_calendar: bool
    finalized_weeks: tuple[int, ...]
    source_kind: str
    context_fingerprint: str
    coherent: bool
    coherence_error: str = ""


@dataclass(frozen=True)
class StandingsView:
    kind: str  # OFFICIAL_KIND or SNAPSHOT_KIND
    label: str
    basis: str
    table: pd.DataFrame
    finalized_weeks: tuple[int, ...] = ()
    note: str = ""

    @property
    def is_official(self) -> bool:
        return self.kind == OFFICIAL_KIND


@dataclass(frozen=True)
class TradeEvaluation:
    allowed: bool
    reason: str = ""
    my_team: str = ""
    partner_team: str = ""
    give: tuple[str, ...] = ()
    receive: tuple[str, ...] = ()
    category_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    verdict: str = ""
    weighted_gain: float = 0.0
    verdict_text: str = ""
    proposal_ok: bool = False
    proposal_message: str = ""
    legality_warnings: tuple[str, ...] = ()
    acting_as: str = ""
    basis: str = (
        "Current-season stats of the players involved (BA/OPS are the plain average of each side's players). "
        "Team needs come from the Current Roster Snapshot, not the official standings."
    )
    # The Trade Center verdict card for the same trade (u3_answers.trade_verdict over the
    # engine's analysis package and trade_roster_issues). verdict_label is the card's label.
    verdict_label: str = ""
    value_label: str = ""
    verdict_headline: str = ""
    verdict_body: str = ""
    verdict_tone: str = ""
    roster_issues: tuple[dict[str, Any], ...] = ()  # every issue: team, kind (slot/over/under), slot, message
    required_position_issues: tuple[str, ...] = ()  # your team: required lineup slots it can no longer fill
    roster_size_issues: tuple[str, ...] = ()  # your team: over the roster size
    open_roster_spots: tuple[str, ...] = ()  # your team: under the roster size (a note, not an issue)
    other_team_notes: tuple[str, ...] = ()
    category_changes: tuple[dict[str, Any], ...] = ()  # category, give, receive, change
    helps: tuple[str, ...] = ()
    hurts: tuple[str, ...] = ()
    positions_lost: tuple[str, ...] = ()
    positions_gained: tuple[str, ...] = ()
    analysis: dict[str, Any] = field(default_factory=dict)  # build_trade_analysis_package, as Trade Center stores it


# --- League -----------------------------------------------------------------------------------


def active_league(session: Any) -> LeagueSummary | None:
    """The league the fantasy pages show, resolved without side effects.

    Source: ``fantasy_league_peek`` (= ``resolve_fantasy_context_for_page`` /
    ``get_active_league_context`` on an isolated view). None when there is no league.
    """
    resolved = peek_resolved_fantasy_context(session)
    context = peek_active_league_context(session)
    if context is None and not resolved.active_league_context_id:
        return None
    context = context or {}
    from fantasy_season_ledger import ledger_initialized, list_periods

    from fantasy_league_lineup_format import lineup_format_block

    slots = tuple((lineup_format_block(context) or {}).get("lineup_slots") or ())
    finalized = tuple(int(p["number"]) for p in list_periods(context) if str(p.get("finalized_at") or "").strip())
    return LeagueSummary(
        league_context_id=str(context.get("league_context_id") or resolved.active_league_context_id or ""),
        league_name=str(context.get("league_name") or context.get("display_name") or context.get("draft_name") or ""),
        my_team=str(resolved.active_team_name or context.get("my_team_name") or ""),
        team_names=tuple(resolved.team_names),
        scoring_format=str(context.get("fantasy_format") or ""),
        lineup_slots=slots,
        has_season_calendar=bool(ledger_initialized(context)),
        finalized_weeks=finalized,
        source_kind=resolved.source_kind,
        context_fingerprint=resolved.context_fingerprint,
        coherent=resolved.coherent,
        coherence_error=resolved.coherence_error,
    )


def team_access(session: Any, team: str):
    """``fantasy_team_control.resolve_team_control`` for ``team`` in the active league (read-only).

    ``.can_manage`` is True for the team's owner, or for the commissioner acting for a team
    nobody has claimed (``.is_proxy``). Use it before showing team-private data (pending
    trades, unsaved lineups, lineups for weeks that haven't started) or any team-perspective
    advice.
    """
    from fantasy_team_control import resolve_team_control

    view = isolated_session_view(session)
    return resolve_team_control(view, peek_active_league_context(session), team)


# --- Standings --------------------------------------------------------------------------------


def official_standings_view(session: Any) -> StandingsView:
    """THE league standings: ``fantasy_season_results.official_standings`` on the active league.

    Empty table (with a note) when the league has no season calendar or no finalized week.
    """
    from fantasy_season_ledger import ledger_initialized
    from fantasy_season_results import official_standings

    context = peek_active_league_context(session)
    if not context or not ledger_initialized(context):
        return StandingsView(OFFICIAL_KIND, OFFICIAL_LABEL, OFFICIAL_BASIS, pd.DataFrame(),
                             note="This league has no season calendar yet, so there are no official standings.")
    table, weeks = official_standings(context)
    note = "" if weeks else "No week is final yet."
    return StandingsView(OFFICIAL_KIND, OFFICIAL_LABEL, OFFICIAL_BASIS, table.copy(), tuple(weeks), note)


def current_roster_standings_view(roster_stats: pd.DataFrame, scoring_format: str = "5x5 Roto") -> StandingsView:
    """Today's rosters on season-to-date stats (``fantasy_standings_snapshot``). NOT official."""
    from fantasy_standings_snapshot import score_current_roster_standings

    if roster_stats is None or getattr(roster_stats, "empty", True):
        return StandingsView(SNAPSHOT_KIND, SNAPSHOT_LABEL, SNAPSHOT_BASIS, pd.DataFrame(), note="No roster stats loaded.")
    table = score_current_roster_standings(roster_stats, scoring_format)
    return StandingsView(SNAPSHOT_KIND, SNAPSHOT_LABEL, SNAPSHOT_BASIS, table)


def loaded_roster_stats(session: Any) -> tuple[pd.DataFrame, str]:
    """(roster stats the Standings/Lineup pages last loaded, loaded-at timestamp). Never fetches.

    Empty frame when no page has loaded current stats in this session — tell the user to open
    Fantasy Standings Tracker rather than fetching.
    """
    view = isolated_session_view(session)
    frame = view.get("fantasy_current_roster_stats")
    loaded_at = str(view.get("_fantasy_standings_stats_loaded_at") or "")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame, loaded_at
    return pd.DataFrame(), loaded_at


# --- Trades -----------------------------------------------------------------------------------


def evaluate_trade_for_team(
    session: Any,
    *,
    my_team: str,
    partner_team: str,
    give: list[str],
    receive: list[str],
    roster_stats: pd.DataFrame,
    scoring_format: str = "5x5 Roto",
    standings: pd.DataFrame | None = None,
) -> TradeEvaluation:
    """Trade value and legality from ``my_team``'s point of view, plus the Trade Center
    verdict card for the same trade.

    Authorization: ``my_team`` must be a team this user may manage (``team_access``); otherwise
    ``allowed`` is False and nothing is computed.

    Sources: value — ``fantasy_trade_evaluation.evaluate_trade`` / ``build_trade_verdict_text``
    with needs from ``fantasy_standings_snapshot``; proposal rules —
    ``fantasy_trade_proposals.validate_proposal_players``; roster/lineup consequences —
    ``fantasy_trade_legality.trade_roster_issues``; the card — ``fantasy_trade_analysis.
    build_trade_analysis_package`` + ``u3_answers.trade_verdict``. Inputs are Trade Center's:
    the standings and hitter pool the session already loaded (``standings`` / ``roster_stats``
    override; without loaded standings they are scored from ``roster_stats``). Evaluating never
    proposes or executes.
    """
    give_t, receive_t = tuple(str(p) for p in give or ()), tuple(str(p) for p in receive or ())
    base = dict(my_team=str(my_team or ""), partner_team=str(partner_team or ""), give=give_t, receive=receive_t)
    context = peek_active_league_context(session)
    if not context:
        return TradeEvaluation(False, "There is no active league.", **base)
    control = team_access(session, my_team)
    if not control.can_manage:
        return TradeEvaluation(False, control.reason or f"You can't manage {my_team}.", **base)
    if roster_stats is None or getattr(roster_stats, "empty", True):
        return TradeEvaluation(False, "Current roster stats aren't loaded. Open Fantasy Standings Tracker first.", **base)

    from fantasy_standings_snapshot import score_current_roster_standings, summarize_team_category_needs
    from fantasy_trade_analysis import build_trade_analysis_package
    from fantasy_trade_category_values import format_trade_category_value
    from fantasy_trade_evaluation import build_trade_verdict_text, evaluate_trade
    from fantasy_trade_legality import trade_roster_issues
    from fantasy_trade_proposals import validate_proposal_players
    from u3_answers import trade_verdict

    view = isolated_session_view(session)
    if standings is None:
        loaded = view.get("fantasy_current_standings")  # what Trade Center reads
        standings = loaded if isinstance(loaded, pd.DataFrame) and not loaded.empty else \
            score_current_roster_standings(roster_stats, scoring_format)
    pool = view.get("_fantasy_current_hitter_stats")  # Trade Center's position lookup for roster checks
    pool = pool if isinstance(pool, pd.DataFrame) and not pool.empty else roster_stats
    my_roster = roster_stats[roster_stats["Team"].astype(str) == str(my_team)]
    table, verdict, gain = evaluate_trade(list(give_t), list(receive_t), my_roster, roster_stats, standings, my_team)
    ok, message = validate_proposal_players(context, proposer_team=my_team, recipient_team=partner_team,
                                            proposer_gives=list(give_t), proposer_receives=list(receive_t))
    issues = [dict(i) for i in trade_roster_issues(context, proposer_team=my_team, recipient_team=partner_team,
                                                     proposer_gives=list(give_t), proposer_receives=list(receive_t),
                                                     stats_pool=pool)]
    package = build_trade_analysis_package(
        give_players=list(give_t), receive_players=list(receive_t), roster_stats=roster_stats, standings=standings,
        my_team=my_team, evaluate_trade_fn=evaluate_trade, build_trade_verdict_text_fn=build_trade_verdict_text,
        summarize_team_category_needs_fn=summarize_team_category_needs,
    )
    card = trade_verdict(package, my_team=my_team, partner=partner_team, roster_issues=issues,
                         format_change=lambda cat, value: format_trade_category_value(cat, value, is_change=True))
    mine = [i for i in issues if str(i.get("team") or "") == str(my_team)]
    return TradeEvaluation(
        True, "", category_table=table, verdict=verdict, weighted_gain=float(gain),
        verdict_text=build_trade_verdict_text(table, gain), proposal_ok=bool(ok), proposal_message=message,
        legality_warnings=tuple(str(i.get("message") or "") for i in issues), acting_as=control.mode,
        verdict_label=str(card["label"]), value_label=str(card["value_label"]), verdict_headline=str(card["headline"]),
        verdict_body=str(card["body"]), verdict_tone=str(card["tone"]), roster_issues=tuple(issues),
        required_position_issues=tuple(str(i["message"]) for i in mine if i.get("kind") == "slot"),
        roster_size_issues=tuple(str(i["message"]) for i in mine if i.get("kind") == "over"),
        open_roster_spots=tuple(str(i["message"]) for i in mine if i.get("kind") == "under"),
        other_team_notes=tuple(card["other_notes"]),
        category_changes=tuple(dict(r) for r in package.get("category_rows") or ()),
        helps=tuple(package.get("helps") or ()), hurts=tuple(package.get("hurts") or ()),
        positions_lost=tuple(package.get("positions_lost") or ()),
        positions_gained=tuple(package.get("positions_gained") or ()), analysis=dict(package), **base,
    )


# --- Lineups ----------------------------------------------------------------------------------


def lineup_report(
    team_roster_stats: pd.DataFrame,
    *,
    slots: list[str] | None = None,
    scoring_format: str = "5x5 Roto",
    custom_weights: dict[str, float] | None = None,
    rate_col: str = "BA",
    league_roster_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Start/sit scores, recommended starters and lineup diagnosis for one team's roster frame.

    Sources: ``fantasy_lineup_scoring`` (the Lineup Assistant's own functions). Returns
    ``{"scored", "recommended", "missing_slots", "slot_warnings", "diagnosis", "basis"}``.
    Recommended starters use the same slot rule Save Lineup enforces
    (``fantasy_slot_eligibility.player_eligible_for_slot_strict``); ``check_lineup`` validates
    any lineup, including one the user built by hand.
    """
    from fantasy_lineup_scoring import build_lineup_assistant_scores, build_position_aware_lineup, lineup_diagnosis_report
    from fantasy_slot_eligibility import enrich_lineup_roster_positions

    scored = enrich_lineup_roster_positions(build_lineup_assistant_scores(team_roster_stats, scoring_format, custom_weights))
    package = build_position_aware_lineup(scored, slots=slots)
    diagnosis = lineup_diagnosis_report(package["lineup_df"], scored, scoring_format, rate_col,
                                        missing_slots=package["missing_slots"], slot_warnings=package["slot_warnings"],
                                        league_roster_df=league_roster_df)
    return {
        "scored": scored,
        "recommended": package["lineup_df"],
        "missing_slots": list(package["missing_slots"]),
        "slot_warnings": list(package["slot_warnings"]),
        "diagnosis": diagnosis,
        "basis": "Season-to-date stats of this roster, scored relative to each other (0-1).",
    }


def explain_slot_eligibility(player_row: Any, slot: str) -> dict[str, Any]:
    """Why a player can or cannot fill a lineup slot, by the rule lineup saves enforce.

    Sources: ``fantasy_weekly_lineup.position_tokens_from_row`` / ``player_eligible_for_slot``
    (``fantasy_lineup_fill`` with ``fantasy_position_eligibility``).
    """
    from fantasy_weekly_lineup import player_eligible_for_slot, position_tokens_from_row

    row = player_row if isinstance(player_row, (pd.Series, dict)) else {}
    tokens = position_tokens_from_row(row)
    name = str((row.get("Player") if hasattr(row, "get") else "") or "")
    eligible = bool(player_eligible_for_slot(tokens, slot))
    positions = ", ".join(tokens) or "none on record"
    reason = (
        f"{name or 'This player'} can play {slot}: eligible at {positions}."
        if eligible
        else f"{name or 'This player'} can't play {slot}: eligible only at {positions}."
    )
    return {"player": name, "slot": str(slot), "eligible": eligible, "eligible_positions": tokens,
            "rule": ELIGIBILITY_RULE, "reason": reason}


def check_lineup(slots: list[str], assignments: dict[str, str], roster_df: pd.DataFrame) -> dict[str, Any]:
    """Would this lineup pass Save Lineup's checks? ``fantasy_weekly_lineup.validate_weekly_lineup``.

    Returns its dict: ok, missing_slots, ineligible_slots, duplicate_players, unfillable_slots,
    messages. (Week lock rules are separate: ``fantasy_season_ledger.save_period_lineup``.)
    """
    from fantasy_weekly_lineup import validate_weekly_lineup

    return validate_weekly_lineup(list(slots), dict(assignments), roster_df)


# --- Ownership --------------------------------------------------------------------------------

OWNERSHIP_BASIS = (
    "League rosters as this session last loaded them (accepted trades applied), the same rosters Waiver Wire "
    "and Trade Center check. Another manager's move since then shows after the league next syncs."
)


@dataclass(frozen=True)
class PlayerOwnership:
    query: str
    status: str  # "your_team" | "other_team" | "free_agent" | "no_league"
    player: str = ""  # the rostered name when found, else the query
    owner_team: str = ""
    my_team: str = ""
    rostered: bool = False  # what Confirm Waiver Move checks ("X is already rostered")
    in_loaded_pool: bool | None = None  # in the current-season stats already loaded (None: none loaded)
    basis: str = OWNERSHIP_BASIS

    @property
    def is_my_team(self) -> bool:
        return self.status == "your_team"

    @property
    def is_free_agent(self) -> bool:
        return self.status == "free_agent"


def _league_rosters_context(session: Any) -> dict[str, Any] | None:
    """The active league as the transaction pages check it, without their network sync: the
    peeked context with accepted-but-unapplied trades reconciled and ownership rebuilt from the
    rosters (``fantasy_waiver_wire.resolve_waiver_league_context`` minus the shared-store pull)."""
    context = peek_active_league_context(session)
    if not context:
        return None
    from fantasy_league_context import build_ownership_map
    from fantasy_trade_roster_sync import reconcile_accepted_trades_in_context

    reconciled, _changed, _traces = reconcile_accepted_trades_in_context(context)
    context = dict(reconciled if isinstance(reconciled, dict) else context)
    context["ownership_map"] = build_ownership_map(context)
    return context


def player_owner(session: Any, player: str) -> PlayerOwnership:
    """Who rosters ``player`` in the active league. League rosters are league-wide information
    (Waiver Wire and Trade Center show every team's players); nothing team-private is returned.

    Sources: ``fantasy_league_context.build_ownership_map`` (owner team, the lookup trade
    proposals use) and ``fantasy_waiver_wire.is_player_rostered`` (the waiver add check)."""
    query = str(player or "").strip()
    context = _league_rosters_context(session)
    league = active_league(session)
    my_team = league.my_team if league else ""
    if not context or not query:
        return PlayerOwnership(query, "no_league" if not context else "free_agent", player=query, my_team=my_team)
    from fantasy_league_context import normalize_player_key
    from fantasy_waiver_wire import is_player_rostered

    record = (context.get("ownership_map") or {}).get(normalize_player_key(query)) or {}
    owner = str(record.get("owner_team") or "").strip()
    rostered = bool(is_player_rostered(context, query))
    name = str(record.get("player_name") or query)
    if owner:
        status = "your_team" if my_team and owner == my_team else "other_team"
    else:
        status = "free_agent" if not rostered else "other_team"
    # "free_agent" means on no roster in this league; in_loaded_pool says whether the loaded
    # current-season stats know the name at all (an unknown name is not a confirmed free agent).
    from fantasy_waiver_wire import _player_identity_keys, loaded_waiver_stats_pool

    pool = loaded_waiver_stats_pool(isolated_session_view(session), context)
    in_pool = None
    if isinstance(pool, pd.DataFrame) and not pool.empty and "Player" in pool.columns:
        wanted = _player_identity_keys(query)
        in_pool = bool(pool["Player"].astype(str).map(lambda n: bool(_player_identity_keys(n) & wanted)).any())
    return PlayerOwnership(query, status, player=name, owner_team=owner, my_team=my_team, rostered=rostered,
                           in_loaded_pool=in_pool)


# --- Weekly lineup status ---------------------------------------------------------------------


@dataclass(frozen=True)
class LineupStatus:
    allowed: bool
    reason: str = ""
    team: str = ""
    week: int = 0
    week_text: str = ""
    has_season_calendar: bool = False
    period_status: str = ""  # upcoming / active / locked / finalized ("" without a season calendar)
    record_status: str = ""  # the saved record: "" (none), "draft", "locked"
    status: str = ""  # the page's words: "Not saved yet", "Draft (not submitted)", "Saved and locked", "Locked"
    locked: bool = False
    edit_message: str = ""
    slots: tuple[tuple[str, str], ...] = ()  # (slot key, label) in board order
    assignments: dict[str, str] = field(default_factory=dict)  # slot key -> player, from the saved record
    roster_loaded: bool = False  # eligibility checks below need the loaded roster stats
    open_positions: tuple[str, ...] = ()
    from_bench: tuple[str, ...] = ()
    needs_waiver_or_trade: tuple[str, ...] = ()
    not_eligible: tuple[str, ...] = ()  # "Player at SLOT"
    assigned_twice: tuple[str, ...] = ()
    complete: bool = False
    headline: str = ""
    body: str = ""
    tone: str = ""
    acting_as: str = ""
    basis: str = (
        "The lineup saved for this team and week (a draft while you build it, locked after Save Lineup), checked "
        "with the rule Save Lineup enforces. Unsaved changes on the Lineup board aren't included."
    )


def week_lineup_status(session: Any, team: str = "", week: int | None = None, *,
                       roster_stats: pd.DataFrame | None = None) -> LineupStatus:
    """The Lineup page's status for ``team``'s lineup in ``week`` (default: the week the page
    opens on). Team-private, so ``team_access(...).can_manage`` is required.

    Sources: ``fantasy_weekly_lineup.lineup_week_state`` (saved record, lock, editability) and
    ``lineup_status_answer`` (= ``u3_answers.lineup_answer`` with ``validate_weekly_lineup``),
    the functions the Lineup page calls. ``roster_stats`` defaults to the stats already loaded."""
    context = peek_active_league_context(session)
    team = str(team or "").strip() or (active_league(session).my_team if context else "")
    if not context:
        return LineupStatus(False, "There is no active league.", team=team)
    control = team_access(session, team)
    if not control.can_manage:
        return LineupStatus(False, control.reason or f"You can't manage {team}.", team=team)
    from fantasy_league_lineup_format import is_lineup_format_commissioner
    from fantasy_lineup_ui import build_slot_key_labels, slot_key_labels_as_tuples
    from fantasy_season_ledger import current_period_number, get_period, period_status
    from fantasy_season_ledger_ui import period_option_label
    from fantasy_weekly_lineup import (
        lineup_status_answer,
        lineup_week_state,
        resolve_weekly_lineup_slots,
        week_label,
    )

    from fantasy_season_ledger_ui import period_week_options

    view = isolated_session_view(session)
    slots = resolve_weekly_lineup_slots(context)
    if not slots:
        return LineupStatus(False, "League starting positions are not configured yet.", team=team)
    ledger_weeks = period_week_options(context)
    if week is None:
        if ledger_weeks:
            week = current_period_number(context) or ledger_weeks[0]
        else:
            from fantasy_weekly_hitter_scoring import get_active_scoring_week

            week = get_active_scoring_week(context)
    week = int(week)
    if ledger_weeks and week not in ledger_weeks:
        return LineupStatus(False, f"Week {week} is not on the league calendar.", team=team, week=week)
    state = lineup_week_state(context, week, team=team, session=view,
                              is_commissioner=bool(is_lineup_format_commissioner(view, context)))
    saved = state["saved"] or {}
    assignments = {str(k): str(v or "").strip() for k, v in dict(saved.get("assignments") or {}).items()}
    if roster_stats is None:
        roster_stats, _loaded_at = loaded_roster_stats(session)
    roster = roster_stats
    if isinstance(roster, pd.DataFrame) and not roster.empty and "Team" in roster.columns:
        roster = roster[roster["Team"].astype(str) == team].copy()
    roster_loaded = isinstance(roster, pd.DataFrame) and not roster.empty
    week_text = period_option_label(context, week) if ledger_weeks else week_label(week)
    answer = lineup_status_answer(
        team=team, week_text=week_text, slots=list(slots), assignments=assignments,
        team_roster=roster if roster_loaded else pd.DataFrame(), locked=state["locked"],
        record_status=str(saved.get("status") or ""), edit_message=state["edit_message"], proxy=control.is_proxy,
    )
    from fantasy_weekly_lineup import validate_weekly_lineup

    validation = validate_weekly_lineup(list(slots), assignments, roster if roster_loaded else pd.DataFrame())
    labels = slot_key_labels_as_tuples(build_slot_key_labels(list(slots)))
    return LineupStatus(
        True, "", team=team, week=week, week_text=week_text, has_season_calendar=bool(ledger_weeks),
        period_status=period_status(get_period(context, week)) if ledger_weeks else "",
        record_status=str(saved.get("status") or ""), status=str(answer["status"]), locked=bool(state["locked"]),
        edit_message=state["edit_message"], slots=tuple(labels), assignments=assignments, roster_loaded=roster_loaded,
        open_positions=tuple(label for key, label in labels if not assignments.get(key)),
        from_bench=tuple(answer["from_bench"]), needs_waiver_or_trade=tuple(answer["need_help"]),
        not_eligible=tuple(f"{i.get('player')} at {i.get('slot')}" for i in (validation.get("ineligible_slots") or [])
                           if isinstance(i, dict)) if roster_loaded else (),
        assigned_twice=tuple(validation.get("duplicate_players") or ()),
        complete=bool(answer["complete"]) and roster_loaded, headline=str(answer["headline"]), body=str(answer["body"]),
        tone=str(answer["tone"]), acting_as=control.mode,
    )


# --- Waivers ----------------------------------------------------------------------------------

WAIVER_BASIS = (
    "Current-season MLB stats for players in your league, the Waiver Wire's own ranking for your team's needs "
    "(not projections). Planning only: a move happens only through Confirm Waiver Move."
)
_POOL_STAT_COLUMNS = ("AB", "R", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS")


def _stat_values(row: pd.Series) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in _POOL_STAT_COLUMNS:
        if col in row.index:
            val = pd.to_numeric(row.get(col), errors="coerce")
            if pd.notna(val):
                out[col] = round(float(val), 3) if col in ("BA", "OBP", "SLG", "OPS") else float(val)
    return out


def _positions(text: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in str(text or "").split(",") if p.strip())


@dataclass(frozen=True)
class WaiverRecommendations:
    allowed: bool
    reason: str = ""
    team: str = ""
    position: str = "All positions"
    headline: str = ""  # the page's answer: "Biggest needs: SB (4th of 4) · …"
    body: str = ""
    weak_categories: tuple[str, ...] = ()
    category_ranks: dict[str, int] = field(default_factory=dict)
    team_count: int = 0
    open_roster_spots: tuple[str, ...] = ()
    adds: tuple[dict[str, Any], ...] = ()  # ranked: player, positions, mlb_team, why, stat_line, comparison, stats, ...
    drops: tuple[dict[str, Any], ...] = ()  # ranked drop candidates: player, positions, why, stats
    acting_as: str = ""
    basis: str = WAIVER_BASIS


def _waiver_inputs(session: Any):
    from fantasy_waiver_wire import loaded_waiver_stats_pool

    context = _league_rosters_context(session)
    if not context:
        return None, pd.DataFrame(), pd.DataFrame()
    view = isolated_session_view(session)
    stats_pool = loaded_waiver_stats_pool(view, context)
    league_df = view.get("fantasy_current_roster_stats")
    league_df = league_df.copy() if isinstance(league_df, pd.DataFrame) and not league_df.empty else pd.DataFrame()
    if league_df.empty and isinstance(stats_pool, pd.DataFrame) and not stats_pool.empty:
        from fantasy_league_context import build_roster_stats_from_league_context, has_full_league_rosters
        from player_name_normalization import normalize_player_name_for_merge

        if has_full_league_rosters(context):
            league_df = build_roster_stats_from_league_context(context, stats_pool,
                                                               normalize_name_fn=normalize_player_name_for_merge)
    return context, stats_pool if isinstance(stats_pool, pd.DataFrame) else pd.DataFrame(), league_df


def waiver_recommendations_view(session: Any, team: str = "", position: str = "All positions", *,
                                limit: int = 3) -> WaiverRecommendations:
    """The Waiver Wire's recommendations for ``team`` (default: yours): the needs headline, the
    top ``limit`` adds (the page shows 3; at most 15) with each card's reason, and drop
    candidates. Team-perspective advice, so ``team_access(...).can_manage`` is required.

    Sources: ``fantasy_waiver_wire.waiver_team_frames`` / ``compute_waiver_recommendations`` /
    ``waiver_open_slots`` / ``waiver_card_fields`` / ``apply_waiver_position_filter`` — the
    functions the Waiver Wire page calls — and ``u1_answers.needs_headline``. Never fetches:
    without loaded current stats it says so."""
    from fantasy_waiver_wire import (
        WAIVER_POSITION_FILTER_OPTIONS,
        apply_waiver_position_filter,
        compute_waiver_recommendations,
        waiver_card_fields,
        waiver_categories_for_context,
        waiver_open_slots,
        waiver_team_frames,
    )
    import u1_answers as u1a

    position = str(position or "All positions")
    if position not in WAIVER_POSITION_FILTER_OPTIONS:
        return WaiverRecommendations(False, f"Unknown position filter: {position}.", position=position)
    context, stats_pool, league_df = _waiver_inputs(session)
    team = str(team or "").strip() or (active_league(session).my_team if context else "")
    if not context:
        return WaiverRecommendations(False, "There is no active league.", team=team, position=position)
    control = team_access(session, team)
    if not control.can_manage:
        return WaiverRecommendations(False, control.reason or f"You can't manage {team}.", team=team, position=position)
    if stats_pool.empty:
        return WaiverRecommendations(False, "Current-season stats aren't loaded yet. Open League Standings and load "
                                            "them, then return to Waiver Wire.", team=team, position=position)
    league_df, my_roster = waiver_team_frames(context, league_df, team)
    computed = compute_waiver_recommendations(context, my_roster=my_roster, league_df=league_df, stats_pool=stats_pool,
                                              categories=waiver_categories_for_context(context))
    needs = computed["needs"]
    adds = computed["adds"]
    adds = apply_waiver_position_filter(adds, position) if not adds.empty else adds
    open_slots = waiver_open_slots(context, my_roster)
    n = max(1, min(int(limit or 3), 15))
    cards = []
    for rank, (_, row) in enumerate(adds.head(n).iterrows(), start=1):
        card = waiver_card_fields(row, my_roster)
        positions = _positions(card["positions"])
        cards.append({"rank": rank, **card, "eligible_positions": positions,
                      "fills_open_spot": tuple(p for p in positions if p in set(open_slots)),
                      "stats": _stat_values(row), "available": True})
    drop_rows = []
    drops = computed["drops"]
    for rank, (_, row) in enumerate((drops.head(n) if isinstance(drops, pd.DataFrame) else pd.DataFrame()).iterrows(),
                                    start=1):
        drop_rows.append({"rank": rank, "player": str(row.get("Player") or row.get("fullName") or ""),
                          "positions": str(row.get("Eligible Positions") or row.get("Primary Position") or "").strip(),
                          "why": str(row.get("Why Drop") or "").strip(), "stats": _stat_values(row)})
    where = "" if position == "All positions" else f" at {position}"
    ranks = {str(k): int(v) for k, v in (needs.get("category_ranks") or {}).items()}
    return WaiverRecommendations(
        True, "", team=team, position=position, headline=u1a.needs_headline(needs),
        body=f"Best free agents for {team or 'your team'}{where}, picked for those needs from current-season stats.",
        weak_categories=tuple(str(c) for c in (needs.get("weaknesses") or ())), category_ranks=ranks,
        team_count=int(needs.get("n_teams") or 0), open_roster_spots=tuple(str(s) for s in open_slots),
        adds=tuple(cards), drops=tuple(drop_rows), acting_as=control.mode,
    )


@dataclass(frozen=True)
class PlayerPool:
    available: bool
    reason: str = ""
    total: int = 0  # players matching, before the limit
    rows: tuple[dict[str, Any], ...] = ()  # player, mlb_team, positions, stats
    unrostered_only: bool = True
    position: str = "All positions"
    loaded_at: str = ""
    basis: str = "Current-season stats this session already loaded (never fetched for a question)."


def loaded_player_pool(session: Any, *, position: str = "All positions", query: str = "",
                       unrostered_only: bool = True, limit: int = 25) -> PlayerPool:
    """The current-season player pool the Waiver Wire already loaded, bounded: unrostered
    players by default (``fantasy_waiver_wire.build_waiver_pool``: rostered anywhere in the
    league, pitchers in hitter-only leagues and positions the league doesn't use are left out),
    in the pool's own order, optionally by position and name. ``limit`` is at most 100."""
    from fantasy_waiver_wire import (
        WAIVER_POSITION_FILTER_OPTIONS,
        apply_waiver_position_filter,
        build_waiver_pool,
        filter_waiver_names_by_search,
    )

    position = str(position or "All positions")
    if position not in WAIVER_POSITION_FILTER_OPTIONS:
        return PlayerPool(False, f"Unknown position filter: {position}.", position=position)
    context, stats_pool, _league_df = _waiver_inputs(session)
    if not context:
        return PlayerPool(False, "There is no active league.", position=position)
    _frame, loaded_at = loaded_roster_stats(session)
    if stats_pool.empty:
        return PlayerPool(False, "Current-season stats aren't loaded yet. Open League Standings and load them.",
                          position=position, loaded_at=loaded_at)
    pool = build_waiver_pool(stats_pool, context) if unrostered_only else stats_pool.copy()
    pool = apply_waiver_position_filter(pool, position) if not pool.empty else pool
    if str(query or "").strip() and not pool.empty and "Player" in pool.columns:
        keep = set(filter_waiver_names_by_search(pool["Player"].astype(str).tolist(), str(query)))
        pool = pool[pool["Player"].astype(str).isin(keep)]
    n = max(1, min(int(limit or 25), 100))
    rows = tuple(
        {"player": str(r.get("Player") or r.get("fullName") or ""), "mlb_team": str(r.get("MLB Team") or r.get("Team") or ""),
         "positions": _positions(str(r.get("Eligible Positions") or r.get("Primary Position") or "")),
         "stats": _stat_values(r)}
        for _, r in pool.head(n).iterrows()
    )
    return PlayerPool(True, "", total=int(len(pool)), rows=rows, unrostered_only=bool(unrostered_only),
                      position=position, loaded_at=loaded_at)


# --- Trade Center draft -----------------------------------------------------------------------


@dataclass(frozen=True)
class PendingTrade:
    allowed: bool
    reason: str = ""
    team: str = ""
    give: tuple[str, ...] = ()
    receive: tuple[str, ...] = ()
    partner: str = ""  # the effective partner (the receive players' team when "Any team" is chosen)
    source: str = "none"  # "builder" (the Trade Center selections), "saved_state", or "none"
    pending_update: bool = False  # a queued change (e.g. a handoff) not yet shown in Trade Center
    is_complete: bool = False  # both sides chosen and one partner: ready to evaluate
    last_analysis: dict[str, Any] = field(default_factory=dict)  # verdict + weighted_gain if analyzed as is
    basis: str = "The trade currently in Trade Center's builder for your team. Read only: nothing is proposed."


def pending_trade_draft(session: Any, team: str = "") -> PendingTrade:
    """The give/receive lists being composed in Trade Center for ``team`` (default: yours), so
    "What do you think of this trade?" can be evaluated with ``evaluate_trade_for_team``.
    Team-private: ``team_access(...).can_manage`` is required. The builder belongs to your own
    team; a commissioner proxy trade is made in the Commissioner Tools panel and isn't here.

    Sources: ``fantasy_trade_builder_state.trade_scope_fingerprint`` / ``trade_scope_state_key``
    / ``read_builder_selection`` (the keys Trade Center writes) and ``resolve_effective_partner``."""
    context = peek_active_league_context(session)
    team = str(team or "").strip() or (active_league(session).my_team if context else "")
    if not context:
        return PendingTrade(False, "There is no active league.", team=team)
    control = team_access(session, team)
    if not control.can_manage:
        return PendingTrade(False, control.reason or f"You can't manage {team}.", team=team)
    from fantasy_league_identity import resolve_canonical_league_id
    from fantasy_trade_analysis import analysis_matches_selection
    from fantasy_trade_builder_state import (
        ANY_TRADE_PARTNER,
        read_builder_selection,
        resolve_effective_partner,
        trade_scope_fingerprint,
        trade_scope_state_key,
    )

    league_id = str(resolve_canonical_league_id(context) or "").strip() or str(context.get("league_context_id") or "")
    view = isolated_session_view(session)
    selection = read_builder_selection(view, trade_scope_state_key(trade_scope_fingerprint(team, league_id)))
    give, receive = selection["give"], selection["receive"]
    roster_stats, _loaded_at = loaded_roster_stats(session)
    partner = selection["partner"]
    if not roster_stats.empty:
        partner = resolve_effective_partner(partner, receive, roster_stats, my_team=team)
    partner = "" if partner == ANY_TRADE_PARTNER else partner
    analysis = selection["analysis"]
    last = {}
    if analysis_matches_selection(analysis, give=give, receive=receive):
        last = {"verdict": str(analysis.get("verdict") or ""), "weighted_gain": float(analysis.get("weighted_gain") or 0.0)}
    return PendingTrade(True, "", team=team, give=tuple(give), receive=tuple(receive), partner=partner,
                        source=selection["source"], pending_update=bool(selection["pending_update"]),
                        is_complete=bool(give and receive and partner), last_analysis=last)


# --- Scoring periods --------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekView:
    available: bool
    reason: str = ""
    number: int = 0
    label: str = ""
    dates: str = ""
    start: str = ""
    end: str = ""
    status: str = ""  # upcoming / active / locked / finalized
    status_label: str = ""  # "Upcoming", "In progress", "Ended — awaiting finalization", "Final"
    finalized: bool = False
    finalized_at: str = ""
    current_week: int | None = None  # the first week not finalized
    last_finalized_week: int | None = None
    weeks: tuple[int, ...] = ()
    categories: tuple[str, ...] = ()
    category_table: tuple[dict[str, Any], ...] = ()  # finalized only: Team, categories, points, Total Points, Rank
    team: str = ""
    team_lineup: dict[str, Any] | None = None  # starters, bench, empty_slots, set_after_lock (None: not visible)
    team_result: dict[str, Any] | None = None  # finalized only: totals, rates, starters with matched_by
    lineup_visibility: str = ""  # "visible", "private" (week not started), "not_set"
    basis: str = (
        "The league's season ledger: each team's lineup is frozen when saved, and a finalized week's results "
        "never change. Later drops and trades don't affect a completed week."
    )


def _snapshot_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    starters = [
        {"slot": s.get("slot"), "slot_key": s.get("slot_key"), "player": s.get("player_name"),
         "eligible_positions": list(s.get("eligible_positions") or []), "eligible_for_slot": s.get("eligible_for_slot"),
         "owner_at_snapshot": s.get("owner_at_snapshot")}
        for s in (snapshot.get("starters") or []) if isinstance(s, dict)
    ]
    return {"starters": starters, "bench": [b.get("player_name") for b in (snapshot.get("bench") or []) if isinstance(b, dict)],
            "empty_slots": list(snapshot.get("empty_slots") or []), "set_after_lock": bool(snapshot.get("set_after_lock")),
            "saved_at": str(snapshot.get("saved_at") or "")}


def week_view(session: Any, number: int | None = None, team: str = "") -> WeekView:
    """One scoring period from the season ledger, in a stable shape (no storage internals, no
    user ids or audit log). ``number`` defaults to the current week; ``last_finalized_week`` is
    "last week". With ``team``: that team's frozen lineup — another team's lineup only once the
    week has started — and, when finalized, its result per starter (``matched_by``: player_id,
    name, or no_games).

    Sources: ``fantasy_season_ledger.list_periods / get_period / period_status /
    period_date_label / current_period_number / get_period_lineup`` and
    ``fantasy_season_results.period_result / period_category_table / scoring_categories``."""
    context = peek_active_league_context(session)
    if not context:
        return WeekView(False, "There is no active league.")
    from fantasy_season_ledger import (
        PERIOD_FINALIZED,
        PERIOD_UPCOMING,
        current_period_number,
        get_period,
        get_period_lineup,
        ledger_initialized,
        list_periods,
        period_date_label,
        period_status,
    )
    from fantasy_season_ledger_ui import STATUS_LABELS
    from fantasy_season_results import period_category_table, period_result, scoring_categories

    if not ledger_initialized(context):
        return WeekView(False, "This league has no season calendar yet, so it has no scoring weeks.")
    periods = list_periods(context)
    weeks = tuple(int(p["number"]) for p in periods)
    finalized = [int(p["number"]) for p in periods if period_status(p) == PERIOD_FINALIZED]
    current = current_period_number(context)
    number = int(number) if number is not None else (current or (finalized[-1] if finalized else weeks[0]))
    period = get_period(context, number)
    base = dict(current_week=current, last_finalized_week=finalized[-1] if finalized else None, weeks=weeks,
                categories=tuple(scoring_categories(context)))
    if not period:
        return WeekView(False, f"Week {number} is not on the league calendar.", number=number, **base)
    status = period_status(period)
    is_final = status == PERIOD_FINALIZED
    table = period_category_table(context, number) if is_final else pd.DataFrame()
    rows = tuple({k: (v.item() if hasattr(v, "item") else v) for k, v in rec.items()} for rec in table.to_dict("records"))
    out = dict(available=True, number=number, label=str(period.get("label") or f"Week {number}"),
               dates=period_date_label(period), start=str(period.get("start") or ""), end=str(period.get("end") or ""),
               status=status, status_label=STATUS_LABELS.get(status, ""), finalized=is_final,
               finalized_at=str(period.get("finalized_at") or ""), category_table=rows, **base)
    team = str(team or "").strip()
    if not team:
        return WeekView(**out)
    from fantasy_team_control import league_team_names

    if team not in league_team_names(context):
        return WeekView(**{**out, "available": False, "reason": f"{team} is not a team in this league.", "team": team})
    snapshot = get_period_lineup(context, number, team)
    if status == PERIOD_UPCOMING and not team_access(session, team).can_manage:
        return WeekView(**out, team=team, lineup_visibility="private")
    lineup = _snapshot_view(snapshot) if snapshot else None
    result = None
    if is_final:
        res = ((period_result(context, number) or {}).get("teams") or {}).get(team)
        if isinstance(res, dict):
            result = {"lineup_missing": bool(res.get("lineup_missing")), "totals": dict(res.get("totals") or {}),
                      "rates": dict(res.get("rates") or {}), "starters": [dict(s) for s in (res.get("starters") or [])],
                      "bench": list(res.get("bench") or []), "empty_slots": list(res.get("empty_slots") or []),
                      "set_after_lock": bool(res.get("set_after_lock"))}
    return WeekView(**out, team=team, team_lineup=lineup, team_result=result,
                    lineup_visibility="visible" if snapshot else "not_set")
