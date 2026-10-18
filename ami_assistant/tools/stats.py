"""Historical stat tools: player lookup, seasons, comparison, leaderboards.

Aggregation mirrors the pages exactly:

* window totals — ``groupby(["playerID", "fullName", "bats"], dropna=False).sum()`` then
  ``baseball_history.add_rate_stats`` (Career Totals);
* Leaderboards — ``leaderboard_aggregation.filter_yearly_for_leaderboards`` +
  ``aggregate_leaderboard_career_totals`` + ``add_rate_stats``;
* rate-stat rankings — ``rate_stat_qualification.qualified_ab`` minimum AB, as the pages default;
* rates rounded to 3 places before sorting (``safe_round_rate_stats`` on the pages).
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from ami_assistant.data import BaseballDataset
from ami_assistant.players import AMBIGUOUS, NOT_FOUND, player_ref, resolve_player
from ami_assistant.tools.registry import (
    AMBIGUOUS_PLAYER,
    BAD_ARGUMENT,
    UNAVAILABLE_SEASON,
    UNKNOWN_PLAYER,
    ToolResult,
    fail,
    tool,
)
from baseball_history import add_rate_stats
from leaderboard_aggregation import aggregate_leaderboard_career_totals, filter_yearly_for_leaderboards
from rate_stat_qualification import AB_PER_TEAM_GAME, RATE_STAT_KEYS, qualified_ab

TOTAL_COLS = ("G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF")
RATE_STATS = tuple(RATE_STAT_KEYS)
RANKABLE_STATS = ("R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
DISPLAY_STATS = ("G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF", "DH", "P")
POSITION_MODES = {"career": "careerPrimaryPos", "season": "primaryPos"}
POSITION_MODE_LABELS = {"career": "Career Primary Position", "season": "Season Primary Position"}

_PLAYER_ID_SCHEMA = {"type": "string", "description": "Lahman playerID from search_players"}
_RANGE_SCHEMA = {
    "type": "array",
    "items": {"type": "integer"},
    "minItems": 2,
    "maxItems": 2,
    "description": "Inclusive [first_season, last_season]; omit for the full career/data range",
}


def round_rates(df: pd.DataFrame) -> pd.DataFrame:
    """The pages' ``safe_round_rate_stats`` for the four rate columns."""
    out = df.copy()
    for col in RATE_STATS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").round(3)
    return out


def window_totals(rows: pd.DataFrame) -> pd.DataFrame:
    """Career Totals aggregation: one row per player, rates recomputed from the totals."""
    cols = [c for c in TOTAL_COLS if c in rows.columns]
    keys = [c for c in ("playerID", "fullName", "bats") if c in rows.columns]
    totals = rows.groupby(keys, as_index=False, dropna=False)[cols].sum()
    return round_rates(add_rate_stats(totals))


def _num(value: Any) -> float | int | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return int(v) if v.is_integer() and abs(v) < 1e12 else round(v, 3)


def stat_line(row: Any, stats: Iterable[str] = DISPLAY_STATS) -> dict[str, Any]:
    return {s: _num(row.get(s)) for s in stats if s in row}


def season_line(row: Any) -> dict[str, Any]:
    line = {"season": int(row["yearID"])}
    team = row.get("primaryTeamName") if hasattr(row, "get") else None
    if isinstance(team, str) and team:
        line["team"] = team
    pos = row.get("primaryPos") if hasattr(row, "get") else None
    if isinstance(pos, str) and pos:
        line["position"] = pos
    line.update(stat_line(row))
    return line


def season_qualifying_ab(ds: BaseballDataset, season: int) -> int:
    """A full season's qualifying AB (Historical Explorer's single-season default)."""
    return int(qualified_ab(ds.season_games, (season, season), span=False)["value"])


def normalize_range(ds: BaseballDataset, year_range: Any) -> tuple[tuple[int, int] | None, str]:
    """Clip a requested range to the data; ``(None, message)`` when nothing is left."""
    if not year_range:
        return (ds.first_season, ds.latest_season), ""
    try:
        lo, hi = int(year_range[0]), int(year_range[1])
    except (TypeError, ValueError, IndexError):
        return None, "That season range isn't valid."
    if lo > hi:
        lo, hi = hi, lo
    if hi < ds.first_season or lo > ds.latest_season:
        return None, (
            f"The app's data covers {ds.first_season}–{ds.latest_season}; "
            f"{lo if lo == hi else f'{lo}–{hi}'} isn't in it."
        )
    clipped = (max(lo, ds.first_season), min(hi, ds.latest_season))
    note = ""
    if clipped != (lo, hi):
        note = f"The data covers {ds.first_season}–{ds.latest_season}, so this uses {clipped[0]}–{clipped[1]}."
    return clipped, note


