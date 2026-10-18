"""Read-only fantasy league tools over the shared interfaces (Phase C/D).

Every number comes from ``fantasy_read_api``, which reads the league through ``fantasy_league_peek``.
Nothing here computes a fantasy statistic, writes the session, fetches data or changes a league:

* league resolution runs on an isolated copy of the session (``fantasy_league_peek``);
* standings keep the API's ``kind`` / ``label`` — official (sum of finalized weeks) and the
  current-roster what-if are never mixed;
* team-perspective data (lineups, trades, a team's weaknesses as advice) requires
  ``team_access(...).can_manage`` — the owner, or the commissioner acting for an unclaimed team —
  and the team must actually be in the league;
* roster stats are only the ones a page already loaded (``loaded_roster_stats``);
* weeks, lineup status, ownership, waivers, the loaded pool and the Trade Center card come from
  the shared readers (``week_view``, ``week_lineup_status``, ``player_owner``,
  ``waiver_recommendations_view``, ``loaded_player_pool``, ``evaluate_trade_for_team``,
  ``pending_trade_draft``); AMI recomputes none of them.

There are deliberately no tools for Save Lineup, Use Suggested Lineup, waiver moves, trades or
finalizing a week.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from ami_assistant.safety import clean_text
from ami_assistant.tools.registry import (
    BAD_ARGUMENT,
    MISSING_ACTIVE_LEAGUE,
    UNKNOWN_PLAYER,
    ToolResult,
    fail,
    tool,
)
from player_name_normalization import normalize_player_name_for_merge

NO_ROSTER_STATS = "no_roster_stats"
NO_SEASON_CALENDAR = "no_season_calendar"
NOT_YOUR_TEAM = "not_your_team"
UNKNOWN_TEAM = "unknown_team"
NO_PENDING_TRADE = "no_pending_trade"
LOAD_STATS_HINT = (
    "Current roster stats aren't loaded in this session. Open League Standings and load stats under "
    "“How current rosters would rank”, then ask again."
)
SLOT_NAMES = {"C": "catcher", "1B": "first base", "2B": "second base", "3B": "third base", "SS": "shortstop",
              "OF": "outfield", "DH": "utility (DH)", "UTIL": "utility", "P": "pitcher"}


# --- helpers ----------------------------------------------------------------------------------


def _api():
    import fantasy_read_api

    return fantasy_read_api


def _no_league(tool_name: str) -> ToolResult:
    return fail(
        tool_name,
        MISSING_ACTIVE_LEAGUE,
        "You don't have an active league in this session. Pick one in Saved Draft Library (under My League), "
        "or draft one first.",
    )


def _num(value: Any) -> Any:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return clean_text(value, 80)
    if pd.isna(v):
        return None
    return int(v) if v.is_integer() else round(v, 4)


def _records(frame: pd.DataFrame, columns: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    cols = [c for c in (columns or list(frame.columns)) if c in frame.columns]
    return [{c: _num(r[c]) if c not in ("Team", "Player", "Fantasy Team") else clean_text(r[c], 80) for c in cols}
            for _, r in frame.head(limit).iterrows()]


def access_payload(control: Any, team: str) -> dict[str, Any]:
    """How the user relates to ``team``, in words the answer can use verbatim."""
    mode = str(getattr(control, "mode", "none") or "none")
    if mode == "owner":
        text = f"{team} is your team."
    elif mode == "commissioner_proxy":
        text = f"You're viewing {team} as commissioner; the team is currently unclaimed."
    else:
        text = clean_text(getattr(control, "reason", ""), 160) or f"{team} is managed by someone else."
    return {"team": team, "mode": mode, "can_manage": bool(getattr(control, "can_manage", False)),
            "is_commissioner": bool(getattr(control, "is_commissioner", False)), "text": text}


def _resolve_team(session: Any, league: Any, team: str | None, tool_name: str) -> tuple[str, dict[str, Any], ToolResult | None]:
    """The league team a question is about (default: my team) and the user's access to it."""
    names = list(league.team_names)
    wanted = str(team or league.my_team or "").strip()
    if not wanted:
        return "", {}, fail(tool_name, UNKNOWN_TEAM, "This league doesn't say which team is yours yet. Claim your team "
                                                  "in Saved Draft Library or the league invite.")
    match = next((n for n in names if n.lower() == wanted.lower()), "")
    if not match:
        return "", {}, fail(tool_name, UNKNOWN_TEAM, f"There's no team called “{wanted}” in {league.league_name or 'this league'}.",
                            teams=names)
    access = access_payload(_api().team_access(session, match), match)
    return match, access, None


def _require_manage(access: dict[str, Any], tool_name: str) -> ToolResult | None:
    if access.get("can_manage"):
        return None
    return fail(tool_name, NOT_YOUR_TEAM, access["text"] + " AMI only shows lineups and team advice for a team you "
                "manage.", access=access)


def _team_frame(session: Any, team: str) -> tuple[pd.DataFrame, str]:
    frame, loaded_at = _api().loaded_roster_stats(session)
    if frame.empty or "Team" not in frame.columns:
        return pd.DataFrame(), loaded_at
    return frame[frame["Team"].astype(str) == team].copy(), loaded_at


