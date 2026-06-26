"""Hall of Fame flags, filters, and Case Mode AMI packet builders."""

from __future__ import annotations

import re
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
HOF_CASE_TARGET_ALREADY_IN_HOF_MSG = (
    "This player is already in the Hall of Fame. Select a non-Hall-of-Fame player to analyze."
)
HOF_DATA_FILENAME = "HallOfFame.csv"
HOF_PLAYER_CATEGORY = "Player"
KNOWN_HOF_PLAYER_IDS = ("ruthba01", "aaronha01", "mayswi01")


def hof_case_target_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s or "player"


def resolve_hof_case_target_slug(slug: str, player_names: list[str] | None = None) -> str:
    """Map resume slug (e.g. albert-pujols) back to a display name when possible."""
    target_slug = str(slug or "").strip().lower()
    for name in player_names or []:
        if hof_case_target_slug(name) == target_slug:
            return str(name).strip()
    cleaned = str(slug or "").replace("-", " ").strip()
    return cleaned.title() if cleaned else ""


def target_player_is_hall_of_famer(
    target: str,
    df: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> bool:
    """True when the named target player is already inducted (not eligible for Case Mode)."""
    name = str(target or "").strip()
    if not name or df is None or df.empty or player_col not in df.columns or hof_col not in df.columns:
        return False
    rows = df[df[player_col].astype(str).str.strip() == name]
    if rows.empty:
        return False
    return bool(rows[hof_col].fillna(False).astype(bool).any())


def hof_case_target_player_options(
    df: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
    hof_col: str = "isHallOfFamer",
) -> list[str]:
    """Player names eligible as Hall of Fame Case Mode targets (non-inducted only)."""
    if df is None or df.empty or player_col not in df.columns:
        return []
    working = df
    if hof_col in working.columns:
        working = working.loc[~working[hof_col].fillna(False).astype(bool)]
    names = working[player_col].dropna().astype(str).str.strip()
    return sorted({n for n in names if n})


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


HOF_CASE_STAT_KEYS = (
    "G",
    "AB",
    "R",
    "H",
    "2B",
    "3B",
    "HR",
    "RBI",
    "SB",
    "BB",
    "BA",
    "OBP",
    "SLG",
    "OPS",
)


def _resolve_primary_position(row: pd.Series | dict[str, Any]) -> str:
    if isinstance(row, dict):
        row = pd.Series(row)
    for col in ("Primary Position", "displayPosition", "careerPrimaryPos", "primaryPos", "POS"):
        if col in row.index:
            val = str(row.get(col) or "").strip()
            if val and val.lower() not in ("nan", "none", ""):
                return val
    return "Unknown"


def _stat_columns_present(df: pd.DataFrame, stats: tuple[str, ...] = HOF_CASE_STAT_KEYS) -> list[str]:
    if df is None or df.empty:
        return []
    return [c for c in stats if c in df.columns]


def _cohort_stat_summary(working: pd.DataFrame, stat: str) -> dict[str, Any]:
    if stat not in working.columns or working.empty:
        return {}
    series = pd.to_numeric(working[stat], errors="coerce").dropna()
    if series.empty:
        return {}
    return {
        "min": float(series.min()),
        "max": float(series.max()),
        "median": float(series.median()),
        "mean": round(float(series.mean()), 3),
        "count": int(series.count()),
    }


def _rank_in_frame(
    df: pd.DataFrame,
    target: str,
    stat: str,
    *,
    player_col: str = "fullName",
    ascending: bool = False,
) -> dict[str, Any] | None:
    if df is None or df.empty or stat not in df.columns or player_col not in df.columns:
        return None
    ranked = df.sort_values(stat, ascending=ascending, na_position="last").reset_index(drop=True)
    names = ranked[player_col].astype(str).str.strip()
    match = names.eq(target)
    if not match.any():
        return None
    idx = int(match.idxmax())
    total = int(len(ranked))
    rank = idx + 1
    value = _num(ranked.iloc[idx].get(stat))
    percentile = round(100.0 * (total - rank) / max(total - 1, 1), 1) if total > 1 else 100.0
    if not ascending:
        percentile = round(100.0 * (total - rank) / max(total - 1, 1), 1) if total > 1 else 100.0
    else:
        percentile = round(100.0 * (rank - 1) / max(total - 1, 1), 1) if total > 1 else 100.0
    return {
        "stat": stat,
        "rank": rank,
        "of": total,
        "value": value,
        "percentile_top": percentile,
        "tier": _percentile_tier(percentile),
    }


def _percentile_tier(percentile_top: float) -> str:
    if percentile_top >= 99:
        return "top 1%"
    if percentile_top >= 95:
        return "top 5%"
    if percentile_top >= 90:
        return "top 10%"
    if percentile_top >= 75:
        return "top quartile"
    if percentile_top >= 50:
        return "above median"
    if percentile_top >= 25:
        return "below median"
    return "bottom quartile"


def _build_cohort_stat_context(
    working: pd.DataFrame,
    target: str,
    *,
    player_col: str = "fullName",
    stats: tuple[str, ...] = HOF_CASE_STAT_KEYS,
) -> dict[str, Any]:
    stat_cols = _stat_columns_present(working, stats)
    summaries: dict[str, Any] = {}
    target_ranks: dict[str, Any] = {}
    for stat in stat_cols:
        summary = _cohort_stat_summary(working, stat)
        if summary:
            summaries[stat] = summary
        rank = _rank_in_frame(working, target, stat, player_col=player_col)
        if rank:
            target_ranks[stat] = rank
    strengths = [s for s, r in target_ranks.items() if r.get("percentile_top", 0) >= 75]
    weaknesses = [s for s, r in target_ranks.items() if r.get("percentile_top", 0) < 25]
    return {
        "cohort_stat_summaries": summaries,
        "target_cohort_ranks": target_ranks,
        "cohort_strength_stats": strengths[:6],
        "cohort_weakness_stats": weaknesses[:6],
    }


def _assess_cohort_selectivity(
    filters_summary: dict[str, Any],
    *,
    total: int,
    hof_rate: float,
    sort_stat: str,
) -> dict[str, Any]:
    stat_mins = filters_summary.get("stat_minimums") if isinstance(filters_summary.get("stat_minimums"), dict) else {}
    threshold_notes: list[str] = []
    selectivity_score = 0
    for stat, val in stat_mins.items():
        n = _num(val)
        if n is None:
            continue
        if stat == "HR" and n >= 500:
            threshold_notes.append("A 500+ HR cohort is historically very Hall-of-Fame heavy.")
            selectivity_score += 3
        elif stat == "HR" and n >= 400:
            threshold_notes.append("A 400+ HR threshold signals elite power and a selective cohort.")
            selectivity_score += 2
        elif stat == "H" and n >= 3000:
            threshold_notes.append("3,000 hits is one of the strongest traditional Hall markers.")
            selectivity_score += 3
        elif stat == "H" and n >= 2500:
            threshold_notes.append("2,500+ hits is a highly selective longevity cohort.")
            selectivity_score += 2
        elif stat == "RBI" and n >= 1500:
            threshold_notes.append("1,500+ RBI filters to established run producers.")
            selectivity_score += 1
    if total <= 15:
        threshold_notes.append("This cohort is selective, so appearing in it is stronger evidence.")
        selectivity_score += 2
    elif total >= 80:
        threshold_notes.append("This cohort is broad, so the HOF rate should be treated with less confidence.")
        selectivity_score -= 1
    if hof_rate >= 70:
        threshold_notes.append("The filtered group has a very high Hall of Fame prevalence.")
    elif hof_rate <= 15 and total >= 10:
        threshold_notes.append("Few players in this cohort are inducted — the case depends on standing out within the group.")
    confidence = "high" if selectivity_score >= 3 else "moderate" if selectivity_score >= 1 else "low"
    return {
        "selectivity": "selective" if selectivity_score >= 2 else "moderate" if selectivity_score >= 0 else "broad",
        "confidence": confidence,
        "threshold_notes": threshold_notes,
        "sort_stat": sort_stat,
        "cohort_size": total,
        "hof_rate_pct": hof_rate,
    }


def _aggregate_position_universe(
    batting_df: pd.DataFrame,
    *,
    player_col: str = "fullName",
) -> pd.DataFrame:
    if batting_df is None or batting_df.empty or "playerID" not in batting_df.columns:
        return pd.DataFrame()
    stat_cols = [c for c in HOF_CASE_STAT_KEYS if c in batting_df.columns and c not in ("BA", "OBP", "SLG", "OPS")]
    group_cols = ["playerID", player_col] if player_col in batting_df.columns else ["playerID"]
    pos_col = None
    for candidate in ("careerPrimaryPos", "primaryPos", "POS"):
        if candidate in batting_df.columns:
            pos_col = candidate
            break
    if pos_col:
        group_cols.append(pos_col)
    grouped = batting_df.groupby(group_cols, as_index=False)[stat_cols].sum()
    if pos_col and pos_col != "careerPrimaryPos":
        grouped = grouped.rename(columns={pos_col: "careerPrimaryPos"})
    elif pos_col is None:
        grouped["careerPrimaryPos"] = "Unknown"
    if all(c in grouped.columns for c in ("H", "AB")):
        grouped["BA"] = grouped["H"] / grouped["AB"].replace(0, pd.NA)
    return grouped


def _build_position_hof_context(
    target: str,
    target_row: dict[str, Any] | None,
    position_universe: pd.DataFrame | None,
    *,
    player_col: str = "fullName",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "primary_position": "Unknown",
        "position_stat_ranks": {},
        "position_percentiles": {},
        "position_rarity_findings": [],
    }
    if not target_row or position_universe is None or position_universe.empty:
        return out
    primary = _resolve_primary_position(target_row)
    out["primary_position"] = primary
    if primary in ("Unknown", ""):
        return out
    pos_col = "careerPrimaryPos" if "careerPrimaryPos" in position_universe.columns else None
    if not pos_col:
        return out
    peers = position_universe[position_universe[pos_col].astype(str).str.strip() == primary].copy()
    if peers.empty:
        return out
    stat_cols = _stat_columns_present(peers)
    ranks: dict[str, Any] = {}
    percentiles: dict[str, Any] = {}
    rarity: list[str] = []
    for stat in stat_cols:
        rank_info = _rank_in_frame(peers, target, stat, player_col=player_col)
        if not rank_info:
            continue
        ranks[stat] = {"rank": rank_info["rank"], "of": rank_info["of"], "value": rank_info["value"]}
        percentiles[stat] = {
            "percentile_top": rank_info["percentile_top"],
            "tier": rank_info["tier"],
        }
        if rank_info["rank"] == 1 and stat in ("HR", "H", "RBI", "SB", "2B", "3B"):
            rarity.append(f"#{rank_info['rank']} all-time among {primary}s in {stat} in this dataset.")
        val = _num(rank_info.get("value"))
        peer_total = int(rank_info.get("of") or 0)
        if val is not None and stat in ("HR", "H", "RBI") and peer_total >= 5:
            above = peers[pd.to_numeric(peers[stat], errors="coerce") >= val]
            count_at_threshold = int(len(above))
            if stat == "HR" and val >= 300 and count_at_threshold <= 5:
                rarity.append(
                    f"One of only {count_at_threshold} {primary}s with {int(val)}+ HR in this dataset."
                )
            elif stat == "H" and val >= 2500 and count_at_threshold <= 5:
                rarity.append(
                    f"One of only {count_at_threshold} {primary}s with {int(val)}+ hits in this dataset."
                )
    out["position_stat_ranks"] = ranks
    out["position_percentiles"] = percentiles
    out["position_rarity_findings"] = rarity[:8]
    return out


def build_hof_case_summary_line(packet: dict[str, Any]) -> str:
    target = str(packet.get("target_player") or "")
    rate = packet.get("hall_of_fame_rate_pct")
    total = packet.get("total_players_returned")
    hof_n = packet.get("hall_of_famers_returned")
    pos = str(packet.get("primary_position") or packet.get("position_context", {}).get("primary_position") or "")
    rank = packet.get("target_rank")
    sort_stat = packet.get("sort_stat") or ""
    parts = [f"Hall of Fame statistical case for {target}"]
    if total is not None:
        parts.append(f"cohort {hof_n}/{total} HOF ({rate}%)")
    if rank and sort_stat:
        parts.append(f"#{rank} in cohort by {sort_stat}")
    if pos and pos != "Unknown":
        parts.append(f"primary position {pos}")
    return " · ".join(parts)


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
    awards_df: pd.DataFrame | None = None,
    awards_fallback_df: pd.DataFrame | None = None,
    position_universe_df: pd.DataFrame | None = None,
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

    sample_cols = [
        c
        for c in (
            player_col,
            sort_stat,
            hof_col,
            "displayPosition",
            "Primary Position",
            "G",
            "HR",
            "H",
            "RBI",
            "R",
            "2B",
            "OPS",
        )
        if c in working.columns
    ]
    sample: list[dict[str, Any]] = []
    if sample_cols and total:
        top = working.sort_values(sort_stat, ascending=False, na_position="last").head(12)
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

    awards_context: dict[str, Any] = {
        "target_awards_summary": {"data_available": False, "message": "Awards data unavailable."},
        "cohort_awards_summary": {"data_available": False, "message": "Awards data unavailable."},
        "target_award_rank": {"data_available": False},
        "cohort_award_comparison": {"data_available": False, "message": "Awards data unavailable."},
    }
    try:
        from awards_players_data import build_hof_case_awards_context

        awards_context = build_hof_case_awards_context(
            target, working, awards_df, fallback_df=awards_fallback_df
        )
    except ImportError:
        pass

    cohort_stats = _build_cohort_stat_context(working, target, player_col=player_col)
    cohort_selectivity = _assess_cohort_selectivity(
        filters_summary,
        total=total,
        hof_rate=hof_rate,
        sort_stat=str(sort_stat or ""),
    )
    position_universe = position_universe_df
    if position_universe is None and awards_fallback_df is not None:
        position_universe = _aggregate_position_universe(awards_fallback_df, player_col=player_col)
    position_context = _build_position_hof_context(
        target,
        target_row,
        position_universe,
        player_col=player_col,
    )
    primary_position = position_context.get("primary_position") or _resolve_primary_position(target_row or {})

    packet = {
        "mode": "hall_of_fame_case",
        "score_label": CASE_SCORE_LABEL,
        "score_buckets": list(CASE_SCORE_BUCKETS),
        "disclaimer": (
            "Statistical Hall of Fame case analysis only — not true Hall of Fame induction odds. "
            "Use cohort strength, career totals, position-adjusted rarity, and supporting awards evidence. "
            "Do not present a guaranteed probability of induction."
        ),
        "target_player": target,
        "primary_position": primary_position,
        "target_in_results": rank is not None,
        "target_rank": rank,
        "total_players_returned": total,
        "hall_of_famers_returned": hof_count,
        "hall_of_fame_rate_pct": hof_rate,
        "sort_stat": str(sort_stat or ""),
        "filters_used": filters_summary,
        "target_player_row": target_row,
        "target_career_stats": target_row,
        "result_sample": sample,
        "cohort_stat_summaries": cohort_stats.get("cohort_stat_summaries"),
        "target_cohort_ranks": cohort_stats.get("target_cohort_ranks"),
        "cohort_strength_stats": cohort_stats.get("cohort_strength_stats"),
        "cohort_weakness_stats": cohort_stats.get("cohort_weakness_stats"),
        "cohort_selectivity": cohort_selectivity,
        "position_context": position_context,
        "position_stat_ranks": position_context.get("position_stat_ranks"),
        "position_percentiles": position_context.get("position_percentiles"),
        "position_rarity_findings": position_context.get("position_rarity_findings"),
        "target_awards_summary": awards_context.get("target_awards_summary"),
        "cohort_awards_summary": awards_context.get("cohort_awards_summary"),
        "target_award_rank": awards_context.get("target_award_rank"),
        "cohort_award_comparison": awards_context.get("cohort_award_comparison"),
    }
    packet["hof_case_summary"] = build_hof_case_summary_line(packet)
    return packet


def build_hof_case_question(target_player: str, packet: dict[str, Any]) -> str:
    target = str(target_player or packet.get("target_player") or "").strip()
    total = packet.get("total_players_returned", 0)
    hof_n = packet.get("hall_of_famers_returned", 0)
    rate = packet.get("hall_of_fame_rate_pct", 0)
    rank = packet.get("target_rank")
    rank_line = f" Target ranks #{rank} in this cohort by {packet.get('sort_stat', 'sort stat')}." if rank else ""
    awards_line = ""
    comparison = packet.get("cohort_award_comparison") if isinstance(packet.get("cohort_award_comparison"), dict) else {}
    target_awards = packet.get("target_awards_summary") if isinstance(packet.get("target_awards_summary"), dict) else {}
    if comparison.get("data_available") and target_awards.get("data_available"):
        awards_line = (
            f" Target has {comparison.get('target_total_awards', 0)} total awards "
            f"({comparison.get('target_major_awards', 0)} major); "
            f"{comparison.get('players_with_more_total_awards', 0)} cohort players have more total awards."
        )
    return (
        f"Hall of Fame Case Mode — assign a {CASE_SCORE_LABEL} for {target}. "
        f"The Career Totals search returned {total} players with {hof_n} Hall of Famers ({rate}% HOF rate).{rank_line}{awards_line} "
        f"Use the statistical cohort and awards summaries in hof_case_packet as supporting evidence. "
        f"Respond with one of: {', '.join(CASE_SCORE_BUCKETS)}. "
        f"Do NOT present this as true Hall of Fame induction odds."
    )


def hof_case_ami_guidance() -> str:
    return (
        "Hall of Fame Case Mode: read hof_case_packet only. "
        f"Assign a {CASE_SCORE_LABEL} using labels {', '.join(CASE_SCORE_BUCKETS)}. "
        "This is a statistical case — not true induction odds or a guaranteed probability.\n\n"
        "Required output sections (use these headings):\n"
        "1. Summary Judgment — one paragraph on the statistical case.\n"
        "2. Statistical Cohort Strength — interpret hall_of_fame_rate_pct, cohort_selectivity, "
        "and filters_used thresholds (e.g., 500+ HR, 3,000 hits).\n"
        "3. Target Player's Standing in the Cohort — use target_player_row / target_career_stats, "
        "target_cohort_ranks, cohort_strength_stats, and cohort_weakness_stats. "
        "Explain where the target ranks on HR, hits, RBI, OPS, etc.\n"
        "4. Position-Based Hall of Fame Case — use primary_position, position_stat_ranks, "
        "position_percentiles, and position_rarity_findings. "
        "Explain whether the totals are exceptional for that position.\n"
        "5. Awards / Accolades Context — use target_awards_summary, cohort_awards_summary, "
        "target_award_rank, and cohort_award_comparison as supporting evidence only.\n"
        "6. Reasons the Case Is Strong — bullet points grounded in stats and cohort position.\n"
        "7. Reasons for Caution — limitations, broad cohorts, below-average awards, position norms.\n"
        f"8. {CASE_SCORE_LABEL} — final bucket with brief justification.\n\n"
        "Interpret the baseball statistics themselves — not just the cohort HOF percentage. "
        "Never say '90% chance of making the Hall of Fame', 'true induction odds', or 'guaranteed probability'. "
        "Use terms like 'statistical case', 'cohort strength', and 'supporting awards evidence'."
    )


def player_in_results(target_player: str, results_df: pd.DataFrame, *, player_col: str = "fullName") -> bool:
    target = str(target_player or "").strip()
    if not target or results_df is None or results_df.empty or player_col not in results_df.columns:
        return False
    names = results_df[player_col].astype(str).str.strip()
    return bool(names.eq(target).any())
