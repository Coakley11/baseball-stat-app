"""Finalized scoring-period results and official league standings.

A period is scored from its lineup snapshots and that period's stats only:

    team period totals = sum over the snapshot's starters of their stats for the period's
                         exact dates (bench players never count; empty slots add nothing)
    AVG = H / AB, OBP = (H+BB+HBP) / (AB+BB+HBP+SF), SLG = TB / AB, OPS = OBP + SLG
                         — always rebuilt from summed components, never averaged.

Finalizing stores every starter's components, the team totals and the stat source in the
ledger. A finalized period is never recomputed: later drops, trades, waiver moves or
lineup changes cannot touch it. Official standings add up finalized periods, then award
roto points per category with ties sharing points (fantasy_team_rates.roto_points).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fantasy_period_stats import COMPONENTS, rates_from_components
from fantasy_season_ledger import (
    PERIOD_FINALIZED,
    PERIOD_LOCKED,
    _ledger_for_write,
    get_period,
    list_periods,
    period_id_for,
    period_status,
)

SCORED_COMPONENTS = tuple(c for c in COMPONENTS if c != "G") + ("G",)
DEFAULT_CATEGORIES = ("R", "HR", "RBI", "SB", "AVG")
RATE_CATEGORIES = ("AVG", "OBP", "SLG", "OPS")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _index_stats(stats_df: pd.DataFrame | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    if stats_df is None or getattr(stats_df, "empty", True):
        return by_id, by_name
    from fantasy_league_context import normalize_player_key

    for rec in stats_df.to_dict("records"):
        pid = rec.get("MLBAM ID")
        try:
            pid_s = str(int(float(pid))) if pid is not None and str(pid).strip() not in ("", "nan") else ""
        except (TypeError, ValueError):
            pid_s = ""
        if pid_s:
            by_id[pid_s] = rec
        key = normalize_player_key(str(rec.get("Player") or ""))
        if key:
            by_name.setdefault(key, rec)
    return by_id, by_name


def _starter_line(starter: dict[str, Any], by_id: dict[str, Any], by_name: dict[str, Any]) -> dict[str, Any]:
    from fantasy_league_context import normalize_player_key

    pid = str(starter.get("player_id") or "").strip()
    rec, matched = None, "no_games"
    if pid and pid in by_id:
        rec, matched = by_id[pid], "player_id"
    else:
        key = starter.get("player_key") or normalize_player_key(str(starter.get("player_name") or ""))
        if key in by_name:
            rec, matched = by_name[key], "name"
    line = {
        "player_name": starter.get("player_name"),
        "player_id": pid,
        "slot": starter.get("slot"),
        "slot_key": starter.get("slot_key"),
        "matched_by": matched,  # "no_games" = no plate appearances in the period
    }
    for comp in SCORED_COMPONENTS:
        line[comp] = float((rec or {}).get(comp) or 0)
    return line


def _sum_components(lines: list[dict[str, Any]]) -> dict[str, float]:
    return {comp: float(sum(float(l.get(comp) or 0) for l in lines)) for comp in SCORED_COMPONENTS}


def compute_period_result(context: dict[str, Any], number: int, stats_df: pd.DataFrame | None) -> dict[str, Any]:
    """Score every team's snapshot for a period from that period's stats (does not store)."""
    period = get_period(context, number) or {}
    by_id, by_name = _index_stats(stats_df)
    teams = sorted(str(t) for t in (context.get("league_rosters") or {}) if str(t).strip())
    lineups = period.get("lineups") or {}
    out_teams: dict[str, Any] = {}
    for team in teams:
        snap = lineups.get(team)
        if not isinstance(snap, dict):
            totals = {comp: 0.0 for comp in SCORED_COMPONENTS}
            out_teams[team] = {"lineup_missing": True, "starters": [], "bench": [], "empty_slots": [],
                               "totals": totals, "rates": rates_from_components(totals)}
            continue
        lines = [_starter_line(s, by_id, by_name) for s in (snap.get("starters") or [])]
        totals = _sum_components(lines)
        out_teams[team] = {
            "lineup_missing": False,
            "starters": lines,
            "bench": [b.get("player_name") for b in (snap.get("bench") or [])],
            "empty_slots": list(snap.get("empty_slots") or []),
            "set_after_lock": bool(snap.get("set_after_lock")),
            "totals": totals,
            "rates": rates_from_components(totals),
        }
    return {
        "period_id": period.get("period_id") or period_id_for(number),
        "number": int(number),
        "start": period.get("start"),
        "end": period.get("end"),
        "teams": out_teams,
        "stats_rows": 0 if stats_df is None else int(len(stats_df)),
        "computed_at": _now_iso(),
    }


def finalize_period(
    context: dict[str, Any],
    number: int,
    *,
    stats_df: pd.DataFrame,
    actor: dict[str, Any],
    is_commissioner: bool,
    score_missing_lineups_as_zero: bool = False,
    stats_source: str = "MLB Stats API byDateRange",
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Score and permanently store a period. Returns (ok, error, result)."""
    if not is_commissioner:
        return False, "Only the commissioner can finalize a scoring period.", None
    period = get_period(context, number)
    if period is None:
        return False, f"Week {int(number)} is not on the league calendar.", None
    label = str(period.get("label") or f"Week {int(number)}")
    status = period_status(period, now=now)
    if status == PERIOD_FINALIZED:
        return False, f"{label} is already final.", None
    if status != PERIOD_LOCKED:
        return False, f"{label} can be finalized after it ends on {period.get('end')}; until then its stats are incomplete.", None
    earlier = [p for p in list_periods(context) if int(p["number"]) < int(number) and period_status(p, now=now) != PERIOD_FINALIZED]
    if earlier:
        return False, f"Finalize {earlier[0]['label']} first — periods are finalized in order.", None
    if stats_df is None or getattr(stats_df, "empty", True):
        return False, f"No stats were returned for {label} ({period.get('start')} – {period.get('end')}).", None
    result = compute_period_result(context, number, stats_df)
    missing = [t for t, r in result["teams"].items() if r.get("lineup_missing")]
    if missing and not score_missing_lineups_as_zero:
        return False, (
            f"No {label} lineup for: {', '.join(missing)}. Set them (as commissioner for unclaimed teams) "
            "or confirm they score zero."
        ), result
    result["stats_source"] = stats_source
    result["missing_lineups_scored_zero"] = missing
    stamp = _now_iso()
    target = _ledger_for_write(context)["periods"][period_id_for(number)]
    target["result"] = copy.deepcopy(result)
    target["finalized_at"] = stamp
    target["finalized_by"] = dict(actor or {})
    target.setdefault("audit", []).append(
        {"at": stamp, "action": "finalized", "actor": dict(actor or {}), "missing_lineups_scored_zero": missing}
    )
    return True, "", result


