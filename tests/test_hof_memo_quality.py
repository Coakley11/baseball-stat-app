"""HOF memo wording, milestone totals, and stale-memo recompose tests."""

from __future__ import annotations

import re
import unittest

import pandas as pd

from hall_of_fame_data import CASE_SCORE_LABEL, build_hof_case_packet
from hof_case_analysis import (
    MEMO_QUALITY_VERSION,
    _build_career_total_evidence,
    _exclude_duplicate_bullets,
    _filter_position_peers,
    _highest_milestone_line,
    compose_hof_statistical_case,
    format_hof_case_memo_markdown,
    resolve_hof_case_analysis,
)


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip().rstrip(".")


def _palmeiro_packet() -> dict:
    return {
        "target_player": "Rafael Palmeiro",
        "primary_position": "1B",
        "sort_stat": "HR",
        "target_rank": 10,
        "total_players_returned": 87,
        "hall_of_famers_returned": 43,
        "hall_of_fame_rate_pct": 49.4,
        "cohort_strength_stats": ["HR", "H", "RBI", "2B", "G"],
        "cohort_weakness_stats": [],
        "target_career_stats": {"HR": 569, "H": 3020, "RBI": 1834, "2B": 585, "G": 2831, "AB": 10472, "R": 1663},
        "target_cohort_ranks": {
            "HR": {"rank": 10, "of": 87, "stat": "HR", "value": 569, "percentile_top": 90, "tier": "top 10%"},
        },
        "position_percentiles": {
            "G": {"percentile_top": 95, "tier": "top 5%"},
            "H": {"percentile_top": 92, "tier": "top 10%"},
            "R": {"percentile_top": 92, "tier": "top 10%"},
            "2B": {"percentile_top": 90, "tier": "top 10%"},
        },
        "position_stat_ranks": {
            "G": {"rank": 20, "of": 7679, "value": 162},
            "H": {"rank": 55, "of": 7679, "value": 203},
            "R": {"rank": 55, "of": 7679, "value": 124},
            "2B": {"rank": 26, "of": 7679, "value": 49},
        },
        "comparable_players": {
            "hall_of_famers": [
                {"fullName": "Frank Thomas", "careerPrimaryPos": "1B", "HR": 521},
                {"fullName": "Ken Griffey Jr.", "careerPrimaryPos": "OF", "HR": 630},
            ],
            "non_hall_of_famers": [
                {"fullName": "Miguel Cabrera", "careerPrimaryPos": "1B", "HR": 507},
            ],
        },
        "filters_used": {"sort_stat": "HR", "stat_minimums": {"HR": 300, "R": 0, "OPS": 0.0}},
        "cohort_selectivity": {"selectivity": "selective"},
    }


class HofMemoQualityTests(unittest.TestCase):
    def test_highest_milestone_569_hr_not_400_and_500(self) -> None:
        line = _highest_milestone_line("HR", 569)
        self.assertIn("569", line or "")
        self.assertIn("500-HR", line or "")
        self.assertNotIn("400", line or "")

    def test_highest_milestone_3020_hits(self) -> None:
        line = _highest_milestone_line("H", 3020)
        self.assertIn("3,020", line or "")
        self.assertIn("3,000-hit", line or "")
        self.assertNotIn("2,500", line or "")

    def test_highest_milestone_1834_rbi(self) -> None:
        line = _highest_milestone_line("RBI", 1834)
        self.assertIn("1,834", line or "")
        self.assertIn("1,500-RBI", line or "")
        self.assertNotIn("1,000", line or "")

    def test_highest_milestone_585_doubles(self) -> None:
        line = _highest_milestone_line("2B", 585)
        self.assertIn("585", line or "")
        self.assertIn("500-double", line or "")
        self.assertNotIn("400-double", line or "")

    def test_career_total_evidence_uses_actual_totals(self) -> None:
        lines = _build_career_total_evidence(_palmeiro_packet())
        joined = " ".join(lines)
        self.assertIn("569", joined)
        self.assertIn("3,020", joined)
        self.assertNotIn("500 home runs", joined)
        self.assertNotIn("400 home runs", joined)

    def test_no_duplicate_strongest_and_supporting(self) -> None:
        analysis = compose_hof_statistical_case(_palmeiro_packet())
        memo = analysis.get("case_memo") or {}
        strongest = [str(x) for x in (memo.get("strongest_evidence") or [])]
        supporting = [str(x) for x in (memo.get("case_evidence") or [])]
        for line in supporting:
            key = _normalize_key(line)
            self.assertNotIn(key, {_normalize_key(x) for x in strongest})

    def test_position_peer_language(self) -> None:
        analysis = compose_hof_statistical_case(_palmeiro_packet())
        memo = analysis.get("case_memo") or {}
        pos_text = " ".join(memo.get("position_era_context") or [])
        self.assertIn("Frank Thomas", pos_text)
        self.assertNotIn("Ken Griffey", pos_text)
        comp_text = " ".join(str(x) for x in (memo.get("comparison_notes") or []))
        self.assertIn("Broader Hall of Fame", comp_text)
        self.assertIn("not-yet-inducted", comp_text.lower())

    def test_position_relative_uses_career_totals_not_rank_values(self) -> None:
        analysis = compose_hof_statistical_case(_palmeiro_packet())
        memo = analysis.get("case_memo") or {}
        pos_text = " ".join(memo.get("position_era_context") or [])
        self.assertIn("2,831", pos_text)
        self.assertIn("3,020", pos_text)
        self.assertIn("1,663", pos_text)
        self.assertIn("585", pos_text)
        self.assertIn("#20", pos_text)
        self.assertIn("#55", pos_text)
        self.assertIn("#26", pos_text)
        self.assertNotIn("(162;", pos_text)
        self.assertNotIn("(203;", pos_text)
        self.assertNotIn("(124;", pos_text)
        self.assertNotIn("(49;", pos_text)

    def test_stale_blob_forces_recompose(self) -> None:
        packet = _palmeiro_packet()
        stale_verdict = {
            "case_memo": {
                "verdict": "Solid",
                "thesis": "old thesis",
                "strongest_evidence": ["500 home runs"],
                "final_takeaway": "old",
            }
        }
        analysis = resolve_hof_case_analysis(packet, stale_verdict)
        memo = analysis.get("case_memo") or {}
        self.assertEqual(memo.get("memo_quality_version"), MEMO_QUALITY_VERSION)
        self.assertIn("569", " ".join(memo.get("strongest_evidence") or []))

    def test_compose_from_real_packet_has_quality_marker(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Rafael Palmeiro", "isHallOfFamer": False, "careerPrimaryPos": "1B", "HR": 569, "H": 3020, "RBI": 1834, "2B": 585, "G": 2831},
                {"fullName": "Frank Thomas", "isHallOfFamer": True, "careerPrimaryPos": "1B", "HR": 521},
            ]
        )
        packet = build_hof_case_packet(
            "Rafael Palmeiro",
            df,
            filters_summary={"sort_stat": "HR", "stat_minimums": {"HR": 300, "R": 0, "OPS": 0.0}},
            sort_stat="HR",
            position_universe_df=df,
        )
        analysis = compose_hof_statistical_case(packet)
        md = format_hof_case_memo_markdown(analysis)
        self.assertIn(MEMO_QUALITY_VERSION, str((analysis.get("case_memo") or {}).get("memo_quality_version")))
        self.assertIn(CASE_SCORE_LABEL, md)


if __name__ == "__main__":
    unittest.main()
