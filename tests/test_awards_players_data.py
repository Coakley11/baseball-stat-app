"""Tests for AwardsPlayers.csv summaries in Hall of Fame Case Mode."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from awards_players_data import (
    build_cohort_award_comparison,
    build_cohort_awards_summary,
    build_hof_case_awards_context,
    build_target_award_rank,
    build_target_awards_summary,
    load_awards_players_df,
)
from hall_of_fame_data import build_hof_case_packet


def _sample_awards_csv() -> str:
    return """playerID,awardID,yearID,lgID,tie,notes
troutmi01,Most Valuable Player,2014,AL,,
troutmi01,Most Valuable Player,2016,AL,,
troutmi01,Silver Slugger,2012,AL,,OF
troutmi01,Rookie of the Year,2012,AL,,
ruthba01,Most Valuable Player,1923,AL,,
ruthba01,Most Valuable Player,1927,AL,,
ruthba01,Gold Glove,1928,AL,,RF
"""


class AwardsPlayersDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "AwardsPlayers.csv").write_text(_sample_awards_csv(), encoding="utf-8")
        self.awards_df = load_awards_players_df(self.base)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_target_awards_summary_counts(self) -> None:
        summary = build_target_awards_summary("troutmi01", self.awards_df)
        self.assertTrue(summary["data_available"])
        self.assertEqual(summary["total_award_count"], 4)
        self.assertEqual(summary["major_award_count"], 4)
        mvp = next(a for a in summary["major_awards"] if a["display_name"] == "MVP")
        self.assertEqual(mvp["count"], 2)
        self.assertEqual(mvp["years"], [2014, 2016])

    def test_cohort_awards_summary_and_rank(self) -> None:
        cohort = pd.DataFrame(
            [
                {"playerID": "troutmi01", "fullName": "Mike Trout", "HR": 310, "isHallOfFamer": False},
                {"playerID": "ruthba01", "fullName": "Babe Ruth", "HR": 714, "isHallOfFamer": True},
            ]
        )
        cohort_summary = build_cohort_awards_summary(cohort, self.awards_df)
        self.assertTrue(cohort_summary["data_available"])
        self.assertEqual(cohort_summary["cohort_size"], 2)
        self.assertEqual(cohort_summary["average_award_count"], 3.5)
        self.assertEqual(cohort_summary["median_award_count"], 3.5)

        counts = pd.DataFrame(
            [
                {"playerID": "troutmi01", "fullName": "Mike Trout", "total_award_count": 4, "major_award_count": 4},
                {"playerID": "ruthba01", "fullName": "Babe Ruth", "total_award_count": 3, "major_award_count": 3},
            ]
        )
        rank = build_target_award_rank("troutmi01", counts)
        self.assertEqual(rank["rank_by_total_awards"], 1)
        self.assertEqual(rank["target_total_awards"], 4)

        comparison = build_cohort_award_comparison("troutmi01", cohort_summary, counts)
        self.assertEqual(comparison["players_with_more_total_awards"], 0)
        self.assertEqual(comparison["players_with_fewer_total_awards"], 1)

    def test_hof_case_packet_includes_awards_fields(self) -> None:
        cohort = pd.DataFrame(
            [
                {"playerID": "troutmi01", "fullName": "Mike Trout", "HR": 310, "isHallOfFamer": False},
                {"playerID": "ruthba01", "fullName": "Babe Ruth", "HR": 714, "isHallOfFamer": True},
            ]
        )
        packet = build_hof_case_packet(
            "Mike Trout",
            cohort,
            filters_summary={},
            sort_stat="HR",
            awards_df=self.awards_df,
        )
        self.assertIn("target_awards_summary", packet)
        self.assertIn("cohort_awards_summary", packet)
        self.assertIn("target_award_rank", packet)
        self.assertIn("cohort_award_comparison", packet)
        self.assertTrue(packet["target_awards_summary"]["data_available"])
        self.assertEqual(packet["target_awards_summary"]["major_award_count"], 4)
        self.assertEqual(packet["cohort_award_comparison"]["target_total_awards"], 4)

    def test_missing_awards_file_is_graceful(self) -> None:
        empty_base = Path(self.tmp.name) / "missing"
        empty_base.mkdir()
        summary = build_target_awards_summary("troutmi01", load_awards_players_df(empty_base))
        self.assertFalse(summary["data_available"])
        cohort = pd.DataFrame([{"playerID": "troutmi01", "fullName": "Mike Trout", "HR": 310}])
        packet = build_hof_case_packet(
            "Mike Trout",
            cohort,
            filters_summary={},
            sort_stat="HR",
            awards_df=load_awards_players_df(empty_base),
        )
        self.assertFalse(packet["target_awards_summary"]["data_available"])
        self.assertEqual(packet["total_players_returned"], 1)


if __name__ == "__main__":
    unittest.main()
