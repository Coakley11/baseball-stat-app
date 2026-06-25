"""Command Center activity for Live Draft Room and Draft Lab handoff."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from baseball_draft_activity import (
    after_live_draft_pick_committed,
    live_draft_activity_metrics,
    log_completed_live_draft,
    log_draft_analysis_created,
    log_live_draft_room_created,
)
from suite_deep_links import build_resume_action_url
from suite_resume_launch import _apply_baseball


def _sample_room(*, complete: bool = False, picks: int = 0) -> dict:
    board = [{"pick": i + 1} for i in range(picks)]
    return {
        "draft_room_id": "ROOM-ABC123",
        "teams": ["Daniel", "Ariel"],
        "config": {"picks_per_team": 2, "teams": ["Daniel", "Ariel"]},
        "draft_board": board,
        "status": "complete" if complete else "in_progress",
        "current_pick_index": picks,
    }


class TestBaseballDraftActivity(unittest.TestCase):
    @patch("suite_activity_client.record_activity")
    def test_completed_live_draft_emits_event(self, record_mock) -> None:
        session: dict = {}
        log_completed_live_draft(_sample_room(complete=True, picks=4), session=session)
        record_mock.assert_called_once()
        args, kwargs = record_mock.call_args
        self.assertEqual(args[0], "baseball")
        self.assertEqual(args[1], "completed_live_draft")
        self.assertEqual(kwargs["resume_title"], "Review completed draft")
        metrics = kwargs["metrics"]
        self.assertEqual(metrics["team_matchup"], "Daniel vs Ariel")
        self.assertEqual(metrics["activity_type"], "completed_live_draft")
        self.assertNotIn("Team A", metrics["team_matchup"])

    @patch("suite_activity_client.record_activity")
    def test_draft_analysis_created_emits_event(self, record_mock) -> None:
        room = _sample_room(complete=True, picks=4)
        session: dict = {"live_draft_room": room}
        log_draft_analysis_created(room, session=session)
        record_mock.assert_called_once()
        _app, event, *_rest = record_mock.call_args[0]
        kwargs = record_mock.call_args[1]
        self.assertEqual(event, "draft_analysis_created")
        self.assertEqual(kwargs["page"], "Draft Simulation Test Mode")
        self.assertEqual(kwargs["metrics"]["teams"], ["Daniel", "Ariel"])

    @patch("baseball_draft_activity.log_completed_live_draft")
    @patch("baseball_draft_activity.log_live_draft_pick")
    def test_after_pick_committed_logs_completion(self, pick_mock, complete_mock) -> None:
        session: dict = {}
        room = _sample_room(complete=True, picks=4)
        after_live_draft_pick_committed(session, room)
        pick_mock.assert_called_once()
        complete_mock.assert_called_once()

    @patch("suite_activity_client.record_activity")
    def test_room_created_deduped_per_session(self, record_mock) -> None:
        session: dict = {}
        room = _sample_room()
        log_live_draft_room_created(room, session=session)
        log_live_draft_room_created(room, session=session)
        self.assertEqual(record_mock.call_count, 1)

    def test_deep_link_opens_draft_lab(self) -> None:
        metrics = live_draft_activity_metrics(
            _sample_room(),
            activity_type="draft_analysis_created",
            feature="Draft Simulation Test Mode",
        )
        url = build_resume_action_url(
            "baseball",
            resume_key="bb:draft_lab:ROOM-ABC123",
            page="Draft Simulation Test Mode",
            metrics=metrics,
            base_url="https://example.test",
        )
        self.assertIn("suite_page=Draft+Simulation+Test+Mode", url)
        self.assertIn("suite_draft_room=ROOM-ABC123", url)
        self.assertIn("suite_resume=bb%3Adraft_lab%3AROOM-ABC123", url)

    def test_resume_launch_maps_draft_lab_page(self) -> None:
        class _QP:
            def get(self, key):
                mapping = {
                    "suite_resume": "bb:draft_lab:ROOM-ABC123",
                    "suite_page": "Draft Simulation Test Mode",
                    "suite_draft_room": "ROOM-ABC123",
                }
                return mapping.get(key, "")

        class _ST:
            session_state: dict = {}

            query_params = _QP()

        st = _ST()
        _apply_baseball(st, "bb:draft_lab:ROOM-ABC123", "Draft Simulation Test Mode")
        self.assertEqual(st.session_state["_navigate_to_page"], "Draft Simulation Test Mode")
        self.assertEqual(st.session_state["_suite_resume_draft_room"], "ROOM-ABC123")


if __name__ == "__main__":
    unittest.main()
