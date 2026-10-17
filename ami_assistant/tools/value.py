"""Trend Value and Valuation tools — the pages' own pipelines, step for step.

Trend Value / Valuation (streamlit_app.py) both:

1. take the last ``window`` seasons of the data (3, 4 or 5 on the page; default 3);
2. total each player's window (``aggregate_recent_player_totals``: groupby + ``add_rate_stats``)
   and keep players with at least ``min_games`` games (default 50);
3. fit per-season slopes over the *whole window's* rows (``trend_slopes.trend_slopes`` — rate
   stats are weighted by plate appearances and shrunk toward that window's league rate, so
   the full window must be passed, not one player's rows);
4. Valuation: keep hitters only (``valuation_scores.valuation_hitter_pool``, window AB >= 10 —
   Phase D7), merge, zero-fill missing trends, ``valuation_scores.add_valuation_scores``.

Draft-sync removal and roster-need boosts are user-specific page options AMI does not apply;
results say so.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ami_assistant.data import BaseballDataset
from ami_assistant.players import player_ref
from ami_assistant.tools.registry import INSUFFICIENT_HISTORY, NOT_IN_POOL, ToolResult, fail, tool
from ami_assistant.tools.stats import RATE_STATS, _num, _resolve_id, round_rates
from lahman_data import add_rate_stats
from projection_breakdown import classify_trend_direction
from trend_slopes import RATE_SHRINK_PA, trend_slopes
from valuation_scores import (
    PERF_COUNT_WEIGHTS,
    PERF_RATE_WEIGHTS,
    TREND_WEIGHTS,
    VALUATION_MIN_AB,
    add_valuation_scores,
    valuation_hitter_pool,
)

TREND_STATS = ("R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS")
WINDOW_TOTAL_COLS = ("G", "R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "HBP", "SF")
PA_INPUTS = ("AB", "BB", "HBP", "SF", "SH", "H", "2B", "3B", "HR")
PAGE_WINDOWS = (3, 4, 5)
DEFAULT_WINDOW = 3
DEFAULT_MIN_GAMES = 50

TREND_METHOD = (
    "Least-squares change per season over the window. BA/OBP/SLG/OPS weight seasons by plate "
    f"appearances and pull small samples toward league average ({RATE_SHRINK_PA} PA), "
    "so a short season can't drive the trend."
)
VALUATION_METHOD = (
    "Valuation Score blends each player's percentile on Current Score (weighted window production) "
    "and on Trend Score (weighted per-season slopes), then rescales so the top of the pool is 100 and the bottom 0."
)

_WINDOW_SCHEMA = {"type": "integer", "minimum": 2, "maximum": 10, "description": "Trailing seasons (page offers 3, 4, 5)"}


_MEMO: dict[tuple, Any] = {}
_MEMO_MAX = 32


def _memo(key: tuple, build: Any) -> Any:
    """Per-process cache (the page uses st.cache_data for the same tables). Results are not mutated."""
    if key not in _MEMO:
        if len(_MEMO) >= _MEMO_MAX:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[key] = build()
    return _MEMO[key]


def window_years(ds: BaseballDataset, window: int) -> list[int]:
    window = max(2, min(int(window or DEFAULT_WINDOW), 10))
    return list(range(ds.latest_season - window + 1, ds.latest_season + 1))


def window_rows(ds: BaseballDataset, years: list[int]) -> pd.DataFrame:
    yearly = ds.yearly
    return yearly[yearly["yearID"].isin(years)].copy().sort_values(["playerID", "yearID"])


def window_pool(recent: pd.DataFrame, min_games: int) -> pd.DataFrame:
    """``aggregate_recent_player_totals`` + the page's Minimum Games Played filter."""
    keys = [c for c in ("playerID", "fullName", "bats") if c in recent.columns]
    cols = [c for c in WINDOW_TOTAL_COLS if c in recent.columns]
    totals = add_rate_stats(recent.groupby(keys, as_index=False, dropna=False)[cols].sum())
    return totals[totals["G"] >= min_games].copy()


def page_trend_table(recent: pd.DataFrame, stats: tuple[str, ...] = TREND_STATS) -> pd.DataFrame:
    """``compute_player_trend_table`` without the Streamlit cache."""
    stats_in = [s for s in stats if s in recent.columns]
    cols = ["playerID"] + [f"{s}_trend" for s in stats_in]
    if recent.empty:
        return pd.DataFrame(columns=cols)
    pa_inputs = [c for c in PA_INPUTS if c in recent.columns and c not in stats_in]
    return trend_slopes(recent[["playerID", "yearID"] + stats_in + pa_inputs], stats_in)[cols]


