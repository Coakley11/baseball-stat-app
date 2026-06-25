"""Draft lab Command Center deep-link resume."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from draft_lab_resume import (
    apply_draft_lab_resume,
    capture_pending_resume_query,
    schedule_draft_lab_resume_navigation,
)
from suite_deep_links import build_resume_action_url
from suite_resume_launch import _apply_baseball, apply_suite_resume_launch


class _QP:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def get(self, key: str):
        return self._mapping.get(key)


class _ST:
    def __init__(self, query: dict[str, str] | None = None):
        self.session_state: dict = {}
        self.query_params = _QP(query or {})


class TestDraftLabResume(unittest.TestCase):
    def test_suite_page_query_schedules_draft_lab_not_historical(self) -> None:
        st = _ST(
            {
                "suite_page": "Draft Simulation Test Mode",
                "suite_draft_room": "ROOM-ABC123",
                "suite_resume": "bb:draft_lab:team:ROOM-ABC123",
            }
        )
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Draft Simulation Test Mode")
        self.assertEqual(st.session_state.get("_navigate_to_page"), "Draft Simulation Test Mode")
        self.assertNotEqual(st.session_state.get("active_page"), "Historical Explorer")
        self.assertTrue(st.session_state.get("_suite_page_user_nav"))

    def test_bb_draft_lab_resume_key_opens_draft_lab(self) -> None:
        st = _ST({"suite_resume": "bb:draft_lab:ROOM-XYZ"})
        _apply_baseball(st, "bb:draft_lab:ROOM-XYZ", "")
        self.assertEqual(st.session_state["_navigate_to_page"], "Draft Simulation Test Mode")
        self.assertEqual(st.session_state["_suite_resume_draft_room"], "ROOM-XYZ")

    def test_pending_query_survives_auth_rerun(self) -> None:
        st = _ST({"suite_page": "Draft Simulation Test Mode", "suite_draft_room": "ROOM-1"})
        capture_pending_resume_query(st, "baseball")
        st.query_params = _QP({})
        st.session_state["_suite_resume_launch_baseball"] = True
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Draft Simulation Test Mode")

    def test_rebuild_from_completed_room(self) -> None:
        st = _ST()
        st.session_state["_suite_resume_draft_room"] = "ROOM-1"
        st.session_state["_suite_pending_draft_lab_resume"] = True
        st.session_state["live_draft_room"] = {
            "draft_room_id": "ROOM-1",
            "status": "complete",
            "teams": ["Daniel", "Ariel"],
            "config": {"picks_per_team": 2},
            "draft_board": [{}, {}, {}, {}],
            "pool": __import__("pandas").DataFrame(),
        }
        with patch("streamlit_app.live_draft_push_analysis_to_session", return_value=True):
            diag = apply_draft_lab_resume(st)
        self.assertTrue(diag.get("rebuild_success"))
        self.assertEqual(diag.get("draft_lab_results_status"), "rebuilt_from_room")

    def test_command_center_url_includes_draft_lab_params(self) -> None:
        url = build_resume_action_url(
            "baseball",
            resume_key="bb:draft_lab:team:ROOM-ABC123",
            page="Draft Simulation Test Mode",
            metrics={
                "draft_room_id": "ROOM-ABC123",
                "draft_section": "team_analysis",
                "team_matchup": "Daniel vs Ariel",
            },
            base_url="https://example.test",
        )
        self.assertIn("suite_page=Draft+Simulation+Test+Mode", url)
        self.assertIn("suite_draft_room=ROOM-ABC123", url)
        self.assertIn("suite_draft_section=team_analysis", url)

    def test_schedule_sets_skip_page_restore(self) -> None:
        st = _ST()
        schedule_draft_lab_resume_navigation(st, page="Draft Simulation Test Mode", room_id="R1")
        self.assertEqual(st.session_state["_skip_page_restore_for"], "Draft Simulation Test Mode")


if __name__ == "__main__":
    unittest.main()