def _resolve_id(ds: BaseballDataset, tool_name: str, player_id: str) -> tuple[str | None, ToolResult | None]:
    if player_id in ds.players.index:
        return player_id, None
    res = resolve_player(ds, player_id)
    if res.status == AMBIGUOUS:
        return None, fail(tool_name, AMBIGUOUS_PLAYER, f"More than one player matches “{player_id}”.",
                          candidates=[c.label for c in res.candidates])
    if res.status == NOT_FOUND or res.player is None:
        return None, fail(tool_name, UNKNOWN_PLAYER, f"No player named “{player_id}” is in the app's data.",
                          suggestions=[c.label for c in res.candidates])
    return res.player.player_id, None


@tool(
    "search_players",
    capability="historical_analytics",
    description="Find players by full name or surname in the app's Lahman data; returns playerIDs and career spans.",
    parameters={"properties": {"query": {"type": "string"}}, "required": ["query"]},
    reuses=("player_name_normalization.normalize_player_name_for_merge",),
    needs_dataset=True,
)
def search_players(*, dataset: BaseballDataset, query: str) -> ToolResult:
    res = resolve_player(dataset, query)
    return ToolResult(tool="search_players", ok=res.status != NOT_FOUND or bool(res.candidates), data=res.as_dict())


@tool(
    "get_player_profile",
    capability="historical_analytics",
    description="Career summary for one player: span, career totals and rates, best qualified seasons by OPS.",
    parameters={"properties": {"player_id": _PLAYER_ID_SCHEMA}, "required": ["player_id"]},
    reuses=("baseball_history.add_rate_stats", "rate_stat_qualification.qualified_ab"),
    needs_dataset=True,
)
def get_player_profile(*, dataset: BaseballDataset, player_id: str, best_n: int = 5) -> ToolResult:
    pid, err = _resolve_id(dataset, "get_player_profile", player_id)
    if err:
        return err
    rows = dataset.player_rows(pid)
    ref = player_ref(dataset, pid)
    totals = window_totals(rows).iloc[0]
    seasons = round_rates(rows)
    seasons = seasons.assign(_qual=[season_qualifying_ab(dataset, int(y)) for y in seasons["yearID"]])
    qualified = seasons[seasons["AB"] >= seasons["_qual"]]
    best = qualified.sort_values(["OPS", "yearID"], ascending=[False, False]).head(int(best_n))
    peak_hr = seasons.sort_values(["HR", "yearID"], ascending=[False, False]).head(1)
    info = dataset.players.loc[pid]
    data: dict[str, Any] = {
        "player": ref.as_dict(),
        "seasons_played": int(rows["yearID"].nunique()),
        "position": str(info.get("position") or ""),
        "bats": str(info.get("bats") or "") if pd.notna(info.get("bats")) else "",
        "career_totals": stat_line(totals),
        "best_seasons_by_ops": [season_line(r) for _, r in best.iterrows()],
        "qualified_season_count": int(len(qualified)),
        "peak_hr_season": season_line(peak_hr.iloc[0]) if len(peak_hr) else None,
        "qualification_rule": f"{AB_PER_TEAM_GAME} AB per scheduled team game in that season",
    }
    if "isHallOfFamer" in rows.columns:
        data["hall_of_famer"] = bool(rows["isHallOfFamer"].fillna(False).astype(bool).any())
    return ToolResult(tool="get_player_profile", ok=True, data=data)


