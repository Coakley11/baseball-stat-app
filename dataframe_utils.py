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
