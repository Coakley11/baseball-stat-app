"""Lineup board moves (hosted phone report 2026-10-26: dragging a player onto a circle did not assign).

Drag and tap send the same move event; the server applies it to its own lineup and says what
happened. Browser runs of the real component: scratchpad lineup_e2e.py (phone touch and desktop).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from fantasy_lineup_interactive_board import (
    BENCH_ZONE,
    apply_drop_event,
    apply_drop_event_with_message,
    resolve_board_move,
)

SLOTS = [("C", "Catcher"), ("2B", "Second Base"), ("SS", "Shortstop")]


def _roster() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "Catcher One", "Primary Position": "C", "Team": "Daniel"},
            {"Player": "Glove A", "Primary Position": "SS", "Positions": "SS/2B", "Team": "Daniel"},
            {"Player": "Glove B", "Primary Position": "2B", "Positions": "2B/SS", "Team": "Daniel"},
            {"Player": "Second Only", "Primary Position": "2B", "Team": "Daniel"},
        ]
    )


class ResolveBoardMoveTests(unittest.TestCase):
    def test_bench_to_open_slot(self) -> None:
        new, msg = resolve_board_move({"C": "", "2B": "", "SS": ""}, SLOTS, player="Catcher One", target="C",
                                      roster_df=_roster())
        self.assertEqual(new["C"], "Catcher One")
        self.assertEqual(msg, "Catcher One moved to Catcher.")

    def test_starters_swap_when_both_eligible(self) -> None:
        new, msg = resolve_board_move({"C": "", "2B": "Glove B", "SS": "Glove A"}, SLOTS, player="Glove A",
                                      target="2B", roster_df=_roster())
        self.assertEqual((new["2B"], new["SS"]), ("Glove A", "Glove B"))
        self.assertIn("Glove B moved to Shortstop", msg)

    def test_displaced_starter_goes_to_bench_and_is_named(self) -> None:
        new, msg = resolve_board_move({"C": "", "2B": "Second Only", "SS": "Glove A"}, SLOTS, player="Glove A",
                                      target="2B", roster_df=_roster())
        self.assertEqual((new["2B"], new["SS"]), ("Glove A", ""))
        self.assertIn("Second Only moved to the bench", msg)

    def test_ineligible_is_refused_with_reason(self) -> None:
        new, msg = resolve_board_move({"C": "", "2B": "", "SS": ""}, SLOTS, player="Catcher One", target="SS",
                                      roster_df=_roster())
        self.assertIsNone(new)
        self.assertIn("can't play Shortstop", msg)

    def test_starter_to_bench_and_bench_to_bench(self) -> None:
        new, msg = resolve_board_move({"C": "Catcher One", "2B": "", "SS": ""}, SLOTS, player="Catcher One",
                                      target=BENCH_ZONE, roster_df=_roster())
        self.assertEqual(new["C"], "")
        self.assertEqual(msg, "Catcher One moved to the bench.")
        new, msg = resolve_board_move({"C": "", "2B": "", "SS": ""}, SLOTS, player="Catcher One",
                                      target=BENCH_ZONE, roster_df=_roster())
        self.assertIsNone(new)
        self.assertIn("already on the bench", msg)

    def test_unknown_player_is_refused(self) -> None:
        new, msg = resolve_board_move({}, SLOTS, player="Not Rostered", target="C", roster_df=_roster())
        self.assertIsNone(new)
        self.assertIn("not on this roster", msg)


class DropEventAuthorityTests(unittest.TestCase):
    def test_move_applies_to_server_lineup_not_the_browsers_copy(self) -> None:
        """A stale browser map (it still shows Glove B at SS) must not overwrite the server's lineup."""
        server = {"C": "Catcher One", "2B": "", "SS": ""}
        event = {"player": "Glove A", "target": "2B", "assignments": {"C": "", "2B": "Glove A", "SS": "Glove B"}}
        new, msg = apply_drop_event_with_message(server, SLOTS, event, roster_df=_roster())
        self.assertEqual(new, {"C": "Catcher One", "2B": "Glove A", "SS": ""})
        self.assertEqual(msg, "Glove A moved to Second Base.")

    def test_refused_move_returns_reason(self) -> None:
        new, msg = apply_drop_event_with_message({}, SLOTS, {"player": "Catcher One", "target": "2B"},
                                                 roster_df=_roster())
        self.assertIsNone(new)
        self.assertIn("can't play Second Base", msg)
        self.assertIsNone(apply_drop_event({}, SLOTS, {"player": "Catcher One", "target": "2B"}, roster_df=_roster()))


class BoardComponentTouchContractTests(unittest.TestCase):
    """The browser tests drive these; this pins the pieces a phone needs."""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.html = (root / "lineup_board_component" / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_long_press_on_photo_does_not_open_the_phone_menu(self) -> None:
        self.assertIn("-webkit-touch-callout: none", self.html)
        self.assertIn('draggable="false"', self.html)
        self.assertIn('addEventListener("contextmenu"', self.html)

    def test_cancelled_drag_ends_at_last_finger_position(self) -> None:
        self.assertIn("cancelled ? ap.lastX : e.clientX", self.html)

    def test_tap_to_assign_and_server_notice_are_wired(self) -> None:
        self.assertIn("function handleFaceTap", self.html)
        self.assertIn("function tryMove", self.html)
        self.assertIn("PAYLOAD.notice", self.html)


if __name__ == "__main__":
    unittest.main()
