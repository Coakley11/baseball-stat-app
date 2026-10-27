"""The global working queue contract (Draft Strategy Assistant Phase 0, 2026-10-27).

One user-owned queue for Simulator, Solo/Live Draft and shared rooms. Only committed picks in
the active draft consume it (once each); Undo restores; reset/delete/import/room changes and
unrelated boards (a finished Live Draft, another league) leave it alone.
"""

from __future__ import annotations

import json
import unittest

import draft_room_state as drs
from draft_actions import _prune_drafted_from_queue
from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue

TEAMS = ["Team A", "Team B", "Team C", "Team D"]
QUEUE = [f"Player {i:02d}" for i in range(1, 11)]


def _session(**extra) -> dict:
    s = {"room_team_count": 4, "room_team_names": "\n".join(TEAMS), "room_rounds": 5, "room_your_team": "Team A"}
    s.update(extra)
    drs.ensure_simulator_board_for_settings(s)
    s[DRAFT_QUEUE_KEY] = list(QUEUE)
    return s


def _pick(s: dict, player: str) -> None:
    df = drs.ensure_runtime_draft_board(s)
    label = drs.open_pick_row_options(df)[0][1]
    res = drs.submit_board_pick_assignment(s, pick_label=label, player_match=player,
                                           pick_row_by_label=drs.pick_label_row_map(df), all_names=[player])
    assert str(res.get("message", "")).startswith("Set "), res
    _prune_drafted_from_queue(s)  # what the pick handlers and the queue panel run


def _finished_live_room(players: list[str]) -> dict:
    board = [{"Fantasy Team": "Team A", "fullName": p, "Pick": i + 1, "Round": 1} for i, p in enumerate(players)]
    return {"draft_room_id": "old-room", "status": "complete", "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2, "rounds": 1}, "draft_board": board, "current_pick_index": len(board)}


class ConsumptionTests(unittest.TestCase):
    def test_eight_drafted_leave_two_and_reruns_do_not_remove_more(self) -> None:
        s = _session()
        for p in QUEUE[:8]:
            _pick(s, p)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE[8:])
        for _ in range(3):
            _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE[8:])

    def test_non_queued_picks_change_nothing(self) -> None:
        s = _session()
        _pick(s, "Someone Else")
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_undo_restores_the_player_to_their_place(self) -> None:
        s = _session()
        _pick(s, QUEUE[3])
        self.assertNotIn(QUEUE[3], s[DRAFT_QUEUE_KEY])
        drs.undo_last_simulator_pick(s)
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)


    def test_undo_to_zero_picks_restores_even_after_the_empty_board_is_rebuilt(self) -> None:
        """Browser run: the Simulator rebuilds an empty board on render; that is not a new draft."""
        s = _session()
        _pick(s, QUEUE[1])
        drs.undo_last_simulator_pick(s)
        drs.ensure_simulator_board_for_settings(s)
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)


    def test_undo_restores_after_a_direct_drafted_removal(self) -> None:
        """Browser run: the pick handlers remove the drafted player directly; the ledger must still
        record his position, or Undo cannot put him back."""
        from draft_state import remove_drafted_player_from_active_queues

        s = _session()
        df = drs.ensure_runtime_draft_board(s)
        label = drs.open_pick_row_options(df)[0][1]
        drs.submit_board_pick_assignment(s, pick_label=label, player_match=QUEUE[2],
                                         pick_row_by_label=drs.pick_label_row_map(df), all_names=[QUEUE[2]])
        remove_drafted_player_from_active_queues(s, QUEUE[2])
        self.assertNotIn(QUEUE[2], s[DRAFT_QUEUE_KEY])
        drs.undo_last_simulator_pick(s)
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)


