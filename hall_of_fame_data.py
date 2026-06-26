"""Hall of Fame flags, filters, and Case Mode AMI packet builders."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HOF_STAR = "⭐"
HOF_SCATTER_COLOR_COL = "Hall of Fame"
HOF_SCATTER_HOF_LABEL = "Hall of Famer"
HOF_SCATTER_NON_HOF_LABEL = "Non-Hall of Famer"
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
HOF_CASE_MODE_EXPLANATION = (
    "Hall of Fame Case Mode lets you evaluate whether a player belongs to a statistical cohort "
    "that historically contains many Hall of Famers. Choose a player, create a career-stat comparison "
    "group using the filters, then send the cohort to AMI for a Hall of Fame statistical case analysis."
)
HOF_CASE_MODE_INSTRUCTIONS = (
    "Select a player, then use the Career Totals filters above to create a comparison group. "
    "The selected player must appear in the filtered results before a Hall of Fame case can be analyzed."
)
HOF_CASE_ANALYZE_BUTTON_LABEL = "Analyze Hall of Fame Statistical Case with AMI"
HOF_DATA_FILENAME = "HallOfFame.csv"
HOF_PLAYER_CATEGORY = "Player"
KNOWN_HOF_PLAYER_IDS = ("ruthba01", "aaronha01", "mayswi01")


def hall_of_fame_csv_path(base_dir: Path | str) -> Path:
    """Absolute path to Lahman ``HallOfFame.csv`` (same folder as ``streamlit_app.py``)."""
    return Path(base_dir) / HOF_DATA_FILENAME


def hof_data_available(base_dir: Path | str) -> bool:
    """True when inducted player HOF data can be loaded from disk."""
    return len(load_hall_of_fame_player_ids(base_dir)) > 0


def hof_file_cache_key(base_dir: Path | str) -> float:
    """Change when ``HallOfFame.csv`` is added or updated (for Streamlit cache busting)."""
    path = hall_of_fame_csv_path(base_dir)
    try:
        return float(path.stat().st_mtime) if path.exists() else 0.0
    except OSError:
        return 0.0


def _column_lookup(df: pd.DataFrame, *names: str) -> str | None:
    lower = {str(c).lower(): str(c) for c in df.columns}
    for name in names:
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def _parse_hof_dataframe(hof: pd.DataFrame) -> pd.DataFrame:
    """Normalize Lahman HallOfFame column names and inducted/category values."""
    if hof is None or hof.empty:
        return pd.DataFrame(columns=["playerID", "inducted", "category"])
    out = hof.copy()
    rename: dict[str, str] = {}
    pid_col = _column_lookup(out, "playerID", "playerid")
    inducted_col = _column_lookup(out, "inducted")
    category_col = _column_lookup(out, "category")
    if pid_col and pid_col != "playerID":
        rename[pid_col] = "playerID"
    if inducted_col and inducted_col != "inducted":
        rename[inducted_col] = "inducted"
    if category_col and category_col != "category":
        rename[category_col] = "category"
    if rename:
        out = out.rename(columns=rename)
    if "playerID" not in out.columns:
        return pd.DataFrame(columns=["playerID", "inducted", "category"])
    out["playerID"] = out["playerID"].astype(str).str.strip()
    out = out[out["playerID"].ne("") & out["playerID"].ne("nan")]
    if "inducted" in out.columns:
        out["inducted"] = out["inducted"].astype(str).str.strip().str.upper()
        out = out[out["inducted"].eq("Y")]
    if "category" in out.columns:
        out["category"] = out["category"].astype(str).str.strip()
        out = out[out["category"].str.casefold().eq(HOF_PLAYER_CATEGORY.casefold())]
    return out.drop_duplicates(subset=["playerID"], keep="first")


def load_hall_of_fame_player_ids(base_dir: Path | str) -> frozenset[str]:
    """Inducted player-category playerIDs from Lahman ``HallOfFame.csv``."""
    path = hall_of_fame_csv_path(base_dir)
    if not path.exists():
        return frozenset()
    try:
        hof = pd.read_csv(path, low_memory=False)
    except Exception:
        return frozenset()
    parsed = _parse_hof_dataframe(hof)
    if parsed.empty or "playerID" not in parsed.columns:
        return frozenset()
    return frozenset(parsed["playerID"].astype(str).tolist())


def hof_csv_modified_time(base_dir: Path | str) -> str | None:
    path = hall_of_fame_csv_path(base_dir)
    try:
        if not path.exists():
            return None
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return None


def count_hof_true(df: pd.DataFrame | None, *, hof_col: str = "isHallOfFamer") -> int:
    if df is None or df.empty or hof_col not in df.columns:
        return 0
    return int(df[hof_col].fillna(False).astype(bool).sum())


def build_hof_cohort_summary_text(
    results_df: pd.DataFrame | None,
    *,
    hof_data_loaded: bool = True,
    hof_col: str = "isHallOfFamer",
) -> str | None:
    """Plain-text Hall of Fame cohort line for display above Career Totals table."""
    if results_df is None or results_df.empty:
        return None
    total = int(len(results_df))
    if not hof_data_loaded:
        return (
            "Hall of Fame Cohort:\n"
            "Hall of Fame data unavailable — add HallOfFame.csv to calculate cohort rate."
        )
    if hof_col not in results_df.columns:
        return (
            "Hall of Fame Cohort:\n"
            "Hall of Fame flags are not available for this result set."
        )
    hof_count = count_hof_true(results_df, hof_col=hof_col)
    rate = round(100.0 * hof_count / total, 1) if total else 0.0
    return f"Hall of Fame Cohort:\n{hof_count} of {total} players are Hall of Famers ({rate}%)"


def render_hof_cohort_summary(st: Any, summary_text: str | None) -> None:
    if summary_text:
        st.markdown(summary_text)


def build_hof_runtime_diagnostics(
    base_dir: Path | str,
    *,
    results_df: pd.DataFrame | None = None,
    batting_df: pd.DataFrame | None = None,
    hof_player_ids: frozenset[str] | None = None,
    hof_cache_key: float | None = None,
    git_commit: str = "",
    hof_filter_value: str = "",
    page_label: str = "",
) -> dict[str, Any]:
    """Full runtime diagnostic bundle for developer panels."""
    path = hall_of_fame_csv_path(base_dir)
    base = Path(base_dir)
    ids = hof_player_ids if hof_player_ids is not None else load_hall_of_fame_player_ids(base_dir)
    first_five = sorted(ids)[:5]
    diag = hof_load_diagnostics(base_dir)
    diag.update(
        {
            "page": page_label,
            "git_commit": git_commit or "unknown",
            "app_base_dir": str(base.resolve()),
            "csv_path_resolved": str(path.resolve()),
            "csv_modified_utc": hof_csv_modified_time(base_dir),
            "hof_cache_key": hof_cache_key,
            "hof_filter_active": str(hof_filter_value or HOF_FILTER_ALL),
            "loaded_hof_player_id_count": len(ids),
            "first_5_hof_player_ids": first_five,
            "batting_df_row_count": int(len(batting_df)) if batting_df is not None else 0,
            "batting_df_isHallOfFamer_true_count": count_hof_true(batting_df),
            "results_df_row_count": int(len(results_df)) if results_df is not None else 0,
            "results_df_isHallOfFamer_true_count": count_hof_true(results_df),
            "root_csv_files": sorted(p.name for p in base.glob("*.csv")),
        }
    )
    diag["sample_player_ids"] = first_five
    return diag


def hof_load_diagnostics(base_dir: Path | str) -> dict[str, Any]:
    """Runtime diagnostics for HOF CSV path, parse, and known-ID checks."""
    path = hall_of_fame_csv_path(base_dir)
    diag: dict[str, Any] = {
        "csv_path": str(path.resolve()),
        "csv_exists": path.exists(),
        "csv_filename": HOF_DATA_FILENAME,
        "hof_data_available": False,
        "inducted_player_count": 0,
        "sample_player_ids": [],
        "known_ids_present": {pid: False for pid in KNOWN_HOF_PLAYER_IDS},
        "columns": [],
        "csv_modified_utc": hof_csv_modified_time(base_dir),
    }
    if not path.exists():
        return diag
    try:
        raw = pd.read_csv(path, low_memory=False, nrows=0)
        diag["columns"] = [str(c) for c in raw.columns]
    except Exception as exc:
        diag["read_error"] = str(exc)
        return diag
    ids = load_hall_of_fame_player_ids(base_dir)
    sample = sorted(ids)[:10]
    diag.update(
        {
            "hof_data_available": bool(ids),
            "inducted_player_count": len(ids),
            "sample_player_ids": sample,
            "known_ids_present": {pid: pid in ids for pid in KNOWN_HOF_PLAYER_IDS},
        }
    )
    return diag


def hof_data_setup_message() -> str:
    return (
        f"Hall of Fame badges and Case Mode require Lahman `{HOF_DATA_FILENAME}` in the app root "
        f"(same folder as `People.csv`, `Batting.csv`, and `Fielding.csv`). "
        f"Download from the [Lahman database](https://sabr.org/lahman-database/) and upload "
        f"`{HOF_DATA_FILENAME}` alongside the other CSVs. Until then, filters still work but "
        f"no ⭐ badges or HOF cohort stats will appear."
    )


def attach_hof_flag(df: pd.DataFrame, hof_ids: frozenset[str], *, id_col: str = "playerID") -> pd.DataFrame:
    """Add or refresh ``isHallOfFamer`` via ``playerID`` membership (never player name)."""
    if df is None or df.empty or id_col not in df.columns:
        return df
    out = df.copy()
    if "isHallOfFamer" in out.columns:
        out = out.drop(columns=["isHallOfFamer"])
    pid = out[id_col].astype(str).str.strip()
    out["isHallOfFamer"] = pid.isin(hof_ids)
    return out


def merge_hof_flag(df: pd.DataFrame, hof_ids: frozenset[str], *, id_col: str = "playerID") -> pd.DataFrame:
    """Attach HOF flag on aggregated page results (always keyed on ``playerID``)."""
    return attach_hof_flag(df, hof_ids, id_col=id_col)


def hof_scatter_color_available(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty:
        return False
    return HOF_SCATTER_COLOR_COL in df.columns or "isHallOfFamer" in df.columns


def ensure_hof_scatter_columns(
    df: pd.DataFrame | None,
    hof_ids: frozenset[str] | None = None,
) -> pd.DataFrame:
    """Ensure scatter plot data has ``isHallOfFamer`` and categorical ``Hall of Fame`` columns."""
    if df is None or df.empty:
        return df
    out = attach_hof_flag(df, hof_ids, id_col="playerID") if hof_ids and "playerID" in df.columns else df.copy()
    if "isHallOfFamer" not in out.columns:
        return out
    hof_mask = out["isHallOfFamer"].fillna(False).astype(bool)
    out[HOF_SCATTER_COLOR_COL] = np.where(
        hof_mask,
        HOF_SCATTER_HOF_LABEL,
        HOF_SCATTER_NON_HOF_LABEL,
    )
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


def _resolve_display_name_column(df: pd.DataFrame, name_col: str | None = None) -> str | None:
    if name_col and name_col in df.columns:
        return name_col
    for candidate in ("Player", "fullName", "Name", "player_name", "full_name"):
        if candidate in df.columns:
            return candidate
    return None


def badge_hof_players_for_table(
    table_df: pd.DataFrame,
    source_df: pd.DataFrame | None = None,
    *,
    name_col: str | None = None,
    hof_col: str = "isHallOfFamer",
) -> pd.DataFrame:
    """Apply ⭐ to the exact player-name column shown in the rendered table."""
    if table_df is None or table_df.empty:
        return table_df
    out = table_df.copy()
    col = _resolve_display_name_column(out, name_col)
    if not col:
        return out.drop(columns=[hof_col], errors="ignore")
    flags = None
    if hof_col in out.columns:
        flags = out[hof_col]
    elif source_df is not None and hof_col in source_df.columns:
        if out.index.equals(source_df.index):
            flags = source_df[hof_col]
        else:
            flags = source_df.reindex(out.index)[hof_col]
    if flags is None:
        return out.drop(columns=[hof_col], errors="ignore")
    out[col] = [
        decorate_player_name(n, h) for n, h in zip(out[col], flags, strict=False)
    ]
    return out.drop(columns=[hof_col], errors="ignore")


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
