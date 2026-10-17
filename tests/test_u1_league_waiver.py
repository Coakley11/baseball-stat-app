"""U1C: League Standings and Waiver Wire lead with the answer; numbers come from official data."""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

import pandas as pd

import u1_answers as u1a
from fantasy_season_results import finalize_period, official_standings
from tests.test_season_results import AFTER_SEASON, COMM, WEEK1, _league, _lineup


def _fake_st():
    st = mock.MagicMock()
    st.columns.side_effect = lambda spec, **_k: [mock.MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    return st


def _markdown_text(st) -> str:
    return " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)


class StrengthsAndGapsTests(unittest.TestCase):
    def test_from_the_official_table(self):
        ctx = _league()
        _lineup(ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])
        self.assertTrue(finalize_period(ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)[0])
        table, _ = official_standings(ctx)
        cats = ("R", "HR", "RBI", "SB", "AVG")
        a = u1a.category_strengths_and_gaps(table, "A", cats)
        b = u1a.category_strengths_and_gaps(table, "B", cats)
        # Week 1 totals (hand-checked): A R 4 HR 3 RBI 6; B R 3 HR 1 RBI 3; SB 0-0; AVG .350-.350.
        self.assertEqual(a["strengths"], ["R (1st)", "HR (1st)", "RBI (1st)", "SB (tied for 1st)", "AVG (tied for 1st)"])
        self.assertEqual(a["opportunities"], [])
        self.assertEqual(b["strengths"], ["SB (tied for 1st)", "AVG (tied for 1st)"])
        # Closest relative gaps for B: R 1 behind (1/4), then RBI 3 behind (3/6) or HR 2 behind (2/3).
        self.assertEqual(b["opportunities"], ["R: 1 behind A", "RBI: 3 behind A"])

    def test_unknown_team_or_empty(self):
        self.assertEqual(u1a.category_strengths_and_gaps(pd.DataFrame(), "A", ("HR",)), {"strengths": [], "opportunities": []})


class LeagueAnswerRenderTests(unittest.TestCase):
    def test_leads_with_place_and_never_uses_the_snapshot(self):
        from league_home_ui import render_league_answer

        ctx = _league()
        ctx["my_team_name"] = "B"
        ctx["league_name"] = "QA League"
        _lineup(ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])
        self.assertTrue(finalize_period(ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)[0])
        st = _fake_st()
        with mock.patch("fantasy_team_control.auth_required", return_value=False), \
                mock.patch("suite_user.get_account_user_id", return_value="local:qa"):
            self.assertTrue(render_league_answer(st, {}, ctx, navigate=lambda *a, **k: None))
        text = _markdown_text(st)
        self.assertIn("You&#x27;re 2nd of 2 · 3 points behind 1st", text)
        self.assertIn("Official standings", text)
        self.assertIn("Closest gain · R: 1 behind A", text)
        src = inspect.getsource(__import__("league_home_ui"))
        self.assertNotIn("score_current_roster_standings", src)
        self.assertNotIn("fantasy_current_standings", src)

    def test_no_league(self):
        from league_home_ui import render_league_answer

        st = _fake_st()
        self.assertFalse(render_league_answer(st, {}, None, navigate=lambda *a, **k: None))
        self.assertIn("No active league", _markdown_text(st))


class WaiverAnswerTests(unittest.TestCase):
    def test_top_adds_with_why_and_buttons_that_only_plan_or_compare(self):
        import fantasy_waiver_wire_ui as wui

        adds = pd.DataFrame([
            {"Player": "Elly De La Cruz", "Eligible Positions": "SS", "MLB Team": "CIN", "OPS": 0.812, "HR": 20,
             "BA": 0.26, "Why Add": "Fills an empty SS spot on your roster"},
            {"Player": "Jo Adell", "Eligible Positions": "OF", "MLB Team": "LAA", "OPS": 0.75, "HR": 15, "BA": 0.24,
             "Why Add": "helps SB"},
        ])
        roster = pd.DataFrame([{"Player": "Willy Adames", "Eligible Positions": "SS", "OPS": 0.690}])
        st = _fake_st()
        cb = mock.MagicMock(side_effect=lambda action, player: (action, player))
        wui._render_u1_waiver_answer(st, needs={"category_ranks": {"SB": 4}, "n_teams": 4, "weaknesses": ["SB"]},
                                     adds=adds, my_roster=roster, my_team="Team 1", position_filter="All positions",
                                     open_slots=["SS"], league_name="QA", player_action_cb=cb)
        text = _markdown_text(st)
        self.assertIn("Biggest needs: SB (4th of 4)", text)
        self.assertIn("Why this helps:</strong> Fills an empty SS spot on your roster", text)
        self.assertIn("Compared with Willy Adames (SS): OPS .812 vs .690", text)
        src = inspect.getsource(wui._render_u1_waiver_answer)
        self.assertNotIn("apply_waiver_move_pairs", src)
        self.assertNotIn("_on_confirm_waiver_move_click", src)
        self.assertIn("on_click=_on_plan_add_click", src)


if __name__ == "__main__":
    unittest.main()
