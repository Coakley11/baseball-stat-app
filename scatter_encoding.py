"""Scatterplot size encoding — safe for boolean/object columns."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

SCATTER_SIZE_NUMERIC_COL = "_scatter_size_numeric"
_SIZE_BLOCKED_NAMES = frozenset(
    {
        "ishalloffamer",
        "is hall of famer",
        "hall of fame",
    }
)


def scatter_numeric_size_values(series: pd.Series) -> pd.Series | None:
    """Coerce a size column to float for quantile sizing; None when not usable."""
    if series is None or len(series) == 0:
        return None
    if pd.api.types.is_bool_dtype(series):
        return series.astype(float)
    vals = pd.to_numeric(series, errors="coerce")
    vals = vals.dropna()
    if vals.empty:
        return None
    return vals.astype(float)


def is_quantitative_size_column(series: pd.Series) -> bool:
    """True when a column can drive continuous dot-size scaling."""
    if pd.api.types.is_bool_dtype(series):
        return False
    vals = scatter_numeric_size_values(series)
    if vals is None or len(vals) == 0:
        return False
    try:
        uniq = vals.nunique(dropna=True)
    except TypeError:
        return False
    return int(uniq) >= 2


def filter_size_by_columns(df: pd.DataFrame, numeric_cols: list[str]) -> list[str]:
    """Size-by options: numeric columns only, excluding boolean/HOF flags."""
    out: list[str] = []
    for col in numeric_cols:
        key = str(col).replace("_", " ").lower().strip()
        if key in _SIZE_BLOCKED_NAMES or col in ("isHallOfFamer",):
            continue
        if col not in df.columns:
            continue
        if is_quantitative_size_column(df[col]):
            out.append(col)
    return out


def _size_column_blocked(size_col: str, series: pd.Series) -> bool:
    key = str(size_col).replace("_", " ").lower().strip()
    if key in _SIZE_BLOCKED_NAMES or size_col in ("isHallOfFamer",):
        return True
    return pd.api.types.is_bool_dtype(series)


def prepare_scatter_size_column(chart_df: pd.DataFrame, size_col: str) -> tuple[pd.DataFrame, str | None]:
    """Return chart_df copy with numeric size column; None when size encoding unavailable."""
    if size_col in (None, "None", "") or size_col not in chart_df.columns:
        return chart_df, None
    if _size_column_blocked(size_col, chart_df[size_col]):
        return chart_df, None
    vals = scatter_numeric_size_values(chart_df[size_col])
    if vals is None or vals.empty:
        return chart_df, None
    try:
        low = float(vals.quantile(0.05))
        high = float(vals.quantile(0.95))
    except (TypeError, ValueError, FloatingPointError):
        return chart_df, None
    if not np.isfinite(low) or not np.isfinite(high):
        return chart_df, None
    if high <= low:
        try:
            low, high = float(vals.min()), float(vals.max())
        except (TypeError, ValueError):
            return chart_df, None
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return chart_df, None
    out = chart_df.copy()
    out[SCATTER_SIZE_NUMERIC_COL] = pd.to_numeric(chart_df[size_col], errors="coerce")
    if pd.api.types.is_bool_dtype(chart_df[size_col]):
        out[SCATTER_SIZE_NUMERIC_COL] = chart_df[size_col].astype(float)
    out[SCATTER_SIZE_NUMERIC_COL] = out[SCATTER_SIZE_NUMERIC_COL].fillna(float(low))
    return out, SCATTER_SIZE_NUMERIC_COL


def scatter_size_domain(chart_df: pd.DataFrame, size_col: str) -> tuple[float, float] | None:
    """5th–95th percentile domain for size scaling."""
    if size_col not in chart_df.columns:
        return None
    vals = scatter_numeric_size_values(chart_df[size_col])
    if vals is None or vals.empty:
        return None
    try:
        low = float(vals.quantile(0.05))
        high = float(vals.quantile(0.95))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            low, high = float(vals.min()), float(vals.max())
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            high = low + 1e-9
        return low, high
    except (TypeError, ValueError, FloatingPointError):
        return None


def build_scatter_size_encoding(chart_df: pd.DataFrame, size_col: str, *, alt_module: Any):
    """Build Altair Size encoding or None; never raises on bad size columns."""
    prepared, num_col = prepare_scatter_size_column(chart_df, size_col)
    if num_col is None:
        return None, chart_df
    domain = scatter_size_domain(prepared, size_col)
    if domain is None:
        return None, chart_df
    low, high = domain
    return (
        alt_module.Size(
            f"{num_col}:Q",
            title=size_col,
            scale=alt_module.Scale(domain=[low, high], range=[20, 300], clamp=True),
            legend=alt_module.Legend(title=size_col),
        ),
        prepared,
    )
