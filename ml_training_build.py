"""Fast vectorized ML training-set construction + on-disk cache."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ML_TRAINING_CACHE_VERSION = 4
ML_TRAINING_MIN_SEASON_AB = 50
ML_TRAINING_MIN_SEASON_G = 15
ML_INFERENCE_MIN_LATEST_G = 30
ML_INFERENCE_MIN_LATEST_AB = 75
ML_INFERENCE_POOL_SOFT_CAP = 650
ML_TRAINING_TARGET_YEAR_SPAN = 18
ML_TRAINING_MIN_CAREER_AB = 250
ML_TRAINING_PLAYER_RECENCY_YEARS = 8

ML_CACHE_DIR = Path(__file__).resolve().parent / ".ml_cache"

_AL_TEAMS = {"BAL", "BOS", "NYY", "TBR", "TOR", "CWS", "CLE", "DET", "KCR", "MIN", "HOU", "LAA", "OAK", "SEA", "TEX"}
_NL_TEAMS = {"ATL", "MIA", "NYM", "PHI", "WAS", "CHC", "CIN", "MIL", "PIT", "STL", "ARI", "COL", "LAD", "SDP", "SFG"}


def ml_training_cache_key(year_pool_sig, lookback_years: int, min_games_per_window: int) -> str:
    n, y0, y1 = year_pool_sig
    return (
        f"v{ML_TRAINING_CACHE_VERSION}_{n}_{y0}_{y1}_{int(lookback_years)}_{int(min_games_per_window)}"
    )


def _bundle_path(cache_key: str) -> Path:
    ML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return ML_CACHE_DIR / f"{cache_key}.joblib"


def load_training_bundle(cache_key: str):
    path = _bundle_path(cache_key)
    if not path.is_file():
        return None
    try:
        import joblib

        return joblib.load(path)
    except Exception:
        return None


def save_training_bundle(cache_key: str, ml_df: pd.DataFrame, feature_cols: list, models: dict | None = None):
    try:
        import joblib

        joblib.dump(
            {"df": ml_df, "feature_cols": feature_cols, "models": models or {}},
            _bundle_path(cache_key),
            compress=3,
        )
    except Exception:
        pass


def vectorized_age_for_season(season_year, birth_year, birth_month, birth_day):
    sy = pd.to_numeric(season_year, errors="coerce")
    by = pd.to_numeric(birth_year, errors="coerce")
    bm = pd.to_numeric(birth_month, errors="coerce").fillna(7)
    bd = pd.to_numeric(birth_day, errors="coerce").fillna(1)
    age = sy - by
    late = (bm > 7) | ((bm == 7) & (bd > 1))
    return age - late.astype(int)


def _batch_polyfit_slope(x_mat: np.ndarray, y_mat: np.ndarray) -> np.ndarray:
    """Row-wise least-squares slope; x_mat/y_mat shape (n, L)."""
    x_mean = x_mat.mean(axis=1, keepdims=True)
    y_mean = y_mat.mean(axis=1, keepdims=True)
    num = ((x_mat - x_mean) * (y_mat - y_mean)).sum(axis=1)
    den = ((x_mat - x_mean) ** 2).sum(axis=1)
    out = np.full(len(num), np.nan, dtype=float)
    ok = den > 1e-12
    out[ok] = num[ok] / den[ok]
    return out


def _append_context_dummies(out: pd.DataFrame) -> pd.DataFrame:
    bats = out["bats"].astype(str).fillna("Unknown")
    pos = out["primaryPos"].astype(str).fillna("DH")
    league = out["League"].astype(str).fillna("Unknown")
    team = out["primaryTeamID"].astype(str).fillna("UNK")
    for b in ["L", "R", "B", "Unknown"]:
        out[f"bats_{b}"] = (bats == b).astype(np.int8)
    for p in ["C", "1B", "2B", "3B", "SS", "OF", "P", "DH"]:
        out[f"pos_{p}"] = (pos == p).astype(np.int8)
    for lg in ["AL", "NL", "Unknown"]:
        out[f"league_{lg}"] = (league == lg).astype(np.int8)
    for t in sorted(_AL_TEAMS | _NL_TEAMS):
        out[f"team_{t}"] = (team == t).astype(np.int8)
    out["Park_Factor"] = pd.to_numeric(out.get("Park_Factor", 1.0), errors="coerce").fillna(1.0)
    return out


def build_training_set_vectorized(
    prepared_df: pd.DataFrame,
    lookback_years: int,
    min_games_per_window: int,
    target_stats: list[str],
    base_feature_stats: list[str],
    derived_feature_stats: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Vectorized supervised rows (consecutive lookback seasons -> next-year targets)."""
    if prepared_df is None or prepared_df.empty:
        return pd.DataFrame(), []

    lookback = int(lookback_years)
    if lookback < 1:
        return pd.DataFrame(), []

    df = prepared_df.sort_values(["playerID", "yearID"]).reset_index(drop=True)
    max_year = int(pd.to_numeric(df["yearID"], errors="coerce").max())
    df = df[pd.to_numeric(df["yearID"], errors="coerce") >= max_year - ML_TRAINING_TARGET_YEAR_SPAN]
    df = df[pd.to_numeric(df.get("AB", 0), errors="coerce").fillna(0) >= ML_TRAINING_MIN_SEASON_AB]
    df = df[pd.to_numeric(df.get("G", 0), errors="coerce").fillna(0) >= ML_TRAINING_MIN_SEASON_G]

    career_ab = df.groupby("playerID", sort=False)["AB"].sum()
    last_year = df.groupby("playerID", sort=False)["yearID"].max()
    keep_players = career_ab[career_ab >= ML_TRAINING_MIN_CAREER_AB].index.intersection(
        last_year[last_year >= max_year - ML_TRAINING_PLAYER_RECENCY_YEARS].index
    )
    df = df[df["playerID"].isin(keep_players)]
    if df.empty:
        return pd.DataFrame(), []

    g = df.copy()
    valid = pd.Series(True, index=g.index)
    shift_frames = []
    for k in range(1, lookback + 1):
        shifted = g.groupby("playerID", sort=False).shift(k)
        valid &= shifted["yearID"].notna()
        valid &= shifted["yearID"].to_numpy(dtype=float) == g["yearID"].to_numpy(dtype=float) - k
        shift_frames.append(shifted)

    hist_g = pd.Series(0.0, index=g.index)
    for k in range(1, lookback + 1):
        hist_g = hist_g + pd.to_numeric(shift_frames[k - 1]["G"], errors="coerce").fillna(0)
    valid &= hist_g >= float(min_games_per_window)

    out = g.loc[valid, [
        "playerID", "fullName", "bats", "primaryPos", "League", "primaryTeamID",
        "yearID", "birthYear", "birthMonth", "birthDay", "Park_Factor",
    ]].copy()
    out = out.rename(columns={"yearID": "predict_year"})
    out["last_year"] = out["predict_year"] - 1
    out["age_entering_year"] = vectorized_age_for_season(
        out["predict_year"], out["birthYear"], out["birthMonth"], out["birthDay"]
    )
    out["age_squared"] = out["age_entering_year"] ** 2

    out["hist_G_total"] = hist_g.loc[valid].to_numpy()
    hist_ab = pd.Series(0.0, index=g.index)
    for k in range(1, lookback + 1):
        hist_ab = hist_ab + pd.to_numeric(shift_frames[k - 1]["AB"], errors="coerce").fillna(0)
    out["hist_AB_total"] = hist_ab.loc[valid].to_numpy()

    g_hist = hist_g.loc[valid]
    out["durability_3yr_avg_G"] = (g_hist / lookback).to_numpy()
    g_stack = [
        pd.to_numeric(shift_frames[k - 1].loc[valid, "G"], errors="coerce").fillna(0)
        for k in range(1, lookback + 1)
    ]
    out["durability_3yr_min_G"] = pd.concat(g_stack, axis=1).min(axis=1).to_numpy()

    weights = np.arange(1, lookback + 1, dtype=float)
    weights = weights / weights.sum()
    year_mat = np.column_stack(
        [out["predict_year"].to_numpy(dtype=float) - k for k in range(lookback, 0, -1)]
    )

    all_feature_stats = list(base_feature_stats) + list(derived_feature_stats)
    feat_blocks = []
    for stat in all_feature_stats:
        if stat not in g.columns:
            continue
        cols_y = [
            pd.to_numeric(shift_frames[k - 1].loc[valid, stat], errors="coerce").fillna(0).to_numpy()
            for k in range(lookback, 0, -1)
        ]
        y_mat = np.column_stack(cols_y)
        feat_blocks.append(pd.DataFrame({
            f"{stat}_mean_{lookback}yr": np.nanmean(y_mat, axis=1),
            f"{stat}_last": cols_y[-1],
            f"{stat}_weighted_recent": (y_mat * weights).sum(axis=1),
            f"{stat}_trend": _batch_polyfit_slope(year_mat, y_mat),
        }, index=out.index))
    if feat_blocks:
        out = pd.concat([out, *feat_blocks], axis=1)
    target_block = {
        f"target_{stat}": pd.to_numeric(g.loc[valid, stat], errors="coerce")
        for stat in target_stats
        if stat in g.columns
    }
    if target_block:
        out = pd.concat([out, pd.DataFrame(target_block, index=out.index)], axis=1)
    out = _append_context_dummies(out)
    exclude = {
        "playerID", "fullName", "bats", "primaryPos", "League", "primaryTeamID",
        "predict_year", "last_year", "birthYear", "birthMonth", "birthDay",
    }
    feature_cols = [c for c in out.columns if c not in exclude and not c.startswith("target_")]
    target_cols = [f"target_{s}" for s in target_stats if f"target_{s}" in out.columns]
    out[feature_cols] = out[feature_cols].apply(pd.to_numeric, errors="coerce")
    if target_cols:
        out[target_cols] = out[target_cols].apply(pd.to_numeric, errors="coerce")
        out = out.dropna(subset=target_cols, how="all")
    return out.reset_index(drop=True), feature_cols


