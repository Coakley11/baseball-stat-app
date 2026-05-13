"""Tunable projection behavior for draft pages (regression, anchoring, trends, ML clip).

Balanced mode reproduces the original hard-coded weights in ``build_realistic_draft_ml_adjustments``.
Other modes rescale those parameters—no global inflation factor.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

PROJECTION_STYLE_OPTIONS: Tuple[str, ...] = (
    "Conservative",
    "Balanced",
    "Aggressive / Upside",
)

_DEFAULT_MODE = "Balanced"


def _balanced_factors() -> Dict[str, Any]:
    """Baseline factors matching pre-style-control draft projection behavior."""
    return {
        "regression_strength_multiplier": 1.0,
        "youth_bump": 0.05,
        "reg_strength_min": 0.10,
        "reg_strength_max": 0.42,
        "trend_clip_hr": (-5.0, 5.0),
        "trend_clip_sb": (-5.0, 5.0),
        "trend_clip_ops": (-0.060, 0.060),
        "trend_clip_ba": (-0.030, 0.030),
        "anchor_player_weight": 0.84,
        # young_breakout, power, speed, plate, playing_time — sum = 1.0
        "breakout_weights": (0.35, 0.20, 0.15, 0.20, 0.10),
        # similar_player_adjusted, category_balance, breakout_probability, risk_score multiplier
        "context_weights": (0.70, 0.15, 0.10, 0.05),
        "raw_adj_clip": 0.10,
        "ml_adj_clip": 0.06,
        "recency_weight_latest": 0.0,
    }


def get_draft_projection_factors(mode: str) -> Dict[str, Any]:
    """Return a copy of factor dict for ``mode`` (unknown → Balanced)."""
    m = (mode or _DEFAULT_MODE).strip()
    base = _balanced_factors()

    if m == "Conservative":
        base.update(
            {
                "regression_strength_multiplier": 1.14,
                "youth_bump": 0.06,
                "reg_strength_min": 0.12,
                "reg_strength_max": 0.50,
                "trend_clip_hr": (-4.0, 4.0),
                "trend_clip_sb": (-4.0, 4.0),
                "trend_clip_ops": (-0.048, 0.048),
                "trend_clip_ba": (-0.024, 0.024),
                "anchor_player_weight": 0.78,
                "breakout_weights": (0.38, 0.16, 0.16, 0.18, 0.12),
                "context_weights": (0.76, 0.17, 0.05, 0.03),
                "raw_adj_clip": 0.08,
                "ml_adj_clip": 0.045,
                "recency_weight_latest": 0.0,
            }
        )
    elif m == "Aggressive / Upside":
        base.update(
            {
                "regression_strength_multiplier": 0.80,
                "youth_bump": 0.03,
                "reg_strength_min": 0.05,
                "reg_strength_max": 0.38,
                "trend_clip_hr": (-6.0, 6.0),
                "trend_clip_sb": (-6.0, 6.0),
                "trend_clip_ops": (-0.080, 0.080),
                "trend_clip_ba": (-0.038, 0.038),
                "anchor_player_weight": 0.91,
                "breakout_weights": (0.28, 0.24, 0.17, 0.23, 0.08),
                "context_weights": (0.62, 0.12, 0.18, 0.08),
                "raw_adj_clip": 0.12,
                "ml_adj_clip": 0.08,
                "recency_weight_latest": 0.12,
            }
        )
    # Balanced or unknown label → baseline factors unchanged

    return dict(base)
