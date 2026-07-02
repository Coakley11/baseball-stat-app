"""Lahman AwardsPlayers.csv loading and Hall of Fame Case Mode award summaries."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import pandas as pd

AWARDS_PLAYERS_FILENAME = "AwardsPlayers.csv"

MAJOR_AWARD_IDS: frozenset[str] = frozenset(
    {
        "Most Valuable Player",
        "Cy Young Award",
        "Gold Glove",
        "Silver Slugger",
        "Rookie of the Year",
        "World Series MVP",
        "Hank Aaron Award",
        "Roberto Clemente Award",
        "Comeback Player of the Year",
        "NLCS MVP",
        "ALCS MVP",
        "TSN Player of the Year",
        "TSN Major League Player of the Year",
        "TSN Pitcher of the Year",
    }
)

AWARD_DISPLAY_NAMES: dict[str, str] = {
    "Most Valuable Player": "MVP",
    "Cy Young Award": "Cy Young",
    "Gold Glove": "Gold Glove",
    "Silver Slugger": "Silver Slugger",
    "Rookie of the Year": "Rookie of the Year",
    "World Series MVP": "World Series MVP",
    "Hank Aaron Award": "Hank Aaron Award",
    "Roberto Clemente Award": "Roberto Clemente Award",
    "Comeback Player of the Year": "Comeback Player of the Year",
    "NLCS MVP": "NLCS MVP",
    "ALCS MVP": "ALCS MVP",
    "TSN Player of the Year": "TSN Player of the Year",
    "TSN Major League Player of the Year": "TSN Major League Player of the Year",
    "TSN Pitcher of the Year": "TSN Pitcher of the Year",
}


def awards_players_csv_path(base_dir: Path | str) -> Path:
    return Path(base_dir) / AWARDS_PLAYERS_FILENAME


def resolve_awards_base_dir() -> Path:
    """Best-effort app root containing AwardsPlayers.csv."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent, Path.cwd()):
        if awards_players_csv_path(candidate).is_file():
            return candidate
    return here


def awards_file_cache_key(base_dir: Path | str) -> float:
    path = awards_players_csv_path(base_dir)
    try:
        return float(path.stat().st_mtime) if path.exists() else 0.0
    except OSError:
        return 0.0


def awards_data_available(base_dir: Path | str) -> bool:
    path = awards_players_csv_path(base_dir)
    return path.is_file()


def awards_data_setup_message() -> str:
    return (
        f"Awards context requires Lahman `{AWARDS_PLAYERS_FILENAME}` in the app root "
        f"(same folder as `streamlit_app.py`). Until then, Hall of Fame Case Mode still works "
        f"but awards summaries will be unavailable."
    )


def load_awards_players_df(base_dir: Path | str) -> pd.DataFrame:
    """Load AwardsPlayers.csv; returns empty frame when missing or unreadable."""
    path = awards_players_csv_path(base_dir)
    if not path.is_file():
        return pd.DataFrame(columns=["playerID", "awardID", "yearID"])
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=["playerID", "awardID", "yearID"])
    rename: dict[str, str] = {}
    for col in df.columns:
        low = str(col).lower()
        if low == "playerid" and col != "playerID":
            rename[col] = "playerID"
        elif low == "awardid" and col != "awardID":
            rename[col] = "awardID"
        elif low == "yearid" and col != "yearID":
            rename[col] = "yearID"
    if rename:
        df = df.rename(columns=rename)
    if "playerID" not in df.columns:
        return pd.DataFrame(columns=["playerID", "awardID", "yearID"])
    df["playerID"] = df["playerID"].astype(str).str.strip()
    df = df[df["playerID"].ne("") & df["playerID"].ne("nan")]
    if "awardID" in df.columns:
        df["awardID"] = df["awardID"].astype(str).str.strip()
    if "yearID" in df.columns:
        df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce")
    return df


def award_display_name(award_id: str) -> str:
    return AWARD_DISPLAY_NAMES.get(str(award_id or "").strip(), str(award_id or "").strip())