def _scoring_format(league: Any) -> str:
    return str(getattr(league, "scoring_format", "") or "5x5 Roto")


def _find_row(frame: pd.DataFrame, player: str) -> pd.Series | None:
    """A roster row by full name, else by an unambiguous surname."""
    if frame is None or frame.empty or "Player" not in frame.columns:
        return None
    want = normalize_player_name_for_merge(player)
    norm = frame["Player"].map(normalize_player_name_for_merge)
    hit = frame[norm == want]
    if hit.empty and " " not in want:
        hit = frame[norm.str.split(" ").str[-1] == want]
    return hit.iloc[0] if len(hit) == 1 else None


def normalize_slot(slot: str) -> str:
    s = str(slot or "").strip().upper()
    return {"DH/UTIL": "UTIL", "SHORTSTOP": "SS", "CATCHER": "C"}.get(s, s)


def league_brief(session: Any) -> dict[str, Any] | None:
    """Small league context for AMI (also used by the page context line). Never writes."""
    league = _api().active_league(session)
    if league is None:
        return None
    brief: dict[str, Any] = {
        "league_name": clean_text(league.league_name, 80),
        "my_team": clean_text(league.my_team, 80),
        "teams": [clean_text(t, 80) for t in league.team_names],
        "scoring_format": _scoring_format(league),
        "lineup_slots": list(league.lineup_slots),
        "has_season_calendar": bool(league.has_season_calendar),
        "finalized_weeks": list(league.finalized_weeks),
        "coherent": bool(league.coherent),
    }
    if league.my_team:
        brief["access"] = access_payload(_api().team_access(session, league.my_team), league.my_team)
    if league.has_season_calendar:
        week = _api().week_view(session)  # the current week, as the league pages show it
        if week.available:
            brief["current_week"] = {"number": int(week.number), "label": clean_text(week.label, 40),
                                     "dates": clean_text(week.dates, 60), "status": clean_text(week.status, 20),
                                     "finalized": bool(week.finalized)}
    return brief


# --- league -----------------------------------------------------------------------------------


@tool(
    "get_active_league",
    capability="fantasy_team",
    description="The league the fantasy pages show: name, your team and your access to it, teams, lineup slots, "
                "the current week and which weeks are final.",
    reuses=("fantasy_read_api.active_league", "fantasy_read_api.team_access", "fantasy_read_api.week_view"),
    needs_session=True,
)
def get_active_league(*, session: Mapping[str, Any]) -> ToolResult:
    brief = league_brief(session)
    if brief is None:
        return _no_league("get_active_league")
    return ToolResult(tool="get_active_league", ok=True, data=brief)


# --- standings --------------------------------------------------------------------------------


