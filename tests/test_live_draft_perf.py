"""Tests for Live Draft Room performance instrumentation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from live_draft_perf import (
    LIVE_DRAFT_PERF_ACTIONS_KEY,
    PHASE_DRAFT_PICK,
    PHASE_QUEUE_ADD,
    PHASE_QUEUE_REMOVE,
    PHASE_RECOMMENDATIONS,
    live_draft_perf_action,
    record_live_draft_action,
    recent_live_draft_actions,
    summarize_live_draft_phases,
    summarize_pick_commit_phases,
)
from live_draft_state import LIVE_DRAFT_PREPARE_FP_KEY, prepare_live_draft_state


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {
                "playerID": "of1",
                "fullName": "Outfield Star",
                "Primary Position": "OF",
                "Expected Fantasy Value": 90.0,
                "Model Rank": 5,
                "Market Rank": 5,
            },
        ]
    )
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_room_id": "room-test-1",
        "config": {"num_teams": 2, "picks_per_team": 5, "fantasy_format": "5x5 Roto"},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class LiveDraftPerfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dev_patch = patch(
            "page_perf_phases.dev_perf_enabled",
            return_value=True,
        )
        self.dev_patch.start()

    def tearDown(self) -> None:
        self.dev_patch.stop()

    def test_record_live_draft_action_appends_row(self) -> None:
        session: dict = {"_page_perf_ns": {"timings": {}}}
        record_live_draft_action(session, "queue_add", 0.012, phase=PHASE_QUEUE_ADD, cache="miss")
        rows = recent_live_draft_actions(session)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "queue_add")
        self.assertEqual(rows[0]["phase"], PHASE_QUEUE_ADD)
        self.assertEqual(rows[0]["cache"], "miss")

    def test_live_draft_perf_action_context_manager(self) -> None:
        session: dict = {"_page_perf_ns": {"timings": {}}}
        with live_draft_perf_action(session, "draft_player", phase=PHASE_DRAFT_PICK):
            pass
        rows = session.get(LIVE_DRAFT_PERF_ACTIONS_KEY)
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(float(rows[0]["elapsed_ms"]), 0.0)

    def test_queue_add_remove_record_actions(self) -> None:
        from draft_state import add_player_to_draft_queue, remove_player_from_draft_queue

        session: dict = {"draft_queue": [], "_page_perf_ns": {"timings": {}}}
        add_player_to_draft_queue(session, "Aaron Judge")
        remove_player_from_draft_queue(session, "Aaron Judge")
        actions = [r["action"] for r in recent_live_draft_actions(session)]
        self.assertIn("queue_add", actions)
        self.assertIn("queue_remove", actions)

    def test_summarize_live_draft_phases(self) -> None:
        session = {
            "_page_perf_ns": {
                "timings": {
                    "live_draft_recommendations": 0.45,
                    "live_draft_score_available": 0.32,
                    "roster_tracker": 0.08,
                    "other_page": 1.0,
                }
            }
        }
        top = summarize_live_draft_phases(session, limit=5)
        names = [name for name, _ in top]
        self.assertIn("live_draft_recommendations", names)
        self.assertNotIn("other_page", names)

    def test_summarize_pick_commit_phases(self) -> None:
        session = {
            "_page_perf_ns": {
                "timings": {
                    "live_draft_pick_canonical_patch": 0.12,
                    "live_draft_pick_make_pick": 0.03,
                    "live_draft_pick_commit": 0.15,
                }
            }
        }
        phases = summarize_pick_commit_phases(session, limit=5)
        names = [name for name, _ in phases]
        self.assertIn("live_draft_pick_canonical_patch", names)
        self.assertNotIn("live_draft_pick_commit", names)

    def test_patch_canonical_uses_session_blob_without_deepcopy(self) -> None:
        from live_draft_state import (
            LIVE_DRAFT_ROOM_KEY,
            LIVE_DRAFT_STATE_KEY,
            patch_canonical_live_draft_pick_fields,
            room_to_persist_dict,
        )
        from live_draft_pick_engine import live_draft_make_pick

        room = _sample_room()
        session: dict = {
            LIVE_DRAFT_ROOM_KEY: room,
            LIVE_DRAFT_STATE_KEY: room_to_persist_dict(room),
        }
        pool_ref = id(session[LIVE_DRAFT_STATE_KEY].get("pool_records"))
        player = {"playerID": "of1", "fullName": "Outfield Star", "Primary Position": "OF"}
        live_draft_make_pick(room, player, enrich_pick_context=False)
        patch_canonical_live_draft_pick_fields(session, room, reason="test_pick", local_edit=True)
        blob = session[LIVE_DRAFT_STATE_KEY]
        self.assertEqual(id(blob.get("pool_records")), pool_ref)
        self.assertEqual(len(blob.get("draft_board") or []), 1)

    def test_prepare_short_circuits_on_second_call(self) -> None:
        session: dict = {
            "_page_perf_ns": {"timings": {}},
            "live_draft_state": {
                "draft_room_id": "room-test-1",
                "status": "in_progress",
                "current_pick_index": 0,
                "draft_board": [],
                "pool_records": [{"playerID": "p1", "fullName": "Player 1", "Primary Position": "OF"}],
                "pool_columns": ["playerID", "fullName", "Primary Position"],
            },
            "live_draft_room": _sample_room(),
        }
        prepare_live_draft_state(session)
        first = float(session.get("_page_perf_ns", {}).get("timings", {}).get("live_draft_prepare_state") or 0.0)
        prepare_live_draft_state(session)
        second_total = float(session.get("_page_perf_ns", {}).get("timings", {}).get("live_draft_prepare_state") or 0.0)
        self.assertIn(LIVE_DRAFT_PREPARE_FP_KEY, session)
        self.assertLess(second_total - first, max(first, 0.05))


class LiveDraftPerfBaselineTests(unittest.TestCase):
    """Programmatic baseline for pool cache path (avoids full streamlit_app import)."""

    def setUp(self) -> None:
        self.dev_patch = patch(
            "page_perf_phases.dev_perf_enabled",
            return_value=True,
        )
        self.dev_patch.start()

    def tearDown(self) -> None:
        self.dev_patch.stop()

    def test_baseline_available_pool_cache_hit(self) -> None:
        from live_draft_ui_cache import cached_live_draft_get_available

        session: dict = {"_page_perf_ns": {"timings": {}}}
        room = _sample_room()

        cached_live_draft_get_available(session, room)
        cached_live_draft_get_available(session, room)

        timings = dict(session.get("_page_perf_ns", {}).get("timings") or {})
        self.assertIn("live_draft_available_pool", timings)
        actions = recent_live_draft_actions(session)
        cache_hits = sum(1 for r in actions if r.get("cache") == "hit")
        cache_misses = sum(1 for r in actions if r.get("cache") == "miss")
        self.assertEqual(cache_misses, 1)
        self.assertEqual(cache_hits, 1)


if __name__ == "__main__":
    unittest.main()
