"""First-pick clock policy (owner decision, 2026-11-06).

1. The first-pick countdown starts only when the draft board and player pool are ready and the
   first manager can make a selection (the live-board paint).
2. A clock that expired solely during initial loading, before pick 1 was ever actionable, gets
   ONE initialization.
3. Once pick 1 has been actionable, its stored deadline survives reruns, page refreshes,
   reconnects and app restarts. A board reload never resets an expired clock; the configured
   timeout / autopick policy applies instead.
"""

from __future__ import annotations

import time
import unittest

from live_draft_ready_contract import prestart_expiration_blocked
from live_draft_state import room_from_persist_dict, room_to_persist_dict
from live_draft_timer_logic import (
    TIMER_LIVE_READY_AT_KEY,
    ensure_live_draft_timer_for_pick,
    first_pick_awaiting_live_ready,
    first_pick_expired_before_actionable,
    live_draft_seconds_remaining,
    live_draft_timer_expired_for_pick,
    mark_expiration_processed,
)


def _room(**extra) -> dict:
    room = {
        "room_code": "TMR001",
        "status": "in_progress",
        "teams": ["Team A", "Team B"],
        "config": {"timer_seconds": 60, "picks_per_team": 2, "teams": ["Team A", "Team B"]},
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
            {"Pick": 3, "Round": 2, "Team": "Team B"},
            {"Pick": 4, "Round": 2, "Team": "Team A"},
        ],
        "current_pick_index": 0,
        "draft_board": [],
        "timer_started_at": None,
        "timer_deadline": None,
        "timer_handled_index": -1,
    }
    room.update(extra)
    return room


def _restart(room: dict) -> dict:
    """App restart / reconnect: the room comes back from its stored blob."""
    return room_from_persist_dict(room_to_persist_dict(room))


