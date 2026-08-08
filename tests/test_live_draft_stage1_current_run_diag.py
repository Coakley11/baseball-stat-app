"""Tests for Stage 1 current-run diagnostic DOM probe."""

from __future__ import annotations

import unittest
from unittest import mock

from live_draft_stage1_current_run_diag import (
    CURRENT_RUN_IMPL_REV,
    CURRENT_RUN_PROBE_ID,
    render_stage1_current_run_diag_probe,
)


class Stage1CurrentRunDiagTests(unittest.TestCase):
    def test_probe_emits_current_script_run_seq(self) -> None:
        session: dict = {
            "_solo_component_diag_enabled": True,
            "_solo_stage1_script_run_seq": 18,
            "_solo_stage1_run_id": "abc123",
            "live_draft_room": {"draft_room_id": "29732FA8", "status": "in_progress"},
        }
        st = mock.Mock()
        captured: list[str] = []

        def _markdown(html: str, **kwargs: object) -> None:
            captured.append(html)

        st.markdown = _markdown
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ), mock.patch(
            "live_draft_stage1_current_run_diag._streamlit_session_id_for_probe",
            return_value="sess-1111",
        ), mock.patch(
            "live_draft_stage1_current_run_diag._deployment_sha",
            return_value="9f7ea7b",
        ):
            render_stage1_current_run_diag_probe(st, session, probe_checkpoint="post_pause")
        self.assertTrue(captured)
        html = captured[0]
        self.assertIn(f'id="{CURRENT_RUN_PROBE_ID}"', html)
        self.assertIn('data-script-run-seq="18"', html)
        self.assertIn('data-room-id="29732FA8"', html)
        self.assertIn('data-streamlit-session-id="sess-1111"', html)
        self.assertIn(f'data-impl-rev="{CURRENT_RUN_IMPL_REV}"', html)
        self.assertIn('data-probe-checkpoint="post_pause"', html)

    def test_probe_skipped_when_diag_disabled(self) -> None:
        session: dict = {"_solo_rv_ladder_step": "RV3"}
        st = mock.Mock()
        with mock.patch(
            "live_draft_stage1_production_ledger.stage1_production_ledger_enabled",
            return_value=False,
        ):
            render_stage1_current_run_diag_probe(st, session)
        st.markdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
