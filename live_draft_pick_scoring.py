"""Pure draft pick scoring — no Streamlit UI imports."""

from __future__ import annotations

import numpy as np
import pandas as pd

def normalize_series(series):
    """Scale a numeric pandas Series to 0-1 safely.

    Used by the fantasy and draft assistant pages so different stats
    can be combined into one score without crashing on missing values,
    all-equal values, or non-numeric data.
    """
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if s.notna().sum() == 0:
        return pd.Series(0.0, index=series.index)
    s = s.fillna(s.median())
    min_val = s.min()
    max_val = s.max()
    if pd.isna(min_val) or pd.isna(max_val) or max_val == min_val:
        return pd.Series(0.0, index=series.index)
    return (s - min_val) / (max_val - min_val)


def safe_numeric_series(df, col, default=0.0):
    """Return a numeric Series for ``col`` with an index-aligned fallback."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype="float64")
DRAFT_POSITION_REPLACEMENT_DEPTHS = {
    "C": 12, "1B": 12, "2B": 12, "3B": 12, "SS": 12, "OF": 36, "DH": 12, "P": 12,
}


def _draft_compute_position_replacement(available, replacement_depths=None):
    """Replacement-level scarcity among remaining players at each position."""
    depths = replacement_depths or DRAFT_POSITION_REPLACEMENT_DEPTHS
    replacement_values = {}
    position_summary_rows = []
    efv_col = "Expected Fantasy Value"
    for pos, pos_group in available.groupby("Primary Position"):
        pos_group = pos_group.copy().sort_values(efv_col, ascending=False)
        depth = depths.get(pos, 12)
        if pos_group.empty:
            continue
        if len(pos_group) >= depth:
            replacement_value = pd.to_numeric(pos_group.iloc[depth - 1][efv_col], errors="coerce")
        else:
            replacement_value = pd.to_numeric(pos_group[efv_col], errors="coerce").min()
        replacement_values[pos] = replacement_value
        top_row = pos_group.iloc[0]
        top_value = pd.to_numeric(top_row.get(efv_col, np.nan), errors="coerce")
        position_summary_rows.append({
            "Position": pos,
            "Available Players": len(pos_group),
            "Replacement Depth": depth,
            "Replacement Value": replacement_value,
            "Top Available": top_row.get("fullName", ""),
            "Top Available Value": top_value,
            "Scarcity Dropoff": top_value - replacement_value if pd.notna(top_value) and pd.notna(replacement_value) else np.nan,
        })
    return replacement_values, position_summary_rows
def _draft_lab_category_need_bonus(available, roster_df):
    if roster_df is None or roster_df.empty:
        return pd.Series(0.0, index=available.index)
    bonus = pd.Series(0.0, index=available.index)
    for col, weight in [("proj_HR", 0.04), ("proj_RBI", 0.035), ("proj_R", 0.035), ("proj_SB", 0.045), ("proj_BA", 0.03), ("proj_OPS", 0.03)]:
        if col not in available.columns or col not in roster_df.columns:
            continue
        roster_val = pd.to_numeric(roster_df[col], errors="coerce").mean()
        pool_val = pd.to_numeric(available[col], errors="coerce").median()
        if pd.notna(roster_val) and pd.notna(pool_val) and roster_val < pool_val:
            bonus += normalize_series(pd.to_numeric(available[col], errors="coerce").fillna(0)) * weight
    return bonus
def _survival_label_from_prob(prob):
    p = float(prob)
    if p >= 0.72:
        return "Likely available at your next pick"
    if p >= 0.50:
        return "May still be there — moderate risk"
    if p >= 0.30:
        return "Coin flip — consider drafting now"
    if p >= 0.15:
        return "Unlikely to survive to your next pick"
    return "Very unlikely — draft now"


def enrich_player_survival_metrics(scored, *, current_pick, next_user_pick, num_teams=12):
    """
    Estimate P(player still available at user's next pick).

    Uses market rank vs pick gap (ADP logistic), snake spacing, and position scarcity pressure.
    """
    out = scored.copy()
    cur = max(1, int(current_pick or 1))
    nxt = int(next_user_pick) if next_user_pick is not None else cur
    gap = max(0, nxt - cur)
    mr = pd.to_numeric(out.get("Market Rank"), errors="coerce").fillna(9999)
    scale = max(10.0, float(num_teams) * 0.92)
    p_at_next = 1.0 / (1.0 + np.exp((mr - nxt) / scale))
    gap_decay = np.power(0.90, np.maximum(0, gap - 1))
    scarcity_pen = (
        normalize_series(out["Position Scarcity Score"])
        if "Position Scarcity Score" in out.columns
        else pd.Series(0.0, index=out.index)
    ) * 0.10
    survival = (p_at_next * gap_decay - scarcity_pen).clip(0.02, 0.99)
    if next_user_pick is None or nxt <= cur:
        survival = pd.Series(1.0, index=out.index)
    out["Survival Probability"] = survival
    out["Survival Label"] = survival.apply(_survival_label_from_prob)
    out["Survival Urgency"] = (1.0 - survival).clip(0, 1)
    if "Decision Score" in out.columns:
        out["Decision Score"] = (
            pd.to_numeric(out["Decision Score"], errors="coerce").fillna(0)
            + normalize_series(out["Survival Urgency"]) * 0.05
        ).clip(lower=0)
    if "Draft Fit Score" in out.columns and "Availability Urgency Component" in out.columns:
        out["Availability Urgency Component"] = (
            pd.to_numeric(out["Availability Urgency Component"], errors="coerce").fillna(0)
            + normalize_series(out["Survival Urgency"]) * 0.04
        )
        out["Draft Fit Score"] = (
            pd.to_numeric(out["Draft Fit Score"], errors="coerce").fillna(0)
            + normalize_series(out["Survival Urgency"]) * 0.04
        ).clip(lower=0)
    return out
def _live_draft_target_counts(config):
    slots = config.get("slots", {})
    return {
        "C": int(slots.get("C", 1)),
        "1B": int(slots.get("1B", 1)),
        "2B": int(slots.get("2B", 1)),
        "3B": int(slots.get("3B", 1)),
        "SS": int(slots.get("SS", 1)),
        "OF": int(slots.get("OF", 3)),
        "DH": int(slots.get("DH", 1)),
        "P": int(slots.get("P", 0)),
    }


def _live_draft_roster_needs(roster_df, target_counts):
    if roster_df is None or roster_df.empty or "Primary Position" not in roster_df.columns:
        return [pos for pos, n in target_counts.items() if n > 0]
    counts = roster_df["Primary Position"].fillna("DH").astype(str).value_counts().to_dict()
    gaps = [pos for pos, target in target_counts.items() if target > 0 and int(counts.get(pos, 0)) < target]
    return gaps


def _live_draft_pick_verdict(row, rule, gaps):
    player = row.get("fullName", "Player")
    pos = row.get("Primary Position", "")
    parts = [f"Drafted via {rule}"]
    if gaps and str(pos) in gaps:
        parts.append(f"fills {pos} need")
    surv = pd.to_numeric(row.get("Survival Probability", np.nan), errors="coerce")
    if pd.notna(surv) and surv < 0.35:
        parts.append(f"~{surv * 100:.0f}% chance to survive to your next pick")
    elif pd.notna(surv) and surv >= 0.72:
        parts.append("likely could have waited")
    dfs = pd.to_numeric(row.get("Draft Fit Score", np.nan), errors="coerce")
    if pd.notna(dfs) and dfs >= 0.72:
        parts.append("strong roster fit")
    efv = pd.to_numeric(row.get("Expected Fantasy Value", np.nan), errors="coerce")
    if pd.notna(efv) and efv >= 0.75:
        parts.append("elite projected value")
    edge = pd.to_numeric(row.get("Fantasy Edge", np.nan), errors="coerce")
    if pd.notna(edge) and edge >= 8:
        parts.append("positive fantasy edge")
    return f"{player}: " + ", ".join(parts[:4]) + "."


def _draft_lab_infer_category_needs(roster_df, available, fantasy_format="5x5 Roto"):
    """Auto-detect category weaknesses from roster vs remaining pool (Draft Assistant logic)."""
    if roster_df is None or roster_df.empty or available is None or available.empty:
        return []
    if fantasy_format == "5x5 Roto":
        triples = [("proj_HR", "HR"), ("proj_RBI", "RBI"), ("proj_SB", "SB"), ("proj_BA", "BA")]
    else:
        triples = [
            ("proj_HR", "Power"),
            ("proj_RBI", "Run Production"),
            ("proj_SB", "Speed"),
            ("proj_OPS", "Walks/OPS"),
        ]
    needs = []
    for col, need_label in triples:
        if col not in roster_df.columns or col not in available.columns:
            continue
        rm = pd.to_numeric(roster_df[col], errors="coerce").mean()
        pm = pd.to_numeric(available[col], errors="coerce").median()
        if pd.notna(rm) and pd.notna(pm) and rm < pm * 0.92:
            needs.append(need_label)
    return needs
def _draft_category_need_bonus_list(available, category_needs, fantasy_format="5x5 Roto"):
    """Explicit category-need bonus from user-selected or auto-detected categories."""
    cat_bonus = pd.Series(0.0, index=available.index)
    if not category_needs:
        return cat_bonus
    if fantasy_format == "5x5 Roto":
        if "R" in category_needs:
            cat_bonus += normalize_series(available["proj_R"]) * 0.05
        if "HR" in category_needs:
            cat_bonus += normalize_series(available["proj_HR"]) * 0.06
        if "RBI" in category_needs:
            cat_bonus += normalize_series(available["proj_RBI"]) * 0.06
        if "SB" in category_needs:
            cat_bonus += normalize_series(available["proj_SB"]) * 0.07
        if "BA" in category_needs:
            cat_bonus += normalize_series(available["proj_BA"]) * 0.05
    else:
        if "Power" in category_needs:
            cat_bonus += normalize_series(available["proj_HR"]) * 0.07
        if "Run Production" in category_needs:
            cat_bonus += normalize_series(available["proj_RBI"] + available["proj_R"]) * 0.06
        if "Speed" in category_needs:
            cat_bonus += normalize_series(available["proj_SB"]) * 0.05
        if "Walks/OPS" in category_needs:
            cat_bonus += normalize_series(available["proj_BB"] + available["proj_OPS"] * 50) * 0.05
        if "Volume" in category_needs:
            cat_bonus += normalize_series(available["AB"]) * 0.04
    return cat_bonus
def apply_draft_pick_scoring(
    available,
    roster_df,
    *,
    fantasy_format="5x5 Roto",
    target_counts=None,
    current_pick=None,
    category_needs=None,
    needed_positions=None,
    use_ml_blend=False,
    ml_blend_weight=0.0,
    replacement_depths=None,
    return_position_summary=False,
    recommendation_mode="decision",
):
    """
    Centralized fantasy draft intelligence engine.

    Powers Live Draft Room, Draft Simulation Test Mode, Fantasy Draft Assistant, and auto-pick.
    Computes Draft Fit Score (roster-construction fit) and Decision Score (blended pick rank).

    All component columns are exposed for the Draft Scoring Breakdown debug expander.
    """
    try:
        from draft_scoring_pool import ensure_draft_scoring_pool_columns

        available = ensure_draft_scoring_pool_columns(available)
    except ImportError:
        pass
    scored = available.copy()
    roster_df = roster_df if roster_df is not None else pd.DataFrame()
    target_counts = target_counts or {}
    gaps = _live_draft_roster_needs(roster_df, target_counts)
    if needed_positions is None:
        needed_positions = gaps if gaps else []

    # --- Positional / roster slot fit (display + Decision roster-need term) ---
    slot_fit = scored["Primary Position"].isin(gaps).astype(float)
    slot_fit = slot_fit.mask(scored["Primary Position"].astype(str).eq("C"), slot_fit * 0.85)
    if category_needs:
        cat_need_raw = _draft_category_need_bonus_list(scored, category_needs, fantasy_format)
    else:
        cat_need_raw = _draft_lab_category_need_bonus(scored, roster_df)
    category_need_norm = normalize_series(cat_need_raw)
    scored["Positional Fit"] = (slot_fit * 0.70 + category_need_norm * 0.30).clip(0, 1)
    scored["Roster Need Score"] = scored["Positional Fit"]
    scored["Position Need Bonus"] = scored["Primary Position"].apply(
        lambda p: 0.08 if str(p) in needed_positions else 0.0
    )
    scored["Category Need Bonus"] = cat_need_raw

    # --- Replacement-level position scarcity (pick-time, from remaining pool) ---
    replacement_values, position_summary_rows = _draft_compute_position_replacement(
        scored, replacement_depths=replacement_depths
    )
    scored["Position Replacement Value"] = scored["Primary Position"].map(replacement_values).fillna(
        pd.to_numeric(scored["Expected Fantasy Value"], errors="coerce").median()
    )
    scored["Position Scarcity Score"] = (
        pd.to_numeric(scored["Expected Fantasy Value"], errors="coerce") -
        pd.to_numeric(scored["Position Replacement Value"], errors="coerce")
    ).clip(lower=0)
    scored["Position Scarcity Bonus"] = normalize_series(scored["Position Scarcity Score"]) * 0.12
    scored.loc[scored["Primary Position"].isin(needed_positions), "Position Scarcity Bonus"] *= 1.25

    # --- Risk & projection confidence ---
    scored["Risk Penalty"] = normalize_series(safe_numeric_series(scored, "Expert Std Dev", 0))
    conf = (
        normalize_series(safe_numeric_series(scored, "Projection Confidence Score", 0.5))
        if "Projection Confidence Score" in scored.columns
        else pd.Series(0.5, index=scored.index)
    )
    scored["Projection Confidence"] = conf

    # --- Availability / urgency (ADP vs current pick) ---
    if current_pick is not None:
        mr = safe_numeric_series(scored, "Market Rank", float(current_pick))
        scored["Availability Probability"] = 1 / (1 + np.exp(-(mr - float(current_pick)) / 35))
    else:
        scored["Availability Probability"] = pd.Series(0.50, index=scored.index)

    # --- Draft Fit Score components (Fantasy Draft Assistant formula, unified) ---
    ml_w = float(ml_blend_weight) if use_ml_blend else 0.0
    value_weight = max(0.38 - (ml_w * 0.25 if use_ml_blend else 0.0), 0.28)
    scored["Player Value Component"] = normalize_series(scored["Expected Fantasy Value"]) * value_weight
    scored["ML Projection Component"] = (
        normalize_series(scored["ML Adjustment"].fillna(0).clip(lower=0)) * ml_w
        if use_ml_blend and "ML Adjustment" in scored.columns
        else pd.Series(0.0, index=scored.index)
    )
    if "Projection Confidence Score" in scored.columns:
        scored["Player Value Component"] *= (0.94 + conf * 0.06)
        scored["Confidence Component"] = conf * 0.02
    else:
        scored["Confidence Component"] = pd.Series(0.0, index=scored.index)

    scored["Market Edge Component"] = normalize_series(safe_numeric_series(scored, "Fantasy Edge", 0)) * 0.22
    scored["Roster Need Component"] = normalize_series(scored["Position Need Bonus"].fillna(0)) * 0.14
    scored["Scarcity Component"] = normalize_series(scored["Position Scarcity Bonus"].fillna(0))
    scored["Category Fit Component"] = normalize_series(scored["Category Need Bonus"].fillna(0)) * 0.08
    scored["Availability Urgency Component"] = (
        1 - pd.to_numeric(scored["Availability Probability"], errors="coerce").fillna(0.50)
    ) * 0.06
    scored["Sleeper Fit Component"] = (
        normalize_series(scored["Sleeper Score"]) * 0.03
        if "Sleeper Score" in scored.columns
        else pd.Series(0.0, index=scored.index)
    )
    scored["Risk Component"] = scored["Risk Penalty"] * 0.08 * (1.12 - conf * 0.12)

    scored["Draft Fit Score"] = (
        scored["Player Value Component"]
        + scored["ML Projection Component"]
        + scored["Market Edge Component"]
        + scored["Roster Need Component"]
        + scored["Scarcity Component"]
        + scored["Category Fit Component"]
        + scored["Availability Urgency Component"]
        + scored["Sleeper Fit Component"]
        + scored["Confidence Component"]
        - scored["Risk Component"]
    ).clip(lower=0)

    # --- Decision Score (auto-pick / balanced recommendation) ---
    rank_component = (
        scored["App Ranking Score"]
        if "App Ranking Score" in scored.columns
        else normalize_series(-pd.to_numeric(scored.get("Model Rank"), errors="coerce").fillna(9999))
    )
    pool_scarcity = (
        normalize_series(scored["Scarcity Score"])
        if "Scarcity Score" in scored.columns
        else normalize_series(scored["Position Scarcity Score"])
    )
    trend_comp = (
        normalize_series(scored["Trend Signal"])
        if "Trend Signal" in scored.columns
        else pd.Series(0.0, index=scored.index)
    )
    sleeper_dec = (
        normalize_series(scored["Sleeper Score"])
        if "Sleeper Score" in scored.columns
        else pd.Series(0.0, index=scored.index)
    )
    market_dec = (
        normalize_series(scored["Market vs Model Score"])
        if "Market vs Model Score" in scored.columns
        else normalize_series(safe_numeric_series(scored, "Fantasy Edge", 0))
    )
    value_dec = normalize_series(scored["Expected Fantasy Value"])

    scored["Decision Value Component"] = value_dec * 0.55
    scored["Decision Rank Component"] = normalize_series(rank_component) * 0.20
    scored["Decision Roster Component"] = normalize_series(scored["Roster Need Score"]) * 0.10
    scored["Decision Scarcity Component"] = pool_scarcity * 0.05
    scored["Decision Trend Component"] = trend_comp * 0.05
    scored["Decision Sleeper Component"] = sleeper_dec * 0.03
    scored["Decision Market Component"] = market_dec * 0.02

    scored["Decision Score"] = (
        scored["Decision Value Component"]
        + scored["Decision Rank Component"]
        + scored["Decision Roster Component"]
        + scored["Decision Scarcity Component"]
        + scored["Decision Trend Component"]
        + scored["Decision Sleeper Component"]
        + scored["Decision Market Component"]
    ).clip(lower=0)
    scored["Draft Fit Rank"] = scored["Draft Fit Score"].rank(ascending=False, method="min")
    if recommendation_mode == "draft_fit":
        scored["Recommendation Score"] = scored["Draft Fit Score"]
        scored["Recommendation Rank"] = scored["Draft Fit Rank"]
    else:
        scored["Recommendation Score"] = scored["Decision Score"]
        scored["Recommendation Rank"] = scored["Decision Score"].rank(ascending=False, method="min")

    if return_position_summary:
        return scored, gaps, position_summary_rows
    return scored, gaps
def _sort_draft_candidates(df, columns, *, ascending=None):
    """Sort by score columns; ascending list length must match column count (pandas 2+)."""
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return df
    if ascending is None:
        asc = [False] * len(cols)
    elif isinstance(ascending, bool):
        asc = [ascending] * len(cols)
    else:
        asc = list(ascending)
        if len(asc) < len(cols):
            asc = asc + [asc[-1] if asc else False] * (len(cols) - len(asc))
        asc = asc[: len(cols)]
    return df.sort_values(cols, ascending=asc, na_position="last")


def score_available_for_rule(available, roster_df, rule, target_counts, config=None):
    config = config or {}
    fantasy_format = config.get("fantasy_format", "5x5 Roto")
    current_pick = int(config.get("current_pick", 1) or 1)
    category_needs = config.get("category_needs")
    if category_needs is None and not roster_df.empty:
        category_needs = _draft_lab_infer_category_needs(roster_df, available, fantasy_format)
    scored, gaps = apply_draft_pick_scoring(
        available,
        roster_df,
        fantasy_format=fantasy_format,
        target_counts=target_counts,
        current_pick=current_pick,
        category_needs=category_needs,
        needed_positions=config.get("needed_positions"),
        use_ml_blend=bool(config.get("use_ml_blend", False)),
        ml_blend_weight=float(config.get("ml_blend_weight", 0) or 0),
    )
    scored = enrich_player_survival_metrics(
        scored,
        current_pick=current_pick,
        next_user_pick=config.get("next_user_pick"),
        num_teams=int(config.get("num_teams", 12) or 12),
    )
    rule = str(rule).strip().lower()
    if rule == "best market rank":
        scored["_pick_score"] = -pd.to_numeric(scored.get("Market Rank"), errors="coerce").fillna(9999)
        scored = _sort_draft_candidates(
            scored, ["_pick_score", "Decision Score", "Expected Fantasy Value"], ascending=False
        )
    elif rule == "best model rank":
        scored["_pick_score"] = -pd.to_numeric(scored.get("Model Rank"), errors="coerce").fillna(9999)
        scored = _sort_draft_candidates(
            scored, ["_pick_score", "Decision Score", "Expected Fantasy Value"], ascending=False
        )
    elif rule == "best projected fantasy value":
        scored = _sort_draft_candidates(
            scored, ["Expected Fantasy Value", "Model Rank"], ascending=[False, True]
        )
    elif rule == "best roster need":
        scored = _sort_draft_candidates(
            scored, ["Positional Fit", "Draft Fit Score", "Expected Fantasy Value"], ascending=False
        )
    else:
        scored = _sort_draft_candidates(
            scored, ["Decision Score", "Draft Fit Score", "Expected Fantasy Value"], ascending=False
        )
    return scored, gaps


live_draft_target_counts = _live_draft_target_counts
live_draft_pick_verdict = _live_draft_pick_verdict
_live_draft_score_available = score_available_for_rule
