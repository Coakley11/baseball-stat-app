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
    "Trend slopes: ordinary least-squares line through recent seasons (minimum 2 seasons with data). "
    "Slopes are capped inside the stabilization layer so one spike year does not dominate."
)

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
        "explain": "Whether the player's home run production has recently been improving or declining.",
    },
    {
        "id": "R",
        "col": "R_trend",
        "season_col": "R",
        "label": "Runs",
        "kind": "counting",
        "explain": "Whether the player is scoring more or fewer runs over recent seasons.",
    },
    {
        "id": "RBI",
        "col": "RBI_trend",
        "season_col": "RBI",
        "label": "RBI",
        "kind": "counting",
        "explain": "Whether the player is driving in more or fewer runs over recent seasons.",
    },
    {
        "id": "SB",
        "col": "SB_trend",
        "season_col": "SB",
        "label": "SB",
        "kind": "counting",
        "explain": "Whether stolen-base production has been trending up or down.",
    },
    {
        "id": "2B",
        "col": "2B_trend",
        "season_col": "2B",
        "label": "2B",
        "kind": "counting",
        "explain": "Whether doubles production has been rising or falling in recent seasons.",
    },
    {
        "id": "3B",
        "col": "3B_trend",
        "season_col": "3B",
        "label": "3B",
        "kind": "counting",
        "explain": "Whether triples production has been rising or falling in recent seasons.",
    },
    {
        "id": "BA",
        "col": "BA_trend",
        "season_col": "BA",
        "label": "AVG",
        "kind": "rate",
        "explain": "Whether batting average has been trending up or down (rate per season).",
    },
    {
        "id": "OPS",
        "col": "OPS_trend",
        "season_col": "OPS",
        "label": "OPS",
        "kind": "rate",
        "explain": "Whether overall offensive production (OPS) has been trending up or down.",
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


def trend_direction_ui(direction: str) -> dict[str, str]:
    """Arrow label and HTML color for trend cards."""
    mapping = {
        "improving": {"arrow": "↑", "label": "Improving", "color": "#1a7f37"},
        "declining": {"arrow": "↓", "label": "Declining", "color": "#b42318"},
        "stable": {"arrow": "→", "label": "Stable", "color": "#57606a"},
        "unknown": {"arrow": "?", "label": "Limited data", "color": "#6e7781"},
    }
    return mapping.get(direction, mapping["unknown"])


def format_trend_slope(value, *, kind: str = "counting") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    v = float(value)
    if kind == "rate":
        return f"{v:+.3f}/yr"
    return f"{v:+.2f}/yr"


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


def build_trend_cards(row, season_history: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    cards = []
    hist = season_history if season_history is not None else pd.DataFrame()
    for spec in TREND_METRICS:
        val = _num(row, spec["col"])
        direction = classify_trend_direction(val, kind=spec["kind"])
        ui = trend_direction_ui(direction)
        spark = pd.DataFrame()
        sc = spec.get("season_col")
        if not hist.empty and sc in hist.columns:
            spark = hist[["yearID", sc]].dropna(subset=[sc]).rename(columns={"yearID": "Year", sc: spec["label"]})
        cards.append({
            "id": spec["id"],
            "label": spec["label"],
            "col": spec["col"],
            "value": val,
            "slope_display": format_trend_slope(val, kind=spec["kind"]),
            "direction": direction,
            "arrow": ui["arrow"],
            "direction_label": ui["label"],
            "color": ui["color"],
            "explain": spec["explain"],
            "sparkline": spark,
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
        "expected_fantasy_value": _num(row, "Expected Fantasy Value"),
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
        bundle["trend_cards"] = build_trend_cards(row, season_history)
        if stabilized:
            bundle["method_notes"].insert(0, PROJECTION_SYSTEM_LABEL)
    return bundle
