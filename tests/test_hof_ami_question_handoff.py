"""Regression tests for HOF AMI question vs conclusion separation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from applied_math_return_insight import _insight_card_conclusion, _insight_card_question
from awards_players_data import load_awards_players_df
from hall_of_fame_data import (
    CASE_SCORE_LABEL,
    build_hof_ami_payload,
    build_hof_case_ami_prompt,
    build_hof_case_display_question,
    build_hof_case_insight_record,
    build_hof_case_packet,
    hof_case_disclaimer_text,
    is_hof_ami_internal_prompt,
)
from hof_case_analysis import (
    compose_hof_statistical_case,
    format_hof_case_memo_markdown,
    render_hof_case_full_analysis,
    resolve_hof_case_analysis,
)
from suite_analytical_question import submit_analytical_question


def _sample_awards_csv() -> str:
    return """playerID,awardID,yearID,lgID,tie,notes
harpebr03,Most Valuable Player,2015,NL,,
harpebr03,Most Valuable Player,2021,NL,,
harpebr03,Silver Slugger,2015,NL,,
harpebr03,Silver Slugger,2016,NL,,
harpebr03,Silver Slugger,2018,NL,,
harpebr03,Silver Slugger,2019,NL,,
harpebr03,Hank Aaron Award,2015,NL,,
harpebr03,Hank Aaron Award,2021,NL,,
harpebr03,Rookie of the Year,2012,NL,,
harpebr03,NLCS MVP,2019,NL,,
"""


class HofAmiQuestionHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp())
        (self.base / "AwardsPlayers.csv").write_text(_sample_awards_csv(), encoding="utf-8")
        self.awards_df = load_awards_players_df(self.base)
        self.cohort = pd.DataFrame(
            [
                {
                    "fullName": "Bryce Harper",
                    "playerID": "harpebr03",
                    "isHallOfFamer": False,
                    "HR": 350,
                    "OBP": 0.390,
                    "careerPrimaryPos": "OF",
                },
                {
                    "fullName": "Mike Trout",
                    "playerID": "troutmi01",
                    "isHallOfFamer": False,
                    "HR": 500,
                    "careerPrimaryPos": "OF",
                },
            ]
        )

    def _harper_packet(self) -> dict:
        return build_hof_case_packet(
            "Bryce Harper",
            self.cohort,
            filters_summary={"sort_stat": "OBP"},
            sort_stat="OBP",
            awards_df=self.awards_df,
            position_universe_df=self.cohort,
        )

    def test_display_question_is_interrogative_and_distinct_from_conclusion(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        insight = build_hof_case_insight_record(
            packet,
            question=display_q,
            question_id="q-harper",
        )
        conclusion = str(insight.get("conclusion") or "")
        question = _insight_card_question(insight)
        self.assertIn("?", question)
        self.assertIn("Bryce Harper", question)
        self.assertIn("statistical Hall of Fame case", conclusion)
        self.assertNotEqual(question.strip(), conclusion.strip())
        self.assertNotEqual(question.strip(), _insight_card_conclusion(insight).strip())

    def test_ami_payload_separates_question_prompt_and_conclusion(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        ami_prompt = build_hof_case_ami_prompt("Bryce Harper", packet)
        insight = build_hof_case_insight_record(packet, question=display_q, question_id="q-harper")
        blob = build_hof_ami_payload(
            packet=packet,
            question=display_q,
            ami_prompt=ami_prompt,
            question_id="q-harper",
            action_url="https://example.test/hof",
            insight=insight,
        )
        self.assertEqual(blob.get("question"), display_q)
        self.assertIn("?", str(blob.get("question") or ""))
        self.assertIn(CASE_SCORE_LABEL, str(blob.get("ami_prompt") or ""))
        thesis = str((blob.get("verdict_context") or {}).get("thesis") or insight.get("conclusion") or "")
        self.assertIn("statistical Hall of Fame case", thesis)
        self.assertNotEqual(str(blob.get("question") or "").strip(), thesis.strip())

    def test_full_hof_case_render_includes_awards_section(self) -> None:
        packet = self._harper_packet()
        st = MagicMock()
        markdown_calls: list[str] = []

        def _capture_md(text: str, **kwargs) -> None:
            markdown_calls.append(str(text))

        st.markdown = _capture_md
        st.caption = lambda *args, **kwargs: None
        self.assertTrue(render_hof_case_full_analysis(st, packet))
        joined = "\n".join(markdown_calls)
        self.assertIn("Awards & accolades", joined)
        self.assertIn("major award", joined.lower())

    def test_internal_prompt_is_detected_and_rejected_as_question(self) -> None:
        packet = self._harper_packet()
        ami_prompt = build_hof_case_ami_prompt("Bryce Harper", packet)
        self.assertTrue(is_hof_ami_internal_prompt(ami_prompt))
        self.assertIn("hof_case_packet", ami_prompt)
        insight = build_hof_case_insight_record(
            packet,
            question=ami_prompt,
            question_id="q-harper-bad",
            ami_prompt=ami_prompt,
        )
        question = _insight_card_question(insight)
        self.assertNotIn("hof_case_packet", question)
        self.assertNotIn("Respond with one of", question)
        self.assertIn("?", question)

    def test_submit_normalizes_internal_prompt_to_display_question(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        ami_prompt = build_hof_case_ami_prompt("Bryce Harper", packet)
        result = submit_analytical_question(
            source_app="baseball",
            source_page="Career Totals",
            question=ami_prompt,
            context={
                "display_question": display_q,
                "ami_prompt": ami_prompt,
                "hof_case_packet": packet,
                "routing_hint": "hof_case_analysis",
            },
            quant_area="hall_of_fame_case",
        )
        self.assertEqual(result.get("question"), display_q)
        self.assertIn(CASE_SCORE_LABEL, str(result.get("ami_prompt") or ""))
        self.assertNotEqual(result.get("question"), ami_prompt)

    def test_insight_uses_cohort_confidence_label(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        insight = build_hof_case_insight_record(packet, question=display_q, question_id="q-harper")
        self.assertIn("cohort_confidence", insight)
        self.assertIn("Cohort filter confidence", str(insight.get("confidence_label") or ""))

    def test_disclaimer_mentions_awards_only_when_awards_exist(self) -> None:
        packet = self._harper_packet()
        with_awards = hof_case_disclaimer_text(packet)
        without_awards = hof_case_disclaimer_text({"target_awards_summary": {"data_available": False}})
        self.assertIn("awards evidence", with_awards)
        self.assertNotIn("awards evidence", without_awards)

    def test_full_report_and_insight_share_verdict_bucket(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        insight = build_hof_case_insight_record(packet, question=display_q, question_id="q-harper")
        resolved = resolve_hof_case_analysis(packet)
        method_bucket = str(insight.get("method") or "").split("—")[-1].strip()
        self.assertEqual(method_bucket, str(resolved.get("verdict_bucket") or ""))

    def test_resolve_prefers_packet_analysis_over_stale_verdict(self) -> None:
        packet = self._harper_packet()
        fresh = compose_hof_statistical_case(packet)
        stale_verdict = {
            "verdict_bucket": "Solid",
            "thesis": "Stale thesis.",
            "case_memo": {
                "memo_quality_version": "hof_memo_quality_v3",
                "verdict": "Solid",
                "thesis": "Stale thesis.",
                "strongest_evidence": ["Old evidence only."],
            },
        }
        resolved = resolve_hof_case_analysis(packet, stale_verdict)
        self.assertEqual(resolved.get("verdict_bucket"), fresh.get("verdict_bucket"))
        memo = format_hof_case_memo_markdown(resolved)
        self.assertIn("Awards & accolades", memo)
        self.assertEqual(
            str((resolved.get("case_memo") or {}).get("verdict") or resolved.get("verdict_bucket") or ""),
            str(fresh.get("verdict_bucket") or ""),
        )


if __name__ == "__main__":
    unittest.main()
