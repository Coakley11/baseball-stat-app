"""Hall of Fame flags, filters, and Case Mode AMI packet builders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

HOF_STAR = "⭐"
HOF_FILTER_ALL = "All Players"
HOF_FILTER_ONLY = "Hall of Famers Only"
HOF_FILTER_NON = "Non-Hall of Famers Only"
HOF_FILTER_OPTIONS = (HOF_FILTER_ALL, HOF_FILTER_ONLY, HOF_FILTER_NON)

CAREER_HOF_FILTER_KEY = "career_hof_membership_filter"
HISTORICAL_HOF_FILTER_KEY = "historical_hof_membership_filter"
CAREER_HOF_CASE_MODE_KEY = "career_hof_case_mode"
CAREER_HOF_CASE_TARGET_KEY = "career_hof_case_target_player"
HOF_CASE_PACKET_KEY = "_hof_case_packet"

CASE_SCORE_LABEL = "Hall of Fame Statistical Case Score"
CASE_SCORE_BUCKETS = ("Weak", "Borderline", "Solid", "Strong", "Very Strong")
HOF_DATA_FILENAME = "HallOfFame.csv"


def hall_of_fame_csv_path(base_dir: Path | str) -> Path:
    """Absolute path to Lahman ``HallOfFame.csv`` (same folder as ``streamlit_app.py``)."""
    return Path(base_dir) / HOF_DATA_FILENAME


def hof_data_available(base_dir: Path | str) -> bool:
    """True when inducted-member HOF data can be loaded from disk."""
    return bool(load_hall_of_fame_player_ids(base_dir))


def hof_data_setup_message() -> str:
    return (
        f"Hall of Fame badges and Case Mode require Lahman `{HOF_DATA_FILENAME}` in the app root "
        f"(same folder as `People.csv`, `Batting.csv`, and `Fielding.csv`). "
        f"Download from the [Lahman database](https://sabr.org/lahman-database/) and upload "
        f"`{HOF_DATA_FILENAME}` alongside the other CSVs. Until then, filters still work but "
        f"no ⭐ badges or HOF cohort stats will appear."
    )


def load_hall_of_fame_player_ids(base_dir: Path | str) -> frozenset[str]:
    """Inducted playerIDs from Lahman ``HallOfFame.csv`` (``inducted == Y``)."""
    path = hall_of_fame_csv_path(base_dir)
    if not path.exists():
        return frozenset()
    try:
        hof = pd.read_csv(path, low_memory=False)
    except Exception:
        return frozenset()
    if "playerID" not in hof.columns:
        return frozenset()
    if "inducted" in hof.columns:
        mask = hof["inducted"].astype(str).str.strip().str.upper().eq("Y")
        return frozenset(hof.loc[mask, "playerID"].astype(str).tolist())
    return frozenset(hof["playerID"].astype(str).tolist())


def attach_hof_flag(df: pd.DataFrame, hof_ids: frozenset[str], *, id_col: str = "playerID") -> pd.DataFrame:
    """Add ``isHallOfFamer`` boolean column."""
    if df is None or df.empty or id_col not in df.columns:
        return df
    out = df.copy()
    out["isHallOfFamer"] = out[id_col].astype(str).isin(hof_ids)
    return out


def apply_hof_membership_filter(
    df: pd.DataFrame,
    filter_value: str,
    *,
    hof_col: str = "isHallOfFamer",
) -> pd.DataFrame:
    if df is None or df.empty or hof_col not in df.columns:
        return df
    mode = str(filter_value or HOF_FILTER_ALL).strip()
    if mode == HOF_FILTER_ONLY:
        return df[df[hof_col].fillna(False).astype(bool)].copy()
    if mode == HOF_FILTER_NON:
        return df[~df[hof_col].fillna(False).astype(bool)].copy()
    return df


def decorate_player_name(name: Any, is_hof: Any) -> str:
    label = str(name or "").strip()
    if not label:
        return label
    if bool(is_hof):
        if not label.startswith(HOF_STAR):
            return f"{HOF_STAR} {label}"
    return label


def decorate_player_column(df: pd.DataFrame, *, name_col: str = "fullName", hof_col: str = "isHallOfFamer") -> pd.DataFrame:
    if df is None or df.empty or name_col not in df.columns:
        return df
    out = df.copy()
    if hof_col in out.columns:
        out[name_col] = [
            decorate_player_name(n, h) for n, h in zip(out[name_col], out[hof_col], strict=False)
        ]
    return out


def _json_safe_value(val: Any) -> Any:
    if val is None or (not isinstance(val, (list, dict, tuple)) and pd.isna(val)):
        return None
    if isinstance(val, (bool,)):
        return bool(val)
    type_name = type(val).__name__
    if type_name in ("bool_", "bool8"):
        return bool(val)
    if type_name in ("int64", "int32", "int16", "int8", "uint64", "uint32", "uint16", "uint8"):
        return int(val)
    if type_name in ("float64", "float32", "float16"):
        return float(val)
    if isinstance(val, (int, float, str)):
        return val
    return str(val)


def _json_safe_row(row: pd.Series) -> dict[str, Any]:
    return {str(k): _json_safe_value(row[k]) for k in row.index if pd.notna(row[k])}


def _num(val: Any) -> float | None:
    n = pd.to_numeric(val, errors="coerce")
    if pd.isna(n):
        return None
    return float(n)
    n = pd.to_numeric(val, errors="coerce")
    if pd.isna(n):
        return None
    return float(n)


def summarize_career_filters(session: dict[str, Any]) -> dict[str, Any]:
    """Capture Career Totals filter state for HOF Case packet."""
    yr = session.get("career_year_range_filter")
    year_range = None
    if isinstance(yr, (list, tuple)) and len(yr) >= 2:
        year_range = [int(yr[0]), int(yr[1])]
    stat_mins: dict[str, Any] = {}
    for key, val in session.items():
        k = str(key)
        if k.startswith("career_") and k.endswith("_min") and val is not None:
            stat_mins[k.replace("career_", "").replace("_min", "")] = val
    return {
        "year_range": year_range,
        "sort_stat": session.get("career_sort_stat_filter"),
        "batting_hand": session.get("career_batting_hand_filter"),
        "position_mode": session.get("career_position_filter_mode"),
        "position": session.get("career_position_filter"),
        "team_filter": session.get("career_team_filter"),
        "by_team": bool(session.get("career_by_team_toggle_filter")),
        "hof_membership_filter": session.get(CAREER_HOF_FILTER_KEY) or HOF_FILTER_ALL,
        "stat_minimums": stat_mins,
    }


def build_hof_case_packet(
    target_player: str,
    results_df: pd.DataFrame,
    *,
    filters_summary: dict[str, Any],
    sort_stat: str,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> dict[str, Any]:
    """Build cohort packet for Baseball AMI Hall of Fame Case Mode."""
    target = str(target_player or "").strip()
    working = results_df.copy() if results_df is not None else pd.DataFrame()
    total = int(len(working))
    if hof_col in working.columns:
        hof_mask = working[hof_col].fillna(False).astype(bool)
        hof_count = int(hof_mask.sum())
    else:
        hof_count = 0
    hof_rate = round(100.0 * hof_count / total, 1) if total else 0.0

    rank: int | None = None
    target_row: dict[str, Any] | None = None
    if total and player_col in working.columns and sort_stat in working.columns:
        ranked = working.sort_values(sort_stat, ascending=False, na_position="last").reset_index(drop=True)
        names = ranked[player_col].astype(str).str.strip()
        match = names.eq(target)
        if match.any():
            idx = int(match.idxmax())
            rank = idx + 1
            row = ranked.iloc[idx]
            target_row = _json_safe_row(row)

    sample_cols = [c for c in (player_col, sort_stat, hof_col, "HR", "H", "RBI", "SB", "OPS") if c in working.columns]
    sample: list[dict[str, Any]] = []
    if sample_cols and total:
        top = working.sort_values(sort_stat, ascending=False, na_position="last").head(8)
        for _, row in top.iterrows():
            entry: dict[str, Any] = {}
            for col in sample_cols:
                val = row.get(col)
                if col == player_col:
                    entry["player"] = decorate_player_name(val, row.get(hof_col))
                elif col == hof_col:
                    entry["hall_of_famer"] = bool(val)
                else:
                    n = _num(val)
                    entry[col] = n if n is not None else val
            sample.append(entry)

    return {
        "mode": "hall_of_fame_case",
        "score_label": CASE_SCORE_LABEL,
        "score_buckets": list(CASE_SCORE_BUCKETS),
        "disclaimer": (
            "Statistical comparison only — not true Hall of Fame induction odds. "
            "Excludes awards, MVPs, All-Stars, postseason, narrative, voting, and reputation."
        ),
        "target_player": target,
        "target_in_results": rank is not None,
        "target_rank": rank,
        "total_players_returned": total,
        "hall_of_famers_returned": hof_count,
        "hall_of_fame_rate_pct": hof_rate,
        "sort_stat": str(sort_stat or ""),
        "filters_used": filters_summary,
        "target_player_row": target_row,
        "result_sample": sample,
    }


def build_hof_case_question(target_player: str, packet: dict[str, Any]) -> str:
    target = str(target_player or packet.get("target_player") or "").strip()
    total = packet.get("total_players_returned", 0)
    hof_n = packet.get("hall_of_famers_returned", 0)
    rate = packet.get("hall_of_fame_rate_pct", 0)
    rank = packet.get("target_rank")
    rank_line = f" Target ranks #{rank} in this cohort by {packet.get('sort_stat', 'sort stat')}." if rank else ""
    return (
        f"Hall of Fame Case Mode — assign a {CASE_SCORE_LABEL} for {target}. "
        f"The Career Totals search returned {total} players with {hof_n} Hall of Famers ({rate}% HOF rate).{rank_line} "
        f"Use only the statistical cohort in hof_case_packet. "
        f"Respond with one of: {', '.join(CASE_SCORE_BUCKETS)}. "
        f"Do NOT present this as true Hall of Fame induction odds."
    )


def hof_case_ami_guidance() -> str:
    return (
        "Hall of Fame Case Mode: read hof_case_packet only. "
        f"Output a {CASE_SCORE_LABEL} using labels {', '.join(CASE_SCORE_BUCKETS)}. "
        "Explain using the filtered cohort's Hall of Fame prevalence and the target's standing. "
        "Never cite awards, MVPs, All-Stars, postseason, narrative, voting history, or reputation. "
        "Never present the score as true induction probability."
    )


def player_in_results(target_player: str, results_df: pd.DataFrame, *, player_col: str = "fullName") -> bool:
    target = str(target_player or "").strip()
    if not target or results_df is None or results_df.empty or player_col not in results_df.columns:
        return False
    names = results_df[player_col].astype(str).str.strip()
    return bool(names.eq(target).any())
