"""Tests for canonical Live Draft Room persistence (Phase 1 + 2)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    LIVE_DRAFT_STATE_KEY,
    apply_cloud_live_draft_state_if_allowed,
    commit_live_draft_room,
    prepare_live_draft_state,
    room_from_persist_dict,
    room_to_persist_dict,
    sanitize_state_dict_for_json,
    verify_json_serializable,
    write_canonical_live_draft_state,
)
from suite_user_persistence import save_user_state


def _sample_room(*, pick_index: int = 2) -> dict:
    pool = pd.DataFrame(
        [
            {
                "playerID": "p1",
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "Expected Fantasy Value": 95.0,
                "Model Rank": 1,
                "Market Rank": 1,
            },
            {
                "playerID": "p2",
                "fullName": "Juan Soto",
                "Primary Position": "OF",
                "Expected Fantasy Value": 92.0,
                "Model Rank": 2,
                "Market Rank": 2,
            },
            {
                "playerID": "p3",
                "fullName": "Corbin Carroll",
                "Primary Position": "OF",
                "Expected Fantasy Value": 88.0,
                "Model Rank": 3,
                "Market Rank": 3,
            },
        ]
    )
    return {
        "draft_room_id": "ROOMTEST",
        "status": "in_progress",
        "config": {
            "league_name": "Test League",
            "num_teams": 4,
            "picks_per_team": 5,
            "user_team": "Team A",
            "scoring_type": "Roto (5x5)",
        },
        "teams": ["Team A", "Team B", "Team C", "Team D"],
        "pick_order": [{"Pick": i + 1, "Round": 1, "Team": "Team A"} for i in range(20)],
        "current_pick_index": pick_index,
        "drafted_player_ids": ["p0", "p1"],
        "draft_board": [
            {"playerID": "p0", "fullName": "Mike Trout", "Pick": 1, "Round": 1, "Fantasy Team": "Team A"},
            {"playerID": "p1", "fullName": "Aaron Judge", "Pick": 2, "Round": 1, "Fantasy Team": "Team B"},
        ],
        "rosters": {
            "Team A": [{"playerID": "p0", "fullName": "Mike Trout"}],
            "Team B": [{"playerID": "p1", "fullName": "Aaron Judge"}],
        },
        "pool": pool,
        "timer_started_at": None,
        "timer_handled_index": -1,
        "paused_remaining_seconds": None,
        "meta": {"sync": {"revision": 2, "storage_backend": "canonical"}},
    }


class TestLiveDraftSerialization(unittest.TestCase):
    def test_pool_roundtrips_through_json(self) -> None:
        room = _sample_room()
        blob = room_to_persist_dict(room)
        self.assertIn("pool_records", blob)
        self.assertNotIn("pool", blob)
        raw = json.dumps(blob, ensure_ascii=False)
        parsed = json.loads(raw)
        restored = room_from_persist_dict(parsed)
        assert restored is not None
        self.assertIsInstance(restored["pool"], pd.DataFrame)
        self.assertEqual(len(restored["pool"]), 3)
        self.assertEqual(restored["current_pick_index"], 2)
        self.assertEqual(len(restored["draft_board"]), 2)

    def test_sanitize_makes_full_state_json_safe(self) -> None:
        room = _sample_room()
        state = {LIVE_DRAFT_ROOM_KEY: room, LIVE_DRAFT_STATE_KEY: room_to_persist_dict(room)}
        safe = sanitize_state_dict_for_json(state)
        ok, err = verify_json_serializable(safe)
        self.assertTrue(ok, err)

    def test_save_user_state_succeeds_with_sanitized_room(self) -> None:
        room = _sample_room()
        state = sanitize_state_dict_for_json(
            {
                "active_page": "Live Draft Room",
                LIVE_DRAFT_STATE_KEY: room_to_persist_dict(room),
                LIVE_DRAFT_ROOM_KEY: room_to_persist_dict(room),
            }
        )
        ok = save_user_state("baseball_live_draft_test", state)
        self.assertTrue(ok)


class TestLiveDraftCanonicalState(unittest.TestCase):
    def test_write_and_prepare_hydrates_runtime_room(self) -> None:
        session: dict = {}
        room = _sample_room()
        write_canonical_live_draft_state(session, room, reason="test", local_edit=True)
        self.assertIn(LIVE_DRAFT_STATE_KEY, session)
        session.pop(LIVE_DRAFT_ROOM_KEY)
        restored = prepare_live_draft_state(session)
        self.assertIsNotNone(restored)
        self.assertIsInstance(restored["pool"], pd.DataFrame)

    def test_cloud_restore_applies_when_not_dirty(self) -> None:
        session: dict = {}
        room = _sample_room()
        blob = room_to_persist_dict(room)
        cloud = {LIVE_DRAFT_STATE_KEY: blob, "page_filter_state": {"Live Draft Room": {LIVE_DRAFT_ROOM_KEY: blob}}}
        self.assertTrue(apply_cloud_live_draft_state_if_allowed(session, cloud))
        self.assertIsInstance(session[LIVE_DRAFT_ROOM_KEY]["pool"], pd.DataFrame)

    def test_disk_workspace_roundtrip(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Live Draft Room",
            "page_filter_state": {},
            LIVE_DRAFT_ROOM_KEY: _sample_room(),
            "live_draft_league_name": "Test League",
        }
        blob = build_baseball_disk_state(st)
        ok, err = verify_json_serializable(blob)
        self.assertTrue(ok, err)
        target: dict = {"page_filter_state": {}}
        st2 = MagicMock()
        st2.session_state = target
        apply_baseball_disk_state(st2, blob)
        prepare_live_draft_state(st2.session_state)
        room = st2.session_state.get(LIVE_DRAFT_ROOM_KEY)
        self.assertIsInstance(room, dict)
        self.assertIsInstance(room.get("pool"), pd.DataFrame)
        self.assertEqual(room.get("current_pick_index"), 2)


class TestLiveDraftRecommendationsAfterRestore(unittest.TestCase):
    def test_available_players_after_restore(self) -> None:
        from streamlit_app import live_draft_get_available

        room = _sample_room()
        blob = room_to_persist_dict(room)
        restored = room_from_persist_dict(blob)
        assert restored is not None
        available = live_draft_get_available(restored)
        self.assertFalse(available.empty)
        self.assertIn("Corbin Carroll", available["fullName"].astype(str).tolist())


class TestLiveDraftCommit(unittest.TestCase):
    def test_commit_force_save_marks_trace(self) -> None:
        st = MagicMock()
        session: dict = {"page_filter_state": {}}
        st.session_state = session
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_save:
            trace = commit_live_draft_room(st, session, _sample_room(), reason="manual_pick")
        mock_save.assert_called_once_with(st, reason="live_draft_pick")
        self.assertTrue(trace["saved"])
        self.assertTrue(trace["last_live_draft_save_success"])
        self.assertTrue(trace["saved_live_draft_state_present"])
        self.assertEqual(trace["saved_pick_count"], 2)


class TestLiveDraftCloudSave(unittest.TestCase):
    def test_live_draft_pick_not_cloud_blocked_by_blank_comparison(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        room = _sample_room()
        blob = room_to_persist_dict(room)
        state = {
            LIVE_DRAFT_STATE_KEY: blob,
            "comparison_state": {"players": []},
        }
        cloud_state = {"comparison_state": {"players": ["Player A", "Player B"]}}
        st = MagicMock()
        st.session_state = {}
        with patch("suite_cloud_state.load_cloud_full_session", return_value=(cloud_state, "ts")):
            reason = _cloud_autosave_blocked_reason(st, "baseball", state, save_reason="live_draft_pick")
        self.assertIsNone(reason)

    def test_autosave_not_blocked_when_live_draft_in_state(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        room = _sample_room()
        blob = room_to_persist_dict(room)
        state = {LIVE_DRAFT_STATE_KEY: blob, "comparison_state": {"players": []}}
        cloud_state = {"comparison_state": {"players": ["Player A"]}}
        st = MagicMock()
        st.session_state = {}
        with patch("suite_cloud_state.load_cloud_full_session", return_value=(cloud_state, "ts")):
            reason = _cloud_autosave_blocked_reason(st, "baseball", state, save_reason="autosave")
        self.assertIsNone(reason)

    def test_prepare_after_workspace_restore_on_non_live_page(self) -> None:
        st = MagicMock()
        st.session_state = {"active_page": "Historical Explorer", "page_filter_state": {}}
        blob = room_to_persist_dict(_sample_room())
        workspace = {
            "active_page": "Historical Explorer",
            "page_filter_state": {"Live Draft Room": {LIVE_DRAFT_ROOM_KEY: blob}},
            LIVE_DRAFT_STATE_KEY: blob,
        }
        apply_baseball_disk_state(st, workspace)
        prepare_live_draft_state(st.session_state)
        room = st.session_state.get(LIVE_DRAFT_ROOM_KEY)
        self.assertIsInstance(room, dict)
        self.assertIsInstance(room.get("pool"), pd.DataFrame)
        self.assertEqual(room.get("current_pick_index"), 2)


if __name__ == "__main__":
    unittest.main()