def trend_table(ds: BaseballDataset, years: list[int]) -> pd.DataFrame:
    return _memo((ds.fingerprint, "slopes", tuple(years)), lambda: page_trend_table(window_rows(ds, years)))


def trend_pool(ds: BaseballDataset, years: list[int], min_games: int) -> pd.DataFrame:
    """Window totals for players with enough games, plus their trend slopes."""
    return _memo(
        (ds.fingerprint, "trend_pool", tuple(years), min_games),
        lambda: window_pool(window_rows(ds, years), min_games).merge(trend_table(ds, years), on="playerID", how="left"),
    )


def _kind(stat: str) -> str:
    return "rate" if stat in RATE_STATS else "counting"


def _window_note(window: int) -> str:
    return "" if window in PAGE_WINDOWS else f"The Trend Value page offers 3-, 4- or 5-season windows; this uses {window}."


@tool(
    "get_player_trends",
    capability="historical_analytics",
    description=(
        "Trend Value numbers for one player: per-season slope of each stat over the trailing window, "
        "direction, and where each slope ranks among hitters with enough games in that window."
    ),
    parameters={
        "properties": {
            "player_id": {"type": "string"},
            "window": _WINDOW_SCHEMA,
            "min_games": {"type": "integer", "minimum": 0},
            "stats": {"type": "array", "items": {"type": "string", "enum": list(TREND_STATS)}},
        },
        "required": ["player_id"],
    },
    reuses=("trend_slopes.trend_slopes", "projection_breakdown.classify_trend_direction", "lahman_data.add_rate_stats"),
    needs_dataset=True,
)
def get_player_trends(
    *,
    dataset: BaseballDataset,
    player_id: str,
    window: int = DEFAULT_WINDOW,
    min_games: int = DEFAULT_MIN_GAMES,
    stats: list[str] | None = None,
) -> ToolResult:
    pid, err = _resolve_id(dataset, "get_player_trends", player_id)
    if err:
        return err
    ref = player_ref(dataset, pid)
    years = window_years(dataset, window)
    window = len(years)
    mine = dataset.player_rows(pid)
    mine = mine[mine["yearID"].isin(years)]
    if mine["yearID"].nunique() < 2:
        return fail(
            "get_player_trends",
            INSUFFICIENT_HISTORY,
            f"{ref.name} has {mine['yearID'].nunique()} season(s) in {years[0]}–{years[-1]}; "
            "a trend needs at least two.",
            player=ref.as_dict(),
            window=[years[0], years[-1]],
            seasons_in_window=sorted(int(y) for y in mine["yearID"].unique()),
        )
    slopes = trend_table(dataset, years)
    pool = trend_pool(dataset, years, int(min_games))
    in_pool = bool((pool["playerID"] == pid).any())
    chosen = [s for s in (stats or TREND_STATS) if s in TREND_STATS] or list(TREND_STATS)
    mine_slopes = slopes[slopes["playerID"] == pid].iloc[0]
    seasons = round_rates(mine)
    out: list[dict[str, Any]] = []
    for stat in chosen:
        col = f"{stat}_trend"
        slope = mine_slopes.get(col)
        pct = None
        if in_pool and pd.notna(slope):
            ranked = pool[col].rank(pct=True)
            pct = round(float(ranked[pool["playerID"] == pid].iloc[0]) * 100, 1)
        out.append(
            {
                "stat": stat,
                "slope_per_season": _num(slope),
                "direction": classify_trend_direction(slope, kind=_kind(stat)),
                "percentile_in_pool": pct,
                "by_season": [{"season": int(r["yearID"]), "value": _num(r[stat])} for _, r in seasons.iterrows()],
            }
        )
    ranked_stats = [t for t in out if t["percentile_in_pool"] is not None]
    ranked_stats.sort(key=lambda t: t["percentile_in_pool"], reverse=True)
    counts = {k: sum(1 for t in out if t["direction"] == k) for k in ("improving", "declining", "stable")}
    return ToolResult(
        tool="get_player_trends",
        ok=True,
        data={
            "player": ref.as_dict(),
            "window": [years[0], years[-1]],
            "window_note": _window_note(window),
            "min_games": int(min_games),
            "pool_size": int(len(pool)),
            "player_in_pool": in_pool,
            "player_window_games": int(mine["G"].sum()),
            "trends": out,
            "direction_counts": counts,
            "strongest": [t["stat"] for t in ranked_stats[:3]],
            "weakest": [t["stat"] for t in ranked_stats[::-1][:3]],
            "method": TREND_METHOD,
            "page_notes": [
                "The Trend Value table shows a player with only one season in the window as 0.0, not blank.",
                "Draft Room sync (removing drafted players) is not applied here.",
            ],
        },
    )


