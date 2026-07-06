"""Shared position and hitter-category needs for Live Draft and Draft Assistant."""

from __future__ import annotations

from typing import Any

import pandas as pd

_BENCH_CODES = frozenset({"BN", "BENCH"})


def filter_bench_gaps(gaps: list[str] | None) -> list[str]:
    """Drop bench slot codes from open-position gap lists."""
    return [g for g in (gaps or []) if str(g or "").strip().upper() not in _BENCH_CODES]


def display_position_needs_label(gaps: list[str] | None) -> str:
    """Human label for UI banners — 'All Positions' when only bench/utility remains."""
    try:
        from live_draft_roster_slots import format_open_position_needs

        return format_open_position_needs(filter_bench_gaps(gaps))
    except ImportError:
        filtered = filter_bench_gaps(gaps)
        return ", ".join(dict.fromkeys(filtered)) if filtered else "All Positions"


def infer_position_needs(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
    *,
    draft_complete: bool = False,
) -> list[str]:
    """Open required roster slots for one team (excludes bench)."""
    if draft_complete:
        return []
    cfg = dict(config or {})
    if not cfg.get("slots"):
        return []
    try:
        from live_draft_roster_slots import get_remaining_position_needs

        return filter_bench_gaps(get_remaining_position_needs(roster_df, cfg))
    except ImportError:
        return []


def _hitter_category_specs(fantasy_format: str) -> list[tuple[str, str, str]]:
    """Projection column, display label, aggregation kind — hitters only."""
    if fantasy_format == "5x5 Roto":
        return [
            ("proj_HR", "HR", "sum"),
            ("proj_RBI", "RBI", "sum"),
            ("proj_SB", "SB", "sum"),
            ("proj_BA", "AVG", "rate"),
        ]
    return [
        ("proj_HR", "Power", "sum"),
        ("proj_RBI", "Run Production", "sum"),
        ("proj_SB", "Speed", "sum"),
        ("proj_OPS", "Walks/OPS", "rate"),
    ]


def infer_hitter_category_needs(
    roster_df: pd.DataFrame | None,
    pool_df: pd.DataFrame | None,
    *,
    fantasy_format: str = "5x5 Roto",
    draft_complete: bool = False,
    weakness_ratio: float = 0.92,
) -> list[str]:
    """
    Hitter category weaknesses from projected roster totals vs pool baseline.

    Uses team sums for counting stats and team mean for rate stats (AVG/OPS).
    Never includes pitcher categories (ERA, WHIP, K, SV, W, etc.).
    """
    if draft_complete:
        return []
    roster_df = roster_df if roster_df is not None else pd.DataFrame()
    pool_df = pool_df if pool_df is not None else pd.DataFrame()
    if roster_df.empty or pool_df.empty:
        return []

    n_players = max(1, len(roster_df))
    needs: list[str] = []
    for col, label, kind in _hitter_category_specs(fantasy_format):
        if col not in pool_df.columns or col not in roster_df.columns:
            continue
        pool_med = float(pd.to_numeric(pool_df[col], errors="coerce").median() or 0)
        if pool_med <= 0 and kind == "rate":
            pool_med = 0.001
        expected = pool_med if kind == "rate" else pool_med * n_players
        if kind == "rate":
            vals = pd.to_numeric(roster_df[col], errors="coerce")
            team_val = float(vals.mean()) if vals.notna().any() else 0.0
        else:
            team_val = float(pd.to_numeric(roster_df[col], errors="coerce").fillna(0).sum())
        if expected > 0 and team_val < expected * weakness_ratio:
            if label not in needs:
                needs.append(label)
    return needs


def infer_draft_team_needs(
    roster_df: pd.DataFrame | None,
    pool_df: pd.DataFrame | None,
    *,
    config: dict[str, Any] | None = None,
    fantasy_format: str = "5x5 Roto",
    draft_complete: bool = False,
) -> tuple[list[str], list[str]]:
    """Position gaps + hitter category needs for one fantasy team."""
    cfg = dict(config or {})
    positions = infer_position_needs(roster_df, cfg, draft_complete=draft_complete)
    categories = infer_hitter_category_needs(
        roster_df,
        pool_df,
        fantasy_format=fantasy_format,
        draft_complete=draft_complete,
    )
    return positions, categories