def resolve_player_id(
    full_name: str,
    results_df: pd.DataFrame | None = None,
    *,
    player_col: str = "fullName",
    id_col: str = "playerID",
    fallback_df: pd.DataFrame | None = None,
) -> str | None:
    target = str(full_name or "").strip()
    if not target:
        return None
    for source in (results_df, fallback_df):
        if source is None or source.empty or player_col not in source.columns or id_col not in source.columns:
            continue
        match = source[source[player_col].astype(str).str.strip().eq(target)]
        if not match.empty:
            pid = str(match.iloc[0][id_col]).strip()
            if pid and pid != "nan":
                return pid
    return None


def _summarize_player_award_rows(rows: pd.DataFrame) -> dict[str, Any]:
    if rows is None or rows.empty or "awardID" not in rows.columns:
        return {
            "total_award_count": 0,
            "major_award_count": 0,
            "awards": [],
            "major_awards": [],
        }

    awards: list[dict[str, Any]] = []
    major_awards: list[dict[str, Any]] = []
    for award_id, group in rows.groupby("awardID", sort=False):
        award_name = str(award_id).strip()
        if not award_name:
            continue
        years = sorted(
            {
                int(y)
                for y in pd.to_numeric(group.get("yearID"), errors="coerce").dropna().astype(int).tolist()
            }
        )
        entry = {
            "award": award_name,
            "display_name": award_display_name(award_name),
            "count": int(len(group)),
            "years": years,
        }
        awards.append(entry)
        if award_name in MAJOR_AWARD_IDS:
            major_awards.append(entry)

    awards.sort(key=lambda x: (-int(x["count"]), x["display_name"]))
    major_awards.sort(key=lambda x: (-int(x["count"]), x["display_name"]))
    total = int(len(rows))
    major_total = int(sum(int(a["count"]) for a in major_awards))
    return {
        "total_award_count": total,
        "major_award_count": major_total,
        "awards": awards,
        "major_awards": major_awards,
    }


def build_target_awards_summary(
    player_id: str | None,
    awards_df: pd.DataFrame | None,
) -> dict[str, Any]:
    pid = str(player_id or "").strip()
    if awards_df is None or awards_df.empty:
        return {
            "data_available": False,
            "player_id": pid or None,
            "message": awards_data_setup_message(),
            "total_award_count": 0,
            "major_award_count": 0,
            "awards": [],
            "major_awards": [],
        }
    if not pid:
        return {
            "data_available": False,
            "player_id": None,
            "message": "Player ID not found for target player.",
            "total_award_count": 0,
            "major_award_count": 0,
            "awards": [],
            "major_awards": [],
        }
    rows = awards_df[awards_df["playerID"].astype(str).eq(pid)]
    summary = _summarize_player_award_rows(rows)
    return {
        "data_available": True,
        "player_id": pid,
        "message": None,
        **summary,
    }


def _cohort_award_counts(results_df: pd.DataFrame, awards_df: pd.DataFrame) -> pd.DataFrame:
    if results_df is None or results_df.empty or "playerID" not in results_df.columns:
        return pd.DataFrame(columns=["playerID", "fullName", "total_award_count", "major_award_count"])
    ids = results_df[["playerID", "fullName"]].drop_duplicates("playerID").copy()
    ids["playerID"] = ids["playerID"].astype(str).str.strip()
    if awards_df is None or awards_df.empty:
        ids["total_award_count"] = 0
        ids["major_award_count"] = 0
        return ids

    grouped = awards_df.groupby("playerID", as_index=False).agg(
        total_award_count=("awardID", "count"),
        major_award_count=("awardID", lambda s: int(sum(str(x).strip() in MAJOR_AWARD_IDS for x in s))),
    )
    grouped["playerID"] = grouped["playerID"].astype(str).str.strip()
    out = ids.merge(grouped, on="playerID", how="left")
    out["total_award_count"] = pd.to_numeric(out["total_award_count"], errors="coerce").fillna(0).astype(int)
    out["major_award_count"] = pd.to_numeric(out["major_award_count"], errors="coerce").fillna(0).astype(int)
    return out


