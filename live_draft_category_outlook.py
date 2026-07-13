"""Team category outlook / projection bars for Live Draft Room."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from live_draft_pick_scoring import _draft_lab_infer_category_needs, safe_numeric_series


def _bar_blocks(level: int, max_blocks: int = 5) -> str:
    filled = max(0, min(max_blocks, int(level)))
    return "▓" * filled + "░" * (max_blocks - filled)


def _level_label(ratio: float) -> tuple[str, int]:
    if ratio < 0.55:
        return "Very Low", 1
    if ratio < 0.75:
        return "Low", 2
    if ratio < 0.95:
        return "Average", 3
    if ratio < 1.15:
        return "Strong", 4
    return "Elite", 5


def _fantasy_format_from_config(config: dict[str, Any]) -> str:
    scoring = str(config.get("scoring_type") or config.get("scoring") or "Roto (5x5)")
    if "point" in scoring.lower():
        return "Points League"
    return "5x5 Roto"


def compute_category_outlook(
    roster_df: pd.DataFrame | None,
    pool_df: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
    roster_gaps: list[str] | None = None,
) -> dict[str, Any]:
    """Live category bars for one team using projected stats vs pool baseline."""
    config = config or {}
    fantasy_format = _fantasy_format_from_config(config)
    roster_df = roster_df if roster_df is not None else pd.DataFrame()
    pool_df = pool_df if pool_df is not None else pd.DataFrame()

    if fantasy_format == "5x5 Roto":
        specs = [
            ("proj_SB", "SB", "sum"),
            ("proj_HR", "HR", "sum"),
            ("proj_RBI", "RBI", "sum"),
            ("proj_BA", "AVG", "rate"),
            ("proj_R", "Runs", "sum"),
        ]
    else:
        specs = [
            ("proj_SB", "Speed", "sum"),
            ("proj_HR", "Power", "sum"),
            ("proj_RBI", "Run Production", "sum"),
            ("proj_OPS", "Walks/OPS", "rate"),
            ("proj_R", "Runs", "sum"),
        ]

    n_players = max(1, len(roster_df))
    bars: list[dict[str, Any]] = []
    needs: list[str] = []
    strengths: list[str] = []

    for col, label, kind in specs:
        if pool_df.empty or col not in pool_df.columns:
            continue
        pool_med = float(pd.to_numeric(pool_df[col], errors="coerce").median() or 0)
        if pool_med <= 0 and kind == "rate":
            pool_med = 0.001

        expected = pool_med if kind == "rate" else pool_med * n_players

        if roster_df.empty or col not in roster_df.columns:
            team_val = 0.0
        elif kind == "rate":
            vals = pd.to_numeric(roster_df[col], errors="coerce")
            team_val = float(vals.mean()) if vals.notna().any() else 0.0
        else:
            team_val = float(pd.to_numeric(roster_df[col], errors="coerce").fillna(0).sum())

        ratio = team_val / expected if expected > 0 else 0.0
        level_txt, level_num = _level_label(ratio)
        bars.append(
            {
                "category": label,
                "column": col,
                "team_value": team_val,
                "expected": expected,
                "ratio": ratio,
                "level": level_txt,
                "level_num": level_num,
                "bar": _bar_blocks(level_num),
            }
        )
        if level_num <= 2:
            needs.append(label)
        elif level_num >= 4:
            strengths.append(label)

    inferred = []
    try:
        from draft_needs import infer_hitter_category_needs

        inferred = infer_hitter_category_needs(
            roster_df,
            pool_df,
            fantasy_format=fantasy_format,
        )
    except ImportError:
        inferred = _draft_lab_infer_category_needs(roster_df, pool_df, fantasy_format=fantasy_format)
    for cat in inferred:
        if cat not in needs:
            needs.append(cat)

    # Prefer projected-total hitter categories; drop position-depth noise from needs list.
    needs = [n for n in needs if not str(n).endswith(" Depth") and n != "Outfield Depth"]

    return {
        "bars": bars,
        "needs_attention": needs[:6],
        "strengths": strengths[:6],
        "fantasy_format": fantasy_format,
    }


def _player_strength_specs(row: Any, config: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Projection columns for ranking a single player's category strengths."""
    pos = str(row.get("Primary Position") or "").upper()
    scoring = str(config.get("scoring_type") or config.get("scoring") or "Roto (5x5)").lower()
    is_pitcher = pos in ("P", "SP", "RP", "CL")

    if is_pitcher:
        return [
            ("proj_SV", "Saves", "sum"),
            ("proj_K", "K", "sum"),
            ("proj_ERA", "ERA", "lower"),
            ("proj_WHIP", "WHIP", "lower"),
        ]
    if "point" in scoring:
        return [
            ("proj_HR", "HR", "sum"),
            ("proj_RBI", "RBI", "sum"),
            ("proj_SB", "SB", "sum"),
            ("proj_R", "Runs", "sum"),
            ("proj_OPS", "OPS", "rate"),
            ("proj_OBP", "OBP", "rate"),
        ]
    return [
        ("proj_HR", "HR", "sum"),
        ("proj_RBI", "RBI", "sum"),
        ("proj_SB", "SB", "sum"),
        ("proj_R", "Runs", "sum"),
        ("proj_BA", "AVG", "rate"),
        ("proj_OBP", "OBP", "rate"),
    ]


