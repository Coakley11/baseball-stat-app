"""Pure helpers for player Projection Breakdown UI (no Streamlit).

Trend slopes are linear regression per season (yearID vs stat), same as ``compute_trend_slope``
in streamlit_app.py. Stabilized counting/rate projections come from ``projection_calibration``
via the Draft Lab / unified draft pool pipeline.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROJECTION_SYSTEM_LABEL = (
    "Draft Lab stabilized pipeline — same anchors, calibration, elite-star protection, "
    "playing-time realism, and confidence logic as Live Draft Room, Draft Simulation Test Mode, "
    "and Fantasy Draft Assistant."
)

TREND_METHOD_NOTE = (
    "Trends use recent full seasons (40+ games when possible). Slopes show per-year change; "
    "big spikes are softened in the actual projection math."
)

# Display caps so one partial year or tiny samples do not show absurd slopes in the popup.
DISPLAY_COUNT_SLOPE_CAP = 10.0
DISPLAY_RATE_SLOPE_CAP = 0.045
MIN_SEASON_GAMES_FOR_TREND = 40

STABILIZED_ROW_MARKERS = frozenset({
    "Projection Confidence Score",
    "proj_G",
    "Realistic Base Projection Score",
    "Elite Star Score",
})


TREND_METRICS = (
    {
        "id": "HR",
        "col": "HR_trend",
        "season_col": "HR",
        "label": "HR",
        "kind": "counting",
        "explain": "Recent trend in home run production.",
    },
    {
        "id": "R",
        "col": "R_trend",
        "season_col": "R",
        "label": "Runs",
        "kind": "counting",
        "explain": "Recent trend in runs scored.",
    },
    {
        "id": "RBI",
        "col": "RBI_trend",
        "season_col": "RBI",
        "label": "RBI",
        "kind": "counting",
        "explain": "Recent trend in runs batted in.",
    },
    {
        "id": "SB",
        "col": "SB_trend",
        "season_col": "SB",
        "label": "SB",
        "kind": "counting",
        "explain": "Recent trend in stolen bases.",
    },
    {
        "id": "2B",
        "col": "2B_trend",
        "season_col": "2B",
        "label": "2B",
        "kind": "counting",
        "explain": "Recent trend in doubles.",
    },
    {
        "id": "3B",
        "col": "3B_trend",
        "season_col": "3B",
        "label": "3B",
        "kind": "counting",
        "explain": "Recent trend in triples.",
    },
    {
        "id": "BA",
        "col": "BA_trend",
        "season_col": "BA",
        "label": "AVG",
        "kind": "rate",
        "explain": "Recent trend in batting average.",
    },
    {
        "id": "OPS",
        "col": "OPS_trend",
        "season_col": "OPS",
        "label": "OPS",
        "kind": "rate",
        "explain": "Recent trend in overall offensive production (OPS).",
    },
)

COUNTING_PROJECTIONS = (
    ("HR", "proj_HR"),
    ("RBI", "proj_RBI"),
    ("R", "proj_R"),
    ("SB", "proj_SB"),
    ("AVG", "proj_BA"),
    ("OPS", "proj_OPS"),
)


def row_has_stabilized_projection(row) -> bool:
    """True when the row came from the unified draft / draft-lab pipeline."""
    if row is None or not hasattr(row, "index"):
        return False
    idx = set(row.index)
    return bool(STABILIZED_ROW_MARKERS & idx)


def _num(row, col, default=np.nan):
    if row is None or not hasattr(row, "get"):
        return default
    try:
        if hasattr(row, "index") and col not in row.index:
            return default
        val = row[col] if hasattr(row, "index") else row.get(col, default)
        return float(val) if val is not None and not (isinstance(val, float) and np.isnan(val)) else default
    except Exception:
        return default


def classify_trend_direction(value, *, kind: str = "counting") -> str:
    """Return improving | declining | stable | unknown."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "unknown"
    v = float(value)
    if kind == "rate":
        if abs(v) < 0.006:
            return "stable"
        return "improving" if v > 0 else "declining"
    if abs(v) < 0.75:
        return "stable"
    return "improving" if v > 0 else "declining"


