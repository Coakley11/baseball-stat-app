"""Per-player season trend slopes (Trend Value, Valuation, Draft, Sleepers).

The trend for a stat is the ordinary least-squares slope of the season values against
calendar year: the change per season. Seasons where the stat is missing are left out,
gap years keep their real spacing, and fewer than two seasons gives no trend (NaN).
Rate stats use each season's own rate, unweighted by playing time.

Same result as fitting ``np.polyfit(year, value, 1)`` per player, computed for all players
at once:  slope = Σ(x − x̄)(y − ȳ) / Σ(x − x̄)².
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def trend_slopes(seasons: pd.DataFrame, stats: Iterable[str]) -> pd.DataFrame:
    """One row per player in ``seasons`` (playerID, yearID, stats…): ``{stat}_trend`` columns."""
    stats = [s for s in stats if s in seasons.columns]
    players = pd.Index(pd.unique(seasons["playerID"]), name="playerID").sort_values()
    out = pd.DataFrame(index=players)
    year = pd.to_numeric(seasons["yearID"], errors="coerce").astype(float)
    for stat in stats:
        value = pd.to_numeric(seasons[stat], errors="coerce").astype(float)
        keep = value.notna() & year.notna()
        frame = pd.DataFrame({"pid": seasons["playerID"][keep], "x": year[keep], "y": value[keep]})
        grouped = frame.groupby("pid", sort=False)
        dx = frame["x"] - grouped["x"].transform("mean")
        dy = frame["y"] - grouped["y"].transform("mean")
        sums = pd.DataFrame({"pid": frame["pid"], "sxy": dx * dy, "sxx": dx * dx}).groupby("pid", sort=False).sum()
        counts = grouped.size()
        slope = (sums["sxy"] / sums["sxx"]).where((counts >= 2) & (sums["sxx"] > 0))
        out[f"{stat}_trend"] = slope.reindex(players).astype(float)
    return out.reset_index()


def reference_slope(seasons: pd.DataFrame, stat: str) -> float:
    """The original per-player fit (kept for equivalence tests)."""
    group = seasons.sort_values("yearID")
    x = pd.to_numeric(group["yearID"], errors="coerce").values
    y = pd.to_numeric(group[stat], errors="coerce").values
    mask = ~pd.isna(y)
    x = x[mask]
    y = y[mask]
    if len(x) < 2:
        return np.nan
    return np.polyfit(x, y, 1)[0]