@tool(
    "get_player_seasons",
    capability="historical_analytics",
    description="Season-by-season batting lines for one player, optionally limited to a season range.",
    parameters={"properties": {"player_id": _PLAYER_ID_SCHEMA, "year_range": _RANGE_SCHEMA}, "required": ["player_id"]},
    reuses=("baseball_history.load_history_frames (yearly rows)",),
    needs_dataset=True,
)
def get_player_seasons(*, dataset: BaseballDataset, player_id: str, year_range: Any = None) -> ToolResult:
    pid, err = _resolve_id(dataset, "get_player_seasons", player_id)
    if err:
        return err
    rng, note = normalize_range(dataset, year_range)
    if rng is None:
        return fail("get_player_seasons", UNAVAILABLE_SEASON, note)
    ref = player_ref(dataset, pid)
    rows = dataset.player_rows(pid)
    rows = rows[(rows["yearID"] >= rng[0]) & (rows["yearID"] <= rng[1])]
    if rows.empty:
        return fail(
            "get_player_seasons",
            UNAVAILABLE_SEASON,
            f"{ref.name} has no seasons in {rng[0]}–{rng[1]} (played {ref.first_season}–{ref.last_season}).",
            player=ref.as_dict(),
        )
    rows = round_rates(rows)
    return ToolResult(
        tool="get_player_seasons",
        ok=True,
        data={
            "player": ref.as_dict(),
            "year_range": list(rng),
            "range_note": note,
            "seasons": [season_line(r) for _, r in rows.iterrows()],
            "totals": stat_line(window_totals(rows).iloc[0]),
        },
    )


@tool(
    "compare_players",
    capability="historical_analytics",
    description=(
        "Compare 2–3 players over a season range (default: each full career): totals and rates summed "
        "the Career Totals way, per-stat leader, and season lines."
    ),
    parameters={
        "properties": {
            "player_ids": {"type": "array", "items": _PLAYER_ID_SCHEMA, "minItems": 2, "maxItems": 3},
            "year_range": _RANGE_SCHEMA,
            "stats": {"type": "array", "items": {"type": "string", "enum": list(RANKABLE_STATS)}},
        },
        "required": ["player_ids"],
    },
    reuses=("baseball_history.add_rate_stats", "rate_stat_qualification.qualified_ab"),
    needs_dataset=True,
)
def compare_players(
    *, dataset: BaseballDataset, player_ids: list[str], year_range: Any = None, stats: list[str] | None = None
) -> ToolResult:
    ids: list[str] = []
    for raw in list(player_ids or [])[:3]:
        pid, err = _resolve_id(dataset, "compare_players", raw)
        if err:
            return err
        if pid not in ids:
            ids.append(pid)
    if len(ids) < 2:
        return fail("compare_players", BAD_ARGUMENT, "Comparing needs two different players.")
    rng, note = (None, "") if not year_range else normalize_range(dataset, year_range)
    if year_range and rng is None:
        return fail("compare_players", UNAVAILABLE_SEASON, note)
    stats = [s for s in (stats or RANKABLE_STATS) if s in RANKABLE_STATS] or list(RANKABLE_STATS)
    players: list[dict[str, Any]] = []
    for pid in ids:
        ref = player_ref(dataset, pid)
        rows = dataset.player_rows(pid)
        if rng is not None:
            rows = rows[(rows["yearID"] >= rng[0]) & (rows["yearID"] <= rng[1])]
        if rows.empty:
            return fail(
                "compare_players",
                UNAVAILABLE_SEASON,
                f"{ref.name} has no seasons in {rng[0]}–{rng[1]} (played {ref.first_season}–{ref.last_season}).",
                player=ref.as_dict(),
            )
        span = (int(rows["yearID"].min()), int(rows["yearID"].max()))
        qual = qualified_ab(dataset.season_games, span, span=True)
        totals = window_totals(rows).iloc[0]
        players.append(
            {
                "player": ref.as_dict(),
                "seasons": sorted(int(y) for y in rows["yearID"].unique()),
                "totals": stat_line(totals),
                "qualifying_ab_for_span": int(qual["value"]),
                "small_sample": bool(float(totals["AB"]) < qual["value"]),
                "season_lines": [season_line(r) for _, r in round_rates(rows).iterrows()],
            }
        )
    leaders: dict[str, Any] = {}
    for stat in stats:
        values = [(p["player"]["name"], p["totals"].get(stat)) for p in players]
        values = [(n, v) for n, v in values if v is not None]
        if len(values) < 2:
            continue
        ordered = sorted(values, key=lambda nv: nv[1], reverse=True)
        tie = ordered[0][1] == ordered[1][1]
        leaders[stat] = {
            "leader": None if tie else ordered[0][0],
            "values": dict(values),
            "margin": _num(ordered[0][1] - ordered[1][1]),
        }
    return ToolResult(
        tool="compare_players",
        ok=True,
        data={
            "year_range": list(rng) if rng else None,
            "range_note": note,
            "basis": "each player's full career" if rng is None else f"seasons {rng[0]}–{rng[1]}",
            "players": players,
            "leaders": leaders,
            "stats": stats,
        },
    )


