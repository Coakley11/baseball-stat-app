"""Draft lab Command Center deep-link resume."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_lab_resume import (
    DRAFT_LAB_RESUME_COMPLETED_KEY,
    DRAFT_LAB_RESUME_ERROR_KEY,
    PENDING_RESUME_QUERY_KEY,
    apply_baseball_suite_resume,
    apply_draft_lab_resume,
    cancel_draft_lab_resume_navigation,
    capture_pending_resume_query,
    draft_lab_resume_consumed,
    finalize_draft_lab_resume,
    forced_page_active,
    load_completed_room_for_resume,
    parse_resume_room_id,
    reapply_pending_baseball_resume,
    schedule_draft_lab_resume_navigation,
)
from draft_room_shared_state import LocalFileSharedRoomStore, shared_room_document
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


def _completed_room(room_id: str = "ROOM-1") -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Primary Position": "3B"},
        ]
    )
    return {
        "draft_room_id": room_id,
        "status": "complete",
        "teams": ["Daniel", "Ariel"],
        "config": {"picks_per_team": 2, "num_teams": 2, "scoring_type": "5x5 Roto"},
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Daniel"},
            {"Pick": 2, "Round": 1, "Team": "Ariel"},
        ],
        "draft_board": [
            {"playerID": "p1", "fullName": "Aaron Judge", "Fantasy Team": "Daniel", "Pick": 1, "Round": 1},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Fantasy Team": "Ariel", "Pick": 2, "Round": 1},
        ],
        "drafted_player_ids": ["p1", "p2"],
        "pool": pool,
    }


class TestDraftLabResume(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

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
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Draft Simulation Test Mode")
        capture_pending_resume_query(st, "baseball")
        st.query_params = _QP({})
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Draft Simulation Test Mode")
        self.assertTrue(st.session_state.get("_suite_resume_launch_baseball"))

    def test_rebuild_from_completed_room_in_session(self) -> None:
        st = _ST()
        st.session_state["_suite_resume_draft_room"] = "ROOM-1"
        st.session_state["_suite_pending_draft_lab_resume"] = True
        st.session_state["live_draft_room"] = _completed_room("ROOM-1")
        with patch("draft_lab_resume._push_analysis_to_session", return_value=True) as push:
            diag = apply_draft_lab_resume(st)
        push.assert_called_once()
        self.assertTrue(diag.get("rebuild_success"))
        self.assertEqual(diag.get("draft_lab_results_status"), "rebuilt_from_room")
        self.assertEqual(diag.get("room_load_source"), "session_live_draft_room")

    def test_fresh_session_query_params_load_room_from_shared_store(self) -> None:
        room = _completed_room("DRAFTID1")
        doc = shared_room_document(room_code="ABC123", host_participant_id="host", live_room=room)
        self.store.save(doc)
        session: dict = {}
        with patch("draft_room_shared_state.get_shared_room_store", return_value=self.store):
            loaded, source = load_completed_room_for_resume(session, "DRAFTID1")
        self.assertIsNotNone(loaded)
        self.assertEqual(source, "local_file_draft_room_id")
        self.assertEqual(str(loaded.get("draft_room_id") or "").upper(), "DRAFTID1")

    def test_suite_draft_room_query_rebuilds_results(self) -> None:
        st = _ST({"suite_page": "Draft Simulation Test Mode", "suite_draft_room": "DRAFTID2"})
        st.session_state["live_draft_room"] = _completed_room("DRAFTID2")
        st.session_state["_suite_pending_draft_lab_resume"] = True

        def _push(_room: dict) -> bool:
            st.session_state["draft_lab_results"] = {"draft": pd.DataFrame([{"Pick": 1}]), "handoff": {"session_id": "DRAFTID2"}}
            return True

        with patch("draft_lab_resume._push_analysis_to_session", side_effect=_push):
            diag = apply_draft_lab_resume(st)
        self.assertTrue(diag.get("rebuild_success"))
        self.assertTrue(diag.get("draft_lab_results_after"))

    def test_bb_draft_lab_team_key_parses_room_id(self) -> None:
        st = _ST({"suite_resume": "bb:draft_lab:team:MYROOM99"})
        self.assertEqual(parse_resume_room_id(st, st.session_state), "MYROOM99")

    def test_invalid_room_shows_restore_error(self) -> None:
        st = _ST({"suite_draft_room": "MISSING99"})
        st.session_state["_suite_pending_draft_lab_resume"] = True
        with patch("draft_room_shared_state.get_shared_room_store", return_value=self.store):
            diag = apply_draft_lab_resume(st)
        self.assertEqual(diag.get("draft_lab_results_status"), "room_not_found")
        err = st.session_state.get(DRAFT_LAB_RESUME_ERROR_KEY)
        self.assertIsInstance(err, dict)
        self.assertIn("MISSING99", str(err.get("message") or ""))

    def test_missing_results_rebuilt_when_room_exists(self) -> None:
        st = _ST()
        st.session_state["_suite_resume_draft_room"] = "ROOM-9"
        st.session_state["live_draft_room"] = _completed_room("ROOM-9")
        self.assertNotIn("draft_lab_results", st.session_state)

        def _push(_room: dict) -> bool:
            st.session_state["draft_lab_results"] = {"draft": pd.DataFrame([{"Pick": 1}]), "handoff": {"session_id": "ROOM-9"}}
            return True

        with patch("draft_lab_resume._push_analysis_to_session", side_effect=_push):
            diag = apply_draft_lab_resume(st)
        self.assertTrue(diag.get("rebuild_attempted"))
        self.assertTrue(diag.get("draft_lab_results_after"))

    def test_team_analysis_section_preference(self) -> None:
        st = _ST({"suite_draft_section": "team_analysis", "suite_draft_room": "ROOM-1"})
        st.session_state["live_draft_room"] = _completed_room("ROOM-1")
        with patch("draft_lab_resume._push_analysis_to_session", return_value=True):
            apply_draft_lab_resume(st)
        self.assertEqual(st.session_state.get("draft_lab_preferred_tab"), "Team Analysis")

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

    def test_finalize_clears_forced_navigation(self) -> None:
        st = _ST()
        st.session_state["_suite_pending_draft_lab_resume"] = True
        st.session_state["_navigate_to_page"] = "Draft Simulation Test Mode"
        st.session_state["_skip_page_restore_for"] = "Draft Simulation Test Mode"
        st.session_state[PENDING_RESUME_QUERY_KEY] = {"suite_page": "Draft Simulation Test Mode"}
        finalize_draft_lab_resume(st, applied=True)
        self.assertTrue(draft_lab_resume_consumed(st.session_state))
        self.assertFalse(forced_page_active(st.session_state))
        self.assertNotIn("_navigate_to_page", st.session_state)

    def test_user_can_navigate_away_after_resume(self) -> None:
        st = _ST()
        schedule_draft_lab_resume_navigation(st, page="Draft Simulation Test Mode", room_id="R1")
        st.session_state["live_draft_room"] = _completed_room("R1")

        def _push(_room: dict) -> bool:
            st.session_state["draft_lab_results"] = {
                "draft": pd.DataFrame([{"Pick": 1}]),
                "handoff": {"session_id": "R1"},
            }
            return True

        with patch("draft_lab_resume._push_analysis_to_session", side_effect=_push):
            apply_draft_lab_resume(st)
        self.assertTrue(draft_lab_resume_consumed(st.session_state))
        cancel_draft_lab_resume_navigation(st, "Live Draft Room")
        st.session_state["active_page"] = "Live Draft Room"
        st.session_state["main_sidebar_page"] = "Live Draft Room"
        self.assertEqual(st.session_state["active_page"], "Live Draft Room")
        self.assertFalse(forced_page_active(st.session_state))

    def test_suite_resume_launch_does_not_reforce_after_completed(self) -> None:
        st = _ST(
            {
                "suite_page": "Draft Simulation Test Mode",
                "suite_draft_room": "ROOM-ABC123",
                "suite_resume": "bb:draft_lab:team:ROOM-ABC123",
            }
        )
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Draft Simulation Test Mode")
        st.session_state[DRAFT_LAB_RESUME_COMPLETED_KEY] = True
        st.session_state["active_page"] = "Live Draft Room"
        st.session_state["main_sidebar_page"] = "Live Draft Room"
        apply_suite_resume_launch(st, "baseball")
        self.assertEqual(st.session_state.get("active_page"), "Live Draft Room")

    def test_resume_applied_only_once(self) -> None:
        st = _ST()
        st.session_state["_suite_resume_draft_room"] = "ROOM-1"
        st.session_state["_suite_pending_draft_lab_resume"] = True
        st.session_state["live_draft_room"] = _completed_room("ROOM-1")

        def _push(_room: dict) -> bool:
            st.session_state["draft_lab_results"] = {
                "draft": pd.DataFrame([{"Pick": 1}]),
                "handoff": {"session_id": "ROOM-1"},
            }
            return True

        with patch("draft_lab_resume._push_analysis_to_session", side_effect=_push) as push:
            apply_draft_lab_resume(st)
            apply_draft_lab_resume(st)
        self.assertEqual(push.call_count, 1)

    def test_bb_live_draft_resume_opens_live_draft_room(self) -> None:
        st = _ST({"suite_resume": "bb:live_draft:ROOM-LIVE", "suite_page": "Live Draft Room"})
        _apply_baseball(st, "bb:live_draft:ROOM-LIVE", "Live Draft Room")
        self.assertEqual(st.session_state.get("_navigate_to_page"), "Live Draft Room")
        self.assertEqual(st.session_state.get("_suite_resume_draft_room"), "ROOM-LIVE")

    def test_reapply_pending_after_auth_clears_url(self) -> None:
        st = _ST()
        st.session_state[PENDING_RESUME_QUERY_KEY] = {
            "suite_page": "Draft Simulation Test Mode",
            "suite_draft_room": "ROOM-9",
            "suite_resume": "bb:draft_lab:team:ROOM-9",
        }
        self.assertTrue(reapply_pending_baseball_resume(st))
        self.assertEqual(st.session_state.get("_navigate_to_page"), "Draft Simulation Test Mode")

    def test_apply_baseball_suite_resume_hydrates_room(self) -> None:
        st = _ST()
        st.session_state["_suite_resume_draft_room"] = "ROOM-1"
        st.session_state["live_draft_room"] = _completed_room("ROOM-1")
        diag = apply_baseball_suite_resume(st)
        self.assertTrue(diag.get("room_hydrated"))

    def test_consumed_resume_rebuilds_when_results_missing(self) -> None:
        st = _ST()
        st.session_state[DRAFT_LAB_RESUME_COMPLETED_KEY] = True
        st.session_state["_suite_resume_draft_room"] = "ROOM-1"
        st.session_state["_suite_pending_draft_lab_resume"] = True
        st.session_state["live_draft_room"] = _completed_room("ROOM-1")

        def _push(_room: dict) -> bool:
            st.session_state["draft_lab_results"] = {
                "draft": pd.DataFrame([{"Pick": 1}]),
                "handoff": {"session_id": "ROOM-1"},
            }
            return True

        with patch("draft_lab_resume._push_analysis_to_session", side_effect=_push) as push:
            diag = apply_draft_lab_resume(st)
        push.assert_called_once()
        self.assertTrue(diag.get("rebuild_success"))


if __name__ == "__main__":
    unittest.main()