class LeftAloneTests(unittest.TestCase):
    def test_reset_neither_clears_nor_replenishes(self) -> None:
        s = _session()
        for p in QUEUE[:3]:
            _pick(s, p)
        drs.reset_simulator_board_only(s)
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE[3:])

    def test_delete_active_draft_keeps_the_queue(self) -> None:
        s = _session()
        drs.delete_active_draft(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_finished_live_draft_or_other_board_does_not_prune(self) -> None:
        s = _session(live_draft_room=_finished_live_room(QUEUE[:2]))
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_viewing_the_queue_panel_does_not_prune(self) -> None:
        s = _session(live_draft_room=_finished_live_room(QUEUE[:4]))
        for _ in range(3):
            _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_imported_board_does_not_consume(self) -> None:
        import pandas as pd

        from draft_import_pipeline import apply_validated_import_to_board

        s = _session()
        imported = drs.build_snake_board(TEAMS, rounds=5)
        imported.loc[0, "Player"], imported.loc[1, "Player"] = QUEUE[0], QUEUE[1]

        class _St:
            session_state = s

            @staticmethod
            def rerun():
                return None

        apply_validated_import_to_board(_St(), s, pd.DataFrame(imported))
        self.assertEqual(drs.table_pick_count(drs.ensure_runtime_draft_board(s)), 2)
        _prune_drafted_from_queue(s)
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)


class SharedRoomTests(unittest.TestCase):
    def _load(self, s: dict, code: str, pid: str, slot_queue: list[str]) -> None:
        from unittest import mock

        import draft_room_participant_state as drps

        slot = {"workflow": {"queue": slot_queue, "queue_revision": 0}}
        with mock.patch.object(drps, "participant_workflow_slot", return_value=slot), \
                mock.patch.object(drps, "resolve_participant_id", return_value=pid), \
                mock.patch.object(drps, "participant_state_for_room", return_value={}), \
                mock.patch.object(drps, "membership_team_for_participant", return_value="Team A"):
            drps.load_participant_workflow_into_session(s, code)

    def test_entering_or_switching_rooms_keeps_the_global_queue(self) -> None:
        s = {DRAFT_QUEUE_KEY: list(QUEUE)}
        self._load(s, "ROOM01", "user-1", ["Room Copy"])
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)
        self._load(s, "ROOM02", "user-1", [])
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_an_intentionally_empty_queue_is_not_refilled_by_a_room(self) -> None:
        s = {DRAFT_QUEUE_KEY: []}
        self._load(s, "ROOM01", "user-1", ["Old Room Copy", "Consumed Player"])
        self.assertEqual(s[DRAFT_QUEUE_KEY], [])

    def test_another_users_room_queue_never_replaces_this_one(self) -> None:
        s = {DRAFT_QUEUE_KEY: list(QUEUE)}
        self._load(s, "ROOM01", "user-1", [])
        self._load(s, "ROOM01", "user-2", ["Their Player"])
        self.assertEqual(s[DRAFT_QUEUE_KEY], QUEUE)

    def test_sign_out_drops_the_session_copy_for_the_next_account(self) -> None:
        import suite_auth

        s = {DRAFT_QUEUE_KEY: list(QUEUE), "_draft_queue_consumed": {"sim:0": {}}, suite_auth.AUTH_SESSION_KEY: True}
        suite_auth._clear_auth_session(s)
        self.assertNotIn(DRAFT_QUEUE_KEY, s)
        self.assertNotIn("_draft_queue_consumed", s)


class PersistenceTests(unittest.TestCase):
    def test_consumption_survives_reload_without_reapplying(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        class _St:
            def __init__(self, ss):
                self.session_state = ss

        s = _session()
        _pick(s, QUEUE[0])
        add_player_to_draft_queue(s, QUEUE[0])  # the user deliberately re-adds him
        blob = json.loads(json.dumps(build_baseball_disk_state(_St(s)), default=str))
        restored: dict = {}
        apply_baseball_disk_state(_St(restored), blob)
        drs.prepare_draft_room_state(restored)
        _prune_drafted_from_queue(restored)
        self.assertEqual(restored[DRAFT_QUEUE_KEY][:9], QUEUE[1:])


if __name__ == "__main__":
    unittest.main()
