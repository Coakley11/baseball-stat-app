"""Small pure helpers shared by the app and the fantasy modules.

Moved verbatim from streamlit_app.py so fantasy_lineup_scoring and the trade/standings
modules can use them without importing the app. streamlit_app imports them back under the
same names. (live_draft_pick_scoring keeps its own identical copy of the two series helpers.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fmt_int(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.0f}"


def fmt_rate_3(x):
    x = pd.to_numeric(x, errors="coerce")
    if pd.isna(x): return ""
    return f"{x:.3f}"


def normalize_series(series):
    """Scale a numeric pandas Series to 0-1 safely.

    Used by the fantasy and draft assistant pages so different stats
    can be combined into one score without crashing on missing values,
    all-equal values, or non-numeric data.
    """
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() == 0:
        return pd.Series(0.0, index=series.index)
    s = s.fillna(s.median())
    min_val = s.min()
    max_val = s.max()
    if pd.isna(min_val) or pd.isna(max_val) or max_val == min_val:
        return pd.Series(0.0, index=series.index)
    return (s - min_val) / (max_val - min_val)


def safe_numeric_series(df, col, default=0.0):
    """Return a numeric Series for ``col`` with an index-aligned fallback."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype="float64")