def _pool_median(pool_df: pd.DataFrame, col: str) -> float:
    if pool_df is None or pool_df.empty or col not in pool_df.columns:
        return 0.0
    return float(pd.to_numeric(pool_df[col], errors="coerce").median() or 0.0)


def _strength_score(player_val: float, pool_med: float, kind: str) -> float | None:
    if kind == "lower":
        if player_val <= 0 or pool_med <= 0:
            return None
        return pool_med / player_val
    if kind == "rate":
        baseline = pool_med if pool_med > 0 else 0.001
        return player_val / baseline
    baseline = pool_med if pool_med > 0 else 1.0
    return player_val / baseline


def _refine_strength_label(label: str, col: str, row: Any, pool_df: pd.DataFrame | None) -> str:
    """Map high-AVG, low-power profiles to Contact instead of a second rate stat."""
    if label != "OBP" or col != "proj_OBP":
        return label
    ba = pd.to_numeric(row.get("proj_BA"), errors="coerce")
    hr = pd.to_numeric(row.get("proj_HR"), errors="coerce")
    pool_hr = _pool_median(pool_df if pool_df is not None else pd.DataFrame(), "proj_HR")
    if pd.notna(ba) and pd.notna(hr) and pool_hr > 0 and float(hr) < pool_hr * 0.85:
        pool_ba = _pool_median(pool_df if pool_df is not None else pd.DataFrame(), "proj_BA")
        if pool_ba > 0 and float(ba) >= pool_ba * 1.03:
            return "Contact"
    return label


def player_top_category_strengths(
    row: Any,
    pool_df: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
    max_count: int = 2,
) -> list[str]:
    """Top 1–2 projected category strengths for a player vs pool baseline."""
    config = config or {}
    pool_df = pool_df if pool_df is not None else pd.DataFrame()
    ranked: list[tuple[float, str, str]] = []

    for col, label, kind in _player_strength_specs(row, config):
        player_val = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(player_val):
            continue
        pool_med = _pool_median(pool_df, col)
        score = _strength_score(float(player_val), pool_med, kind)
        if score is None or score <= 0:
            continue
        ranked.append((score, label, col))

    ranked.sort(key=lambda item: item[0], reverse=True)
    labels: list[str] = []
    for _score, label, col in ranked:
        refined = _refine_strength_label(label, col, row, pool_df)
        try:
            from live_draft_ux import describe_strength

            refined = describe_strength(refined)
        except ImportError:
            pass
        if refined in labels:
            continue
        labels.append(refined)
        if len(labels) >= max_count:
            break
    return labels
