"""Concise roster-context labels for Draft Assistant (no new scoring formulas).

Uses only projected stats and fields already on the recommendation row plus
simple roster-vs-pool averages computed in the app.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


def _f(x, default=np.nan):
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        return v if pd.notna(v) else default
    except Exception:
        return default


def team_fit_summary_line(
    row: Mapping[str, Any],
    *,
    draft_format: str,
    needed_positions: Iterable[str],
    category_needs: Iterable[str],
    roster_means: dict,
    pool_means: dict,
    current_position_counts: dict,
    target_position_counts: dict,
) -> str:
    """Return a short human-readable line (existing projections only)."""
    tags: list[str] = []
    needed = {str(p).strip() for p in needed_positions if str(p).strip()}
    cat_need = {str(c).strip() for c in category_needs if str(c).strip()}

    pos = str(row.get("Primary Position", "") or "").strip()
    tgt = int(target_position_counts.get(pos, 0) or 0)
    cur = int(current_position_counts.get(pos, 0) or 0)
    if pos and pos in needed:
        tags.append("Fills positional need")
    elif pos and tgt > 0 and cur >= tgt:
        tags.append(f"Depth at {pos}")

    if draft_format == "5x5 Roto":
        cat_map = {"R": "proj_R", "HR": "proj_HR", "RBI": "proj_RBI", "SB": "proj_SB", "BA": "proj_BA"}
        short = {"R": "runs", "HR": "HR", "RBI": "RBI", "SB": "SB", "BA": "AVG"}
    else:
        cat_map = {
            "Power": "proj_HR",
            "Run Production": "proj_RBI",
            "Speed": "proj_SB",
            "Walks/OPS": "proj_OPS",
            "Volume": "AB",
        }
        short = {
            "Power": "power",
            "Run Production": "RBI/R",
            "Speed": "SB",
            "Walks/OPS": "OPS",
            "Volume": "volume",
        }

    for label in cat_need:
        col = cat_map.get(label)
        if not col or col not in pool_means:
            continue
        rm = roster_means.get(col)
        pm = pool_means.get(col)
        if rm is None or pm is None or pd.isna(rm) or pd.isna(pm):
            continue
        if rm >= pm:
            continue
        pv = _f(row.get(col))
        if pd.isna(pv) or pd.isna(pm) or pm == 0:
            continue
        if pv >= pm:
            tags.append(f"Boosts {short.get(label, label)} vs roster")

    sc_b = _f(row.get("Position Scarcity Bonus"), 0.0)
    if not np.isnan(sc_b) and sc_b > 0.055:
        tags.append("Thin position upside")

    cat_b = _f(row.get("Category Need Bonus"), 0.0)
    if not np.isnan(cat_b) and cat_b > 0.04:
        tags.append("Category-need match")

    risk_pen = _f(row.get("Risk Penalty"), 0.0)
    brk = _f(row.get("Breakout Probability"))
    if not np.isnan(brk):
        if brk >= 0.55 and not np.isnan(risk_pen) and risk_pen > 0.035:
            tags.append("Upside; more volatility")
        elif brk >= 0.55:
            tags.append("Breakout-style upside")
    if not np.isnan(risk_pen) and risk_pen > 0.05:
        tags.append("Higher projection risk")

    fe = _f(row.get("Fantasy Edge"))
    if not np.isnan(fe):
        if fe >= 25:
            tags.append("Strong value vs market")
        elif fe <= -18:
            tags.append("Market premium profile")

    efv = _f(row.get("Expected Fantasy Value"))
    if not np.isnan(efv) and not np.isnan(risk_pen) and efv > 0 and risk_pen < 0.025:
        tags.append("Safer floor signal")

    if not tags:
        return "Balanced roster fit"

    out: list[str] = []
    for t in tags:
        if t not in out:
            out.append(t)
        if len(out) >= 4:
            break
    return " · ".join(out)
