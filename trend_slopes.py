"""Per-player season trend slopes (Trend Value, Valuation, Draft, Sleepers).

The trend for a stat is the least-squares slope of the season values against calendar
year: the change per season. Seasons where the stat is missing are left out, gap years
keep their real spacing, and fewer than two seasons gives no trend (NaN).

Counting stats (R, HR, …) use the plain fit: slope = Σ(x − x̄)(y − ȳ) / Σ(x − x̄)²,
the same as ``np.polyfit(year, value, 1)`` per player.

Rate stats (BA, OBP, SLG, OPS) weight seasons by playing time so a tiny sample cannot drive
the trend. Each season's rate is first pulled toward that season's league rate in proportion
to its sample — rate·PA + league·k over PA + k, with k = ``RATE_SHRINK_PA`` — and the line is
then fitted with plate appearances as weights. Weighting alone is not enough: with two
seasons any weighted line still passes through both points, so a 5-PA season would keep its
full pull. A 650-PA season keeps ~76% of its distance from league average; a 5-PA season
keeps ~2%. When the season rows lack the columns needed for plate appearances, rate stats
fall back to the plain fit.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

RATE_STATS = ("BA", "OBP", "SLG", "OPS")
RATE_SHRINK_PA = 200
_PA_PARTS = ("AB", "BB", "HBP", "SF", "SH")
_RATE_INPUTS = ("H", "2B", "3B", "HR")


def _plain_slopes(pid: pd.Series, x: pd.Series, y: pd.Series) -> tuple[pd.Series, pd.Series]:
    frame = pd.DataFrame({"pid": pid, "x": x, "y": y})
    grouped = frame.groupby("pid", sort=False)
    dx = frame["x"] - grouped["x"].transform("mean")
    dy = frame["y"] - grouped["y"].transform("mean")
    sums = pd.DataFrame({"pid": frame["pid"], "sxy": dx * dy, "sxx": dx * dx}).groupby("pid", sort=False).sum()
    counts = grouped.size()
    return (sums["sxy"] / sums["sxx"]).where((counts >= 2) & (sums["sxx"] > 0)), counts


def _weighted_slopes(pid: pd.Series, x: pd.Series, y: pd.Series, w: pd.Series) -> pd.Series:
    frame = pd.DataFrame({"pid": pid, "x": x, "y": y, "w": w, "wx": w * x, "wy": w * y})
    sums = frame.groupby("pid", sort=False)[["w", "wx", "wy"]].sum()
    xm = frame["pid"].map(sums["wx"] / sums["w"])
    ym = frame["pid"].map(sums["wy"] / sums["w"])
    frame["sxy"] = frame["w"] * (frame["x"] - xm) * (frame["y"] - ym)
    frame["sxx"] = frame["w"] * (frame["x"] - xm) ** 2
    frame["seasons"] = (frame["w"] > 0).astype(int)
    agg = frame.groupby("pid", sort=False)[["sxy", "sxx", "seasons"]].sum()
    return (agg["sxy"] / agg["sxx"]).where((agg["seasons"] >= 2) & (agg["sxx"] > 0))


def _league_rates(seasons: pd.DataFrame) -> pd.DataFrame:
    """Each season's league BA/OBP/SLG/OPS from summed totals of the rows given."""
    num = seasons[["yearID", *_PA_PARTS, *_RATE_INPUTS]].apply(pd.to_numeric, errors="coerce").fillna(0)
    t = num.groupby("yearID").sum()
    ab = t["AB"].replace(0, np.nan)
    obp_den = (t["AB"] + t["BB"] + t["HBP"] + t["SF"]).replace(0, np.nan)
    singles = t["H"] - t["2B"] - t["3B"] - t["HR"]
    out = pd.DataFrame(index=t.index)
    out["BA"] = t["H"] / ab
    out["OBP"] = (t["H"] + t["BB"] + t["HBP"]) / obp_den
    out["SLG"] = (singles + 2 * t["2B"] + 3 * t["3B"] + 4 * t["HR"]) / ab
    out["OPS"] = out["OBP"] + out["SLG"]
    return out


def trend_slopes(seasons: pd.DataFrame, stats: Iterable[str]) -> pd.DataFrame:
    """One row per player in ``seasons`` (playerID, yearID, stats…): ``{stat}_trend`` columns."""
    stats = [s for s in stats if s in seasons.columns]
    players = pd.Index(pd.unique(seasons["playerID"]), name="playerID").sort_values()
    out = pd.DataFrame(index=players)
    year = pd.to_numeric(seasons["yearID"], errors="coerce").astype(float)
    weighted_ok = all(c in seasons.columns for c in (*_PA_PARTS, *_RATE_INPUTS))
    if weighted_ok and any(s in RATE_STATS for s in stats):
        pa = seasons[list(_PA_PARTS)].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1).astype(float)
        league = _league_rates(seasons)
    for stat in stats:
        value = pd.to_numeric(seasons[stat], errors="coerce").astype(float)
        if stat in RATE_STATS and weighted_ok:
            keep = value.notna() & year.notna() & (pa > 0)
            lg = year[keep].map(league[stat])
            shrunk = (value[keep] * pa[keep] + lg * RATE_SHRINK_PA) / (pa[keep] + RATE_SHRINK_PA)
            slope = _weighted_slopes(seasons["playerID"][keep], year[keep], shrunk, pa[keep])
        else:
            keep = value.notna() & year.notna()
            slope, _ = _plain_slopes(seasons["playerID"][keep], year[keep], value[keep])
        out[f"{stat}_trend"] = slope.reindex(players).astype(float)
    return out.reset_index()


def reference_slope(seasons: pd.DataFrame, stat: str) -> float:
    """The original unweighted per-player fit (counting stats; equivalence tests)."""
    group = seasons.sort_values("yearID")
    x = pd.to_numeric(group["yearID"], errors="coerce").values
    y = pd.to_numeric(group[stat], errors="coerce").values
    mask = ~pd.isna(y)
    x = x[mask]
    y = y[mask]
    if len(x) < 2:
        return np.nan
    return np.polyfit(x, y, 1)[0]
