"""Regression tests for HOF AMI question vs conclusion separation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from applied_math_return_insight import (
    _insight_card_conclusion,
    _insight_card_question,
    _insight_confidence_caption,
)
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
    rehydrate_hof_case_packet_awards,
)
from hof_case_analysis import (
    compose_hof_statistical_case,
    format_hof_case_memo_markdown,
    render_hof_case_full_analysis,
    resolve_hof_case_analysis,
    sync_hof_display_analysis,
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
        self.assertEqual(str(insight.get("confidence_label") or ""), "Cohort filter confidence")
        caption = _insight_confidence_caption(insight, method=str(insight.get("method") or ""))
        conf = str(insight.get("cohort_confidence") or insight.get("confidence") or "")
        self.assertEqual(caption, f"Cohort filter confidence: **{conf}**")
        self.assertNotIn(f"{conf}: {conf}", caption)

    def test_insight_confidence_caption_handles_legacy_embedded_value(self) -> None:
        legacy = {
            "cohort_confidence": "low",
            "confidence": "low",
            "confidence_label": "Cohort filter confidence: low",
            "method": f"{CASE_SCORE_LABEL} — Strong",
        }
        caption = _insight_confidence_caption(legacy, method=legacy["method"])
        self.assertEqual(caption, "Cohort filter confidence: low")
        self.assertNotIn("low: low", caption)

    def test_render_ignores_legacy_verdict_memo_and_shows_awards(self) -> None:
        packet = self._harper_packet()
        legacy_markdown = (
            "### Verdict: Solid\n\n"
            "Bryce Harper's statistical Hall of Fame case is **Solid**.\n\n"
            "#### Statistical case\n"
            "**Strongest evidence**\n"
            "- 350 home runs.\n"
            "**Weakest evidence / cautions**\n"
            "- Limited relative value by home runs.\n"
            "**Cohort interpretation**\n"
            "- Small cohort.\n"
        )
        stale_verdict = {
            "verdict_bucket": "Solid",
            "case_memo": {"_preformatted_markdown": legacy_markdown},
        }
        st = MagicMock()
        markdown_calls: list[str] = []

        def _capture_md(text: str, **kwargs) -> None:
            markdown_calls.append(str(text))

        st.markdown = _capture_md
        st.caption = lambda *args, **kwargs: None
        self.assertTrue(render_hof_case_full_analysis(st, packet, verdict=stale_verdict))
        joined = "\n".join(markdown_calls)
        self.assertIn("Awards & accolades", joined)
        self.assertIn(CASE_SCORE_LABEL, joined)
        self.assertNotIn("### Verdict: Solid", joined)
        self.assertTrue(
            any(token in joined for token in ("MVP", "Silver Slugger", "Hank Aaron Award", "Rookie of the Year"))
        )

    def test_full_report_and_ami_bucket_match_for_fresh_packet(self) -> None:
        packet = self._harper_packet()
        display_q = build_hof_case_display_question("Bryce Harper", packet)
        insight = build_hof_case_insight_record(packet, question=display_q, question_id="q-harper")
        resolved = resolve_hof_case_analysis(packet)
        method_bucket = str(insight.get("method") or "").split("—")[-1].strip()
        memo = format_hof_case_memo_markdown(resolved)
        self.assertEqual(method_bucket, str(resolved.get("verdict_bucket") or ""))
        self.assertIn(f"{CASE_SCORE_LABEL}: {method_bucket}", memo)

    def test_disclaimer_mentions_awards_only_when_awards_exist(self) -> None:
        packet = self._harper_packet()
        with_awards = hof_case_disclaimer_text(packet)
        without_awards = hof_case_disclaimer_text({"target_awards_summary": {"data_available": False}})
        self.assertIn("awards evidence", with_awards)
        self.assertNotIn("awards evidence", without_awards)
        memo = format_hof_case_memo_markdown(resolve_hof_case_analysis(packet))
        if "Awards & accolades" in memo:
            self.assertIn("awards evidence", memo)

    def _alex_rodriguez_cohort(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "fullName": "Alex Rodriguez",
                    "playerID": "rodrial01",
                    "isHallOfFamer": False,
                    "G": 2784,
                    "AB": 10566,
                    "R": 2021,
                    "H": 3115,
                    "HR": 696,
                    "RBI": 2086,
                    "2B": 548,
                    "OBP": 0.380,
                    "OPS": 0.930,
                    "careerPrimaryPos": "SS",
                },
                {
                    "fullName": "Cal Ripken Jr.",
                    "playerID": "ripkeca01",
                    "isHallOfFamer": True,
                    "G": 3001,
                    "HR": 431,
                    "OBP": 0.340,
                    "OPS": 0.787,
                    "careerPrimaryPos": "SS",
                },
            ]
        )

    def _alex_rodriguez_packet(self) -> dict:
        repo_awards = Path(__file__).resolve().parents[1] / "AwardsPlayers.csv"
        awards_df = load_awards_players_df(repo_awards.parent) if repo_awards.is_file() else self.awards_df
        return build_hof_case_packet(
            "Alex Rodriguez",
            self._alex_rodriguez_cohort(),
            filters_summary={"sort_stat": "G"},
            sort_stat="G",
            awards_df=awards_df,
            position_universe_df=self._alex_rodriguez_cohort(),
        )

    def _rendered_markdown(self, packet: dict, *, verdict: dict | None = None) -> str:
        st = MagicMock()
        markdown_calls: list[str] = []

        def _capture_md(text: str, **kwargs) -> None:
            markdown_calls.append(str(text))

        st.markdown = _capture_md
        st.caption = lambda *args, **kwargs: None
        self.assertTrue(render_hof_case_full_analysis(st, packet, verdict=verdict))
        return "\n".join(markdown_calls)

    def test_full_report_rehydrates_awards_for_alex_rodriguez(self) -> None:
        packet = self._alex_rodriguez_packet()
        stripped = dict(packet)
        stripped["target_awards_summary"] = {"data_available": False}
        stripped["cohort_award_comparison"] = {"data_available": False}
        rehydrated = rehydrate_hof_case_packet_awards(stripped)
        self.assertTrue((rehydrated.get("target_awards_summary") or {}).get("data_available"))
        rendered = self._rendered_markdown(stripped)
        self.assertIn("Awards & accolades", rendered)
        self.assertTrue(any(token in rendered for token in ("MVP", "Silver Slugger", "Hank Aaron Award", "Gold Glove")))
        self.assertIn("major award", rendered.lower())

    def test_preformatted_full_report_without_awards_is_upgraded_on_render(self) -> None:
        packet = self._alex_rodriguez_packet()
        fresh = compose_hof_statistical_case(packet)
        memo_md = format_hof_case_memo_markdown(fresh, packet=packet)
        stripped_lines: list[str] = []
        skip = False
        for line in memo_md.splitlines():
            if line.strip() == "#### Awards & accolades":
                skip = True
                continue
            if skip and line.startswith("#### "):
                skip = False
            if not skip:
                stripped_lines.append(line)
        preformatted = "\n".join(stripped_lines)
        rendered = self._rendered_markdown(packet, verdict={"case_memo": preformatted})
        self.assertIn("Awards & accolades", rendered)
        self.assertIn("Silver Slugger", rendered)
        self.assertNotIn("Awards context unavailable", rendered)

    def test_rendered_full_report_thesis_mentions_awards(self) -> None:
        packet = self._alex_rodriguez_packet()
        rendered = self._rendered_markdown(packet)
        self.assertIn("major award", rendered.lower())
        synced = sync_hof_display_analysis(compose_hof_statistical_case(packet), packet)
        thesis = str(synced.get("thesis") or "")
        self.assertIn("major award", thesis.lower())

    def test_disclaimer_mentions_awards_only_when_rendered_report_has_awards(self) -> None:
        packet = self._alex_rodriguez_packet()
        rendered = self._rendered_markdown(packet)
        self.assertIn("Awards & accolades", rendered)
        self.assertIn("awards evidence", rendered.lower())
        no_awards_packet = {"target_awards_summary": {"data_available": False}}
        bare_md = format_hof_case_memo_markdown(
            compose_hof_statistical_case(
                build_hof_case_packet(
                    "Alex Rodriguez",
                    self._alex_rodriguez_cohort(),
                    filters_summary={"sort_stat": "G"},
                    sort_stat="G",
                    awards_df=pd.DataFrame(columns=["playerID", "awardID", "yearID"]),
                    position_universe_df=self._alex_rodriguez_cohort(),
                )
            ),
            packet=no_awards_packet,
        )
        self.assertNotIn("awards evidence", bare_md.lower())

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
