"""Canonical Live Draft: ten consecutive auto-picks stay in sync across components.

Validates the production Solo expire path (expire_current_pick_and_advance):
- no duplicate picks
- no skipped picks
- no delayed batches (exactly one advance per expire)
- timer never frozen at zero after an advance
- sidebar / banner / snapshot agree on pick, team, revision
- drafted players leave recommendations and the queue immediately
"""

from __future__ import annotations

import time
import unittest

import pandas as pd

from draft_actions import draft_action_context
from live_draft_canonical_snapshot import (
    CANONICAL_SNAPSHOT_KEY,
    get_canonical_live_draft_snapshot,
    install_canonical_live_draft_snapshot,
)
from live_draft_solo_timer import expire_current_pick_and_advance, solo_clock_expired
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining
from live_draft_ui_cache import REC_CACHE_KEY


def _ten_pick_solo_room(*, timer_seconds: int = 5) -> dict:
    teams = ["Team A", "Team B"]
    picks_per_team = 5  # 10 total picks
    pick_order = []
    pick_n = 1
    for rnd in range(1, picks_per_team + 1):
        seq = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in seq:
            pick_order.append({"Pick": pick_n, "Round": rnd, "Team": team})
            pick_n += 1
    pool = pd.DataFrame(
        [
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": "OF",
                "Expected Fantasy Value": 200 - i,
                "Decision Score": 100.0 - i,
                "Draft Fit Score": 90.0 - i,
                "Positional Fit": 80.0 - i,
                "Scarcity Score": 70.0 - i,
            }
            for i in range(1, 80)
        ]
    )
    room = {
        "draft_room_id": "SOLO-CANON-10",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
        "revision": 1,
        "meta": {"sync": {"revision": 1}},
        "config": {
            "num_teams": 2,
            "picks_per_team": picks_per_team,
            "rounds": picks_per_team,
            "timer_seconds": timer_seconds,
            "teams": teams,
            "your_team": "Team A",
            "user_team": "Team A",
            "draft_setup_mode": "solo",
            "auto_pick_rule": "balanced recommendation",
            "queue_auto_pick": False,
        },
        "pool": pool,
    }
    live_draft_reset_timer(room)
    return room


class CanonicalTenAutoPickTests(unittest.TestCase):
    def test_ten_consecutive_auto_picks_stay_canonical(self) -> None:
        room = _ten_pick_solo_room()
        # Seed queue as names (canonical session form) so drafted prune matches.
        queue = [f"Player {i}" for i in range(1, 16)]
        session: dict = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": room,
            "draft_queue": list(queue),
            REC_CACHE_KEY: {
                "key": ("seed",),
                "top_rec": room["pool"].head(12).copy(),
                "best_avail": room["pool"].head(12).copy(),
                "pos_fit": room["pool"].head(8).copy(),
                "value_sleep": room["pool"].head(8).copy(),
            },
        }
        install_canonical_live_draft_snapshot(session, room, state_source="test_start")

        seen_player_ids: list[str] = []
        pick_numbers: list[int] = []
        teams_seen: list[str] = []

        def _fast_score(available, roster_df, rule_key, target_counts, config=None):
            scored = available.copy()
            if "Decision Score" not in scored.columns:
                scored["Decision Score"] = range(len(scored), 0, -1)
            return scored.sort_values("Decision Score", ascending=False), []

        from unittest.mock import patch

        from live_draft_pick_commit import PickCommitResult

        with patch("live_draft_autopick.score_available_for_rule", side_effect=_fast_score):
            with patch(
                "live_draft_pick_commit.persist_applied_pick",
                return_value=PickCommitResult(
                    ok=True,
                    message="ok",
                    error="",
                    commit_path="test",
                    board_size_before=0,
                    board_size_after=0,
                    current_pick_index_before=0,
                    current_pick_index_after=0,
                ),
            ):
                for expected_committed in range(1, 11):
                    room["timer_deadline"] = time.time() - 0.05
                    self.assertTrue(solo_clock_expired(room), f"clock expired before pick {expected_committed}")

                    before_idx = int(room.get("current_pick_index") or 0)
                    before_team = str((room.get("pick_order") or [{}])[before_idx].get("Team") or "")

                    t0 = time.perf_counter()
                    result = expire_current_pick_and_advance(room, session=session)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0

                    self.assertTrue(result.ok, result)
                    self.assertTrue(result.advanced or result.complete, result)
                    self.assertEqual(result.committed_picks, expected_committed)
                    # No delayed batch: exactly one new board row per expire.
                    self.assertEqual(len(room.get("draft_board") or []), expected_committed)
                    self.assertLess(elapsed_ms, 30000.0, f"pick {expected_committed} took {elapsed_ms:.1f}ms")

                    last = (room.get("draft_board") or [])[-1]
                    pid = str(last.get("playerID") or "")
                    pname = str(last.get("fullName") or last.get("Player") or "")
                    self.assertTrue(pid)
                    self.assertNotIn(pid, seen_player_ids, f"duplicate pick {pid}")
                    seen_player_ids.append(pid)

                    # Timer must restart immediately (never frozen at zero mid-draft).
                    if expected_committed < 10:
                        self.assertEqual(str(room.get("status") or ""), "in_progress")
                        self.assertFalse(solo_clock_expired(room), f"stuck at zero after pick {expected_committed}")
                        self.assertGreater(live_draft_seconds_remaining(room), 0)
                        self.assertEqual(int(room.get("current_pick_index") or -1), expected_committed)
                    else:
                        self.assertEqual(str(room.get("status") or ""), "complete")
                        self.assertTrue(result.complete)

                    # Canonical snapshot + draft_action_context must agree.
                    snap = get_canonical_live_draft_snapshot(session, room, refresh=True)
                    ctx = draft_action_context(session)
                    if expected_committed < 10:
                        expected_team = str((room.get("pick_order") or [{}])[expected_committed].get("Team") or "")
                        self.assertEqual(snap.get("current_pick_index"), expected_committed)
                        self.assertEqual(ctx.get("current_pick_index"), expected_committed)
                        self.assertEqual(str(snap.get("team_on_clock") or ""), expected_team)
                        self.assertEqual(str(ctx.get("on_clock_team") or ""), expected_team)
                        self.assertEqual(snap.get("revision"), ctx.get("revision"))
                        self.assertNotEqual(before_team, "")
                        pick_numbers.append(int(snap.get("current_pick") or 0))
                        teams_seen.append(str(snap.get("team_on_clock") or ""))

                    # Drafted player must leave recommendations and the account queue.
                    rec = session.get(REC_CACHE_KEY) or {}
                    for table_key in ("top_rec", "best_avail", "pos_fit", "value_sleep"):
                        table = rec.get(table_key)
                        if isinstance(table, pd.DataFrame) and not table.empty and "playerID" in table.columns:
                            ids = set(table["playerID"].astype(str))
                            self.assertNotIn(pid, ids, f"{pname} still in {table_key}")
                    queue_now = session.get("draft_queue") or []
                    queued_names = {
                        str(x.get("fullName") or x.get("Player") or x).strip().lower()
                        if isinstance(x, dict)
                        else str(x).strip().lower()
                        for x in queue_now
                    }
                    self.assertNotIn(pname.lower(), queued_names)

        self.assertEqual(len(seen_player_ids), 10)
        self.assertEqual(len(set(seen_player_ids)), 10)
        # Pick numbers must be strictly increasing with no skips while in progress.
        self.assertEqual(pick_numbers, list(range(2, 11)))
        self.assertIn(CANONICAL_SNAPSHOT_KEY, session)


if __name__ == "__main__":
    unittest.main()
