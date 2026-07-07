"""Tests for weekly lineup management (Phase 1)."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_league_context import get_active_league_context, save_simulator_league_context
from fantasy_weekly_lineup import (
    DEFAULT_WEEKLY_SLOTS,
    build_lineup_summary,
    compute_weekly_starter_totals,
    eligible_players_for_slot,
    get_saved_weekly_lineup,
    player_eligible_for_slot,
    resolve_weekly_lineup_slots,
    save_weekly_lineup,
    validate_weekly_lineup,
)


def _roster_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Catcher One", "Primary Position": "C", "R": 20, "HR": 5, "RBI": 18, "SB": 1, "AVG": 0.240},
            {"Player": "Corner Bat", "Primary Position": "1B", "R": 30, "HR": 12, "RBI": 40, "SB": 2, "AVG": 0.270},
            {"Player": "Middle Man", "Primary Position": "2B", "R": 25, "HR": 4, "RBI": 20, "SB": 8, "AVG": 0.255},
            {"Player": "Hot Corner", "Primary Position": "3B", "R": 28, "HR": 10, "RBI": 35, "SB": 3, "AVG": 0.265},
            {"Player": "Short Stop", "Primary Position": "SS", "R": 32, "HR": 8, "RBI": 28, "SB": 10, "AVG": 0.280},
            {"Player": "Outfield A", "Primary Position": "OF", "R": 35, "HR": 15, "RBI": 42, "SB": 12, "AVG": 0.290},
            {"Player": "Outfield B", "Primary Position": "OF", "R": 22, "HR": 6, "RBI": 24, "SB": 5, "AVG": 0.250},
            {"Player": "Outfield C", "Primary Position": "OF", "R": 18, "HR": 3, "RBI": 15, "SB": 7, "AVG": 0.245},
            {"Player": "Utility Guy", "Primary Position": "DH", "R": 26, "HR": 9, "RBI": 30, "SB": 4, "AVG": 0.260},
            {"Player": "Bench Bat", "Primary Position": "1B", "R": 8, "HR": 2, "RBI": 6, "SB": 0, "AVG": 0.210},
        ]
    )


class WeeklyLineupTests(unittest.TestCase):
    def test_default_slots_when_context_has_no_slot_config(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Catcher One", "Pick": 1}])
        _, context = save_simulator_league_context(session, board, my_team_name="Daniel")
        self.assertEqual(resolve_weekly_lineup_slots(context), list(DEFAULT_WEEKLY_SLOTS))

    def test_player_eligible_util_accepts_dh(self) -> None:
        self.assertTrue(player_eligible_for_slot(["DH"], "UTIL"))

    def test_validate_detects_missing_slot(self) -> None:
        roster = _roster_df()
        slots = ["C", "1B"]
        assignments = {"C": "Catcher One", "1B": ""}
        result = validate_weekly_lineup(slots, assignments, roster)
        self.assertFalse(result["ok"])
        self.assertTrue(any("First Base is empty" in str(m) for m in result["messages"]))

    def test_save_and_reload_weekly_lineup(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": name, "Pick": i + 1, "Primary Position": pos}
                for i, (name, pos) in enumerate(
                    [
                        ("Catcher One", "C"),
                        ("Corner Bat", "1B"),
                        ("Middle Man", "2B"),
                        ("Hot Corner", "3B"),
                        ("Short Stop", "SS"),
                        ("Outfield A", "OF"),
                        ("Outfield B", "OF"),
                        ("Outfield C", "OF"),
                        ("Utility Guy", "DH"),
                    ]
                )
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        roster = _roster_df()
        slots = list(DEFAULT_WEEKLY_SLOTS)
        assignments = {
            "C": "Catcher One",
            "1B": "Corner Bat",
            "2B": "Middle Man",
            "3B": "Hot Corner",
            "SS": "Short Stop",
            "OF": "Outfield A",
            "OF_2": "Outfield B",
            "OF_3": "Outfield C",
            "UTIL": "Utility Guy",
        }
        result = save_weekly_lineup(
            session,
            week=1,
            slots=slots,
            assignments=assignments,
            my_team="Daniel",
            roster_df=roster,
        )
        self.assertTrue(result.get("ok"))
        context = get_active_league_context(session)
        assert context is not None
        saved = get_saved_weekly_lineup(context, 1)
        assert saved is not None
        self.assertEqual(saved.get("week"), 1)
        self.assertEqual(saved["assignments"].get("C"), "Catcher One")
        self.assertIn("Bench Bat", saved.get("not_starting") or [])

    def test_compute_weekly_starter_totals(self) -> None:
        roster = _roster_df()
        assignments = {"C": "Catcher One", "1B": "Corner Bat"}
        totals = compute_weekly_starter_totals(roster, assignments)
        self.assertEqual(int(totals["totals"]["HR"]), 17)
        self.assertEqual(len(totals["starters"]), 2)

    def test_eligible_players_for_catcher_slot(self) -> None:
        roster = _roster_df()
        eligible = eligible_players_for_slot(roster, "C")
        self.assertIn("Catcher One", eligible)
        self.assertNotIn("Corner Bat", eligible)

    def test_build_lineup_summary_lists_starters_bench_and_open_slots(self) -> None:
        roster = _roster_df()
        slots = ["C", "1B", "2B"]
        assignments = {"C": "Catcher One", "1B": "Corner Bat", "2B": ""}
        summary = build_lineup_summary(slots, assignments, roster)
        self.assertTrue(any("Catcher One" in line for line in summary["starters"]))
        self.assertIn("Second Base", summary["open_slots"])
        self.assertIn("Bench Bat", summary["bench"])

    def test_waiver_filter_for_slot_label(self) -> None:
        from fantasy_weekly_lineup import waiver_filter_for_slot_label

        self.assertEqual(waiver_filter_for_slot_label("Catcher"), "C")
        self.assertEqual(waiver_filter_for_slot_label("Second Base"), "2B")
        self.assertEqual(waiver_filter_for_slot_label("Utility"), "DH/UTIL")


if __name__ == "__main__":
    unittest.main()
