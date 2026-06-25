"""Safe table display formatting helpers (no Streamlit dependency)."""

from __future__ import annotations

import pandas as pd


def safe_format_stat_value(val, *, kind: str = "count") -> str:
    """Format a single cell; returns empty string for None/blank/non-numeric."""
    if val is None or (isinstance(val, str) and not str(val).strip()):
        return ""
    num = pd.to_numeric(val, errors="coerce")
    if pd.isna(num):
        return str(val) if val != "" else ""
    if kind == "rate":
        s = f"{num:.4f}"
        if 0 <= num < 1 and s.startswith("0."):
            return s[1:]
        if -1 < num < 0 and s.startswith("-0."):
            return "-" + s[2:]
        return s
    if kind == "int":
        return f"{int(round(num))}"
    return f"{num:.1f}"


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def filter_styler_format_map(display_df: pd.DataFrame, fmt: dict) -> dict:
    """Keep only formatters for columns that are numeric (avoid Styler crashes on strings)."""
    out: dict = {}
    for col, spec in (fmt or {}).items():
        if col not in display_df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(display_df[col]):
            continue
        out[col] = spec
    return out
