"""Team rate stats and roto category points for fantasy standings.

* Team rates follow the usual roto rule: rebuild the rate from the summed parts, so a
  regular's 600 at-bats count more than a bench bat's 20. Team BA = ΣH / ΣAB,
  OBP = Σ(H+BB+HBP) / Σ(AB+BB+HBP+SF), SLG = ΣTB / ΣAB, OPS = OBP + SLG.
  When the parts are missing (e.g. an uploaded CSV with only BA), the plain mean of
  the players' rates is used instead.
* Roto points: with N teams the best team in a category gets N points and the worst 1.
  Tied teams split the points they cover — two teams tied for first in a 4-team
  league get (4 + 3) / 2 = 3.5 each.
"""

from __future__ import annotations

import pandas as pd


def _num(df: pd.DataFrame, col: str) -> pd.Series | None:
    if col not in df.columns:
        return None
    vals = pd.to_numeric(df[col], errors="coerce")
    return vals if vals.notna().any() else None


def _sum(df: pd.DataFrame, *cols: str) -> float | None:
    """Sum of the listed columns; None when any is missing. HBP/SF default to 0."""
    total = 0.0
    for col in cols:
        vals = _num(df, col)
        if vals is None:
            if col in ("HBP", "SF"):
                continue
            return None
        total += float(vals.fillna(0).sum())
    return total


def _from_components(df: pd.DataFrame, stat: str) -> float | None:
    ab = _sum(df, "AB")
    if stat == "BA":
        hits = _sum(df, "H")
        return hits / ab if hits is not None and ab else None
    if stat == "OBP":
        on_base = _sum(df, "H", "BB", "HBP")
        chances = _sum(df, "AB", "BB", "HBP", "SF")
        return on_base / chances if on_base is not None and chances else None
    if stat == "SLG":
        if _sum(df, "H", "2B", "3B", "HR") is None or not ab:
            return None
        total_bases = _sum(df, "H") + _sum(df, "2B") + 2 * _sum(df, "3B") + 3 * _sum(df, "HR")
        return total_bases / ab
    if stat == "OPS":
        obp, slg = _from_components(df, "OBP"), _from_components(df, "SLG")
        return obp + slg if obp is not None and slg is not None else None
    return None


def team_rate(df: pd.DataFrame, stat: str) -> float | None:
    """Team value for a rate stat (BA/AVG, OBP, SLG, OPS) from the players in ``df``."""
    stat = str(stat or "").strip().upper()
    if stat == "AVG":
        stat = "BA"
    if df is None or df.empty:
        return None
    value = _from_components(df, stat)
    if value is not None:
        return value
    vals = _num(df, stat)
    return float(vals.mean()) if vals is not None else None


def roto_points(values: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    """Roto points per team for one category; ties share the points they span."""
    return pd.to_numeric(values, errors="coerce").rank(ascending=higher_is_better, method="average")