@tool(
    "get_official_standings",
    capability="fantasy_team",
    description="League Standings (official) — the sum of finalized weeks — with a team's place, gap to first, "
                "strongest categories and closest category gains (the same chips League Standings shows).",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.official_standings_view", "u1_answers.category_strengths_and_gaps",
            "fantasy_read_api.week_view (categories)"),
    needs_session=True,
)
def get_official_standings(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_official_standings")
    name, access, err = _resolve_team(session, league, team, "get_official_standings")
    if err:
        return err
    view = api.official_standings_view(session)
    data: dict[str, Any] = {"kind": view.kind, "label": view.label, "basis": view.basis, "note": view.note,
                            "finalized_weeks": list(view.finalized_weeks), "team": name, "access": access,
                            "league_name": clean_text(league.league_name, 80), "team_count": len(league.team_names)}
    table = view.table
    if table is None or table.empty:
        data["rows"] = []
        return ToolResult(tool="get_official_standings", ok=True, data=data)
    import u1_answers

    categories = tuple(api.week_view(session).categories)  # the league's scoring categories
    data["categories"] = list(categories)
    data["rows"] = _records(table, ["Rank", "Team", "Total Points"])
    mine = table[table["Team"].astype(str) == name]
    if not mine.empty:
        me = mine.iloc[0]
        rank, points = int(me["Rank"]), float(me["Total Points"])
        leader_points = float(pd.to_numeric(table["Total Points"]).max())
        ahead = table[pd.to_numeric(table["Total Points"]) > points]
        data["position"] = {
            "rank": rank,
            "tied": int((table["Rank"] == rank).sum()) > 1,
            "points": _num(points),
            "behind_first": _num(leader_points - points),
            "next_team_up": (clean_text(ahead.sort_values("Total Points").iloc[0]["Team"], 80) if not ahead.empty else ""),
            "behind_next": (_num(float(ahead["Total Points"].min()) - points) if not ahead.empty else 0),
        }
        data["by_category"] = [
            {"category": c, "value": _num(me.get(c)), "points": _num(me.get(f"{c} Points"))} for c in categories
        ]
        # The exact phrases League Standings shows as chips; all opportunities, not just two.
        notes = u1_answers.category_strengths_and_gaps(table, name, categories, max_gaps=len(categories))
        data["strengths"] = list(notes["strengths"])
        data["opportunities"] = list(notes["opportunities"])
    return ToolResult(tool="get_official_standings", ok=True, data=data)


@tool(
    "get_current_roster_standings",
    capability="fantasy_team",
    description="How current rosters would rank (not official standings): today's rosters on season-to-date stats. "
                "Analysis only — never the league standings.",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.loaded_roster_stats", "fantasy_read_api.current_roster_standings_view"),
    needs_session=True,
)
def get_current_roster_standings(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_current_roster_standings")
    name, access, err = _resolve_team(session, league, team, "get_current_roster_standings")
    if err:
        return err
    frame, loaded_at = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("get_current_roster_standings", NO_ROSTER_STATS, LOAD_STATS_HINT)
    view = api.current_roster_standings_view(frame, _scoring_format(league))
    table = view.table
    data: dict[str, Any] = {"kind": view.kind, "label": view.label, "basis": view.basis, "note": view.note,
                            "loaded_at": clean_text(loaded_at, 40), "team": name, "access": access,
                            "rows": _records(table, ["League Rank", "Fantasy Team", "Total Roto Points"])}
    mine = table[table["Fantasy Team"].astype(str) == name] if "Fantasy Team" in table.columns else pd.DataFrame()
    if not mine.empty:
        rank = mine.iloc[0].get("League Rank")
        data["position"] = {"rank": _num(rank), "tied": int((table["League Rank"] == rank).sum()) > 1,
                            "points": _num(mine.iloc[0].get("Total Roto Points"))}
    return ToolResult(tool="get_current_roster_standings", ok=True, data=data)


# --- weeks (fantasy_read_api.week_view) -------------------------------------------------------


def _week_info(view: Any) -> dict[str, Any]:
    return {"number": int(view.number), "label": clean_text(view.label, 40), "dates": clean_text(view.dates, 60),
            "status": clean_text(view.status, 20), "status_label": clean_text(view.status_label, 60),
            "finalized": bool(view.finalized)}


def _week(session: Mapping[str, Any], tool_name: str, week: Any, which: str, team: str = "") -> tuple[Any, ToolResult | None]:
    """The week asked about, from ``week_view``. ``which``: "current" or "last_final" when no number."""
    api = _api()
    number = None
    if week not in (None, ""):
        try:
            number = int(week)
        except (TypeError, ValueError):
            return None, fail(tool_name, BAD_ARGUMENT, f"“{week}” isn't a week number.")
    if number is None and which == "last_final":
        probe = api.week_view(session)
        if not probe.available:
            return None, _week_unavailable(tool_name, probe)
        if probe.last_finalized_week is None:
            return None, fail(tool_name, BAD_ARGUMENT, "No week is final yet.", weeks=list(probe.weeks))
        number = probe.last_finalized_week
    view = api.week_view(session, number, team=team)
    if not view.available:
        return None, _week_unavailable(tool_name, view)
    return view, None


def _week_unavailable(tool_name: str, view: Any) -> ToolResult:
    reason = clean_text(view.reason, 200)
    if "season calendar" in reason:
        return fail(tool_name, NO_SEASON_CALENDAR, reason + " The commissioner sets it on the Lineup page "
                    "(“Set the season calendar”).")
    if "not a team" in reason:
        return fail(tool_name, UNKNOWN_TEAM, reason)
    if "no active league" in reason.lower():
        return _no_league(tool_name)
    weeks = list(getattr(view, "weeks", ()) or ())
    if weeks:
        reason += f" (weeks {min(weeks)}–{max(weeks)})"
    return fail(tool_name, BAD_ARGUMENT, reason, weeks=weeks)


@tool(
    "get_week",
    capability="fantasy_team",
    description="One scoring week: dates and status (upcoming/active/locked/finalized), and once final, the week's "
                "category table and your team's totals. Default: the last finalized week.",
    parameters={"properties": {"week": {"type": "integer"}, "team": {"type": "string"},
                               "which": {"type": "string", "enum": ["last_final", "current"]}}},
    reuses=("fantasy_read_api.week_view",),
    needs_session=True,
)
def get_week(*, session: Mapping[str, Any], week: Any = None, team: str | None = None, which: str = "last_final") -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_week")
    name, access, err = _resolve_team(session, league, team, "get_week")
    if err:
        return err
    view, err = _week(session, "get_week", week, which, team=name)
    if err:
        return err
    data: dict[str, Any] = {"week": _week_info(view), "team": name, "access": access, "basis": view.basis}
    if view.finalized:
        data["table"] = [{"Rank": _num(r.get("Rank")), "Team": clean_text(r.get("Team"), 80),
                          "Total Points": _num(r.get("Total Points"))} for r in view.category_table]
        mine = next((r for r in view.category_table if str(r.get("Team")) == name), None)
        if mine is not None:
            data["rank"], data["points"] = _num(mine.get("Rank")), _num(mine.get("Total Points"))
        result = view.team_result or {}
        data["totals"] = {k: _num(v) for k, v in (result.get("totals") or {}).items() if k in ("AB", "H", "HR", "R", "RBI", "SB")}
        data["rates"] = {k: _num(v) for k, v in (result.get("rates") or {}).items()}
        data["lineup_missing"] = bool(result.get("lineup_missing"))
    return ToolResult(tool="get_week", ok=True, data=data)


@tool(
    "get_week_lineup",
    capability="fantasy_team",
    description="The lineup saved for a week (starters by slot, bench, empty slots) — the frozen snapshot that week is "
                "scored from. Another team's lineup only once its week has started.",
    parameters={"properties": {"week": {"type": "integer"}, "team": {"type": "string"},
                               "which": {"type": "string", "enum": ["current", "last_final"]}}},
    reuses=("fantasy_read_api.week_view",),
    needs_session=True,
)
def get_week_lineup(*, session: Mapping[str, Any], week: Any = None, team: str | None = None,
                    which: str = "current") -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_week_lineup")
    name, access, err = _resolve_team(session, league, team, "get_week_lineup")
    if err:
        return err
    view, err = _week(session, "get_week_lineup", week, which, team=name)
    if err:
        return err
    if view.lineup_visibility == "private":
        return fail("get_week_lineup", NOT_YOUR_TEAM, f"{name}'s {view.label} lineup stays private until the week starts.")
    snap = view.team_lineup or {}
    data: dict[str, Any] = {"week": _week_info(view), "team": name, "access": access, "saved": bool(snap)}
    if snap:
        data["starters"] = [{"slot": clean_text(s.get("slot"), 10), "player": clean_text(s.get("player"), 80),
                             "eligible_positions": [clean_text(p, 6) for p in s.get("eligible_positions") or []]}
                            for s in snap.get("starters") or []]
        data["bench"] = [clean_text(b, 80) for b in snap.get("bench") or []]
        data["empty_slots"] = [clean_text(e if not isinstance(e, Mapping) else e.get("slot"), 10) for e in snap.get("empty_slots") or []]
        data["set_after_lock"] = bool(snap.get("set_after_lock"))
    return ToolResult(tool="get_week_lineup", ok=True, data=data)


@tool(
    "explain_player_week",
    capability="fantasy_team",
    description="Why a player did or didn't count for a team in a finalized week, from that week's frozen lineup and "
                "scored result — not from today's roster.",
    parameters={"properties": {"player": {"type": "string"}, "week": {"type": "integer"}, "team": {"type": "string"}},
                "required": ["player"]},
    reuses=("fantasy_read_api.week_view", "fantasy_read_api.player_owner"),
    needs_session=True,
)
def explain_player_week(*, session: Mapping[str, Any], player: str, week: Any = None, team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("explain_player_week")
    name, access, err = _resolve_team(session, league, team, "explain_player_week")
    if err:
        return err
    view, err = _week(session, "explain_player_week", week, "last_final", team=name)
    if err:
        return err
    if view.lineup_visibility == "private":
        return fail("explain_player_week", NOT_YOUR_TEAM, f"{name}'s {view.label} lineup stays private until the week starts.")
    want = normalize_player_name_for_merge(player)

    def same(n: Any) -> bool:
        cand = normalize_player_name_for_merge(n)
        return cand == want or (" " not in want and cand.split(" ")[-1:] == [want])

    snap = view.team_lineup or {}
    in_snapshot = [str(s.get("player") or "") for s in snap.get("starters") or []] + [str(b or "") for b in snap.get("bench") or []]
    snap_name = next((n for n in in_snapshot if n and same(n)), "")
    owner = api.player_owner(session, snap_name or player)  # today's owner, for contrast only
    data: dict[str, Any] = {"week": _week_info(view), "team": name, "access": access,
                            "player": clean_text(snap_name or owner.player or player, 80),
                            "owner_now": clean_text(owner.owner_team, 80), "owner_status": owner.status,
                            "on_a_roster": bool(owner.rostered), "basis": view.basis}
    if not view.finalized:
        data["reason"] = "not_final"
        return ToolResult(tool="explain_player_week", ok=True, data=data)
    result = view.team_result or {}
    starter = next((s for s in result.get("starters") or [] if same(s.get("player_name"))), None)
    if starter is not None:
        matched = str(starter.get("matched_by") or "").strip()
        data.update(reason="counted" if matched and matched != "no_games" else "no_stats",
                    slot=clean_text(starter.get("slot"), 10),
                    stats={k: _num(starter.get(k)) for k in ("AB", "H", "HR", "R", "RBI", "SB")})
    elif any(same(b) for b in snap.get("bench") or []):
        data["reason"] = "bench"
    elif result.get("lineup_missing") or not snap:
        data["reason"] = "no_lineup"
    else:
        data["reason"] = "not_in_lineup"
    return ToolResult(tool="explain_player_week", ok=True, data=data)


# --- lineups and eligibility ------------------------------------------------------------------


def _bench(frame: Any, rec: Any) -> list[str]:
    """Rostered players the recommendation leaves out (not the saved lineup's bench)."""
    if "Player" not in getattr(frame, "columns", ()):
        return []
    starters = set(rec["Player"].astype(str)) if "Player" in getattr(rec, "columns", ()) else set()
    return [clean_text(p, 80) for p in frame["Player"].astype(str) if p not in starters]


@tool(
    "get_lineup_status",
    capability="fantasy_team",
    description="The Lineup page's status for a team you manage: Not saved yet / Draft (not submitted) / Saved and "
                "locked, open positions, players who could fill them from the bench, and slots only a waiver add or "
                "trade can fill.",
    parameters={"properties": {"team": {"type": "string"}, "week": {"type": "integer"}}},
    reuses=("fantasy_read_api.week_lineup_status",),
    needs_session=True,
)
def get_lineup_status(*, session: Mapping[str, Any], team: str | None = None, week: Any = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_lineup_status")
    name, access, err = _resolve_team(session, league, team, "get_lineup_status")
    if err:
        return err
    denied = _require_manage(access, "get_lineup_status")
    if denied:
        return denied
    try:
        number = int(week) if week not in (None, "") else None
    except (TypeError, ValueError):
        return fail("get_lineup_status", BAD_ARGUMENT, f"“{week}” isn't a week number.")
    frame, _loaded = api.loaded_roster_stats(session)
    lineup = api.week_lineup_status(session, name, number, roster_stats=frame if not frame.empty else None)
    if not lineup.allowed:
        return fail("get_lineup_status", BAD_ARGUMENT, clean_text(lineup.reason, 200), access=access)
    texts = lambda xs: [clean_text(x, 80) for x in xs]  # noqa: E731
    return ToolResult(tool="get_lineup_status", ok=True, data={
        "team": name, "access": access, "week": int(lineup.week), "week_text": clean_text(lineup.week_text, 60),
        "status": clean_text(lineup.status, 40), "record_status": lineup.record_status, "locked": bool(lineup.locked),
        "edit_message": clean_text(lineup.edit_message, 200), "complete": bool(lineup.complete),
        "slots": [clean_text(label, 10) for _key, label in lineup.slots],
        "assignments": {clean_text(k, 10): clean_text(v, 80) for k, v in lineup.assignments.items() if v},
        "open_positions": texts(lineup.open_positions), "from_bench": texts(lineup.from_bench),
        "needs_waiver_or_trade": texts(lineup.needs_waiver_or_trade), "not_eligible": texts(lineup.not_eligible),
        "assigned_twice": texts(lineup.assigned_twice), "roster_loaded": bool(lineup.roster_loaded),
        "headline": clean_text(lineup.headline, 200), "body": clean_text(lineup.body, 400), "basis": lineup.basis,
    })


@tool(
    "get_lineup_report",
    capability="fantasy_team",
    description="The lineup report (Lineup & Trades page) for a team you manage: recommended starters by slot (Save Lineup's slot "
                "rule), slots the roster can't fill, warnings, and the diagnosis (strongest/weakest areas).",
    parameters={"properties": {"team": {"type": "string"}}},
    reuses=("fantasy_read_api.lineup_report", "fantasy_read_api.loaded_roster_stats"),
    needs_session=True,
)
def get_lineup_report(*, session: Mapping[str, Any], team: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_lineup_report")
    name, access, err = _resolve_team(session, league, team, "get_lineup_report")
    if err:
        return err
    denied = _require_manage(access, "get_lineup_report")
    if denied:
        return denied
    frame, loaded_at = _team_frame(session, name)
    if frame.empty:
        return fail("get_lineup_report", NO_ROSTER_STATS, LOAD_STATS_HINT)
    slots = list(league.lineup_slots) or None
    report = api.lineup_report(frame, slots=slots, scoring_format=_scoring_format(league))
    rec = report["recommended"]
    diag = report.get("diagnosis") or {}
    data = {
        "team": name, "access": access, "slots": slots or [], "loaded_at": clean_text(loaded_at, 40),
        "recommended": [{"slot": clean_text(r.get("Fantasy slot"), 10), "player": clean_text(r.get("Player"), 80),
                         "call": clean_text(r.get("Start/Sit Recommendation"), 20)} for _, r in rec.iterrows()],
        "bench": _bench(frame, rec),
        "missing_slots": [clean_text(s, 10) for s in report["missing_slots"]],
        "slot_warnings": [clean_text(w, 200) for w in report["slot_warnings"]],
        "strongest": clean_text(diag.get("strongest"), 120) if not isinstance(diag.get("strongest"), list)
        else [clean_text(x, 40) for x in diag.get("strongest")],
        "weakest": clean_text(diag.get("weakest"), 120) if not isinstance(diag.get("weakest"), list)
        else [clean_text(x, 40) for x in diag.get("weakest")],
        "basis": report.get("basis", ""),
    }
    return ToolResult(tool="get_lineup_report", ok=True, data=data)


@tool(
    "check_slot_eligibility",
    capability="fantasy_team",
    description="Can a rostered player fill a lineup slot? Uses the exact rule Save Lineup enforces (his eligible "
                "positions; no assumed 1B/3B or 2B/SS swaps).",
    parameters={"properties": {"player": {"type": "string"}, "slot": {"type": "string"}}, "required": ["player", "slot"]},
    reuses=("fantasy_read_api.explain_slot_eligibility", "fantasy_read_api.loaded_roster_stats"),
    needs_session=True,
)
def check_slot_eligibility(*, session: Mapping[str, Any], player: str, slot: str) -> ToolResult:
    api = _api()
    if api.active_league(session) is None:
        return _no_league("check_slot_eligibility")
    frame, _loaded = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("check_slot_eligibility", NO_ROSTER_STATS, LOAD_STATS_HINT)
    row = _find_row(frame, player)
    if row is None:
        return fail("check_slot_eligibility", UNKNOWN_PLAYER,
                    f"“{player}” isn't on a roster in this league (or the name matches more than one player).")
    result = api.explain_slot_eligibility(row, normalize_slot(slot))
    result = {k: (clean_text(v, 240) if isinstance(v, str) else v) for k, v in result.items()}
    result["team"] = clean_text(row.get("Team"), 80)
    return ToolResult(tool="check_slot_eligibility", ok=True, data=result)


@tool(
    "find_eligible_players",
    capability="fantasy_team",
    description="Which players on your roster can fill a slot (Save Lineup's rule), split into this week's starters "
                "and bench when a lineup is saved.",
    parameters={"properties": {"slot": {"type": "string"}, "team": {"type": "string"}, "bench_only": {"type": "boolean"}},
                "required": ["slot"]},
    reuses=("fantasy_read_api.explain_slot_eligibility", "fantasy_read_api.week_lineup_status"),
    needs_session=True,
)
def find_eligible_players(*, session: Mapping[str, Any], slot: str, team: str | None = None, bench_only: bool = False) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("find_eligible_players")
    name, access, err = _resolve_team(session, league, team, "find_eligible_players")
    if err:
        return err
    denied = _require_manage(access, "find_eligible_players")
    if denied:
        return denied
    frame, _loaded = _team_frame(session, name)
    if frame.empty:
        return fail("find_eligible_players", NO_ROSTER_STATS, LOAD_STATS_HINT)
    slot = normalize_slot(slot)
    # This week's saved starters, from the Lineup page's own status reader.
    status = api.week_lineup_status(session, name)
    saved = status.allowed and status.record_status in ("draft", "locked") and bool(status.assignments)
    starters = {normalize_player_name_for_merge(p) for p in status.assignments.values() if p} if saved else set()
    week = {"number": int(status.week), "label": clean_text(status.week_text, 60), "status": clean_text(status.status, 40)} if saved else None
    eligible = []
    for _, row in frame.iterrows():
        res = api.explain_slot_eligibility(row, slot)
        if res["eligible"]:
            eligible.append({"player": clean_text(row.get("Player"), 80), "eligible_positions": res["eligible_positions"],
                             "starting": normalize_player_name_for_merge(row.get("Player")) in starters})
    if bench_only and week is not None:
        eligible = [e for e in eligible if not e["starting"]]
    return ToolResult(tool="find_eligible_players", ok=True, data={
        "team": name, "access": access, "slot": slot, "slot_name": SLOT_NAMES.get(slot, slot), "week": week,
        "bench_only": bool(bench_only), "lineup_saved": week is not None, "eligible": eligible,
        "rule": api.ELIGIBILITY_RULE})


# --- players: ownership and the loaded pool ---------------------------------------------------


@tool(
    "get_player_owner",
    capability="fantasy_team",
    description="Who owns a player in your league right now: your team, another team, or nobody (a free agent).",
    parameters={"properties": {"player": {"type": "string"}}, "required": ["player"]},
    reuses=("fantasy_read_api.player_owner",),
    needs_session=True,
)
def get_player_owner(*, session: Mapping[str, Any], player: str) -> ToolResult:
    api = _api()
    if api.active_league(session) is None:
        return _no_league("get_player_owner")
    own = api.player_owner(session, player)
    if own.status == "no_league":
        return _no_league("get_player_owner")
    return ToolResult(tool="get_player_owner", ok=True, data={
        "player": clean_text(own.player or player, 80), "status": own.status, "owner_team": clean_text(own.owner_team, 80),
        "my_team": clean_text(own.my_team, 80), "rostered": bool(own.rostered), "in_loaded_pool": own.in_loaded_pool,
        "basis": own.basis})


@tool(
    "find_available_players",
    capability="fantasy_team",
    description="Unrostered players from the current-season pool this session already loaded (never fetched), "
                "optionally by position or name.",
    parameters={"properties": {"position": {"type": "string"}, "query": {"type": "string"},
                               "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
    reuses=("fantasy_read_api.loaded_player_pool",),
    needs_session=True,
)
def find_available_players(*, session: Mapping[str, Any], position: str | None = None, query: str = "",
                           limit: int = 10) -> ToolResult:
    api = _api()
    if api.active_league(session) is None:
        return _no_league("find_available_players")
    filt = waiver_position(position)
    pool = api.loaded_player_pool(session, position=filt, query=str(query or ""), limit=max(1, min(int(limit or 10), 25)))
    if not pool.available:
        return fail("find_available_players", NO_ROSTER_STATS, clean_text(pool.reason, 240))
    return ToolResult(tool="find_available_players", ok=True, data={
        "position": filt, "total": int(pool.total), "loaded_at": clean_text(pool.loaded_at, 40), "basis": pool.basis,
        "rows": [{"player": clean_text(r.get("player"), 80), "mlb_team": clean_text(r.get("mlb_team"), 10),
                  "positions": clean_text(r.get("positions"), 30),
                  "stats": {k: _num(v) for k, v in (r.get("stats") or {}).items()}} for r in pool.rows]})


def waiver_position(position: str | None) -> str:
    """AMI's slot code as the Waiver Wire's position filter ("All positions", "C", …, "DH/UTIL")."""
    slot = normalize_slot(position or "")
    return {"": "All positions", "DH": "DH/UTIL", "UTIL": "DH/UTIL"}.get(slot, slot)


# --- trades -----------------------------------------------------------------------------------


def _resolve_trade_player(session: Mapping[str, Any], name: str) -> Any:
    """A typed name → its rostered spelling and owner, by the shared ownership reader."""
    return _api().player_owner(session, name)


@tool(
    "evaluate_trade",
    capability="fantasy_team",
    description="What a trade would do for a team you manage — the Trade Center's own verdict card (Balanced / Favors "
                "your team / Favors the other team / Creates roster issue), roster issues (e.g. no catcher left), "
                "category changes and proposal checks. With no players named, the trade composed in Trade Center. "
                "Read-only — it never proposes or executes.",
    parameters={"properties": {"give": {"type": "array", "items": {"type": "string"}},
                               "receive": {"type": "array", "items": {"type": "string"}},
                               "partner": {"type": "string"}, "team": {"type": "string"}, "slot": {"type": "string"}}},
    reuses=("fantasy_read_api.evaluate_trade_for_team", "fantasy_read_api.pending_trade_draft",
            "fantasy_read_api.player_owner"),
    needs_session=True,
)
def evaluate_trade(*, session: Mapping[str, Any], give: list[str] | None = None, receive: list[str] | None = None,
                   partner: str | None = None, team: str | None = None, slot: str | None = None) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("evaluate_trade")
    name, access, err = _resolve_team(session, league, team, "evaluate_trade")
    if err:
        return err
    frame, _loaded = api.loaded_roster_stats(session)
    if frame.empty:
        return fail("evaluate_trade", NO_ROSTER_STATS, LOAD_STATS_HINT)
    source = "named"
    if not give and not receive:
        # "What do you think of this trade?": the trade being composed in Trade Center.
        draft = api.pending_trade_draft(session, name)
        if not draft.allowed:
            return fail("evaluate_trade", NOT_YOUR_TEAM, clean_text(draft.reason, 200) or access["text"], access=access)
        if not draft.is_complete:
            return fail("evaluate_trade", NO_PENDING_TRADE,
                        "There's no complete trade in Trade Center yet (pick players on both sides). Or name the players, "
                        "e.g. “Would trading Aaron Judge for Kyle Tucker leave me without a catcher?”",
                        give=list(draft.give), receive=list(draft.receive))
        give_names, recv_names, partner_team, source = list(draft.give), list(draft.receive), draft.partner, "trade_center"
    else:
        owners = [_resolve_trade_player(session, p) for p in list(give or []) + list(receive or [])]
        unknown = [o.query for o in owners if not o.rostered]
        if unknown or not give or not receive:
            return fail("evaluate_trade", UNKNOWN_PLAYER, "I couldn't match "
                        + (", ".join(f"“{m}”" for m in unknown) if unknown else "the players")
                        + " to a roster in this league. Name the players on each side.")
        gives, recvs = owners[:len(give or [])], owners[len(give or []):]
        not_mine = [o.player for o in gives if o.owner_team != name]
        if not_mine:
            return fail("evaluate_trade", BAD_ARGUMENT, f"{', '.join(not_mine)} {'is' if len(not_mine) == 1 else 'are'} "
                        f"not on {name}, so {name} can't trade {'him' if len(not_mine) == 1 else 'them'}.")
        give_names, recv_names = [o.player for o in gives], [o.player for o in recvs]
        teams = {o.owner_team for o in recvs}
        partner_team = str(partner or (teams.pop() if len(teams) == 1 else "")).strip()
        if not partner_team:
            return fail("evaluate_trade", BAD_ARGUMENT, "The players you'd receive are on different teams; which team is the trade with?")
    ev = api.evaluate_trade_for_team(session, my_team=name, partner_team=partner_team, give=give_names,
                                     receive=recv_names, roster_stats=frame, scoring_format=_scoring_format(league))
    if not ev.allowed:
        return fail("evaluate_trade", NOT_YOUR_TEAM, clean_text(ev.reason, 200) or access["text"], access=access)
    texts = lambda xs, n=240: [clean_text(x, n) for x in xs]  # noqa: E731
    data: dict[str, Any] = {
        "team": name, "partner": clean_text(partner_team, 80), "give": give_names, "receive": recv_names,
        "source": source, "access": access, "acting_as": ev.acting_as,
        # The Trade Center card, as the card shows it.
        "verdict_label": clean_text(ev.verdict_label, 40), "value_label": clean_text(ev.value_label, 40),
        "verdict_headline": clean_text(ev.verdict_headline, 200), "verdict_body": clean_text(ev.verdict_body, 400),
        "required_position_issues": texts(ev.required_position_issues),
        "roster_size_issues": texts(ev.roster_size_issues), "open_roster_spots": texts(ev.open_roster_spots),
        "other_team_notes": texts(ev.other_team_notes),
        "roster_issues": [{"team": clean_text(i.get("team"), 80), "kind": clean_text(i.get("kind"), 10),
                           "slot": clean_text(i.get("slot"), 10), "message": clean_text(i.get("message"), 240)}
                          for i in ev.roster_issues],
        "category_changes": [{k: (_num(v) if k != "category" else clean_text(v, 10)) for k, v in dict(c).items()}
                             for c in ev.category_changes],
        "helps": texts(ev.helps, 10), "hurts": texts(ev.hurts, 10),
        "verdict": clean_text(ev.verdict, 40), "weighted_gain": _num(ev.weighted_gain),
        "proposal_ok": bool(ev.proposal_ok), "proposal_message": clean_text(ev.proposal_message, 200), "basis": ev.basis,
    }
    if slot:
        # "Would this leave me without a catcher?" — straight from the shared roster issues.
        slot = normalize_slot(slot)
        gap = [i for i in data["roster_issues"] if i["team"] == name and i["kind"] == "slot" and i["slot"] == slot]
        data["slot_check"] = {"slot": slot, "slot_name": SLOT_NAMES.get(slot, slot), "leaves_unfilled": bool(gap)}
    return ToolResult(tool="evaluate_trade", ok=True, data=data)


# --- waivers (fantasy_read_api.waiver_recommendations_view) -----------------------------------


@tool(
    "get_waiver_recommendations",
    capability="fantasy_team",
    description="The Waiver Wire's own recommendations for a team you manage: the needs headline, the top adds with "
                "each card's reason and how they compare with your current starter, open roster spots, and drop "
                "candidates. Read-only — it never adds or drops anyone.",
    parameters={"properties": {"position": {"type": "string"}, "team": {"type": "string"}, "player": {"type": "string"},
                               "limit": {"type": "integer", "minimum": 1, "maximum": 15}}},
    reuses=("fantasy_read_api.waiver_recommendations_view",),
    needs_session=True,
)
def get_waiver_recommendations(*, session: Mapping[str, Any], position: str | None = None, team: str | None = None,
                               player: str | None = None, limit: int = 3) -> ToolResult:
    api = _api()
    league = api.active_league(session)
    if league is None:
        return _no_league("get_waiver_recommendations")
    name, access, err = _resolve_team(session, league, team, "get_waiver_recommendations")
    if err:
        return err
    denied = _require_manage(access, "get_waiver_recommendations")
    if denied:
        return denied
    filt = waiver_position(position)
    # A question about one player looks further down the same ranked list (at most 15 cards).
    view = api.waiver_recommendations_view(session, name, filt, limit=15 if player else max(1, min(int(limit or 3), 15)))
    if not view.allowed:
        code = NO_ROSTER_STATS if "stats" in view.reason.lower() else BAD_ARGUMENT
        return fail("get_waiver_recommendations", code, clean_text(view.reason, 240), access=access)
    cards = [{"rank": int(a.get("rank") or 0), "player": clean_text(a.get("player"), 80),
              "positions": clean_text(a.get("positions"), 30), "mlb_team": clean_text(a.get("mlb_team"), 10),
              "why": clean_text(a.get("why"), 300), "stat_line": clean_text(a.get("stat_line"), 200),
              "comparison": clean_text(a.get("comparison"), 200),
              "fills_open_spot": [clean_text(p, 6) for p in a.get("fills_open_spot") or ()]} for a in view.adds]
    data: dict[str, Any] = {
        "team": name, "access": access, "position": filt, "headline": clean_text(view.headline, 240),
        "body": clean_text(view.body, 240), "weak_categories": [clean_text(c, 10) for c in view.weak_categories],
        "category_ranks": {clean_text(k, 10): int(v) for k, v in view.category_ranks.items()},
        "team_count": int(view.team_count), "open_roster_spots": [clean_text(s, 10) for s in view.open_roster_spots],
        "adds": cards, "drops": [{"player": clean_text(d.get("player"), 80), "positions": clean_text(d.get("positions"), 30),
                                  "why": clean_text(d.get("why"), 300)} for d in view.drops[:3]],
        "basis": view.basis,
    }
    if player:
        want = normalize_player_name_for_merge(player)
        hit = next((c for c in cards if normalize_player_name_for_merge(c["player"]) == want
                    or (" " not in want and normalize_player_name_for_merge(c["player"]).split(" ")[-1] == want)), None)
        data["asked_player"] = clean_text(player, 80)
        data["asked_card"] = hit
        if hit is None:
            own = api.player_owner(session, player)
            data["asked_owner"] = {"status": own.status, "owner_team": clean_text(own.owner_team, 80),
                                   "player": clean_text(own.player, 80)}
        data["adds"] = cards[:3]
    return ToolResult(tool="get_waiver_recommendations", ok=True, data=data)
