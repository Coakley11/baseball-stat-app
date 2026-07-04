"""Draft-lab stabilization anchors + light ML output calibration (shared with fantasy pages)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _num(x, col_or_default=None, default=np.nan):
    """Numeric series from a column or from an existing series."""
    if isinstance(x, pd.DataFrame):
        col = col_or_default
        if col not in x.columns:
            return pd.Series(default, index=x.index)
        return pd.to_numeric(x[col], errors="coerce").fillna(default)
    fill = col_or_default if col_or_default is not None else default
    return pd.to_numeric(x, errors="coerce").fillna(fill)


def _norm(s):
    x = pd.to_numeric(s, errors="coerce").fillna(0)
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        return pd.Series(0.5, index=x.index)
    return (x - lo) / (hi - lo)


def build_projection_source(recent: pd.DataFrame) -> pd.DataFrame:
    projection_source = recent.copy()
    for c in ["G", "AB", "H", "HR", "RBI", "R", "SB", "BB", "HBP", "SF", "BA", "OPS"]:
        if c not in projection_source.columns:
            projection_source[c] = 0
        projection_source[c] = pd.to_numeric(projection_source[c], errors="coerce").fillna(0)
    projection_source["PA_est"] = (
        projection_source["AB"] + projection_source["BB"] + projection_source["HBP"] + projection_source["SF"]
    )
    safe_pa = projection_source["PA_est"].replace(0, np.nan)
    for stat in ["HR", "RBI", "R", "SB"]:
        projection_source[f"{stat}_per_PA"] = (
            (projection_source[stat] / safe_pa).replace([np.inf, -np.inf], np.nan).fillna(0)
        )
    projection_source["PA_per_G"] = (
        (projection_source["PA_est"] / projection_source["G"].replace(0, np.nan))
        .replace([np.inf, -np.inf], np.nan)
    )
    projection_source["AB_per_PA"] = (
        (projection_source["AB"] / safe_pa).replace([np.inf, -np.inf], np.nan)
    )
    return projection_source


def merge_stabilization_support(pool: pd.DataFrame, projection_source: pd.DataFrame) -> pd.DataFrame:
    years_played = projection_source.groupby("playerID")["yearID"].nunique()
    recent_avg = projection_source.groupby("playerID")[
        ["G", "AB", "PA_est", "H", "2B", "3B", "BB", "HR", "RBI", "R", "SB", "BA", "OPS", "PA_per_G", "AB_per_PA"]
    ].mean().add_prefix("avg_")
    recent_max = projection_source.groupby("playerID")[
        ["G", "AB", "PA_est", "H", "2B", "3B", "BB", "HR", "RBI", "R", "SB"]
    ].max().add_prefix("max_")
    recent_std = projection_source.groupby("playerID")[
        ["G", "AB", "PA_est", "HR_per_PA", "RBI_per_PA", "R_per_PA", "SB_per_PA", "BA", "OPS"]
    ].std().add_prefix("std_")
    latest_support = (
        projection_source.sort_values(["playerID", "yearID"])
        .groupby("playerID")
        .tail(1)[
            ["playerID", "G", "AB", "PA_est", "HR", "RBI", "R", "SB", "BA", "OPS", "PA_per_G", "AB_per_PA"]
        ]
        .rename(
            columns={
                c: f"latest_support_{c}"
                for c in ["G", "AB", "PA_est", "HR", "RBI", "R", "SB", "BA", "OPS", "PA_per_G", "AB_per_PA"]
            }
        )
    )
    support = pd.concat([years_played.rename("years_played"), recent_avg, recent_max, recent_std], axis=1).reset_index()
    return pool.merge(latest_support, on="playerID", how="left").merge(support, on="playerID", how="left")


def apply_stabilized_counting_projections(pool: pd.DataFrame, projection_source: pd.DataFrame) -> pd.DataFrame:
    """Same stabilized counting/rate logic used in Draft Lab / Live Draft Room."""
    out = pool.copy()
    total_pa = _num(out, "PA_est", 0)
    total_ab = _num(out, "AB", 0)
    years = _num(out, "years_played", 0)
    latest_g = _num(out, "latest_support_G", np.nan).fillna(_num(out, "G", 0))
    avg_g = _num(out, "avg_G", np.nan).fillna(latest_g)
    max_g = _num(out, "max_G", np.nan).fillna(avg_g)
    g_trend = _num(out, "G_trend", 0).clip(-18, 18)
    trend_g = (latest_g + g_trend).clip(lower=0)
    durability = (avg_g / 145).clip(0.35, 1.05)
    projected_g = (latest_g * 0.42 + avg_g * 0.38 + trend_g * 0.20)
    projected_g = projected_g * (0.92 + durability * 0.08)
    projected_g = np.minimum(projected_g, np.maximum(max_g + 8, avg_g * 1.18))
    projected_g = pd.Series(projected_g, index=out.index).clip(lower=20, upper=150)
    if "Primary Position" in out.columns:
        catcher_mask = out["Primary Position"].astype(str).eq("C")
        projected_g = projected_g.mask(catcher_mask, projected_g.clip(upper=132))

    latest_pa_pg = _num(out, "latest_support_PA_per_G", np.nan)
    avg_pa_pg = _num(out, "avg_PA_per_G", np.nan)
    pa_pg = (latest_pa_pg.fillna(avg_pa_pg) * 0.55 + avg_pa_pg.fillna(latest_pa_pg) * 0.45).fillna(3.7).clip(2.2, 4.75)
    latest_ab_per_pa = _num(out, "latest_support_AB_per_PA", np.nan)
    avg_ab_per_pa = _num(out, "avg_AB_per_PA", np.nan)
    ab_per_pa = (
        latest_ab_per_pa.fillna(avg_ab_per_pa) * 0.55 + avg_ab_per_pa.fillna(latest_ab_per_pa) * 0.45
    ).fillna(0.89).clip(0.74, 0.96)
    projected_pa = (projected_g * pa_pg).clip(lower=60, upper=720)
    projected_ab = (projected_pa * ab_per_pa).clip(lower=40, upper=650)
    out["proj_G"] = projected_g.round(1)
    out["proj_PA"] = projected_pa.round(1)
    out["proj_AB"] = projected_ab.round(1)

    limited_data = (total_ab < 450) | (years < 2)
    very_limited_data = (total_ab < 250) | (years < 2)
    volatility = (
        _norm(_num(out, "std_PA_est", 0)) * 0.45
        + _norm(_num(out, "std_OPS", 0)) * 0.35
        + _norm(_num(out, "std_BA", 0)) * 0.20
    )
    consistency = (1 - volatility).clip(0, 1)
    sample_score = (total_ab / 1100).clip(0, 1)
    games_score = (avg_g / 125).clip(0, 1)
    avg_hr = _num(out, "avg_HR", 0)
    max_hr = _num(out, "max_HR", 0)
    avg_ops = _num(out, "avg_OPS", 0)
    power_history = _norm(avg_hr * 0.55 + max_hr * 0.45)
    production_history = _norm(avg_ops)
    multi_season_strength = ((years >= 3).astype(float) * 0.22 + (years >= 2).astype(float) * 0.10)
    playing_time_strength = (projected_g / 145).clip(0, 1)
    elite_star_score = (
        power_history * 0.30
        + production_history * 0.24
        + consistency * 0.22
        + multi_season_strength
        + playing_time_strength * 0.14
    ).clip(0, 1)
    stable_veteran = (years >= 3) & (consistency >= 0.58) & (volatility < 0.48)
    injury_risk = (projected_g < avg_g * 0.82) | (durability < 0.55)
    age_vals = _num(out, "Age", np.nan)
    age_regression = (age_vals >= 33) & (volatility >= 0.45)
    role_uncertainty = (years < 2) & (playing_time_strength < 0.55)
    limited_playing_time = (playing_time_strength < 0.50) & ~very_limited_data
    star_protected = (
        (elite_star_score >= 0.82)
        & (consistency >= 0.65)
        & (playing_time_strength >= 0.80)
        & (years >= 3)
        & ((power_history >= 0.62) | (production_history >= 0.62))
    )
    confidence_score = (
        sample_score * 0.32
        + games_score * 0.22
        + consistency * 0.32
        + (years / 4).clip(0, 1) * 0.10
        + elite_star_score * 0.04
    ).clip(0, 1)
    confidence_score = (confidence_score * (1 - volatility * 0.22)).clip(0, 1)
    confidence_score = confidence_score - very_limited_data.astype(float) * 0.12
    confidence_score = confidence_score - (volatility >= 0.70).astype(float) * 0.10
    confidence_score = pd.Series(confidence_score, index=out.index).clip(0, 1)

    out["Elite Star Score"] = elite_star_score.round(4)
    out["Projection Confidence Score"] = confidence_score
    out["Projection Confidence"] = np.select(
        [confidence_score >= 0.78, confidence_score >= 0.52],
        ["High Confidence", "Medium Confidence"],
        default="Risky Projection",
    )
    out["Projection Warning"] = np.select(
        [
            injury_risk,
            very_limited_data,
            limited_playing_time,
            volatility >= 0.70,
            age_regression,
            role_uncertainty,
            limited_data & ~star_protected,
        ],
        [
            "Injury Risk",
            "Small Sample Size",
            "Limited Playing Time",
            "High Volatility",
            "Age Regression Risk",
            "Role Uncertainty",
            "Small Sample Size",
        ],
        default="",
    )
    out["Volatility Score"] = volatility.round(4)
    out["Star Protected"] = star_protected.astype(bool)
    out["Very Limited Data"] = very_limited_data.astype(bool)

    league_rates = {}
    for stat in ["HR", "RBI", "R", "SB"]:
        denom = projection_source["PA_est"].sum()
        league_rates[stat] = float(projection_source[stat].sum() / denom) if denom else 0.0
    league_ba = (
        float(projection_source["H"].sum() / projection_source["AB"].sum())
        if projection_source["AB"].sum()
        else 0.250
    )
    league_ops = (
        float(projection_source["OPS"].replace(0, np.nan).median())
        if projection_source["OPS"].replace(0, np.nan).notna().any()
        else 0.720
    )

    cap_rules = {
        "HR": ("proj_HR", 62, 8, 1.28, 2.30, True),
        "RBI": ("proj_RBI", 135, 18, 1.28, 1.95, True),
        "R": ("proj_R", 135, 18, 1.28, 1.95, True),
        "SB": ("proj_SB", 62, 10, 1.20, 2.35, False),
    }
    base_rate_regression = (360 / (total_pa + 360)).clip(0.16, 0.62)
    rate_regression = (
        base_rate_regression
        + very_limited_data.astype(float) * 0.10
        + volatility * 0.06
        + injury_risk.astype(float) * 0.05
        - elite_star_score * 0.20
        - stable_veteran.astype(float) * 0.06
        - star_protected.astype(float) * 0.08
    ).clip(0.08, 0.74)
    star_weight = elite_star_score.clip(0, 1)
    for stat, (proj_col, hard_cap, support_pad, avg_cap_mult, league_cap_mult, star_soft_cap) in cap_rules.items():
        total_rate = (_num(out, stat, 0) / total_pa.replace(0, np.nan)).fillna(0)
        latest_rate = (
            _num(out, f"latest_support_{stat}", 0)
            / _num(out, "latest_support_PA_est", np.nan).replace(0, np.nan)
        ).fillna(total_rate)
        rate_trend = _num(out, f"{stat}_per_PA_trend", 0)
        trend_rate = (latest_rate + rate_trend).clip(lower=0)
        blended_rate = (
            total_rate * (0.50 - star_weight * 0.10)
            + latest_rate * (0.32 + star_weight * 0.12)
            + trend_rate * (0.18 + star_weight * 0.05)
        )
        stabilized_rate = blended_rate * (1 - rate_regression) + league_rates[stat] * rate_regression
        avg_stat = _num(out, f"avg_{stat}", 0)
        max_stat = _num(out, f"max_{stat}", np.nan).fillna(avg_stat)
        star_cap_lift = np.where(star_soft_cap, star_weight * 0.20, star_weight * 0.06)
        rate_cap = np.maximum(
            total_rate * (avg_cap_mult + star_cap_lift),
            league_rates[stat] * (league_cap_mult + star_cap_lift),
        )
        rate_cap = np.where(very_limited_data, np.maximum(total_rate * 1.08, league_rates[stat] * 1.50), rate_cap)
        if star_soft_cap:
            elite_slugger = star_protected & (
                (avg_stat >= np.where(stat == "HR", 30, 85))
                | (max_stat >= np.where(stat == "HR", 38, 105))
            )
            elite_rate_floor = np.maximum(total_rate, latest_rate) * (0.92 + star_weight * 0.18)
            stabilized_rate = np.where(elite_slugger, np.maximum(stabilized_rate, elite_rate_floor), stabilized_rate)
        projected = np.minimum(stabilized_rate, rate_cap) * projected_pa
        hard_cap_eff = hard_cap + np.where(star_soft_cap, star_weight * 10, star_weight * 4)
        support_pad_eff = support_pad + np.where(star_soft_cap, star_weight * 6, star_weight * 2)
        support_mult = np.where(very_limited_data, 1.10, 1.25) + np.where(star_soft_cap, star_weight * 0.22, star_weight * 0.08)
        support_cap = np.maximum(max_stat + support_pad_eff, avg_stat * support_mult)
        projected = np.minimum(projected, np.minimum(hard_cap_eff, support_cap))
        if star_soft_cap:
            talent_floor = (avg_stat * 0.52 + max_stat * 0.48) * (
                projected_pa / total_pa.replace(0, np.nan)
            ).replace([np.inf, -np.inf], np.nan).fillna(1)
            star_floor = talent_floor * (0.90 + star_weight * 0.10)
            projected = np.maximum(projected, star_floor)
        if star_protected.any():
            protected_boost = 1 + star_weight * np.where(star_protected, 0.035, 0.0)
            projected = projected * protected_boost
        out[proj_col] = pd.Series(projected, index=out.index).clip(lower=0).round(1)

    ba_regression = (400 / (total_ab + 400)).clip(0.18, 0.62)
    ops_regression = (430 / (total_pa + 430)).clip(0.18, 0.62)
    ba_regression = (ba_regression - elite_star_score * 0.08 - stable_veteran.astype(float) * 0.03).clip(0.14, 0.62)
    ops_regression = (ops_regression - elite_star_score * 0.08 - stable_veteran.astype(float) * 0.03).clip(0.14, 0.62)
    latest_ba = _num(out, "latest_support_BA", np.nan).fillna(_num(out, "latest_BA", np.nan))
    avg_ba = _num(out, "avg_BA", np.nan).fillna(_num(out, "BA", np.nan))
    ba_trend = _num(out, "BA_trend", 0).clip(-0.025, 0.025)
    blended_ba = (
        avg_ba.fillna(league_ba) * 0.55
        + latest_ba.fillna(avg_ba).fillna(league_ba) * 0.35
        + (latest_ba.fillna(avg_ba).fillna(league_ba) + ba_trend) * 0.10
    )
    out["proj_BA"] = (blended_ba * (1 - ba_regression) + league_ba * ba_regression).clip(0.185, 0.340)
    latest_ops = _num(out, "latest_support_OPS", np.nan).fillna(_num(out, "latest_OPS", np.nan))
    avg_ops = _num(out, "avg_OPS", np.nan).fillna(_num(out, "OPS", np.nan))
    ops_trend = _num(out, "OPS_trend", 0).clip(-0.060, 0.060)
    blended_ops = (
        avg_ops.fillna(league_ops) * 0.55
        + latest_ops.fillna(avg_ops).fillna(league_ops) * 0.35
        + (latest_ops.fillna(avg_ops).fillna(league_ops) + ops_trend) * 0.10
    )
    out["proj_OPS"] = (blended_ops * (1 - ops_regression) + league_ops * ops_regression).clip(0.560, 1.050)
    return out


def calibration_blend_weight(
    confidence_score,
    elite_star_score,
    volatility,
    star_protected,
    very_limited,
    *,
    counting=True,
):
    """Light final blend toward draft-lab anchors (ML model already regressed)."""
    conf = pd.to_numeric(confidence_score, errors="coerce").fillna(0.45)
    elite = pd.to_numeric(elite_star_score, errors="coerce").fillna(0)
    vol = pd.to_numeric(volatility, errors="coerce").fillna(0)
    w = 0.22 - conf * 0.10 + vol * 0.12 + very_limited.astype(float) * 0.10 - elite * 0.10
    w = w - star_protected.astype(float) * 0.06
    if counting:
        return w.clip(0.10, 0.38)
    return w.clip(0.06, 0.26)


def apply_ml_final_output_calibration(pred_df: pd.DataFrame, anchors: pd.DataFrame) -> pd.DataFrame:
    """Light sanity-check layer after ML RF + aging + similarity adjustments."""
    if pred_df.empty or anchors.empty or "playerID" not in pred_df.columns:
        return pred_df

    out = pred_df.merge(
        anchors,
        on="playerID",
        how="left",
        suffixes=("", "_stab"),
    )
    conf = _num(out, "Projection Confidence Score", 0.45)
    elite = _num(out, "Elite Star Score", 0)
    vol = _num(out, "Volatility Score", 0)
    star_prot = out.get("Star Protected", pd.Series(False, index=out.index)).fillna(False)
    very_lim = out.get("Very Limited Data", pd.Series(False, index=out.index)).fillna(False)

    count_map = {
        "Predicted HR": ("proj_HR", {"min_elite": 0.75, "min_conf": 0.74, "floor_pct": 0.90, "undershoot_w": 0.68, "require_star": True}),
        "Predicted RBI": ("proj_RBI", {"min_elite": 0.75, "min_conf": 0.72, "floor_pct": 0.86, "undershoot_w": 0.52, "require_star": True}),
        "Predicted R": ("proj_R", {"min_elite": 0.75, "min_conf": 0.72, "floor_pct": 0.86, "undershoot_w": 0.52, "require_star": True}),
        "Predicted SB": ("proj_SB", {"min_elite": 0.82, "min_conf": 0.76, "floor_pct": 0.82, "undershoot_w": 0.30, "require_star": False}),
    }
    for ml_col, (stab_col, guard_cfg) in count_map.items():
        if ml_col not in out.columns or stab_col not in out.columns:
            continue
        ml_val = _num(out[ml_col], 0)
        stab_val = _num(out[stab_col], ml_val)
        w = calibration_blend_weight(conf, elite, vol, star_prot, very_lim, counting=True)
        star_req = star_prot if guard_cfg.get("require_star", False) else pd.Series(True, index=out.index)
        elite_guard = (
            (elite >= guard_cfg["min_elite"])
            & (conf >= guard_cfg["min_conf"])
            & (~very_lim)
            & star_req.fillna(False)
        )
        stab_safe = stab_val.replace(0, np.nan)
        undershoot = ((stab_val - ml_val) / stab_safe).replace([np.inf, -np.inf], np.nan).fillna(0).clip(0, 0.55)
        w = (w + elite_guard.astype(float) * undershoot * guard_cfg["undershoot_w"]).clip(0.10, 0.66)
        blended = (ml_val * (1 - w) + stab_val * w).clip(lower=0)
        elite_floor = stab_val * guard_cfg["floor_pct"]
        out[ml_col] = np.where(elite_guard, np.maximum(blended, elite_floor), blended)

    rate_map = {
        "Predicted BA": ("proj_BA", {"min_elite": 0.80, "min_conf": 0.76, "floor_pct": 0.96, "undershoot_w": 0.18}),
        "Predicted OPS": ("proj_OPS", {"min_elite": 0.80, "min_conf": 0.76, "floor_pct": 0.96, "undershoot_w": 0.22}),
    }
    for ml_col, (stab_col, guard_cfg) in rate_map.items():
        if ml_col not in out.columns or stab_col not in out.columns:
            continue
        ml_val = _num(out[ml_col], np.nan)
        stab_val = _num(out[stab_col], ml_val)
        w = calibration_blend_weight(conf, elite, vol, star_prot, very_lim, counting=False)
        elite_guard = (elite >= guard_cfg["min_elite"]) & (conf >= guard_cfg["min_conf"]) & (~very_lim) & star_prot.fillna(False)
        stab_safe = stab_val.replace(0, np.nan)
        undershoot = ((stab_val - ml_val) / stab_safe).replace([np.inf, -np.inf], np.nan).fillna(0).clip(0, 0.35)
        w = (w + elite_guard.astype(float) * undershoot * guard_cfg["undershoot_w"]).clip(0.06, 0.28)
        blended = ml_val * (1 - w) + stab_val * w
        elite_floor = stab_val * guard_cfg["floor_pct"]
        out[ml_col] = np.where(elite_guard, np.maximum(blended, elite_floor), blended)

    # Secondary counting stats: soft caps from recent averages (no second regression).
    for ml_col, stat in [("Predicted H", "H"), ("Predicted 2B", "2B"), ("Predicted 3B", "3B"), ("Predicted BB", "BB")]:
        if ml_col not in out.columns:
            continue
        ml_val = _num(out[ml_col], 0)
        avg_col = f"avg_{stat}"
        max_col = f"max_{stat}"
        if avg_col in out.columns:
            avg_s = _num(out[avg_col], ml_val)
            max_s = _num(out[max_col], avg_s) if max_col in out.columns else avg_s * 1.25
            cap = np.maximum(max_s * 1.20, avg_s * 1.32)
            floor = avg_s * (0.62 + elite * 0.12)
            w = calibration_blend_weight(conf, elite, vol, star_prot, very_lim, counting=True) * 0.55
            capped = ml_val.clip(floor, cap)
            out[ml_col] = ml_val * (1 - w) + capped * w

    # OBP / SLG: gentle pull toward BA/OPS-implied range when present
    if "Predicted OBP" in out.columns and "Predicted BA" in out.columns:
        obp = _num(out["Predicted OBP"], np.nan)
        ba = _num(out["Predicted BA"], np.nan)
        w = calibration_blend_weight(conf, elite, vol, star_prot, very_lim, counting=False) * 0.35
        implied = (ba + 0.04).clip(0.220, 0.480)
        out["Predicted OBP"] = obp * (1 - w) + implied * w
    if "Predicted SLG" in out.columns and "Predicted OPS" in out.columns and "Predicted OBP" in out.columns:
        slg = _num(out["Predicted SLG"], np.nan)
        ops = _num(out["Predicted OPS"], np.nan)
        obp = _num(out["Predicted OBP"], np.nan)
        w = calibration_blend_weight(conf, elite, vol, star_prot, very_lim, counting=False) * 0.35
        implied = (ops - obp).clip(0.280, 0.720)
        out["Predicted SLG"] = slg * (1 - w) + implied * w

    out["Calibration Applied"] = True
    return out
