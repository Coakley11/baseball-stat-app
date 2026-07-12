"""Fetch current-season MLB hitter stats (no Streamlit)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from player_name_normalization import normalize_player_name_for_merge


def fetch_mlb_api_hitter_stats(season: int = 2026) -> pd.DataFrame:
    """Fetch current-season MLB hitter stats from the public MLB Stats API.

    Returns a normalized dataframe with:
    Player, HR, RBI, R, SB, BA, OBP, SLG, OPS, AB, H, BB.
    """
    import requests

    url = "https://statsapi.mlb.com/api/v1/stats"
    params = {
        "stats": "season",
        "group": "hitting",
        "playerPool": "ALL",
        "season": int(season),
        "sportIds": 1,
        "limit": 5000,
        "hydrate": "person",
    }

    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        raise RuntimeError(f"Could not fetch MLB API stats: {e}") from e

    rows: list[dict] = []
    for split in payload.get("stats", [{}])[0].get("splits", []):
        player = split.get("player", {}) or {}
        stat = split.get("stat", {}) or {}
        rows.append(
            {
                "Player": player.get("fullName", ""),
                "Player Key": normalize_player_name_for_merge(player.get("fullName", "")),
                "MLBAM ID": player.get("id", None),
                "MLB Team": (split.get("team", {}) or {}).get("name", ""),
                "Primary Position": (player.get("primaryPosition", {}) or {}).get("abbreviation", ""),
                "G": stat.get("gamesPlayed", np.nan),
                "AB": stat.get("atBats", np.nan),
                "H": stat.get("hits", np.nan),
                "2B": stat.get("doubles", np.nan),
                "3B": stat.get("triples", np.nan),
                "HR": stat.get("homeRuns", np.nan),
                "RBI": stat.get("rbi", np.nan),
                "R": stat.get("runs", np.nan),
                "SB": stat.get("stolenBases", np.nan),
                "BB": stat.get("baseOnBalls", np.nan),
                "BA": stat.get("avg", np.nan),
                "OBP": stat.get("obp", np.nan),
                "SLG": stat.get("slg", np.nan),
                "OPS": stat.get("ops", np.nan),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for col in ("G", "AB", "H", "2B", "3B", "HR", "RBI", "R", "SB", "BB", "BA", "OBP", "SLG", "OPS"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Primary Position" in df.columns:
        df["Primary Position"] = df["Primary Position"].replace(
            {
                "LF": "OF",
                "CF": "OF",
                "RF": "OF",
                "RF/LF": "OF",
                "OF": "OF",
                "TWP": "DH",
                "PH": "DH",
                "PR": "DH",
            }
        ).fillna("DH")

    return df
