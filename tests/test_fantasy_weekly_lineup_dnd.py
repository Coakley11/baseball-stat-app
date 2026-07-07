"""Tests for weekly lineup drag-and-drop helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_weekly_lineup import validate_weekly_lineup
from fantasy_weekly_lineup_dnd import (
    assignments_from_sortable_containers,
    bench_container_header,
    build_sortable_containers,
    parse_container_slot_key,
    slot_container_header,
)


def _roster_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Catcher One", "player_id": "c1", "Primary Position": "C", "HR": 5, "RBI": 18, "SB": 1, "OPS": 0.720},
            {"Player": "Corner Bat", "player_id": "b1", "Primary Position": "1B", "HR": 12, "RBI": 40, "SB": 2, "OPS": 0.820},
            {"Player": "Middle Man", "player_id": "b2", "Primary Position": "2B", "HR": 4, "RBI": 20, "SB": 8, "OPS": 0.760},
            {"Player": "Bench Bat", "player_id": "bn1", "Primary Position": "OF", "HR": 2, "RBI": 6, "SB": 0, "OPS": 0.610},
        ]
    )


class WeeklyLineupDndTests(unittest.TestCase):
    def test_slot_header_round_trip(self) -> None:
        header = slot_container_header("2B", "Second Base")
        self.assertEqual(parse_container_slot_key(header), "2B")
        self.assertIn("Second Base", header)

    def test_build_containers_places_unassigned_on_bench(self) -> None:
        roster = _roster_df()
        slot_keys = [("C", "Catcher"), ("1B", "First Base")]
        assignments = {"C": "Catcher One", "1B": ""}
        containers = build_sortable_containers(slot_keys, assignments, roster)
        self.assertEqual(len(containers), 3)
        bench = next(c for c in containers if bench_container_header() == c["header"])
        self.assertIn("Corner Bat", bench["items"])
        self.assertIn("Bench Bat", bench["items"])

    def test_assign_player_from_bench_to_valid_slot(self) -> None:
        roster = _roster_df()
        slot_keys = [("C", "Catcher"), ("1B", "First Base")]
        containers = [
            {"header": slot_container_header("C", "Catcher"), "items": ["Catcher One"]},
            {"header": slot_container_header("1B", "First Base"), "items": ["Corner Bat"]},
            {"header": bench_container_header(), "items": ["Middle Man", "Bench Bat"]},
        ]
        assignments = assignments_from_sortable_containers(containers, slot_keys, roster)
        self.assertEqual(assignments["C"], "Catcher One")
        self.assertEqual(assignments["1B"], "Corner Bat")
        validation = validate_weekly_lineup(["C", "1B"], assignments, roster)
        self.assertTrue(validation["ok"])

    def test_duplicate_player_kept_in_one_slot_only(self) -> None:
        roster = _roster_df()
        slot_keys = [("C", "Catcher"), ("1B", "First Base")]
        containers = [
            {"header": slot_container_header("C", "Catcher"), "items": ["Catcher One"]},
            {"header": slot_container_header("1B", "First Base"), "items": ["Catcher One"]},
            {"header": bench_container_header(), "items": ["Corner Bat"]},
        ]
        assignments = assignments_from_sortable_containers(containers, slot_keys, roster)
        assigned_names = [assignments["C"], assignments["1B"]]
        self.assertEqual(assigned_names.count("Catcher One"), 1)

    def test_invalid_slot_assignment_flagged_by_validation(self) -> None:
        roster = _roster_df()
        slot_keys = [("C", "Catcher"), ("1B", "First Base")]
        containers = [
            {"header": slot_container_header("C", "Catcher"), "items": ["Corner Bat"]},
            {"header": slot_container_header("1B", "First Base"), "items": []},
            {"header": bench_container_header(), "items": ["Catcher One"]},
        ]
        assignments = assignments_from_sortable_containers(containers, slot_keys, roster)
        validation = validate_weekly_lineup(["C", "1B"], assignments, roster)
        self.assertFalse(validation["ok"])
        self.assertTrue(any("not eligible" in str(m).lower() for m in validation["messages"]))


if __name__ == "__main__":
    unittest.main()
