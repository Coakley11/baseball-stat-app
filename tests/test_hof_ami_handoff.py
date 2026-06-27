"""HOF case AMI full-analysis handoff tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from hall_of_fame_data import build_hof_ami_payload, build_hof_case_packet
from suite_analytical_question import (
    analytical_question_continue_copy,
    build_question_payload,
    hydrate_applied_intelligence_session,
    render_applied_intelligence_solve_problem_content,
    render_suite_applied_math_insight,
    should_prefer_hof_full_memo_renderer,
    submit_analytical_question,
)


class HofAmiHandoffTests(unittest.TestCase):
    def test_hof_continue_copy_uses_player_title(self) -> None:
        payload = build_question_payload(
            source_app="baseball",
            source_page="Career Totals",
            question="Hall of Fame statistical case for Albert Pujols",
            context={
                "player": "Albert Pujols",
                "hof_case_packet": {
                    "mode": "hall_of_fame_case",
                    "target_player": "Albert Pujols",
                    "hof_case_summary": "Hall of Fame statistical case for Albert Pujols · cohort 12/40 HOF (30%)",
                },
                "routing_hint": "hof_case_analysis",
            },
            quant_area="hall_of_fame_case",
        )
        title, subtitle, button = analytical_question_continue_copy(payload)
        self.assertIn("Albert Pujols", title)
        self.assertIn("Open full Hall of Fame analysis", title)
        self.assertIn("cohort 12/40 HOF", subtitle)
        self.assertNotIn("Do NOT present", subtitle)
        self.assertIn("Open analysis", button)

    def test_hof_submit_records_hof_event_not_generic_resume(self) -> None:
        upserts: list = []
        activities: list = []
        with patch("suite_analytical_question._upsert_applied_intelligence_resume", side_effect=lambda p, **k: upserts.append((p, k))):
            with patch("suite_analytical_question._store_question_context_blob"):
                with patch("suite_activity_client.record_activity", side_effect=lambda *a, **k: activities.append((a, k))):
                    result = submit_analytical_question(
                        source_app="baseball",
                        source_page="Career Totals",
                        question="Hall of Fame statistical case for Albert Pujols",
                        context={
                            "player": "Albert Pujols",
                            "hof_case_packet": {
                                "mode": "hall_of_fame_case",
                                "target_player": "Albert Pujols",
                            },
                            "routing_hint": "hof_case_analysis",
                        },
                        quant_area="hall_of_fame_case",
                    )
        self.assertFalse(upserts)
        self.assertTrue(str(result.get("action_url") or "").strip())
        self.assertIn("suite_ai_question_id", str(result.get("action_url") or ""))
        self.assertTrue(activities)
        event_type = activities[0][0][1]
        self.assertEqual(event_type, "hof_case_analysis_submitted")
        resume_key = str(activities[0][1].get("resume_key") or "")
        self.assertTrue(resume_key.startswith("hof:ami:"))

    def test_hof_hydrate_selects_full_memo_renderer_not_compact_card(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Freddie Freeman", "isHallOfFamer": False, "HR": 350, "careerPrimaryPos": "1B"},
                {"fullName": "Frank Thomas", "isHallOfFamer": True, "HR": 521, "careerPrimaryPos": "1B"},
            ]
        )
        packet = build_hof_case_packet(
            "Freddie Freeman",
            df,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            position_universe_df=df,
        )
        blob = build_hof_ami_payload(
            packet=packet,
            question="Hall of Fame case for Freddie Freeman",
            question_id="q-freeman",
            action_url="https://example.test/?suite_ai_question_id=q-freeman&suite_hof_case=1",
            insight={"conclusion": "One-line compact thesis", "insight_id": "ins-f"},
        )
        st = MagicMock()
        st.session_state = {}
        st.query_params = {
            "suite_ai_question_id": "q-freeman",
            "suite_hof_case": "1",
            "suite_ai_area": "hall_of_fame_case",
            "suite_hof_target": "Freddie Freeman",
        }

        with patch("suite_analytical_question.load_analytical_question_payload", return_value=blob):
            hydrate_applied_intelligence_session(st)

        self.assertTrue(st.session_state.get("_suite_hof_case"))
        self.assertTrue(st.session_state.get("_hof_case_packet"))
        self.assertFalse(st.session_state.get("_ami_force_insight_render"))
        self.assertIsNone(st.session_state.get("_ami_pending_insight"))
        diag = st.session_state.get("_suite_ai_hydrate_diag") or {}
        self.assertEqual(diag.get("selected_renderer"), "render_hof_case_full_analysis")
        self.assertTrue(diag.get("hof_case_packet_present"))
        self.assertTrue(diag.get("verdict_context_present"))
        self.assertTrue(diag.get("insight_present"))
        self.assertTrue(diag.get("target_player_present"))
        self.assertTrue(should_prefer_hof_full_memo_renderer(st))

    def test_render_suite_applied_math_insight_routes_hof_to_full_memo(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Freddie Freeman", "isHallOfFamer": False, "HR": 350, "careerPrimaryPos": "1B"},
                {"fullName": "Frank Thomas", "isHallOfFamer": True, "HR": 521, "careerPrimaryPos": "1B"},
            ]
        )
        packet = build_hof_case_packet(
            "Freddie Freeman",
            df,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            position_universe_df=df,
        )
        st = MagicMock()
        st.session_state = {
            "_suite_hof_case": True,
            "_hof_case_packet": packet,
            "_hof_case_verdict": {},
        }
        st.markdown = MagicMock()
        st.caption = MagicMock()

        with patch("hof_case_analysis.render_hof_case_full_analysis", return_value=True) as mock_full:
            ok = render_suite_applied_math_insight(st, source_app="", source_page="Solve a Problem")
        self.assertTrue(ok)
        mock_full.assert_called_once()

    def test_render_applied_intelligence_solve_problem_content_prefers_full_memo(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Freddie Freeman", "isHallOfFamer": False, "HR": 350, "careerPrimaryPos": "1B"},
                {"fullName": "Frank Thomas", "isHallOfFamer": True, "HR": 521, "careerPrimaryPos": "1B"},
            ]
        )
        packet = build_hof_case_packet(
            "Freddie Freeman",
            df,
            filters_summary={"sort_stat": "HR"},
            sort_stat="HR",
            position_universe_df=df,
        )
        st = MagicMock()
        st.session_state = {
            "_suite_hof_case": True,
            "_hof_case_packet": packet,
        }
        st.markdown = MagicMock()
        st.caption = MagicMock()

        with patch("hof_case_analysis.render_hof_case_full_analysis", return_value=True) as mock_full:
            ok = render_applied_intelligence_solve_problem_content(st)
        self.assertTrue(ok)
        mock_full.assert_called_once()


if __name__ == "__main__":
    unittest.main()