def period_result(context: dict[str, Any] | None, number: int) -> dict[str, Any] | None:
    period = get_period(context, number)
    if not period or not str(period.get("finalized_at") or "").strip():
        return None
    result = period.get("result")
    return copy.deepcopy(result) if isinstance(result, dict) else None


def scoring_categories(context: dict[str, Any] | None) -> tuple[str, ...]:
    try:
        from fantasy_weekly_hitter_scoring import resolve_hitter_scoring_profile

        profile = resolve_hitter_scoring_profile(context)
        cats = tuple(c for c in profile.display_categories if c in set(SCORED_COMPONENTS) | set(RATE_CATEGORIES))
        if profile.scoring_mode == "roto" and cats:
            return cats
    except Exception:
        pass
    return DEFAULT_CATEGORIES


def _category_value(totals: dict[str, float], cat: str) -> float | None:
    if cat in RATE_CATEGORIES:
        return rates_from_components(totals).get(cat)
    return float(totals.get(cat) or 0)


def standings_from_totals(team_totals: dict[str, dict[str, float]], categories: tuple[str, ...]) -> pd.DataFrame:
    """Roto table from cumulative component totals; tied teams split points."""
    from fantasy_team_rates import roto_points

    rows = []
    for team, totals in sorted(team_totals.items()):
        row: dict[str, Any] = {"Team": team}
        for cat in categories:
            row[cat] = _category_value(totals, cat)
        row["H"] = totals.get("H", 0.0)
        row["AB"] = totals.get("AB", 0.0)
        rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    point_cols = []
    for cat in categories:
        col = f"{cat} Points"
        values = pd.to_numeric(table[cat], errors="coerce")
        # No at-bats means no average: rank below every team that has one (ties among them split).
        table[col] = roto_points(values.fillna(float("-inf")))
        point_cols.append(col)
    table["Total Points"] = table[point_cols].sum(axis=1)
    table["Rank"] = table["Total Points"].rank(ascending=False, method="min").astype(int)
    return table.sort_values(["Rank", "Team"]).reset_index(drop=True)


def official_standings(context: dict[str, Any] | None) -> tuple[pd.DataFrame, list[int]]:
    """(standings, finalized period numbers) — the league's official season standings."""
    finalized = [p for p in list_periods(context) if str(p.get("finalized_at") or "").strip()]
    teams = sorted(str(t) for t in ((context or {}).get("league_rosters") or {}) if str(t).strip())
    totals: dict[str, dict[str, float]] = {t: {c: 0.0 for c in SCORED_COMPONENTS} for t in teams}
    for period in finalized:
        for team, res in ((period.get("result") or {}).get("teams") or {}).items():
            bucket = totals.setdefault(team, {c: 0.0 for c in SCORED_COMPONENTS})
            for comp in SCORED_COMPONENTS:
                bucket[comp] += float((res.get("totals") or {}).get(comp) or 0)
    if not finalized:
        return pd.DataFrame(), []
    table = standings_from_totals(totals, scoring_categories(context))
    table.insert(1, "Weeks", len(finalized))
    return table, [int(p["number"]) for p in finalized]


def period_category_table(context: dict[str, Any] | None, number: int) -> pd.DataFrame:
    """One finalized period: each team's totals and that week's category points."""
    result = period_result(context, number)
    if not result:
        return pd.DataFrame()
    totals = {team: res.get("totals") or {} for team, res in (result.get("teams") or {}).items()}
    return standings_from_totals(totals, scoring_categories(context))
