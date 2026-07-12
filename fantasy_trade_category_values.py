"""Trade category value resolution, aggregation, and display formatting."""

from __future__ import annotations

import pandas as pd

RATE_CATEGORIES = {
    "BA",
    "AVG",
    "OBP",
    "SLG",
    "OPS",
}

OPS_COLUMN_ALIASES = (
    "OPS",
    "On-base Plus Slugging",
    "On-Base Plus Slugging",
)
OBP_COLUMN_ALIASES = (
    "OBP",
    "On-base Percentage",
    "On Base Percentage",
)
SLG_COLUMN_ALIASES = (
    "SLG",
    "Slugging",
    "Slugging Percentage",
)


def _norm_col(name: str) -> str:
    return str(name or "").strip().upper()


def find_roster_column(df: pd.DataFrame | None, aliases: tuple[str, ...]) -> str | None:
    if df is None or df.empty:
        return None
    lookup = {_norm_col(col): col for col in df.columns}
    for alias in aliases:
        hit = lookup.get(_norm_col(alias))
        if hit:
            return hit
    return None


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def _row_numeric(row: pd.Series, aliases: tuple[str, ...]) -> float | None:
    for alias in aliases:
        if alias in row.index:
            num = pd.to_numeric(row.get(alias), errors="coerce")
            if pd.notna(num):
                return float(num)
    lookup = {_norm_col(str(col)): col for col in row.index}
    for alias in aliases:
        col = lookup.get(_norm_col(alias))
        if col is None:
            continue
        num = pd.to_numeric(row.get(col), errors="coerce")
        if pd.notna(num):
            return float(num)
    return None


def player_ops_value(row: pd.Series) -> float | None:
    direct = _row_numeric(row, OPS_COLUMN_ALIASES)
    if direct is not None:
        return direct
    obp = _row_numeric(row, OBP_COLUMN_ALIASES)
    slg = _row_numeric(row, SLG_COLUMN_ALIASES)
    if obp is not None and slg is not None:
        return obp + slg
    return None


def package_ops_value(df: pd.DataFrame | None) -> float:
    if df is None or df.empty:
        return float("nan")
    if len(df) == 1:
        value = player_ops_value(df.iloc[0])
        return float(value) if value is not None else float("nan")

    obp_col = find_roster_column(df, OBP_COLUMN_ALIASES)
    slg_col = find_roster_column(df, SLG_COLUMN_ALIASES)
    if obp_col and slg_col:
        obp = _numeric_series(df, obp_col)
        slg = _numeric_series(df, slg_col)
        if obp.notna().all() and slg.notna().all():
            return float(obp.mean()) + float(slg.mean())
        return float("nan")

    ops_col = find_roster_column(df, OPS_COLUMN_ALIASES)
    if ops_col:
        return float("nan")

    return float("nan")


def aggregate_trade_package_value(df: pd.DataFrame | None, category: str) -> float:
    cat = str(category or "").strip().upper()
    if df is None or df.empty:
        return float("nan")

    if cat == "OPS":
        return package_ops_value(df)

    if cat in RATE_CATEGORIES:
        aliases: tuple[str, ...]
        if cat == "AVG":
            aliases = ("AVG", "BA")
        else:
            aliases = (cat,)
        col = find_roster_column(df, aliases)
        if not col:
            return float("nan")
        values = _numeric_series(df, col)
        if values.notna().any():
            return float(values.mean())
        return float("nan")

    col = find_roster_column(df, (cat,)) or (cat if cat in df.columns else None)
    if not col:
        return float("nan")
    values = _numeric_series(df, col)
    if values.notna().any():
        return float(values.sum())
    return float("nan")


def format_trade_category_value(category: str, value: object, *, is_change: bool = False) -> str:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "—"

    cat = str(category or "").strip().upper()
    if cat in RATE_CATEGORIES:
        if is_change:
            text = f"{float(num):+.3f}"
            return text.replace("+0.", "+.").replace("-0.", "-.")
        return f"{float(num):.3f}".lstrip("0")

    if is_change:
        return f"{int(round(float(num))):+d}"
    return str(int(round(float(num))))
