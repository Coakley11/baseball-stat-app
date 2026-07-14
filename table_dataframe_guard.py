"""Shared DataFrame coercion + diagnostics for table render callers."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def is_pandas_dataframe(obj: Any) -> bool:
    return isinstance(obj, pd.DataFrame)


def dataframe_shape(obj: Any) -> tuple[int, int] | None:
    if isinstance(obj, pd.DataFrame):
        return tuple(obj.shape)  # type: ignore[return-value]
    data = getattr(obj, "data", None)
    if isinstance(data, pd.DataFrame):
        return tuple(data.shape)  # type: ignore[return-value]
    return None


def ensure_dataframe(obj: Any, *, caller: str = "", key: str = "") -> pd.DataFrame:
    """Return a pandas DataFrame. Never returns None.

    Accepts DataFrame (copied), recovers Styler.data, coerces list/dict records,
    or returns empty when input is None / unusable.
    """
    if isinstance(obj, pd.DataFrame):
        return obj.copy()

    type_name = type(obj).__name__ if obj is not None else "NoneType"
    shape = dataframe_shape(obj)
    logger.warning(
        "ensure_dataframe: non-DataFrame → coerce | caller=%s key=%s type=%s is_none=%s shape=%s",
        caller or "—",
        key or "—",
        type_name,
        obj is None,
        shape,
    )

    # pandas Styler has .data but no .copy() — common crash source for render_output_table.
    data = getattr(obj, "data", None)
    if isinstance(data, pd.DataFrame):
        return data.copy()

    if obj is None:
        return pd.DataFrame()

    try:
        return pd.DataFrame(obj)
    except Exception:
        return pd.DataFrame()
