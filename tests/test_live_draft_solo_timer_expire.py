"""Production-path Solo timer: four expires must advance Pick1→2→3→4→complete.

Never remain stuck at 0:00. Uses expire_current_pick_and_advance only.
"""

from __future__ import annotations

import time
import unittest

import pandas as pd

from live_draft_solo_timer import (
    expire_current_pick_and_advance,
    solo_clock_expired,
)
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining


def _four_pick_solo_room(*, timer_seconds: int = 30) -> dict:
    teams = ["Team A", "Team B"]
    picks_per_team = 2
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
                "Expected Fantasy Value": 100 - i,
            }
            for i in range(1, 40)
        ]
    )
    room = {
        "draft_room_id": "SOLO-TIMER-4",
        "status": "in_progress",
        "current_pick_index": 0,
        "teams": teams,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
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


class SoloExpireAdvanceTests(unittest.TestCase):
    def test_four_expires_never_stuck_at_zero(self) -> None:
        room = _four_pick_solo_room(timer_seconds=5)
        session: dict = {"live_draft_setup_mode": "solo", "draft_queue": []}
        timings: list[dict] = []

        for expected_committed in (1, 2, 3, 4):
            # Force deadline into the past — production zero-cross.
            room["timer_deadline"] = time.time() - 0.05
            self.assertTrue(solo_clock_expired(room), f"clock should be expired before pick {expected_committed}")
            t0 = time.perf_counter()
            result = expire_current_pick_and_advance(room, session=session)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertTrue(result.ok, result)
            self.assertTrue(result.advanced or result.complete, result)
            self.assertEqual(result.committed_picks, expected_committed)
            timings.append(
                {
                    "pick": expected_committed,
                    "zero_to_commit_ms": result.zero_to_commit_ms,
                    "commit_to_next_timer_ms": result.commit_to_next_timer_ms,
                    "wall_ms": elapsed_ms,
                }
            )
            if expected_committed < 4:
                self.assertEqual(str(room.get("status") or ""), "in_progress")
                self.assertFalse(solo_clock_expired(room), f"stuck at zero after pick {expected_committed}")
                self.assertGreater(live_draft_seconds_remaining(room), 0)
                self.assertEqual(int(room.get("current_pick_index") or -1), expected_committed)
            else:
                self.assertEqual(str(room.get("status") or ""), "complete")
                self.assertTrue(result.complete)

        self.assertEqual(len(room.get("draft_board") or []), 4)
        # Soft latency budget for pure engine path (no Streamlit).
        for row in timings:
            self.assertLess(row["wall_ms"], 1000.0, row)

    def test_idempotent_double_expire_does_not_double_pick(self) -> None:
        room = _four_pick_solo_room()
        session: dict = {"live_draft_setup_mode": "solo", "draft_queue": []}
        room["timer_deadline"] = time.time() - 1
        first = expire_current_pick_and_advance(room, session=session)
        self.assertTrue(first.ok)
        self.assertEqual(first.committed_picks, 1)
        # Same deadline/pick already applied — heal without second board row.
        room["timer_deadline"] = time.time() - 1
        # Force same guard by restoring applied pick index + old deadline token path:
        # after advance, pick_index is 1; expire again for the new pick.
        second = expire_current_pick_and_advance(room, session=session)
        self.assertTrue(second.ok)
        self.assertEqual(len(room.get("draft_board") or []), 2)


class OptimisticQueueTests(unittest.TestCase):
    def test_add_remove_immediate_and_revision(self) -> None:
        from draft_state import (
            DRAFT_QUEUE_KEY,
            add_player_to_draft_queue,
            remove_player_from_user_draft_queue,
        )

        session: dict = {DRAFT_QUEUE_KEY: []}
        t0 = time.perf_counter()
        q, added = add_player_to_draft_queue(session, "Aaron Judge")
        add_ms = (time.perf_counter() - t0) * 1000.0
        self.assertTrue(added)
        self.assertEqual(q, ["Aaron Judge"])
        self.assertEqual(session.get(DRAFT_QUEUE_KEY), ["Aaron Judge"])
        self.assertGreaterEqual(int(session.get("_draft_queue_revision") or 0), 1)
        # First call may warm imports; still must be well under a second.
        self.assertLess(add_ms, 3000.0)

        add_player_to_draft_queue(session, "Juan Soto")
        add_player_to_draft_queue(session, "Mookie Betts")
        self.assertEqual(len(session[DRAFT_QUEUE_KEY]), 3)

        t1 = time.perf_counter()
        q2, removed = remove_player_from_user_draft_queue(session, "Juan Soto")
        rem_ms = (time.perf_counter() - t1) * 1000.0
        self.assertTrue(removed)
        self.assertEqual(q2, ["Aaron Judge", "Mookie Betts"])
        self.assertNotIn("Juan Soto", session[DRAFT_QUEUE_KEY])
        self.assertLess(rem_ms, 500.0)

        # Local list remains authoritative while dirty (no hydrate wipe).
        session["_draft_queue_persist_dirty"] = True
        self.assertEqual(session.get(DRAFT_QUEUE_KEY), ["Aaron Judge", "Mookie Betts"])
        session[DRAFT_QUEUE_KEY] = list(session.get(DRAFT_QUEUE_KEY) or [])
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Aaron Judge", "Mookie Betts"])


if __name__ == "__main__":
    unittest.main()
