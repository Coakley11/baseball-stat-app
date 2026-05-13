"""Concise draft-board strategy hints for Draft Assistant (no new scoring formulas).

Uses only columns already on the recommendation row plus pre-aggregated board
context from the same pipeline that builds Position Scarcity and Availability.
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


def draft_strategy_line(
    row: Mapping[str, Any],
    *,
    draft_format: str,
    current_pick: int,
    position_dropoff_by_pos: Mapping[str, Any],
    median_scarcity_dropoff: float | None,
    remaining_high_sb_count: int,
    category_needs: Iterable[str],
    roster_means: Mapping[str, Any],
    pool_means: Mapping[str, Any],
) -> str:
    """Return up to three short fragments joined by ' · ' (existing projections + board stats only)."""
    tags: list[str] = []
    pos = str(row.get("Primary Position", "") or "").strip()

    ap = _f(row.get("Availability Probability"))
    mr = _f(row.get("Market Rank"))
    pick = float(current_pick) if current_pick else np.nan

    # --- Availability / timing (uses same Availability Probability as Draft Fit) ---
    if not np.isnan(ap):
        if ap <= 0.38:
            tags.append("Low odds he lasts to your next pick at this market rank — snipe timing if you want him")
        elif ap >= 0.74:
            md = median_scarcity_dropoff if median_scarcity_dropoff is not None and not np.isnan(median_scarcity_dropoff) else None
            my_d = _f(position_dropoff_by_pos.get(pos), np.nan)
            if md is None or np.isnan(my_d) or my_d < md * 1.08:
                tags.append("Board ADP suggests you can likely wait a round unless you need the positional tier")

    if np.isnan(ap) and not np.isnan(mr) and not np.isnan(pick) and mr <= pick + 5:
        tags.append("Market rank lines up near your pick — treat availability as tight if ADP is accurate")

    # --- Positional scarcity curve (Scarcity Dropoff from assistant heatmap logic) ---
    my_drop = _f(position_dropoff_by_pos.get(pos), np.nan)
    if pos == "DH" and np.isnan(my_drop):
        my_drop = _f(position_dropoff_by_pos.get("DH"), np.nan)
    md = median_scarcity_dropoff
    if not np.isnan(my_drop) and md is not None and not np.isnan(md) and md > 0 and my_drop >= md * 1.18:
        tags.append("This position has a steep EFV cliff among remaining hitters — scarcity is real")

    # --- Speed on the wire (5x5 roto; hitter pool only in this app) ---
    if draft_format == "5x5 Roto" and remaining_high_sb_count >= 0:
        sb = _f(row.get("proj_SB"))
        if remaining_high_sb_count <= 14 and not np.isnan(sb) and sb >= 11:
            tags.append("Speed contributors are thinning on the board — this bat still carries SB")

    # --- Value vs ADP (Fantasy Edge already in row) ---
    fe = _f(row.get("Fantasy Edge"))
    if not np.isnan(fe) and fe >= 20:
        tags.append("Strong model edge vs market rank (same Fantasy Edge signal as the table)")

    # --- Category balance vs flagged needs (projection means only) ---
    cat_need = {str(c).strip() for c in category_needs if str(c).strip()}
    if "BA" in cat_need and "proj_BA" in roster_means and "proj_BA" in pool_means:
        rm = _f(roster_means.get("proj_BA"))
        pm = _f(pool_means.get("proj_BA"))
        pv = _f(row.get("proj_BA"))
        if not np.isnan(rm) and not np.isnan(pm) and rm < pm and not np.isnan(pv) and pv >= pm:
            tags.append("Balances AVG vs your roster gap vs the remaining pool")

    if "SB" in cat_need and draft_format == "5x5 Roto":
        sb = _f(row.get("proj_SB"))
        pm = _f(pool_means.get("proj_SB")) if pool_means else np.nan
        if not np.isnan(sb) and not np.isnan(pm) and sb >= pm and remaining_high_sb_count <= 18:
            tags.append("Fills flagged SB need while true speed is still on the table")

    # --- Risk posture (Risk Penalty + Breakout already in assistant row) ---
    risk = _f(row.get("Risk Penalty"), 0.0)
    brk = _f(row.get("Breakout Probability"))
    if not np.isnan(brk) and brk >= 0.55 and not np.isnan(risk) and risk > 0.042:
        tags.append("High-upside pick; adds expert-disagreement volatility")
    elif not np.isnan(risk) and risk < 0.024 and not np.isnan(fe) and fe > -15:
        tags.append("Safer expert-rank floor relative to other names in this band")

    # Dedupe, cap length
    out: list[str] = []
    for t in tags:
        if t and t not in out:
            out.append(t)
        if len(out) >= 3:
            break
    if not out:
        return "Neutral board read vs current filters — use Draft Fit / Team fit for the decision."
    return " · ".join(out)