@tool(
    "get_leaderboard",
    capability="historical_analytics",
    description=(
        "Rank players on one stat over a season range, optionally within a position. Rate stats (BA/OBP/SLG/OPS) "
        "use the app's qualified at-bat minimum. Mirrors Leaderboards (no position) and Career Totals (position)."
    ),
    parameters={
        "properties": {
            "stat": {"type": "string", "enum": list(RANKABLE_STATS)},
            "year_range": _RANGE_SCHEMA,
            "position": {"type": "string", "enum": list(POSITIONS)},
            "position_mode": {"type": "string", "enum": list(POSITION_MODES)},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 50},
            "min_ab": {"type": "integer", "minimum": 0},
            "focus_player_id": _PLAYER_ID_SCHEMA,
        },
        "required": ["stat"],
    },
    reuses=(
        "leaderboard_aggregation.filter_yearly_for_leaderboards",
        "leaderboard_aggregation.aggregate_leaderboard_career_totals",
        "baseball_history.add_rate_stats",
        "rate_stat_qualification.qualified_ab",
    ),
    needs_dataset=True,
)
def get_leaderboard(
    *,
    dataset: BaseballDataset,
    stat: str,
    year_range: Any = None,
    position: str | None = None,
    position_mode: str = "career",
    top_n: int = 10,
    min_ab: int | None = None,
    focus_player_id: str | None = None,
) -> ToolResult:
    stat = str(stat or "").upper() if str(stat or "").upper() in RANKABLE_STATS else str(stat or "")
    if stat not in RANKABLE_STATS:
        return fail("get_leaderboard", BAD_ARGUMENT, f"Can't rank by “{stat}”. Options: {', '.join(RANKABLE_STATS)}.")
    rng, note = normalize_range(dataset, year_range)
    if rng is None:
        return fail("get_leaderboard", UNAVAILABLE_SEASON, note)
    position = str(position or "").upper() or None
    if position and position not in POSITIONS:
        return fail("get_leaderboard", BAD_ARGUMENT, f"Unknown position “{position}”.")
    mode = position_mode if position_mode in POSITION_MODES else "career"
    yearly = dataset.yearly
    if position:
        # Career Totals: filter seasons, then position, then one row per player.
        rows = yearly[(yearly["yearID"] >= rng[0]) & (yearly["yearID"] <= rng[1])]
        rows = rows[rows[POSITION_MODES[mode]] == position]
        board = add_rate_stats(
            rows.groupby(["playerID", "fullName", "bats"], as_index=False, dropna=False)[
                [c for c in TOTAL_COLS if c in rows.columns]
            ].sum()
        )
        source_page = "Career Totals"
    else:
        board = add_rate_stats(aggregate_leaderboard_career_totals(filter_yearly_for_leaderboards(yearly, rng)))
        source_page = "Leaderboards"
    qualification = None
    if stat in RATE_STATS:
        qualification = qualified_ab(dataset.season_games, rng, span=True)
        floor = int(qualification["value"] if min_ab is None else min_ab)
    else:
        floor = int(min_ab or 0)
    if floor:
        board = board[board["AB"].fillna(-float("inf")) >= floor]
    board = round_rates(board).sort_values(stat, ascending=False, na_position="last").reset_index(drop=True)
    board["rank"] = board[stat].rank(ascending=False, method="min")
    top_n = max(1, min(int(top_n or 10), 50))
    rows_out = [
        {"rank": int(r["rank"]), "player_id": r["playerID"], "player": r["fullName"], **stat_line(r)}
        for _, r in board.head(top_n).iterrows()
    ]
    focus = None
    if focus_player_id:
        hit = board[board["playerID"] == focus_player_id]
        if len(hit):
            r = hit.iloc[0]
            focus = {"rank": int(r["rank"]), "player": r["fullName"], **stat_line(r)}
        else:
            focus = {"player": dataset.player_name(focus_player_id), "rank": None}
    return ToolResult(
        tool="get_leaderboard",
        ok=True,
        data={
            "stat": stat,
            "year_range": list(rng),
            "range_note": note,
            "position": position,
            "position_mode": POSITION_MODE_LABELS[mode] if position else None,
            "source_page": source_page,
            "min_ab": floor,
            "qualification": qualification,
            "pool_size": int(len(board)),
            "rows": rows_out,
            "focus": focus,
        },
    )
