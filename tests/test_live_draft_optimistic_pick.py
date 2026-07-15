"""Phase 2: optimistic manual pick — local board advances before durable persist."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_pick_commit import commit_manual_live_pick
from live_draft_pick_persist import (
    PICK_PERSIST_DIRTY_KEY,
    already_applied_pick_guard,
    flush_deferred_pick_persist,
    mark_applied_pick_guard,
    pick_guard_token,
)
from live_draft_rerun_scope import live_draft_expensive_recompute_required, mark_live_draft_optimistic_pick_tick
from live_draft_ui_cache import REC_CACHE_KEY, patch_live_draft_caches_after_pick


def _room() -> dict:
    pool = pd.DataFrame(
        [
            {
                "playerID": "judgea001",
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "Expected Fantasy Value": 90.0,
                "Model Rank": 1,
                "Market Rank": 1,
            },
            {
                "playerID": "sotoj001",
                "fullName": "Juan Soto",
                "Primary Position": "OF",
                "Expected Fantasy Value": 88.0,
                "Model Rank": 2,
                "Market Rank": 2,
            },
        ]
    )
    teams = ["Daniel", "Rival"]
    return {
        "status": "in_progress",
        "draft_room_id": "opt-room",
        "current_pick_index": 0,
        "config": {
            "your_team": "Daniel",
            "fantasy_format": "5x5 Roto",
            "num_teams": 2,
            "picks_per_team": 3,
            "slot_of": 2,
            "slot_p": 1,
        },
        "teams": teams,
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Daniel"},
            {"Pick": 2, "Round": 1, "Team": "Rival"},
            {"Pick": 3, "Round": 2, "Team": "Rival"},
            {"Pick": 4, "Round": 2, "Team": "Daniel"},
        ],
        "draft_board": [],
        "rosters": {t: [] for t in teams},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_seconds": 60,
    }


class OptimisticManualPickTests(unittest.TestCase):
    def test_optimistic_commit_mutates_without_force_save_or_shared(self) -> None:
        session: dict = {}
        room = _room()
        row = room["pool"].iloc[0].to_dict()
        with (
            patch("live_draft_pick_commit.persist_applied_pick") as mock_persist,
            patch("baseball_persistent_state.force_save_baseball_state") as mock_save,
            patch("draft_room_context.commit_shared_room_state") as mock_shared,
        ):
            result = commit_manual_live_pick(
                session,
                room,
                row,
                source="live_draft_room",
                optimistic=True,
            )
            mock_persist.assert_not_called()
            mock_save.assert_not_called()
            mock_shared.assert_not_called()
        self.assertTrue(result.ok)
        self.assertEqual(result.commit_path, "optimistic_local")
        self.assertEqual(len(room["draft_board"]), 1)
        self.assertEqual(room["current_pick_index"], 1)
        self.assertTrue(session.get(PICK_PERSIST_DIRTY_KEY))

    def test_idempotent_guard_blocks_duplicate(self) -> None:
        session: dict = {}
        room = _room()
        row = room["pool"].iloc[0].to_dict()
        token = pick_guard_token(room, player_id="judgea001", player_name="Aaron Judge")
        mark_applied_pick_guard(session, token)
        self.assertTrue(already_applied_pick_guard(session, token))
        result = commit_manual_live_pick(session, room, row, source="live_draft_room", optimistic=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.commit_path, "idempotent_guard")
        self.assertEqual(len(room["draft_board"]), 0)

    def test_rec_cache_patched_not_wiped(self) -> None:
        session: dict = {
            REC_CACHE_KEY: {
                "key": ("old",),
                "top_rec": pd.DataFrame(
                    [{"fullName": "Aaron Judge", "playerID": "judgea001"}, {"fullName": "Juan Soto", "playerID": "sotoj001"}]
                ),
                "best_avail": pd.DataFrame([{"fullName": "Aaron Judge", "playerID": "judgea001"}]),
                "pos_fit": pd.DataFrame(),
                "value_sleep": pd.DataFrame(),
            }
        }
        room = _room()
        room["current_pick_index"] = 1
        room["draft_board"] = [{"Player": "Aaron Judge"}]
        room["drafted_player_ids"] = ["judgea001"]
        patch_live_draft_caches_after_pick(session, room, player_id="judgea001", player_name="Aaron Judge")
        entry = session[REC_CACHE_KEY]
        self.assertTrue(entry.get("optimistic_hold"))
        top = entry["top_rec"]
        self.assertTrue(all(str(x) != "Aaron Judge" for x in top["fullName"].tolist()))
        self.assertIn("Juan Soto", top["fullName"].tolist())

    def test_optimistic_tick_skips_expensive(self) -> None:
        session: dict = {}
        mark_live_draft_optimistic_pick_tick(session)
        self.assertFalse(live_draft_expensive_recompute_required(session))

    def test_ten_consecutive_optimistic_picks(self) -> None:
        session: dict = {}
        room = _room()
        # Expand pool + pick order for 10 picks.
        names = [f"Player {i}" for i in range(10)]
        room["pool"] = pd.DataFrame(
            [
                {
                    "playerID": f"p{i}",
                    "fullName": n,
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 80 - i,
                    "Model Rank": i + 1,
                    "Market Rank": i + 1,
                }
                for i, n in enumerate(names)
            ]
        )
        room["pick_order"] = [
            {"Pick": i + 1, "Round": (i // 2) + 1, "Team": room["teams"][i % 2]} for i in range(10)
        ]
        t0 = time.perf_counter()
        with patch("live_draft_pick_commit.persist_applied_pick"):
            for i, n in enumerate(names):
                row = room["pool"].iloc[i].to_dict()
                result = commit_manual_live_pick(
                    session, room, row, source="live_draft_room", optimistic=True
                )
                self.assertTrue(result.ok, msg=result.message)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(len(room["draft_board"]), 10)
        self.assertEqual(room["current_pick_index"], 10)
        self.assertLess(elapsed_ms, 1000.0, f"10 optimistic picks took {elapsed_ms:.1f}ms")

    def test_deferred_flush_failure_keeps_local_board(self) -> None:
        session: dict = {}
        room = _room()
        session["live_draft_room"] = room
        row = room["pool"].iloc[0].to_dict()
        commit_manual_live_pick(session, room, row, source="live_draft_room", optimistic=True)
        self.assertEqual(len(room["draft_board"]), 1)
        with patch(
            "live_draft_pick_commit.persist_applied_pick",
            return_value=MagicMock(ok=False, message="shared down", error="shared_commit_failed"),
        ):
            ok = flush_deferred_pick_persist(session, st_obj=None)
            self.assertFalse(ok)
        self.assertEqual(len(session["live_draft_room"]["draft_board"]), 1)
        self.assertTrue(session.get(PICK_PERSIST_DIRTY_KEY))


class ProcessPendingShouldNotDoubleRerun(unittest.TestCase):
    @patch("draft_ui.draft_player", return_value={"ok": True, "message": "Drafted."})
    def test_should_rerun_false(self, _draft: MagicMock) -> None:
        from draft_ui import PENDING_MANUAL_PICK_KEY, process_pending_manual_draft_pick

        session = {
            PENDING_MANUAL_PICK_KEY: {
                "player_name": "Aaron Judge",
                "candidate_source": "test",
                "player_still_available_at_click": True,
            },
            "live_draft_room": _room(),
        }
        result = process_pending_manual_draft_pick(MagicMock(), session)
        self.assertTrue(result.get("ok"))
        self.assertFalse(result.get("should_rerun"))


if __name__ == "__main__":
    unittest.main()