def build_cohort_awards_summary(
    results_df: pd.DataFrame,
    awards_df: pd.DataFrame | None,
) -> dict[str, Any]:
    counts = _cohort_award_counts(results_df, awards_df if awards_df is not None else pd.DataFrame())
    cohort_size = int(len(counts))
    if awards_df is None or awards_df.empty:
        return {
            "data_available": False,
            "message": awards_data_setup_message(),
            "cohort_size": cohort_size,
            "average_award_count": 0.0,
            "median_award_count": 0,
            "average_major_award_count": 0.0,
            "median_major_award_count": 0,
            "per_player_counts": [],
        }

    totals = counts["total_award_count"].astype(int).tolist()
    majors = counts["major_award_count"].astype(int).tolist()
    per_player = [
        {
            "player_id": str(row["playerID"]),
            "player": str(row.get("fullName") or ""),
            "total_award_count": int(row["total_award_count"]),
            "major_award_count": int(row["major_award_count"]),
        }
        for _, row in counts.iterrows()
    ]
    return {
        "data_available": True,
        "message": None,
        "cohort_size": cohort_size,
        "average_award_count": round(float(statistics.mean(totals)), 1) if totals else 0.0,
        "median_award_count": round(float(statistics.median(totals)), 1) if totals else 0.0,
        "average_major_award_count": round(float(statistics.mean(majors)), 1) if majors else 0.0,
        "median_major_award_count": round(float(statistics.median(majors)), 1) if majors else 0.0,
        "per_player_counts": per_player,
    }