@tool(
    "get_trend_leaders",
    capability="historical_analytics",
    description="Trend Value table for one stat: the fastest improving (or declining) hitters over the trailing window.",
    parameters={
        "properties": {
            "stat": {"type": "string", "enum": list(TREND_STATS)},
            "window": _WINDOW_SCHEMA,
            "min_games": {"type": "integer", "minimum": 0},
            "direction": {"type": "string", "enum": ["improving", "declining"]},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 25},
        },
        "required": ["stat"],
    },
    reuses=("trend_slopes.trend_slopes", "lahman_data.add_rate_stats"),
    needs_dataset=True,
)
def get_trend_leaders(
    *,
    dataset: BaseballDataset,
    stat: str = "OPS",
    window: int = DEFAULT_WINDOW,
    min_games: int = DEFAULT_MIN_GAMES,
    direction: str = "improving",
    top_n: int = 10,
) -> ToolResult:
    stat = str(stat or "OPS").upper()
    if stat not in TREND_STATS:
        return fail("get_trend_leaders", "bad_argument", f"Trend Value doesn't track “{stat}”.")
    years = window_years(dataset, window)
    pool = trend_pool(dataset, years, int(min_games))
    col = f"{stat}_trend"
    # The page zero-fills one-season players; leave them out of a "fastest movers" list.
    ranked = pool[pool[col].notna()].sort_values(col, ascending=direction == "declining")
    rows = [
        {"player": r["fullName"], "player_id": r["playerID"], "slope_per_season": _num(r[col]),
         "direction": classify_trend_direction(r[col], kind=_kind(stat)), "window_games": int(r["G"])}
        for _, r in ranked.head(max(1, min(int(top_n or 10), 25))).iterrows()
    ]
    return ToolResult(
        tool="get_trend_leaders",
        ok=True,
        data={
            "stat": stat,
            "direction": direction,
            "window": [years[0], years[-1]],
            "window_note": _window_note(len(years)),
            "min_games": int(min_games),
            "pool_size": int(ranked.shape[0]),
            "rows": rows,
            "method": TREND_METHOD,
        },
    )


def valuation_pool(ds: BaseballDataset, window: int, min_games: int, w_current: float, w_trend: float) -> tuple[pd.DataFrame, list[int]]:
    """The Valuation page table (before roster-need adjustments), sorted best first."""
    years = window_years(ds, window)

    def build() -> pd.DataFrame:
        # The page's own pool rule (Phase D7): games filter, then hitters only (window AB >= 10).
        pool = valuation_hitter_pool(window_pool(window_rows(ds, years), min_games))
        pool = pool.merge(trend_table(ds, years), on="playerID", how="left")
        for stat in TREND_STATS:  # add_latest_and_projection_columns zero-fills missing trends
            col = f"{stat}_trend"
            pool[col] = pd.to_numeric(pool.get(col, 0.0), errors="coerce").fillna(0)
        add_valuation_scores(pool, w_current, w_trend)
        pool = pool.sort_values("Valuation_Score", ascending=False).reset_index(drop=True)
        pool["rank"] = pool["Valuation_Score"].rank(ascending=False, method="min").astype(int)
        return pool

    return _memo((ds.fingerprint, "valuation", tuple(years), min_games, w_current, w_trend), build), years


def _contributions(row: pd.Series) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    perf = [{"stat": s, "points": _num(float(row[s]) * w)} for s, w in PERF_COUNT_WEIGHTS.items()]
    perf += [{"stat": s, "points": _num(float(row[s] if pd.notna(row[s]) else 0) * 100 * w)} for s, w in PERF_RATE_WEIGHTS.items()]
    trend = [
        {"stat": col.replace("_trend", ""), "points": _num(float(row.get(col, 0) or 0) * w), "slope": _num(row.get(col))}
        for col, w in TREND_WEIGHTS.items()
    ]
    perf.sort(key=lambda d: d["points"] or 0, reverse=True)
    trend.sort(key=lambda d: d["points"] or 0, reverse=True)
    return perf, trend