def _player_recent_tail_map(df: pd.DataFrame, lookback: int) -> dict[str, pd.DataFrame]:
    tails: dict[str, pd.DataFrame] = {}
    for pid, grp in df.groupby("playerID", sort=False):
        tails[str(pid)] = grp.sort_values("yearID").tail(lookback)
    return tails


def _pad_tail_matrix(tails: dict[str, pd.DataFrame], player_ids, lookback: int, col: str) -> np.ndarray:
    rows = []
    for pid in player_ids:
        tail = tails.get(str(pid), pd.DataFrame())
        if col in tail.columns:
            vals = pd.to_numeric(tail[col], errors="coerce").fillna(0).tolist()
        else:
            vals = []
        while len(vals) < lookback:
            vals.insert(0, 0.0)
        rows.append(vals[-lookback:])
    return np.asarray(rows, dtype=float)


def _pad_tail_years(tails: dict[str, pd.DataFrame], player_ids, lookback: int, last_years) -> np.ndarray:
    rows = []
    for pid, last_year in zip(player_ids, last_years, strict=False):
        tail = tails.get(str(pid), pd.DataFrame())
        if "yearID" in tail.columns and not tail.empty:
            years = pd.to_numeric(tail["yearID"], errors="coerce").fillna(last_year).astype(float).tolist()
        else:
            years = [float(last_year)]
        while len(years) < lookback:
            years.insert(0, years[0] - 1.0 if years else float(last_year) - 1.0)
        rows.append(years[-lookback:])
    return np.asarray(rows, dtype=float)


