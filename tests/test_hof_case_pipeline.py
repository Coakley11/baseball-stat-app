"""Tests for HOF publish/handoff pipeline diagnostics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd


class HofCasePipelineTests(unittest.TestCase):
    def test_hof_pipeline_debug_hidden_without_developer_mode(self) -> None:
        from unittest.mock import MagicMock

        from hof_case_pipeline import render_hof_pipeline_debug

        st = MagicMock()
        render_hof_pipeline_debug(st, {}, developer_mode=False)
        st.expander.assert_not_called()

    def test_hof_pipeline_debug_shown_in_developer_mode(self) -> None:
        from unittest.mock import MagicMock

        from hof_case_pipeline import render_hof_pipeline_debug

        st = MagicMock()
        render_hof_pipeline_debug(st, {}, developer_mode=True)
        st.expander.assert_called_once()

    def test_record_and_build_pipeline_status(self) -> None:
        from applied_math_return_insight import SESSION_PENDING_KEY
        from hof_case_pipeline import (
            build_hof_pipeline_status,
            init_hof_pipeline_run,
            record_hof_pipeline_step,
        )

        session: dict = {
            SESSION_PENDING_KEY: {
                "insight_id": "ins-1",
                "question_id": "q-1",
                "conclusion": "Compact thesis.",
                "source_page": "Career Totals",
                "full_analysis_url": "https://example.test/?suite_ai_question_id=q-1&suite_hof_case=1",
            },
            "_ami_force_insight_render": True,
        }
        init_hof_pipeline_run(session, target_player="Jason Giambi")
        record_hof_pipeline_step(session, "compact_insight_built", ok=True)
        status = build_hof_pipeline_status(session)
        self.assertIn("deploy_commit", status)
        self.assertIn("checks", status)
        self.assertTrue(status["checks"]["baseball_card_staged_in_session"])
        self.assertIn("suite_ai_question_id", status.get("open_full_analysis_url_params", {}))

    def test_hof_case_submit_bypasses_ami_send_defer(self) -> None:
        from baseball_persistent_state import force_save_baseball_state

        st = MagicMock()
        st.session_state = {
            "_suite_defer_baseball_save_reason": "ami_send:Career Totals",
            "_suite_persist_insight_dirty": True,
        }
        with patch("baseball_persistent_state.force_autosave", return_value=True) as mock_autosave:
            result = force_save_baseball_state(st, reason="hof_case_submit")
        self.assertTrue(result)
        mock_autosave.assert_called_once()
        self.assertNotIn("_suite_defer_baseball_save_reason", st.session_state)

    def test_ami_send_defer_still_blocks_unrelated_save(self) -> None:
        from baseball_persistent_state import force_save_baseball_state

        st = MagicMock()
        st.session_state = {"_suite_defer_baseball_save_reason": "ami_send:Career Totals"}
        with patch("baseball_persistent_state.force_autosave", return_value=True) as mock_autosave:
            result = force_save_baseball_state(st, reason="page_change")
        self.assertFalse(result)
        mock_autosave.assert_not_called()

    def test_publish_flow_integration(self) -> None:
        from hall_of_fame_data import (
            build_hof_ami_payload,
            build_hof_case_insight_record,
            build_hof_case_packet,
            build_hof_case_question,
            summarize_career_filters,
        )
        from hof_case_pipeline import init_hof_pipeline_run, record_hof_pipeline_step

        df = pd.DataFrame(
            [
                {"fullName": "Jason Giambi", "isHallOfFamer": False, "HR": 440, "careerPrimaryPos": "1B"},
                {"fullName": "Frank Thomas", "isHallOfFamer": True, "HR": 521},
            ]
        )
        session: dict = {"career_year_range_filter": [2000, 2024], "career_sort_stat_filter": "HR"}
        packet = build_hof_case_packet(
            "Jason Giambi",
            df,
            filters_summary=summarize_career_filters(session),
            sort_stat="HR",
            position_universe_df=df,
        )
        question = build_hof_case_question("Jason Giambi", packet)
        init_hof_pipeline_run(session, target_player="Jason Giambi")
        insight = build_hof_case_insight_record(packet, question=question, question_id="q-giambi")
        record_hof_pipeline_step(session, "compact_insight_built", ok=bool(insight.get("conclusion")))
        blob = build_hof_ami_payload(
            packet=packet,
            question=question,
            question_id="q-giambi",
            action_url="https://example.test/?suite_ai_question_id=q-giambi&suite_hof_case=1",
            insight=insight,
        )
        self.assertTrue(blob.get("hof_case_packet"))
        self.assertTrue(blob.get("insight"))
        self.assertTrue(blob.get("verdict_context"))


if __name__ == "__main__":
    unittest.main()