def build_target_award_rank(
    target_player_id: str | None,
    cohort_counts: pd.DataFrame,
) -> dict[str, Any]:
    pid = str(target_player_id or "").strip()
    size = int(len(cohort_counts))
    empty = {
        "data_available": False,
        "cohort_size": size,
        "rank_by_total_awards": None,
        "rank_by_major_awards": None,
        "target_total_awards": 0,
        "target_major_awards": 0,
    }
    if not pid or cohort_counts.empty:
        return empty

    match = cohort_counts[cohort_counts["playerID"].astype(str).eq(pid)]
    if match.empty:
        return empty

    target_total = int(match.iloc[0]["total_award_count"])
    target_major = int(match.iloc[0]["major_award_count"])
    ranked_total = cohort_counts.sort_values(
        ["total_award_count", "fullName"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    ranked_major = cohort_counts.sort_values(
        ["major_award_count", "fullName"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)

    rank_total = int(ranked_total.index[ranked_total["playerID"].astype(str).eq(pid)][0]) + 1
    rank_major = int(ranked_major.index[ranked_major["playerID"].astype(str).eq(pid)][0]) + 1
    return {
        "data_available": True,
        "cohort_size": size,
        "rank_by_total_awards": rank_total,
        "rank_by_major_awards": rank_major,
        "target_total_awards": target_total,
        "target_major_awards": target_major,
    }


def build_cohort_award_comparison(
    target_player_id: str | None,
    cohort_summary: dict[str, Any],
    cohort_counts: pd.DataFrame,
) -> dict[str, Any]:
    pid = str(target_player_id or "").strip()
    if not cohort_summary.get("data_available") or not pid or cohort_counts.empty:
        return {
            "data_available": False,
            "message": cohort_summary.get("message") or "Awards comparison unavailable.",
        }

    match = cohort_counts[cohort_counts["playerID"].astype(str).eq(pid)]
    if match.empty:
        return {
            "data_available": False,
            "message": "Target player is not in the cohort award table.",
        }

    target_total = int(match.iloc[0]["total_award_count"])
    target_major = int(match.iloc[0]["major_award_count"])
    totals = cohort_counts["total_award_count"].astype(int)
    majors = cohort_counts["major_award_count"].astype(int)
    return {
        "data_available": True,
        "message": None,
        "target_total_awards": target_total,
        "target_major_awards": target_major,
        "cohort_average_total_awards": cohort_summary.get("average_award_count", 0.0),
        "cohort_median_total_awards": cohort_summary.get("median_award_count", 0),
        "cohort_average_major_awards": cohort_summary.get("average_major_award_count", 0.0),
        "cohort_median_major_awards": cohort_summary.get("median_major_award_count", 0),
        "players_with_more_total_awards": int((totals > target_total).sum()),
        "players_with_fewer_total_awards": int((totals < target_total).sum()),
        "players_with_same_total_awards": int((totals == target_total).sum()),
        "players_with_more_major_awards": int((majors > target_major).sum()),
        "players_with_fewer_major_awards": int((majors < target_major).sum()),
        "players_with_same_major_awards": int((majors == target_major).sum()),
    }


def build_hof_case_awards_context(
    target_player: str,
    results_df: pd.DataFrame,
    awards_df: pd.DataFrame | None,
    *,
    fallback_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Award summaries for Hall of Fame Case packet and UI."""
    target_id = resolve_player_id(target_player, results_df, fallback_df=fallback_df)
    cohort_counts = _cohort_award_counts(results_df, awards_df if awards_df is not None else pd.DataFrame())
    cohort_summary = build_cohort_awards_summary(results_df, awards_df)
    target_summary = build_target_awards_summary(target_id, awards_df)
    target_rank = build_target_award_rank(target_id, cohort_counts)
    comparison = build_cohort_award_comparison(target_id, cohort_summary, cohort_counts)
    return {
        "target_awards_summary": target_summary,
        "cohort_awards_summary": cohort_summary,
        "target_award_rank": target_rank,
        "cohort_award_comparison": comparison,
    }


def format_target_awards_summary_text(summary: dict[str, Any], *, player_name: str = "") -> str | None:
    if not summary.get("data_available"):
        return None
    header = f"Awards — {player_name}:" if player_name else "Target player awards:"
    lines = [header]
    major = summary.get("major_awards") or []
    if major:
        for aw in major[:10]:
            years = aw.get("years") or []
            year_text = f" ({', '.join(str(y) for y in years)})" if years and len(years) <= 6 else ""
            if years and len(years) > 6:
                year_text = f" ({years[0]}–{years[-1]})"
            lines.append(f"- {aw.get('display_name', aw.get('award'))}: {aw.get('count')}{year_text}")
    else:
        lines.append("- No major awards listed in AwardsPlayers.csv")
    lines.append(
        f"Total awards: {summary.get('total_award_count', 0)} · "
        f"Major awards: {summary.get('major_award_count', 0)}"
    )
    return "\n".join(lines)


def format_cohort_awards_summary_text(
    cohort_summary: dict[str, Any],
    comparison: dict[str, Any],
    target_rank: dict[str, Any],
) -> str | None:
    if not cohort_summary.get("data_available"):
        return None
    lines = [
        "Awards in cohort:",
        (
            f"Avg {cohort_summary.get('average_award_count', 0)} total awards per player "
            f"(median {cohort_summary.get('median_award_count', 0)}); "
            f"avg {cohort_summary.get('average_major_award_count', 0)} major awards "
            f"(median {cohort_summary.get('median_major_award_count', 0)})."
        ),
    ]
    if comparison.get("data_available"):
        lines.append(
            f"Target: {comparison.get('target_total_awards', 0)} total awards "
            f"(rank #{target_rank.get('rank_by_total_awards', '—')} in cohort); "
            f"{comparison.get('players_with_more_total_awards', 0)} players have more, "
            f"{comparison.get('players_with_fewer_total_awards', 0)} have fewer."
        )
        lines.append(
            f"Target major awards: {comparison.get('target_major_awards', 0)} "
            f"(rank #{target_rank.get('rank_by_major_awards', '—')}); "
            f"{comparison.get('players_with_more_major_awards', 0)} players have more major awards."
        )
    return "\n".join(lines)
