"""Safe helpers for DataFrame vs list/dict session values (Streamlit Cloud persistence)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def coerce_dataframe(value: Any, *, empty: bool = True) -> pd.DataFrame:
    """Return a DataFrame; tolerate None, list, dict, or already-DataFrame inputs."""
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, list):
        try:
            return pd.DataFrame(value) if value else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    if isinstance(value, dict):
        try:
            return pd.DataFrame([value])
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def is_dataframe_empty(value: Any) -> bool:
    """True when value is missing or an empty DataFrame; safe for non-DataFrame types."""
    if value is None:
        return True
    if hasattr(value, "empty"):
        try:
            return bool(value.empty)
        except (TypeError, ValueError):
            return True
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return True


def safe_collection_len(value: Any) -> int:
    """Length without ``value or []`` — avoids ambiguous DataFrame truthiness."""
    if value is None:
        return 0
    if hasattr(value, "empty"):
        try:
            return 0 if value.empty else len(value)
        except (TypeError, ValueError):
            return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _sanitize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (np.floating, np.float32, np.float64)):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if hasattr(value, "item"):
        try:
            return _sanitize_scalar(value.item())
        except Exception:
            pass
    return value


def sanitize_for_json(value: Any) -> Any:
    """Recursively coerce persisted state to strict JSON (NaN/inf → None)."""
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        return sanitize_for_json(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return sanitize_for_json(value.to_dict())
    if isinstance(value, np.ndarray):
        return sanitize_for_json(value.tolist())
    if isinstance(value, (float, int, str, bool, np.floating, np.integer, np.bool_)):
        return _sanitize_scalar(value)
    if isinstance(value, dict):
        return {str(k): sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_json(v) for v in value]
    if hasattr(value, "tolist"):
        try:
            return sanitize_for_json(value.tolist())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _sanitize_scalar(value.item())
        except Exception:
            pass
    return str(value)


def has_dataframe_column(value: Any, column: str) -> bool:
    """True when value is a non-empty DataFrame containing ``column``."""
    df = coerce_dataframe(value)
    if is_dataframe_empty(df):
        return False
    return str(column) in df.columns


def can_merge_on_column(left: Any, right: Any, column: str) -> bool:
    """True when both sides are DataFrames with a shared merge key column."""
    left_df = coerce_dataframe(left)
    right_df = coerce_dataframe(right)
    key = str(column)
    return (
        not is_dataframe_empty(left_df)
        and not is_dataframe_empty(right_df)
        and key in left_df.columns
        and key in right_df.columns
    )


def safe_merge_dataframes(
    left: Any,
    right: Any,
    on: str,
    *,
    how: str = "left",
) -> pd.DataFrame:
    """Merge when merge key exists on both sides; otherwise return left coerced."""
    left_df = coerce_dataframe(left)
    if can_merge_on_column(left_df, right, on):
        return left_df.merge(coerce_dataframe(right), on=str(on), how=how)
    return left_df.copy() if not is_dataframe_empty(left_df) else pd.DataFrame()


def safe_sort_dataframe(
    value: Any,
    column: str,
    *,
    ascending: bool = True,
    **kwargs: Any,
) -> pd.DataFrame:
    """Sort by column when present; return empty DataFrame instead of raising KeyError."""
    df = coerce_dataframe(value)
    if is_dataframe_empty(df) or str(column) not in df.columns:
        return pd.DataFrame()
    return df.sort_values(str(column), ascending=ascending, **kwargs)


def safe_dataframe_first_row(value: Any, column: str | None = None) -> dict[str, Any]:
    """First row as dict when DataFrame is non-empty; optional column guard."""
    df = coerce_dataframe(value)
    if is_dataframe_empty(df):
        return {}
    if column is not None and str(column) not in df.columns:
        return {}
    try:
        row = df.iloc[0]
        return row.to_dict() if hasattr(row, "to_dict") else {}
    except Exception:
        return {}


def ensure_lab_team_rank_column(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute Projected Team Rank when team_summary was restored without it."""
    if is_dataframe_empty(df):
        return df
    if "Projected Team Rank" in df.columns:
        return df
    if "Total Projected Fantasy Value" not in df.columns:
        return df
    out = df.copy()
    out["Projected Team Rank"] = out["Total Projected Fantasy Value"].rank(
        ascending=False, method="min"
    )
    return out
