"""Safe helpers for DataFrame vs list/dict session values (Streamlit Cloud persistence)."""
from __future__ import annotations

from typing import Any

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
