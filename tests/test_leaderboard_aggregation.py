"""Leaderboard career aggregation must group by playerID, not name alone."""

from __future__ import annotations

import unittest

import pandas as pd

from leaderboard_aggregation import (
    aggregate_leaderboard_career_totals,
    build_leaderboard_aggregation_diagnostics,
    build_leaderboard_summary,
    filter_yearly_for_leaderboards,
)


def _griffey_fixture() -> pd.DataFrame:
    rows = []
    for pid, hrs in (("griffke02", 630), ("griffke01", 152)):
        rows.append(
            {
                "playerID": pid,
                "fullName": "Ken Griffey",
                "bats": "L",
                "yearID": 1990,
                "R": 100,
                "AB": 500,
                "H": 2781 if pid == "griffke02" else 2143,
                "2B": 200,
                "3B": 10,
                "HR": hrs,
                "RBI": 500,
                "SB": 50,
                "BB": 200,
                "HBP": 5,
                "SF": 5,
            }
        )
    return pd.DataFrame(rows)


class LeaderboardAggregationTests(unittest.TestCase):
    def test_groups_by_player_id_not_name_only(self) -> None:
        yearly = _griffey_fixture()
        filtered = filter_yearly_for_leaderboards(yearly, (1980, 2000))
        leaderboard = aggregate_leaderboard_career_totals(filtered)
        self.assertEqual(len(leaderboard), 2)
        by_id = leaderboard.set_index("playerID")
        self.assertEqual(int(by_id.loc["griffke02", "HR"]), 630)
        self.assertEqual(int(by_id.loc["griffke01", "HR"]), 152)
        self.assertEqual(int(by_id.loc["griffke02", "H"]), 2781)

    def test_name_only_groupby_would_inflate_griffey(self) -> None:
        yearly = _griffey_fixture()
        filtered = filter_yearly_for_leaderboards(yearly, (1980, 2000))
        wrong = filtered.groupby(["fullName", "bats"], as_index=False)[["H", "HR"]].sum()
        self.assertEqual(int(wrong.iloc[0]["H"]), 4924)
        self.assertEqual(int(wrong.iloc[0]["HR"]), 782)

    def test_diagnostics_flag_ambiguous_names(self) -> None:
        yearly = _griffey_fixture()
        filtered = filter_yearly_for_leaderboards(yearly, (1980, 2000))
        leaderboard = aggregate_leaderboard_career_totals(filtered)
        diag = build_leaderboard_aggregation_diagnostics(filtered, leaderboard, year_range=(1980, 2000))
        self.assertEqual(diag["ambiguous_fullName_bats_groups"], 1)
        self.assertEqual(diag["leaderboard_rows"], 2)
        self.assertEqual(diag["distinct_player_ids_in_source"], 2)

    def test_leaderboard_summary_tracks_sort_category(self) -> None:
        leaderboard = pd.DataFrame(
            [
                {"fullName": "Player A", "HR": 500, "score": 88.5},
                {"fullName": "Player B", "HR": 762, "score": 94.2},
            ]
        )
        summary = build_leaderboard_summary(leaderboard, sort_stat="HR", displayed_count=2)
        self.assertEqual(summary["highest_score"], "Player B — 94.2")
        self.assertEqual(summary["category_leader_label"], "Home Run Leader")
        self.assertEqual(summary["category_leader"], "Player B — 762")
        self.assertEqual(summary["players_displayed"], "2")


if __name__ == "__main__":
    unittest.main()
