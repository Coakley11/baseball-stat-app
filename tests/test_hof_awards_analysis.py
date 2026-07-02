"""Hall of Fame awards integration in case memo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from awards_players_data import load_awards_players_df
from hall_of_fame_data import build_hof_case_packet
from hof_case_analysis import compose_hof_statistical_case, format_hof_case_memo_markdown


def _sample_awards_csv() -> str:
    return """playerID,awardID,yearID,lgID,tie,notes
troutmi01,Most Valuable Player,2014,AL,,
troutmi01,Most Valuable Player,2016,AL,,
troutmi01,Most Valuable Player,2019,AL,,
troutmi01,Silver Slugger,2012,AL,,
bondsba01,Most Valuable Player,1990,NL,,
bondsba01,Most Valuable Player,1992,NL,,
"""


class HofAwardsAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp())
        (self.base / "AwardsPlayers.csv").write_text(_sample_awards_csv(), encoding="utf-8")
        self.awards_df = load_awards_players_df(self.base)

    def test_compose_includes_awards_analysis_section(self) -> None:
        cohort = pd.DataFrame(
            [
                {"fullName": "Mike Trout", "playerID": "troutmi01", "isHallOfFamer": False, "HR": 500, "careerPrimaryPos": "OF"},
                {"fullName": "Barry Bonds", "playerID": "bondsba01", "isHallOfFamer": False, "HR": 762, "careerPrimaryPos": "OF"},
            ]
        )
        packet = build_hof_case_packet(
            "Mike Trout",
            cohort,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            awards_df=self.awards_df,
            position_universe_df=cohort,
        )
        analysis = compose_hof_statistical_case(packet)
        memo = analysis.get("case_memo") or {}
        awards_lines = memo.get("awards_analysis") or []
        self.assertTrue(awards_lines)
        self.assertTrue(any("major award" in str(x).lower() for x in awards_lines))
        md = format_hof_case_memo_markdown(analysis)
        self.assertIn("#### Awards & accolades", md)
        self.assertIn("MVP", md)

    def test_thesis_weaves_awards_clause(self) -> None:
        cohort = pd.DataFrame(
            [
                {"fullName": "Mike Trout", "playerID": "troutmi01", "isHallOfFamer": False, "HR": 500, "careerPrimaryPos": "OF"},
            ]
        )
        packet = build_hof_case_packet(
            "Mike Trout",
            cohort,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            awards_df=self.awards_df,
            position_universe_df=cohort,
        )
        analysis = compose_hof_statistical_case(packet)
        thesis = str(analysis.get("thesis") or "").lower()
        self.assertIn("award", thesis)

    def test_packet_includes_player_photo_on_identity(self) -> None:
        cohort = pd.DataFrame(
            [
                {"fullName": "Mike Trout", "playerID": "troutmi01", "isHallOfFamer": False, "HR": 500, "careerPrimaryPos": "OF"},
            ]
        )
        packet = build_hof_case_packet(
            "Mike Trout",
            cohort,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            awards_df=self.awards_df,
            position_universe_df=cohort,
        )
        identity = packet.get("target_identity") or {}
        photo = identity.get("player_photo") or {}
        self.assertIn("headshot_url", photo)
        self.assertTrue(photo.get("has_photo"), photo)
        self.assertEqual(photo.get("mlbam_id"), 545361)


if __name__ == "__main__":
    unittest.main()
