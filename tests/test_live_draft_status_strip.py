"""Live Draft Room status strip (2026-11-06): on the clock, up next, your next pick, recent picks."""

from __future__ import annotations

import copy
import unittest

from live_draft_status_strip import draft_status, render_draft_status_strip, strip_html

TEAMS = ["Danny", "Barry", "Cara"]


def snake(rounds: int = 3) -> list[dict]:
    order, pick = [], 1
    for rnd in range(1, rounds + 1):
        seq = TEAMS if rnd % 2 else TEAMS[::-1]
        for team in seq:
            order.append({"Pick": pick, "Round": rnd, "Team": team})
            pick += 1
    return order


def room_after(picks: int) -> dict:
    order = snake()
    board = [{"Pick": s["Pick"], "Round": s["Round"], "Team": s["Team"], "Fantasy Team": s["Team"],
              "fullName": f"Player {s['Pick']}", "Primary Position": "OF"} for s in order[:picks]]
    return {"pick_order": order, "current_pick_index": picks, "draft_board": board}


class DraftStatusTests(unittest.TestCase):
    def test_on_the_clock_up_next_and_your_next_pick(self) -> None:
        status = draft_status(room_after(1), viewer_team="Cara")  # Barry on the clock, Cara next
        self.assertEqual((status["on_clock"], status["current_pick"], status["round"]), ("Barry", 2, 1))
        self.assertEqual((status["up_next"], status["up_next_pick"]), ("Cara", 3))
        self.assertEqual((status["viewer_next_pick"], status["picks_until_viewer"]), (3, 1))
        self.assertFalse(status["viewer_on_clock"])

    def test_snake_turn_and_the_viewer_on_the_clock(self) -> None:
        status = draft_status(room_after(3), viewer_team="Cara")  # round 2 starts with Cara again
        self.assertTrue(status["viewer_on_clock"])
        self.assertEqual((status["current_pick"], status["round"], status["picks_until_viewer"]), (4, 2, 0))
        self.assertIn("You&#x27;re on the clock", strip_html(status).replace("'", "&#x27;"))

    def test_recent_picks_newest_first_and_marked_for_the_viewer(self) -> None:
        status = draft_status(room_after(7), viewer_team="Danny")
        self.assertEqual([r["pick"] for r in status["recent"]], [7, 6, 5, 4, 3])
        html = strip_html(status)
        self.assertIn('class="ldr-chip mine"><b>#7</b> Player 7 OF · Danny', html)

    def test_nothing_is_painted_when_the_draft_is_over_and_the_room_is_never_changed(self) -> None:
        class St:
            def __init__(self):
                self.calls = 0

            def markdown(self, *_a, **_k):
                self.calls += 1

        done = room_after(9)
        st = St()
        self.assertFalse(render_draft_status_strip(st, done, viewer_team="Danny"))
        live = room_after(2)
        before = copy.deepcopy(live)
        self.assertTrue(render_draft_status_strip(st, live, viewer_team="Danny"))
        self.assertEqual(st.calls, 1)
        self.assertEqual(live, before)  # read-only

    def test_team_and_player_names_are_escaped(self) -> None:
        room = room_after(1)
        room["draft_board"][0]["fullName"] = "<b>x</b>"
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", strip_html(draft_status(room)))


if __name__ == "__main__":
    unittest.main()
