"""Career offensive leaderboard aggregation from yearly Lahman rows."""

from __future__ import annotations

from typing import Any

import pandas as pd

LEADERBOARD_COUNTING_COLS = (
    "R",
    "AB",
    "H",
    "2B",
    "3B",
    "HR",
    "RBI",
    "SB",
    "BB",
    "HBP",
    "SF",
)

LEADERBOARD_GROUPBY_COLS = ("playerID", "fullName", "bats")

LEADERBOARD_CATEGORY_LEADER_LABELS: dict[str, str] = {
    "score": "Score Leader",
    "HR": "Home Run Leader",
    "H": "Hit Leader",
    "RBI": "RBI Leader",
    "R": "Run Leader",
    "2B": "Doubles Leader",
    "3B": "Triples Leader",
    "SB": "Stolen Base Leader",
    "BB": "Walk Leader",
    "BA": "Batting Average Leader",
    "OBP": "OBP Leader",
    "SLG": "SLG Leader",
    "OPS": "OPS Leader",
    "AB": "At Bat Leader",
}

RATE_LEADERBOARD_STATS = frozenset({"BA", "OBP", "SLG", "OPS"})


def filter_yearly_for_leaderboards(
    yearly_df: pd.DataFrame,
    year_range: tuple[int, int] | list[int],
) -> pd.DataFrame:
    lo, hi = int(year_range[0]), int(year_range[1])
    return yearly_df[(yearly_df["yearID"] >= lo) & (yearly_df["yearID"] <= hi)].copy()


def aggregate_leaderboard_career_totals(filtered_leaders: pd.DataFrame) -> pd.DataFrame:
    """One row per playerID (same grouping as Career Totals page)."""
    cols = [c for c in LEADERBOARD_COUNTING_COLS if c in filtered_leaders.columns]
    return filtered_leaders.groupby(list(LEADERBOARD_GROUPBY_COLS), as_index=False)[cols].sum()


def leaderboard_category_leader_label(sort_stat: str) -> str:
    return LEADERBOARD_CATEGORY_LEADER_LABELS.get(str(sort_stat or "").strip(), f"{sort_stat} Leader")


def build_leaderboard_summary(
    leaderboard: pd.DataFrame,
    *,
    sort_stat: str,
    displayed_count: int,
) -> dict[str, str]:
    """Summary card values for the current filtered leaderboard view."""
    out = {
        "highest_score": "N/A",
        "category_leader": "N/A",
        "category_leader_label": leaderboard_category_leader_label(sort_stat),
        "players_displayed": str(int(displayed_count)),
    }
    if leaderboard is None or leaderboard.empty:
        return out

    if "score" in leaderboard.columns:
        top_score = leaderboard.sort_values("score", ascending=False, na_position="last").iloc[0]
        score_val = pd.to_numeric(top_score.get("score"), errors="coerce")
        if pd.notna(score_val):
            out["highest_score"] = f"{top_score.get('fullName', 'N/A')} — {float(score_val):.1f}"

    if sort_stat in leaderboard.columns:
        top_cat = leaderboard.sort_values(sort_stat, ascending=False, na_position="last").iloc[0]
        cat_val = pd.to_numeric(top_cat.get(sort_stat), errors="coerce")
        if pd.notna(cat_val):
            if sort_stat in RATE_LEADERBOARD_STATS:
                formatted = f"{float(cat_val):.3f}"
            elif sort_stat == "score":
                formatted = f"{float(cat_val):.1f}"
            else:
                formatted = f"{int(round(float(cat_val))):,}"
            out["category_leader"] = f"{top_cat.get('fullName', 'N/A')} — {formatted}"

    return out


def build_leaderboard_aggregation_diagnostics(
    filtered_leaders: pd.DataFrame,
    leaderboard: pd.DataFrame,
    *,
    year_range: tuple[int, int] | list[int],
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "year_range": [int(year_range[0]), int(year_range[1])],
        "aggregation_method": "groupby(playerID, fullName, bats).sum()",
        "groupby_keys": list(LEADERBOARD_GROUPBY_COLS),
        "source_yearly_rows": int(len(filtered_leaders)),
        "leaderboard_rows": int(len(leaderboard)),
    }
    if "playerID" in filtered_leaders.columns:
        diag["distinct_player_ids_in_source"] = int(filtered_leaders["playerID"].nunique())
    if {"fullName", "bats", "playerID"}.issubset(filtered_leaders.columns):
        name_groups = (
            filtered_leaders.groupby(["fullName", "bats"], dropna=False)["playerID"]
            .nunique()
            .reset_index(name="player_count")
        )
        ambiguous = name_groups[name_groups["player_count"] > 1]
        diag["ambiguous_fullName_bats_groups"] = int(len(ambiguous))
        if not ambiguous.empty:
            diag["ambiguous_name_examples"] = [
                {
                    "fullName": str(row["fullName"]),
                    "bats": str(row["bats"]),
                    "player_count": int(row["player_count"]),
                }
                for _, row in ambiguous.head(10).iterrows()
            ]
    if {"playerID", "fullName"}.issubset(leaderboard.columns):
        dup_ids = leaderboard.groupby("playerID")["fullName"].nunique()
        multi_name = dup_ids[dup_ids > 1]
        diag["duplicate_player_id_rows"] = int((leaderboard["playerID"].duplicated()).sum())
        diag["player_ids_with_multiple_names"] = int(len(multi_name))
    return diag
