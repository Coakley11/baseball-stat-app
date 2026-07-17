"""Regression tests for Live Draft deadline expiration tokens and timer lifecycle."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_expired_pick import (
    LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY,
    clear_autopick_backoff_for_manual,
    clear_autopick_state_for_pick_advance,
    handle_expired_pick_on_page,
    run_expired_autopick_once,
)
from live_draft_pick_commit import PickCommitResult
from live_draft_timer_logic import (
    LAST_PROCESSED_EXPIRATION_TOKEN_KEY,
    build_expiration_token,
    expiration_already_processed,
    live_draft_display_seconds,
    live_draft_pause_timer,
    live_draft_reset_timer,
    live_draft_resume_timer,
    live_draft_seconds_remaining,
    reconstruct_timer_deadline,
)


def _room(**overrides: object) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Primary Position": "3B"},
            {"playerID": "p3", "fullName": "Juan Soto", "Primary Position": "OF"},
        ]
    )
    now = time.time()
    base = {
        "status": "in_progress",
        "draft_room_id": "ROOM1",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "your_team": "Daniel",
            "timer_seconds": 10,
            "queue_auto_pick": True,
        },
        "your_team": "Daniel",
        "teams": ["Daniel", "Guest"],
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Daniel" if i % 2 == 0 else "Guest"}
            for i in range(4)
        ],
        "draft_board": [],
        "rosters": {"Daniel": [], "Guest": []},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_started_at": now - 20,
        "timer_deadline": now - 5,
        "timer_handled_index": -1,
    }
    base.update(overrides)
    return base


class ExpirationTokenTests(unittest.TestCase):
    def test_token_includes_draft_pick_team_deadline(self) -> None:
        room = _room()
        token = build_expiration_token(room)
        self.assertIn("ROOM1", token)
        self.assertIn("|0|", token)
        self.assertIn("Daniel", token)

    def test_mark_prevents_duplicate_processing(self) -> None:
        room = _room()
        token = build_expiration_token(room)
        from live_draft_timer_logic import mark_expiration_processed

        mark_expiration_processed(room, token)
        self.assertTrue(expiration_already_processed(room, token))


class TimerExpirationAdvanceTests(unittest.TestCase):
    @patch("live_draft_expired_pick.persist_applied_pick")
    @patch("live_draft_expired_pick.run_autopick_selection")
    @patch("live_draft_expired_pick.sync_expected_revision", return_value=None)
    @patch("live_draft_expired_pick._multiplayer_autopick_allowed", return_value=True)
    def test_expiration_advances_pick_and_restarts_timer(
        self,
        _host: MagicMock,
        _rev: MagicMock,
        mock_sel: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        room = _room()
        session = {"live_draft_room": room}

        def _select(r, session=None):
            r["draft_board"].append({"playerID": "p1", "fullName": "Aaron Judge", "Team": "Daniel"})
            r["current_pick_index"] = 1
            live_draft_reset_timer(r)
            return True, "Drafted Aaron Judge."

        mock_sel.side_effect = _select
        mock_persist.return_value = PickCommitResult(
            ok=True,
            message="Drafted Aaron Judge.",
            error="",
            commit_path="single_user",
            board_size_before=0,
            board_size_after=1,
            current_pick_index_before=0,
            current_pick_index_after=1,
        )
        token_before = build_expiration_token(room)
        result = run_expired_autopick_once(session, room)
        self.assertTrue(result.ok)
        self.assertEqual(room["current_pick_index"], 1)
        self.assertGreater(live_draft_seconds_remaining(room), 0)
        self.assertEqual(session.get(LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY), token_before)
        self.assertEqual(room.get(LAST_PROCESSED_EXPIRATION_TOKEN_KEY), token_before)

    @patch("live_draft_expired_pick.persist_applied_pick")
    @patch("live_draft_expired_pick.run_autopick_selection")
    @patch("live_draft_expired_pick.sync_expected_revision", return_value=None)
    @patch("live_draft_expired_pick._multiplayer_autopick_allowed", return_value=True)
    def test_expiration_processed_only_once(
        self,
        _host: MagicMock,
        _rev: MagicMock,
        mock_sel: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        room = _room()
        session = {"live_draft_room": room}

        def _select(r, session=None):
            r["draft_board"].append({"playerID": "p1", "fullName": "Aaron Judge"})
            r["current_pick_index"] = 1
            live_draft_reset_timer(r)
            return True, "ok"

        mock_sel.side_effect = _select
        mock_persist.return_value = PickCommitResult(
            ok=True,
            message="ok",
            error="",
            commit_path="single_user",
            board_size_before=0,
            board_size_after=1,
            current_pick_index_before=0,
            current_pick_index_after=1,
        )
        # Keep the same pre-advance room snapshot for a duplicate Streamlit rerun.
        room_stale = dict(room)
        room_stale["draft_board"] = []
        room_stale["current_pick_index"] = 0
        room_stale["timer_deadline"] = room["timer_deadline"]
        room_stale["timer_started_at"] = room["timer_started_at"]

        r1 = run_expired_autopick_once(session, room)
        self.assertTrue(r1.ok)
        self.assertEqual(mock_sel.call_count, 1)

        # Simulate a duplicate rerun that still sees the expired deadline token.
        session["live_draft_room"] = room_stale
        room_stale[LAST_PROCESSED_EXPIRATION_TOKEN_KEY] = session[LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY]
        r2 = run_expired_autopick_once(session, room_stale)
        self.assertTrue(r2.handled)
        self.assertEqual(mock_sel.call_count, 1)

    @patch("live_draft_expired_pick.persist_applied_pick")
    @patch("live_draft_expired_pick.run_autopick_selection")
    @patch("live_draft_expired_pick.sync_expected_revision", return_value=None)
    @patch("live_draft_expired_pick._multiplayer_autopick_allowed", return_value=True)
    def test_duplicate_reruns_do_not_create_duplicate_picks(
        self,
        _host: MagicMock,
        _rev: MagicMock,
        mock_sel: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        room = _room()
        session = {"live_draft_room": room}
        picks = {"n": 0}

        def _select(r, session=None):
            picks["n"] += 1
            r["draft_board"].append({"playerID": f"p{picks['n']}", "fullName": f"Player {picks['n']}"})
            r["current_pick_index"] = picks["n"]
            live_draft_reset_timer(r)
            return True, "ok"

        mock_sel.side_effect = _select
        mock_persist.return_value = PickCommitResult(
            ok=True,
            message="ok",
            error="",
            commit_path="single_user",
            board_size_before=0,
            board_size_after=1,
            current_pick_index_before=0,
            current_pick_index_after=1,
        )
        run_expired_autopick_once(session, room)
        # Second call with advanced room should not pick again for old token path.
        run_expired_autopick_once(session, room)
        self.assertEqual(picks["n"], 1)


class QueueAutopickTests(unittest.TestCase):
    def test_queued_player_selected_first(self) -> None:
        from live_draft_autopick import live_draft_auto_pick

        room = _room(
            timer_deadline=time.time() + 30,
            timer_started_at=time.time(),
        )
        session = {
            "live_draft_room": room,
            "draft_queue": ["Juan Soto", "Aaron Judge"],
            "your_team": "Daniel",
        }
        with patch("live_draft_autopick.score_available_for_rule") as mock_score:
            mock_score.return_value = (
                pd.DataFrame([{"fullName": "Aaron Judge", "playerID": "p1", "Primary Position": "OF"}]),
                [],
            )
            ok, msg = live_draft_auto_pick(room, session=session)
        self.assertTrue(ok, msg)
        self.assertIn("Juan Soto", msg)
        self.assertEqual(room["draft_board"][-1]["fullName"], "Juan Soto")
        mock_score.assert_not_called()

    def test_fallback_recommendation_when_queue_empty(self) -> None:
        from live_draft_autopick import live_draft_auto_pick

        room = _room(
            timer_deadline=time.time() + 30,
            timer_started_at=time.time(),
        )
        session = {"live_draft_room": room, "draft_queue": [], "your_team": "Daniel"}
        with patch(
            "live_draft_autopick.score_available_for_rule",
            return_value=(
                pd.DataFrame([{"fullName": "Aaron Judge", "playerID": "p1", "Primary Position": "OF"}]),
                [],
            ),
        ):
            ok, msg = live_draft_auto_pick(room, session=session)
        self.assertTrue(ok, msg)
        self.assertEqual(room["draft_board"][-1]["fullName"], "Aaron Judge")


class PauseResumeReloadTests(unittest.TestCase):
    def test_pause_preserves_remaining_time(self) -> None:
        room = _room(
            status="in_progress",
            timer_deadline=time.time() + 7.2,
            timer_started_at=time.time() - 2.8,
        )
        before = live_draft_seconds_remaining(room)
        preserved = live_draft_pause_timer(room)
        self.assertEqual(room["status"], "paused")
        self.assertEqual(preserved, before)
        self.assertEqual(int(room["paused_remaining_seconds"]), before)
        self.assertIsNone(room.get("timer_deadline"))

    def test_resume_restarts_from_preserved_time(self) -> None:
        room = _room(status="paused", timer_deadline=None, timer_started_at=None, paused_remaining_seconds=6)
        live_draft_resume_timer(room, 6)
        room["status"] = "in_progress"
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 5)
        self.assertLessEqual(remaining, 6)

    def test_reload_reconstructs_deadline(self) -> None:
        started = time.time() - 3
        room = _room(
            status="in_progress",
            timer_started_at=started,
            timer_deadline=None,
            config={"timer_seconds": 10, "num_teams": 2, "your_team": "Daniel"},
        )
        changed = reconstruct_timer_deadline(room)
        self.assertTrue(changed)
        self.assertIsNotNone(room.get("timer_deadline"))
        self.assertAlmostEqual(float(room["timer_deadline"]), started + 10, delta=0.5)
        self.assertGreater(live_draft_seconds_remaining(room), 0)

    def test_banner_and_control_display_match(self) -> None:
        room = _room(timer_deadline=time.time() + 4, timer_started_at=time.time() - 6)
        self.assertEqual(live_draft_display_seconds(room), live_draft_seconds_remaining(room))


class ManualNearZeroTests(unittest.TestCase):
    def test_manual_pick_blocks_second_timer_pick(self) -> None:
        room = _room()
        session = {"live_draft_room": room}
        token = build_expiration_token(room)
        clear_autopick_backoff_for_manual(session, room)
        # Simulate successful manual advance.
        room["current_pick_index"] = 1
        live_draft_reset_timer(room)
        clear_autopick_state_for_pick_advance(session, 1)
        self.assertEqual(session.get(LAST_PROCESSED_EXPIRATION_TOKEN_SESSION_KEY), token)
        # Stale expired view of the old pick must not auto-pick again.
        stale = _room()
        stale[LAST_PROCESSED_EXPIRATION_TOKEN_KEY] = token
        session["live_draft_room"] = stale
        with patch("live_draft_expired_pick.run_autopick_selection") as mock_sel:
            result = run_expired_autopick_once(session, stale)
            mock_sel.assert_not_called()
            self.assertTrue(result.handled)


class FinalPickStopsTimerTests(unittest.TestCase):
    @patch("live_draft_expired_pick.persist_applied_pick")
    @patch("live_draft_expired_pick.run_autopick_selection")
    @patch("live_draft_expired_pick.sync_expected_revision", return_value=None)
    @patch("live_draft_expired_pick._multiplayer_autopick_allowed", return_value=True)
    def test_final_pick_completes_and_stops_timer(
        self,
        _host: MagicMock,
        _rev: MagicMock,
        mock_sel: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        room = _room(current_pick_index=3, pick_order=[
            {"Pick": 1, "Round": 1, "Team": "Daniel"},
            {"Pick": 2, "Round": 1, "Team": "Guest"},
            {"Pick": 3, "Round": 2, "Team": "Guest"},
            {"Pick": 4, "Round": 2, "Team": "Daniel"},
        ])

        def _select(r, session=None):
            from live_draft_timer_logic import live_draft_clear_timer

            r["draft_board"].append({"playerID": "p1", "fullName": "Aaron Judge"})
            r["current_pick_index"] = 4
            r["status"] = "complete"
            live_draft_clear_timer(r)
            return True, "Draft complete."

        mock_sel.side_effect = _select
        mock_persist.return_value = PickCommitResult(
            ok=True,
            message="Draft complete.",
            error="",
            commit_path="single_user",
            board_size_before=3,
            board_size_after=4,
            current_pick_index_before=3,
            current_pick_index_after=4,
        )
        session = {"live_draft_room": room}
        result = run_expired_autopick_once(session, room)
        self.assertTrue(result.ok)
        self.assertEqual(room["status"], "complete")
        self.assertIsNone(room.get("timer_deadline"))
        # Further expire handling must no-op.
        result2 = handle_expired_pick_on_page(session, room)
        self.assertFalse(result2.ok)
        self.assertFalse(result2.should_rerun)


if __name__ == "__main__":
    unittest.main()
