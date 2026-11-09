"""Strict positional eligibility (owner decision, 2026-11-08).

A player eligible only at 2B doesn't qualify for SS, and 1B and 3B aren't interchangeable. Multi-position players
fill each position they're listed at, OF takes LF/CF/RF, and UTIL/DH take any hitter. The same rule applies to
draft roster slots, the on-the-clock gate, recommendations, recap cards and lineups. An existing lineup that
breaks the rule is reported ("not eligible"), never silently changed.
"""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_lineup_fill import can_fill
from fantasy_slot_eligibility import _player_eligible_for_slot
from fantasy_weekly_lineup import validate_weekly_lineup
from live_draft_roster_enforcement import player_eligible_for_required_positions
from live_draft_roster_slots import _eligible_for_draft_slot, _eligible_for_open_need_recommendation
from player_photos import _eligible_for_slot as recap_eligible

RULES = (_eligible_for_draft_slot, _eligible_for_open_need_recommendation, _player_eligible_for_slot, recap_eligible)
CASES = [
    (["2B"], "SS", False), (["SS"], "2B", False), (["1B"], "3B", False), (["3B"], "1B", False),
    (["SS", "2B"], "SS", True), (["SS", "2B"], "2B", True), (["1B", "3B"], "3B", True),
    (["OF"], "OF", True), (["OF"], "UTIL", True), (["DH"], "UTIL", True), (["DH"], "SS", False),
    (["C"], "C", True), (["C"], "1B", False),
]


class StrictEligibilityTests(unittest.TestCase):
    def test_every_rule_agrees(self) -> None:
        for toks, slot, want in CASES:
            for rule in RULES:
                self.assertEqual(rule(list(toks), slot), want, f"{rule.__module__}.{rule.__name__}({toks}, {slot})")
            self.assertEqual(can_fill(toks, slot), want, f"can_fill({toks}, {slot})")

    def test_outfield_aliases(self) -> None:
        self.assertTrue(can_fill(["CF"], "OF"))

    def test_the_on_the_clock_gate(self) -> None:
        self.assertFalse(player_eligible_for_required_positions({"Primary Position": "2B"}, ["SS"]))
        self.assertTrue(player_eligible_for_required_positions({"Primary Position": "SS"}, ["SS"]))


class SavedLineupTests(unittest.TestCase):
    def test_an_old_invalid_lineup_is_reported_not_changed(self) -> None:
        roster = pd.DataFrame([{"Player": "Gleyber Torres", "Primary Position": "2B"},
                               {"Player": "Aaron Judge", "Primary Position": "OF"}])
        assignments = {"SS": "Gleyber Torres", "OF": "Aaron Judge"}
        result = validate_weekly_lineup(["SS", "OF"], dict(assignments), roster)
        self.assertFalse(result["ok"])
        self.assertIn({"slot": "SS", "player": "Gleyber Torres"}, result["ineligible_slots"])
        self.assertTrue(any("not eligible" in m for m in result["messages"]))
        self.assertEqual(assignments, {"SS": "Gleyber Torres", "OF": "Aaron Judge"})  # nothing removed


if __name__ == "__main__":
    unittest.main()