@tool(
    "get_player_valuation",
    capability="historical_analytics",
    description=(
        "Valuation page numbers: Valuation Score (0–100 within the pool), Current Score, Trend Score, their "
        "percentiles, the player's rank, and which stats drive each component. Omit player_id for the top of the board."
    ),
    parameters={
        "properties": {
            "player_id": {"type": "string"},
            "window": _WINDOW_SCHEMA,
            "min_games": {"type": "integer", "minimum": 0},
            "weight_current": {"type": "number", "minimum": 0, "maximum": 10},
            "weight_trend": {"type": "number", "minimum": 0, "maximum": 10},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 25},
        }
    },
    reuses=("valuation_scores.valuation_hitter_pool", "valuation_scores.add_valuation_scores", "trend_slopes.trend_slopes",
            "lahman_data.add_rate_stats"),
    needs_dataset=True,
)
def get_player_valuation(
    *,
    dataset: BaseballDataset,
    player_id: str | None = None,
    window: int = DEFAULT_WINDOW,
    min_games: int = DEFAULT_MIN_GAMES,
    weight_current: float = 1.0,
    weight_trend: float = 1.0,
    top_n: int = 5,
) -> ToolResult:
    pid = None
    if player_id:
        pid, err = _resolve_id(dataset, "get_player_valuation", player_id)
        if err:
            return err
    pool, years = valuation_pool(dataset, window, int(min_games), float(weight_current), float(weight_trend))
    window = len(years)
    board = [
        {
            "rank": int(r["rank"]),
            "player": r["fullName"],
            "player_id": r["playerID"],
            "valuation_score": _num(r["Valuation_Score"] * 100),
            "current_score": _num(r["Perf_Score"]),
            "trend_score": _num(r["Trend_Score"]),
        }
        for _, r in pool.head(max(1, min(int(top_n or 5), 25))).iterrows()
    ]
    data: dict[str, Any] = {
        "window": [years[0], years[-1]],
        "window_note": _window_note(window),
        "min_games": int(min_games),
        "weights": {"current": float(weight_current), "trend": float(weight_trend)},
        "pool_size": int(len(pool)),
        "top": board,
        "method": VALUATION_METHOD,
        "page_notes": [
            f"Hitters only: players with fewer than {VALUATION_MIN_AB} window at-bats (pitchers' batting lines) are left out, as on the page.",
            "All positions; the page's Fantasy Position filter changes the pool and therefore every score.",
            "Draft Room sync and roster-need boosts for your active team are not applied here.",
        ],
    }
    if pid:
        ref = player_ref(dataset, pid)
        hit = pool[pool["playerID"] == pid]
        if hit.empty:
            rows = dataset.player_rows(pid)
            in_window = rows["yearID"].isin(years)
            games, at_bats = int(rows.loc[in_window, "G"].sum()), int(rows.loc[in_window, "AB"].sum())
            return fail(
                "get_player_valuation",
                NOT_IN_POOL,
                f"{ref.name} had {games} games and {at_bats} at-bats in {years[0]}–{years[-1]}; the Valuation pool "
                f"needs at least {int(min_games)} games and {VALUATION_MIN_AB} at-bats (hitters only).",
                player=ref.as_dict(),
                **data,
            )
        row = hit.iloc[0]
        perf, trend = _contributions(row)
        data["player"] = ref.as_dict()
        data["valuation"] = {
            "rank": int(row["rank"]),
            "valuation_score": _num(row["Valuation_Score"] * 100),
            "current_score": _num(row["Perf_Score"]),
            "trend_score": _num(row["Trend_Score"]),
            "current_percentile": _num(row["Perf_Pct"] * 100),
            "trend_percentile": _num(row["Trend_Pct"] * 100),
            "window_totals": {s: _num(row[s]) for s in ("G", "AB", "R", "HR", "RBI", "SB", "BA", "OBP", "SLG", "OPS")},
            "top_current_drivers": perf[:3],
            "top_trend_drivers": [t for t in trend if (t["points"] or 0) > 0][:3],
            "trend_drags": [t for t in trend[::-1] if (t["points"] or 0) < 0][:3],
        }
    return ToolResult(tool="get_player_valuation", ok=True, data=data)
