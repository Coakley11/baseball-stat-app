"""Start Live Draft board resolution and promotion."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_live_start import find_live_pool_row, replay_simulator_board_on_live_room


class TestDraftLiveStart(unittest.TestCase):
    def test_replay_skips_missing_players_and_continues(self) -> None:
        pool = pd.DataFrame(
            [
                {"fullName": "Mike Trout", "playerID": "1"},
                {"fullName": "Ronald Acuna Jr.", "playerID": "2"},
            ]
        )
        room = {
            "draft_board": [],
            "drafted_player_ids": [],
            "current_pick_index": 0,
            "pick_order": [{"Pick": 1}, {"Pick": 2}, {"Pick": 3}],
            "rosters": {},
        }
        board = pd.DataFrame(
            [
                {"Pick": 1, "Player": "Mike Trout"},
                {"Pick": 2, "Player": "Unknown Player"},
                {"Pick": 3, "Player": "Ronald Acuna Jr."},
            ]
        )
        picks: list[str] = []

        def make_pick(r, row, verdict=""):
            picks.append(str(row.get("fullName")))
            room["draft_board"].append(row)
            room["drafted_player_ids"].append(str(row.get("playerID")))
            room["current_pick_index"] = int(room.get("current_pick_index", 0)) + 1
            return True, "ok"

        def current_slot(r):
            idx = int(r.get("current_pick_index", 0))
            if idx >= len(r.get("pick_order", [])):
                return None
            return r["pick_order"][idx]

        def available(r):
            drafted = set(r.get("drafted_player_ids") or [])
            return pool[~pool["playerID"].isin(drafted)]

        trace = replay_simulator_board_on_live_room(
            room,
            board,
            make_pick_fn=make_pick,
            current_slot_fn=current_slot,
            available_fn=available,
        )
        self.assertEqual(trace["applied"], 2)
        self.assertEqual(trace["skipped"], 1)
        self.assertEqual(picks, ["Mike Trout", "Ronald Acuna Jr."])

    def test_last_name_pool_match(self) -> None:
        pool = pd.DataFrame([{"fullName": "Ronald Acuna Jr.", "playerID": "1"}])
        row = find_live_pool_row(pool, "Ronald Acuña Jr.")
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
