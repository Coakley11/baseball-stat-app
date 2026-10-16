"""Valuation page scores: recent production blended with trend momentum.

* Perf_Score  — weighted window totals (R, H, 2B, 3B, HR, RBI, SB) plus window rates ×100
  (BA, OBP, SLG, OPS). Rates come from the window totals.
* Trend_Score — weighted per-season trend slopes (trend_slopes); rate slopes ×100.
  A player without a trend (one season) contributes 0.
* Valuation_Raw = w_current·Perf + w_trend·Trend, min–max scaled to 0–1 over the players
  being valued (Valuation_Score); all-equal or empty → 0.
"""

from __future__ import annotations

import pandas as pd

TREND_WEIGHTS = {
    "R_trend": 1.0, "H_trend": 0.5, "2B_trend": 0.75, "3B_trend": 0.75, "HR_trend": 2.0,
    "RBI_trend": 1.5, "SB_trend": 1.0, "BB_trend": 0.5,
    "BA_trend": 100, "OBP_trend": 100, "SLG_trend": 100, "OPS_trend": 100,
}
PERF_COUNT_WEIGHTS = {"R": 0.10, "H": 0.05, "2B": 0.05, "3B": 0.05, "HR": 0.25, "RBI": 0.20, "SB": 0.10}
PERF_RATE_WEIGHTS = {"BA": 0.05, "OBP": 0.10, "SLG": 0.10, "OPS": 0.10}


def add_valuation_scores(df: pd.DataFrame, w_current: float, w_trend: float) -> pd.DataFrame:
    """Add Trend_Score, Perf_Score, Valuation_Raw and Valuation_Score to ``df`` (in place)."""
    df["Trend_Score"] = sum(df[col].fillna(0) * w for col, w in TREND_WEIGHTS.items())
    df["Perf_Score"] = sum(df[col] * w for col, w in PERF_COUNT_WEIGHTS.items()) + sum(
        df[col].fillna(0) * 100 * w for col, w in PERF_RATE_WEIGHTS.items()
    )
    df["Valuation_Raw"] = w_current * df["Perf_Score"] + w_trend * df["Trend_Score"]
    val_min = df["Valuation_Raw"].min()
    val_max = df["Valuation_Raw"].max()
    if pd.notna(val_min) and pd.notna(val_max) and val_max != val_min:
        df["Valuation_Score"] = (df["Valuation_Raw"] - val_min) / (val_max - val_min)
    else:
        df["Valuation_Score"] = 0.0
    return df
