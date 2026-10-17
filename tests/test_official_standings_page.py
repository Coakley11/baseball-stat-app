"""The Standings page shows official standings (finalized weeks) apart from the current-roster snapshot."""

from __future__ import annotations

import unittest
from pathlib import Path

from fantasy_season_results import finalize_period
from fantasy_season_results_ui import render_official_standings
from tests.test_season_results import AFTER_SEASON, COMM, WEEK1, _league, _lineup

APP = Path(__file__).resolve().parent.parent / "streamlit_app.py"


class _FakeSt:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args[0] if args else None))
            return args[1][0] if name == "selectbox" and len(args) > 1 and args[1] else None

        return _record

    def texts(self, kind):
        return [str(arg) for name, arg in self.calls if name == kind]


class StandingsPageWiringTests(unittest.TestCase):
    def test_page_renders_official_standings_before_the_roster_snapshot(self):
        src = APP.read_text(encoding="utf-8")
        page = src[src.index('elif active_page == "Fantasy Standings Tracker":'):]
        # U1: the answer (your place, from official standings), then the official table, then
        # the current-roster analysis — which never looks like the standings.
        answer = page.index("render_league_answer(st, st.session_state, _answer_ctx, navigate_to_page)")
        official = page.index("render_official_standings(st, _answer_ctx)")
        snapshot = page.index("st.subheader(_SNAPSHOT_LABEL)")
        self.assertLess(answer, official)
        self.assertLess(official, snapshot)
        self.assertNotIn('st.subheader("Live Fantasy Standings")', src)

    def test_legacy_weekly_table_is_hidden_for_ledger_leagues(self):
        src = APP.read_text(encoding="utf-8")
        self.assertIn("if active_league_context is not None and not _uses_season_ledger:", src)


class RenderOfficialStandingsTests(unittest.TestCase):
    def test_league_without_calendar_says_where_standings_come_from(self):
        ctx = {"league_rosters": {"A": {}, "B": {}}}
        st = _FakeSt()
        self.assertFalse(render_official_standings(st, ctx))
        self.assertEqual(st.texts("subheader"), ["League Standings (official)"])
        self.assertIn("current-roster snapshot, not the standings", st.texts("info")[0])
        self.assertEqual(st.texts("dataframe"), [])

    def test_calendar_without_final_week_shows_no_table(self):
        st = _FakeSt()
        self.assertTrue(render_official_standings(st, _league()))
        self.assertIn("No week is final yet", st.texts("info")[0])
        self.assertEqual(st.texts("dataframe"), [])

    def test_finalized_week_shows_points_table_without_components(self):
        ctx = _league()
        _lineup(ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])
        ok, err, _ = finalize_period(ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertTrue(ok, err)
        st = _FakeSt()
        self.assertTrue(render_official_standings(st, ctx))
        tables = [arg for name, arg in st.calls if name == "dataframe"]
        self.assertTrue(tables)
        shown = tables[0]
        self.assertEqual(list(shown["Team"]), ["A", "B"])
        self.assertNotIn("H", shown.columns)
        self.assertNotIn("AB", shown.columns)
        self.assertEqual(shown.loc[0, "AVG"], ".350")  # (5+2)/(10+10), formatted like a batting average
        self.assertIn("Sum of finalized weeks (1)", st.texts("caption")[0])


if __name__ == "__main__":
    unittest.main()