class FirstPickStartsWhenActionable(unittest.TestCase):
    def test_start_leaves_pick_one_unarmed_until_the_live_board_paints(self) -> None:
        room = _room()
        self.assertTrue(first_pick_awaiting_live_ready(room))
        self.assertFalse(live_draft_timer_expired_for_pick(room))
        self.assertTrue(prestart_expiration_blocked(room))
        # Sidebar / timer-bar paints are not the readiness boundary.
        self.assertFalse(ensure_live_draft_timer_for_pick(room))
        self.assertIsNone(room["timer_deadline"])
        # The live board (pool ready, pick controls shown) arms a full clock.
        self.assertTrue(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertTrue(room.get(TIMER_LIVE_READY_AT_KEY))
        self.assertGreaterEqual(live_draft_seconds_remaining(room), 59)

    def test_unarmed_first_pick_survives_a_restart_unarmed(self) -> None:
        room = _restart(_room())
        self.assertIsNone(room.get("timer_deadline"))
        self.assertTrue(first_pick_awaiting_live_ready(room))


class ExpiredDuringLoadingGetsOneInitialization(unittest.TestCase):
    def _expired_before_ready(self) -> dict:
        now = time.time()
        return _room(timer_started_at=now - 75, timer_deadline=now - 15)

    def test_expired_before_actionable_is_not_autopicked_and_is_initialized_once(self) -> None:
        room = self._expired_before_ready()
        self.assertTrue(first_pick_expired_before_actionable(room))
        self.assertFalse(live_draft_timer_expired_for_pick(room), "no autopick before pick 1 was actionable")
        self.assertTrue(prestart_expiration_blocked(room))
        self.assertFalse(ensure_live_draft_timer_for_pick(room), "only the live board initializes it")

        self.assertTrue(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertTrue(room.get(TIMER_LIVE_READY_AT_KEY))
        self.assertGreaterEqual(live_draft_seconds_remaining(room), 59)
        self.assertFalse(first_pick_expired_before_actionable(room))

        # It expires again, now while actionable: that is a real expiry, never re-initialized.
        room["timer_started_at"] = time.time() - 70
        room["timer_deadline"] = time.time() - 10
        before = room["timer_deadline"]
        self.assertFalse(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertEqual(room["timer_deadline"], before)
        self.assertTrue(live_draft_timer_expired_for_pick(room), "the timeout / autopick policy applies")
        self.assertFalse(prestart_expiration_blocked(room))

    def test_the_one_initialization_survives_a_restart(self) -> None:
        room = self._expired_before_ready()
        ensure_live_draft_timer_for_pick(room, live_board_ready=True)
        restored = _restart(room)
        self.assertTrue(restored.get(TIMER_LIVE_READY_AT_KEY), "the live-ready stamp is stored with the room")
        self.assertAlmostEqual(float(restored["timer_deadline"]), float(room["timer_deadline"]), places=3)
        # Expire it after the restart: still a real expiry.
        restored["timer_deadline"] = time.time() - 5
        restored["timer_started_at"] = restored["timer_deadline"] - 60
        self.assertFalse(ensure_live_draft_timer_for_pick(restored, live_board_ready=True))
        self.assertTrue(live_draft_timer_expired_for_pick(restored))

    def test_a_processed_expiry_is_never_reinitialized(self) -> None:
        room = self._expired_before_ready()
        mark_expiration_processed(room, expired_pick_index=0)
        self.assertFalse(first_pick_expired_before_actionable(room))


class ActionableDeadlineIsDurable(unittest.TestCase):
    def _armed(self) -> dict:
        room = _room()
        ensure_live_draft_timer_for_pick(room, live_board_ready=True)
        return room

    def test_reruns_and_board_reloads_keep_the_running_deadline(self) -> None:
        room = self._armed()
        deadline = room["timer_deadline"]
        for _ in range(5):
            self.assertFalse(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
            self.assertFalse(ensure_live_draft_timer_for_pick(room))
        self.assertEqual(room["timer_deadline"], deadline)

    def test_refresh_reconnect_and_restart_keep_the_deadline(self) -> None:
        room = self._armed()
        deadline = float(room["timer_deadline"])
        for _ in range(3):
            room = _restart(room)
            ensure_live_draft_timer_for_pick(room, live_board_ready=True)
            self.assertAlmostEqual(float(room["timer_deadline"]), deadline, places=3)

    def test_board_reload_never_resets_an_expired_actionable_clock(self) -> None:
        room = self._armed()
        room["timer_started_at"] = time.time() - 90
        room["timer_deadline"] = time.time() - 30
        expired_at = room["timer_deadline"]
        room = _restart(room)
        self.assertFalse(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertAlmostEqual(float(room["timer_deadline"]), float(expired_at), places=3)
        self.assertEqual(live_draft_seconds_remaining(room), 0)
        self.assertTrue(live_draft_timer_expired_for_pick(room))

    def test_older_start_armed_room_painted_in_time_is_stamped_actionable(self) -> None:
        """A room armed at Start by older code that paints before expiry: the paint records that
        pick 1 is actionable, so its later expiry is real (no second chance)."""
        now = time.time()
        room = _room(timer_started_at=now - 10, timer_deadline=now + 50)
        self.assertFalse(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertTrue(room.get(TIMER_LIVE_READY_AT_KEY))
        room["timer_deadline"] = time.time() - 1
        self.assertFalse(first_pick_expired_before_actionable(room))
        self.assertTrue(live_draft_timer_expired_for_pick(room))

    def test_later_picks_never_reinitialize(self) -> None:
        now = time.time()
        room = _room(current_pick_index=1, draft_board=[{"Pick": 1, "Team": "Team A", "Player": "X"}],
                     timer_started_at=now - 70, timer_deadline=now - 10)
        self.assertFalse(first_pick_expired_before_actionable(room))
        self.assertFalse(ensure_live_draft_timer_for_pick(room, live_board_ready=True))
        self.assertTrue(live_draft_timer_expired_for_pick(room))


if __name__ == "__main__":
    unittest.main()
