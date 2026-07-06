"""Tests for end-of-draft required-position enforcement."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_roster_enforcement import (
    check_required_position_gate,
    compute_required_position_enforcement,
    count_team_picks_remaining,
    format_required_pick_message,
    player_eligible_for_required_positions,
)


def _room_with_picks(team: str, *, idx: int, total_for_team: int) -> dict:
    order = [{"Team": team, "Pick": i + 1} for i in range(total_for_team)]
    return {"pick_order": order, "current_pick_index": idx, "config": {"slots": {"C": 1, "1B": 1, "OF": 3, "BN": 4}}}


class LiveDraftRosterEnforcementTests(unittest.TestCase):
    def test_count_team_picks_remaining(self) -> None:
        room = _room_with_picks("Daniel", idx=1, total_for_team=3)
        self.assertEqual(count_team_picks_remaining(room, "Daniel"), 2)
        self.assertEqual(count_team_picks_remaining(room, "Rival"), 0)

    def test_enforcement_when_picks_equal_open_slots(self) -> None:
        roster = pd.DataFrame([{"Primary Position": "1B", "Expected Fantasy Value": 0.8}])
        config = {"slots": {"C": 1, "1B": 1, "OF": 0, "BN": 0}}
        active, required = compute_required_position_enforcement(roster, config, picks_remaining=1)
        self.assertTrue(active)
        self.assertEqual(required, ["C"])

    def test_no_enforcement_when_picks_exceed_open_slots(self) -> None:
        roster = pd.DataFrame([{"Primary Position": "1B", "Expected Fantasy Value": 0.8}])
        config = {"slots": {"C": 1, "1B": 1, "OF": 0, "BN": 0}}
        active, required = compute_required_position_enforcement(roster, config, picks_remaining=3)
        self.assertFalse(active)
        self.assertEqual(required, [])

    def test_format_required_pick_message(self) -> None:
        msg = format_required_pick_message(["C"])
        self.assertIn("C", msg)
        self.assertIn("before the draft ends", msg)
        msg2 = format_required_pick_message(["C", "1B"])
        self.assertIn("C", msg2)
        self.assertIn("1B", msg2)

    def test_player_eligible_multi_position(self) -> None:
        row = {"Primary Position": "C,1B"}
        self.assertTrue(player_eligible_for_required_positions(row, ["C"]))
        self.assertTrue(player_eligible_for_required_positions(row, ["1B"]))
        self.assertFalse(player_eligible_for_required_positions(row, ["SS"]))

    def test_gate_blocks_ineligible_player(self) -> None:
        room = {
            **_room_with_picks("Daniel", idx=2, total_for_team=3),
            "rosters": {"Daniel": [{"Primary Position": "1B"}]},
        }
        enf = compute_required_position_enforcement(
            pd.DataFrame(room["rosters"]["Daniel"]),
            room["config"],
            picks_remaining=1,
        )
        self.assertTrue(enf[0])
        self.assertFalse(player_eligible_for_required_positions({"Primary Position": "P"}, enf[1]))
        self.assertTrue(player_eligible_for_required_positions({"Primary Position": "C"}, enf[1]))


if __name__ == "__main__":
    unittest.main()
