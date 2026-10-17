"""Hitting stats for an exact scoring period (inclusive MLB game dates).

Uses the MLB Stats API ``byDateRange`` split, which returns each hitter's totals for the
date range with every component needed to rebuild rate stats (AB, H, 2B, 3B, HR, BB,
HBP, SF, TB, PA). Checked against a player's game log: the range totals match exactly.

Only additive components are kept; rates are always rebuilt from summed components.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import pandas as pd

COMPONENTS = ("PA", "AB", "H", "2B", "3B", "HR", "R", "RBI", "SB", "BB", "HBP", "SF", "TB", "G")
_API_FIELDS = {
    "PA": "plateAppearances", "AB": "atBats", "H": "hits", "2B": "doubles", "3B": "triples",
    "HR": "homeRuns", "R": "runs", "RBI": "rbi", "SB": "stolenBases", "BB": "baseOnBalls",
    "HBP": "hitByPitch", "SF": "sacFlies", "TB": "totalBases", "G": "gamesPlayed",
}

PeriodStatsProvider = Callable[[str, str], pd.DataFrame]


def fetch_period_hitting_stats(start: str | date, end: str | date, *, timeout: float = 20.0) -> pd.DataFrame:
    """Every MLB hitter's totals between ``start`` and ``end`` inclusive."""
    import requests

    start_s = str(start)[:10]
    end_s = str(end)[:10]
    params = {
        "stats": "byDateRange", "group": "hitting", "playerPool": "ALL", "sportIds": 1, "limit": 5000,
        "season": int(start_s[:4]), "startDate": start_s, "endDate": end_s,
    }
    resp = requests.get("https://statsapi.mlb.com/api/v1/stats", params=params, timeout=timeout)
    resp.raise_for_status()
    rows: list[dict[str, Any]] = []
    for split in (resp.json().get("stats") or [{}])[0].get("splits", []):
        player = split.get("player") or {}
        stat = split.get("stat") or {}
        row: dict[str, Any] = {"MLBAM ID": player.get("id"), "Player": player.get("fullName", "")}
        for col, field in _API_FIELDS.items():
            row[col] = stat.get(field, 0) or 0
        rows.append(row)
    df = pd.DataFrame(rows, columns=["MLBAM ID", "Player", *COMPONENTS])
    for col in COMPONENTS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def rates_from_components(c: dict[str, float]) -> dict[str, float | None]:
    """AVG = H/AB; OBP = (H+BB+HBP)/(AB+BB+HBP+SF); SLG = TB/AB; OPS = OBP + SLG."""
    ab = float(c.get("AB") or 0)
    on_base_den = ab + float(c.get("BB") or 0) + float(c.get("HBP") or 0) + float(c.get("SF") or 0)
    avg = float(c.get("H") or 0) / ab if ab else None
    obp = (float(c.get("H") or 0) + float(c.get("BB") or 0) + float(c.get("HBP") or 0)) / on_base_den if on_base_den else None
    tb = c.get("TB")
    if tb is None:
        tb = float(c.get("H") or 0) + float(c.get("2B") or 0) + 2 * float(c.get("3B") or 0) + 3 * float(c.get("HR") or 0)
    slg = float(tb) / ab if ab else None
    ops = obp + slg if obp is not None and slg is not None else None
    return {"AVG": avg, "OBP": obp, "SLG": slg, "OPS": ops}
