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
                # Stronger trust in player line vs league median than the first Aggressive pass.
                "regression_strength_multiplier": 0.72,
                "youth_bump": 0.025,
                "reg_strength_min": 0.04,
                "reg_strength_max": 0.32,
                "trend_clip_hr": (-7.0, 7.0),
                "trend_clip_sb": (-7.0, 7.0),
                "trend_clip_ops": (-0.095, 0.095),
                "trend_clip_ba": (-0.045, 0.045),
                "anchor_player_weight": 0.945,
                # More weight on trend channels; slightly less on “young bucket” alone.
                "breakout_weights": (0.22, 0.27, 0.18, 0.25, 0.08),
                # Blend stays near the player anchor so ML adj stays interpretable; breakout gets more lift than Balanced.
                "context_weights": (0.625, 0.082, 0.218, 0.075),
                # Symmetric fallbacks (used if asymmetric keys absent).
                "raw_adj_clip": 0.12,
                "ml_adj_clip": 0.075,
                # Wider raw gap, asymmetric ML clip: more room for upside than downside.
                "raw_adj_clip_neg": -0.11,
                "raw_adj_clip_pos": 0.15,
                "ml_adj_clip_neg": -0.048,
                "ml_adj_clip_pos": 0.110,
                "recency_weight_latest": 0.18,
                # Top of the base-category distribution: pull even less toward group median.
                "anchor_elite_relax_quantile": 0.90,
                "anchor_elite_boost": 0.035,
                # Stretch (contextual − anchor) before clipping (1.0 = legacy behavior).
                "ml_residual_scale": 1.0,
                # Down-weight the risk subtraction in the contextual blend (still capped downstream).
                "context_risk_scale": 0.78,
                # ML residual uses weighted blend without a second pool-wide min–max (see ``build_realistic_draft_ml_adjustments``).
                "contextual_blend_pre_normalize": True,
            }
        )
    # Balanced or unknown label → baseline factors unchanged

    return dict(base)