def build_current_rows_vectorized(
    prepared_df: pd.DataFrame,
    lookback_years: int,
    min_games_per_window: int,
    base_feature_stats: list[str],
    derived_feature_stats: list[str],
    max_player_pool: int | None = 300,
) -> pd.DataFrame:
    """One feature row per active player (inference allows partial lookback histories)."""
    if prepared_df is None or prepared_df.empty:
        return pd.DataFrame()
    lookback = max(1, int(lookback_years))
    df = prepared_df.dropna(subset=["playerID", "yearID"]).copy()
    df["yearID"] = df["yearID"].astype(int)
    max_data_year = int(df["yearID"].max())
    latest_by_player = df.groupby("playerID", sort=False)["yearID"].max()
    active_ids = latest_by_player.index[latest_by_player >= max_data_year - 1]
    df = df[df["playerID"].isin(active_ids)].sort_values(["playerID", "yearID"])
    if df.empty:
        return pd.DataFrame()

    is_latest = df.groupby("playerID", sort=False)["yearID"].transform("max") == df["yearID"]
    latest = df.loc[is_latest].copy()
    latest_g = pd.to_numeric(latest["G"], errors="coerce").fillna(0)
    latest_ab = pd.to_numeric(latest["AB"], errors="coerce").fillna(0)

    tails = _player_recent_tail_map(df, lookback)
    window_g = latest["playerID"].astype(str).map(lambda pid: pd.to_numeric(tails[pid]["G"], errors="coerce").fillna(0).sum())
    window_ab = latest["playerID"].astype(str).map(lambda pid: pd.to_numeric(tails[pid]["AB"], errors="coerce").fillna(0).sum())
    latest["window_G"] = pd.to_numeric(window_g, errors="coerce").fillna(0)
    latest["window_AB"] = pd.to_numeric(window_ab, errors="coerce").fillna(0)

    fantasy_gate = (latest_g >= ML_INFERENCE_MIN_LATEST_G) & (latest_ab >= ML_INFERENCE_MIN_LATEST_AB)
    volume_gate = (latest["window_G"] >= float(min_games_per_window)) & (latest["window_AB"] >= ML_INFERENCE_MIN_LATEST_AB)
    eligible = fantasy_gate | volume_gate
    out = latest.loc[eligible, [
        "playerID", "fullName", "bats", "primaryPos", "League", "primaryTeamID",
        "yearID", "birthYear", "birthMonth", "birthDay", "Park_Factor",
    ]].copy()
    if out.empty:
        return out

    out["last_year"] = out["yearID"]
    out["prediction_year"] = out["yearID"] + 1
    out["age_entering_year"] = vectorized_age_for_season(
        out["prediction_year"], out["birthYear"], out["birthMonth"], out["birthDay"]
    )
    out["age_squared"] = out["age_entering_year"] ** 2
    player_ids = out["playerID"].astype(str).tolist()
    out["hist_G_total"] = [pd.to_numeric(tails[pid]["G"], errors="coerce").fillna(0).sum() for pid in player_ids]
    out["hist_AB_total"] = [pd.to_numeric(tails[pid]["AB"], errors="coerce").fillna(0).sum() for pid in player_ids]
    out["durability_3yr_avg_G"] = out["hist_G_total"] / lookback
    out["durability_3yr_min_G"] = [
        pd.to_numeric(tails[pid]["G"], errors="coerce").fillna(0).min() if not tails[pid].empty else 0
        for pid in player_ids
    ]

    weights = np.arange(1, lookback + 1, dtype=float)
    weights = weights / weights.sum()
    all_feature_stats = list(base_feature_stats) + list(derived_feature_stats)
    year_mat = _pad_tail_years(tails, player_ids, lookback, out["last_year"].to_numpy(dtype=float))
    for stat in all_feature_stats:
        y_mat = _pad_tail_matrix(tails, player_ids, lookback, stat)
        out[f"{stat}_mean_{lookback}yr"] = np.nanmean(y_mat, axis=1)
        out[f"{stat}_last"] = y_mat[:, -1]
        out[f"{stat}_weighted_recent"] = (y_mat * weights).sum(axis=1)
        if lookback >= 2 and np.nanstd(year_mat, axis=1).max() > 0:
            out[f"{stat}_trend"] = _batch_polyfit_slope(year_mat, y_mat)
        else:
            out[f"{stat}_trend"] = 0.0

    for stat in base_feature_stats:
        if stat in df.columns:
            out[f"Last {stat}"] = out["playerID"].astype(str).map(
                lambda pid: pd.to_numeric(tails[pid][stat].iloc[-1], errors="coerce") if stat in tails[pid].columns and not tails[pid].empty else np.nan
            )

    out = _append_context_dummies(out)
    if max_player_pool and len(out) > int(max_player_pool):
        ranked = out.sort_values("hist_AB_total", ascending=False).reset_index(drop=True)
        core = ranked.head(int(max_player_pool))
        last_ab = pd.to_numeric(ranked.get("Last AB", ranked.get("AB_last", 0)), errors="coerce").fillna(0)
        last_g = pd.to_numeric(ranked.get("Last G", ranked.get("G_last", 0)), errors="coerce").fillna(0)
        extras = ranked[
            ~ranked["playerID"].isin(core["playerID"])
            & (last_ab >= ML_INFERENCE_MIN_LATEST_AB)
            & (last_g >= ML_INFERENCE_MIN_LATEST_G)
        ]
        merged = pd.concat([core, extras], ignore_index=True).drop_duplicates(subset=["playerID"], keep="first")
        if len(merged) > ML_INFERENCE_POOL_SOFT_CAP:
            merged = merged.sort_values("hist_AB_total", ascending=False).head(ML_INFERENCE_POOL_SOFT_CAP)
        out = merged.reset_index(drop=True)
    return out.reset_index(drop=True)