def cap_slope_for_display(value, *, kind: str = "counting"):
    """Clip extreme slopes for fan-facing trend cards."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    v = float(value)
    if kind == "rate":
        return float(np.clip(v, -DISPLAY_RATE_SLOPE_CAP, DISPLAY_RATE_SLOPE_CAP))
    return float(np.clip(v, -DISPLAY_COUNT_SLOPE_CAP, DISPLAY_COUNT_SLOPE_CAP))


def compute_season_trend_slope(season_df: pd.DataFrame, stat_col: str):
    """Per-season linear trend (same method as the app's ``compute_trend_slope``)."""
    if season_df is None or season_df.empty or stat_col not in season_df.columns:
        return np.nan
    group = season_df.sort_values("yearID")
    x = pd.to_numeric(group["yearID"], errors="coerce").values
    y = pd.to_numeric(group[stat_col], errors="coerce").values
    mask = ~np.isnan(y)
    x, y = x[mask], y[mask]
    if len(x) < 2:
        return np.nan
    return float(np.polyfit(x, y, 1)[0])


def compute_display_trends_from_seasons(
    season_df: pd.DataFrame | None,
    *,
    min_games: int = MIN_SEASON_GAMES_FOR_TREND,
) -> tuple[dict[str, float], int]:
    """
    Trend slopes from qualifying recent seasons only.
    Returns (col -> slope, seasons_used).
    """
    if season_df is None or season_df.empty:
        return {}, 0
    df = season_df.copy()
    if "G" in df.columns:
        df = df[pd.to_numeric(df["G"], errors="coerce").fillna(0) >= int(min_games)]
    seasons_used = len(df)
    if seasons_used < 2:
        return {}, seasons_used
    out = {}
    for spec in TREND_METRICS:
        sc = spec["season_col"]
        if sc not in df.columns:
            continue
        slope = compute_season_trend_slope(df, sc)
        if slope is None or (isinstance(slope, float) and np.isnan(slope)):
            continue
        out[spec["col"]] = cap_slope_for_display(slope, kind=spec["kind"])
    return out, seasons_used


def format_trimmed_signed(value) -> str:
    """Signed slope with trimmed decimals (e.g. +2, +2.4, -0.018, +0.007)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    v = float(value)
    if abs(v) < 1e-9:
        return "+0"
    av = abs(v)
    if av >= 10:
        decimals = 0
    elif av >= 1:
        decimals = 1
    else:
        decimals = 3
    text = f"{v:+.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
        if text in ("+", "-"):
            text += "0"
    return text


def _slope_unit(metric_id: str, display_label: str) -> str:
    if metric_id == "BA":
        return "AVG"
    return display_label


def format_trend_slope_line(value, metric_id: str, display_label: str, *, kind: str = "counting") -> str:
    """Human-readable slope line, e.g. ``Slope: +2.4 HR/year``."""
    num = format_trimmed_signed(value)
    if num == "n/a":
        return "Slope: n/a"
    unit = _slope_unit(metric_id, display_label)
    suffix = "/year"
    return f"Slope: {num} {unit}{suffix}"


def trend_direction_display_label(direction: str, value, *, kind: str = "counting") -> str:
    """Plain label: Improving, Stable, Declining, Slight decline, etc."""
    if direction == "unknown":
        return "Limited data"
    if direction == "stable":
        return "Stable"
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Stable" if direction == "stable" else direction.title()
    v = float(value)
    av = abs(v)
    if direction == "improving":
        if kind == "rate" and av < 0.015:
            return "Slight improvement"
        if kind == "counting" and av < 2.5:
            return "Slight improvement"
        return "Improving"
    if direction == "declining":
        if kind == "rate" and av < 0.015:
            return "Slight decline"
        if kind == "counting" and av < 2.5:
            return "Slight decline"
        return "Declining"
    return direction.title()


def trend_direction_ui(direction: str, value=None, *, kind: str = "counting") -> dict[str, str]:
    """Arrow, label, and HTML color for trend rows."""
    label = trend_direction_display_label(direction, value, kind=kind)
    if direction == "improving":
        color = "#1a7f37"
        arrow = "↑"
    elif direction == "declining":
        color = "#b42318"
        arrow = "↓"
    elif direction == "stable":
        color = "#57606a"
        arrow = "→"
    else:
        color = "#6e7781"
        arrow = "?"
    return {"arrow": arrow, "label": label, "color": color}


def format_trend_slope(value, *, kind: str = "counting") -> str:
    """Legacy alias — prefer ``format_trend_slope_line``."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    return format_trimmed_signed(value) + "/yr"


def player_season_history(
    yearly_df: pd.DataFrame,
    player_id: str,
    *,
    window_years: int = 3,
    stat_cols: tuple[str, ...] = ("HR", "R", "RBI", "SB", "2B", "3B", "BA", "OPS", "G", "AB"),
) -> pd.DataFrame:
    """Recent season lines for sparklines (newest year last)."""
    if yearly_df is None or yearly_df.empty or not player_id:
        return pd.DataFrame()
    sub = yearly_df[yearly_df["playerID"].astype(str) == str(player_id)].copy()
    if sub.empty:
        return pd.DataFrame()
    sub = sub.sort_values("yearID").tail(int(window_years))
    cols = ["yearID"] + [c for c in stat_cols if c in sub.columns]
    out = sub[cols].copy()
    for c in cols:
        if c != "yearID":
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def build_trend_cards(
    row,
    season_history: pd.DataFrame | None = None,
    *,
    season_overrides: dict[str, float] | None = None,
    seasons_used: int = 0,
) -> list[dict[str, Any]]:
    """Compact trend rows (direction + slope + explanation); prefers season-based slopes when available."""
    overrides = dict(season_overrides or {})
    if not overrides and season_history is not None and not season_history.empty:
        overrides, seasons_used = compute_display_trends_from_seasons(season_history)

    cards = []
    for spec in TREND_METRICS:
        val = overrides.get(spec["col"])
        if val is None or (isinstance(val, float) and np.isnan(val)):
            val = cap_slope_for_display(_num(row, spec["col"]), kind=spec["kind"])
        else:
            val = cap_slope_for_display(val, kind=spec["kind"])

        direction = classify_trend_direction(val, kind=spec["kind"])
        ui = trend_direction_ui(direction, val, kind=spec["kind"])
        trend_name = _slope_unit(spec["id"], spec["label"])
        title = f"{trend_name} Trend"
        explain = spec["explain"]
        if seasons_used > 0 and seasons_used < 2:
            explain = f"{explain} Limited playing time in the window — treat as a soft read."
        elif spec["col"] not in overrides and seasons_used >= 2:
            explain = f"{explain} Based on the model's recent-season blend."

        cards.append({
            "id": spec["id"],
            "title": title,
            "label": spec["label"],
            "col": spec["col"],
            "value": val,
            "slope_line": format_trend_slope_line(val, spec["id"], spec["label"], kind=spec["kind"]),
            "slope_display": format_trimmed_signed(val),
            "direction": direction,
            "arrow": ui["arrow"],
            "direction_label": ui["label"],
            "color": ui["color"],
            "explain": explain,
        })
    return cards


def build_projection_snapshot(row) -> dict[str, Any]:
    """Extract stabilized projection fields from a pool row."""
    projections = {}
    for label, col in COUNTING_PROJECTIONS:
        v = _num(row, col)
        if not np.isnan(v):
            projections[label] = v

    conf = row.get("Projection Confidence") if hasattr(row, "get") else None
    conf_score = _num(row, "Projection Confidence Score")
    warning = row.get("Projection Warning") if hasattr(row, "get") else ""
    if isinstance(warning, float) and np.isnan(warning):
        warning = ""

    efv_raw = _num(row, "Expected Fantasy Value")
    player_grade = None
    if efv_raw is not None and not (isinstance(efv_raw, float) and np.isnan(efv_raw)):
        ev = float(efv_raw)
        player_grade = round(ev * 100.0, 2) if 0 < ev <= 1.5 else round(ev, 2)

    return {
        "projections": projections,
        "confidence_label": str(conf).strip() if conf is not None and str(conf).strip() else None,
        "confidence_score": None if np.isnan(conf_score) else conf_score,
        "warning": str(warning).strip() if warning else "",
        "proj_g": _num(row, "proj_G"),
        "proj_ab": _num(row, "proj_AB"),
        "elite_star_score": _num(row, "Elite Star Score"),
        "star_protected": bool(row.get("Star Protected")) if hasattr(row, "get") else False,
        "very_limited_data": bool(row.get("Very Limited Data")) if hasattr(row, "get") else False,
        "volatility_score": _num(row, "Volatility Score"),
        "player_grade": player_grade,
        "realistic_base": _num(row, "Realistic Base Projection Score"),
        "ml_adjustment": _num(row, "ML Adjustment"),
        "ml_projection_score": _num(row, "ML Projection Score"),
        "breakout_probability": _num(row, "Breakout Probability"),
        "risk_score": _num(row, "Risk Score"),
        "market_rank": _num(row, "Market Rank"),
        "model_rank": _num(row, "Model Rank"),
        "fantasy_edge": _num(row, "Fantasy Edge"),
        "primary_position": row.get("Primary Position") if hasattr(row, "get") else None,
        "age": _num(row, "Age"),
        "games": _num(row, "G"),
        "ab": _num(row, "AB"),
        "years_played": _num(row, "years_played"),
    }


def build_projection_breakdown_bundle(
    player_display_name: str,
    row,
    *,
    data_source: str,
    projection_system: str,
    window_years: int = 3,
    projection_style: str = "Balanced",
    fantasy_format: str = "5x5 Roto",
    season_history: pd.DataFrame | None = None,
    lahman_fallback: dict | None = None,
) -> dict[str, Any]:
    """Structured payload for the Projection Breakdown dialog."""
    stabilized = row_has_stabilized_projection(row)
    bundle = {
        "player_name": str(player_display_name).strip(),
        "data_source": data_source,
        "projection_system": projection_system if stabilized else (
            "Legacy page table (simple latest + trend slope). "
            "Open from Draft Assistant / Sleepers for full stabilized numbers."
        ),
        "stabilized": stabilized,
        "window_years": int(window_years),
        "projection_style": projection_style,
        "fantasy_format": fantasy_format,
        "method_notes": [TREND_METHOD_NOTE],
        "trend_cards": [],
        "snapshot": {},
        "lahman_fallback": lahman_fallback,
    }
    if row is not None and hasattr(row, "index"):
        bundle["snapshot"] = build_projection_snapshot(row)
        season_overrides, seasons_used = compute_display_trends_from_seasons(season_history)
        bundle["trend_cards"] = build_trend_cards(
            row,
            season_history,
            season_overrides=season_overrides,
            seasons_used=seasons_used,
        )
        bundle["trend_seasons_used"] = seasons_used
        if stabilized:
            bundle["method_notes"].insert(0, PROJECTION_SYSTEM_LABEL)
    return bundle
