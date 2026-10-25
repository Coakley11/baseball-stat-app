"""U1A: grouped navigation (same page keys), Home as the default for new visits only,
top-of-page clutter moved off non-Home pages, and the Home league summary."""

from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path

import nav_groups as ng
from home_page import league_summary
from tests.test_season_results import AFTER_SEASON, COMM, WEEK1, WEEK2, _league, _lineup

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def _page_options() -> list[str]:
    for node in ast.parse(APP).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PAGE_OPTIONS" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError("PAGE_OPTIONS not found")


class NavGroupsTests(unittest.TestCase):
    def test_every_page_in_exactly_one_section(self):
        options = _page_options()
        self.assertEqual(sorted(ng.NAV_ORDER), sorted(options))
        self.assertEqual(len(ng.NAV_ORDER), len(set(ng.NAV_ORDER)))
        self.assertEqual(ng.SECTION_ORDER, ("Home", "Players", "Insights", "Draft", "My League", "Account"))
        self.assertEqual(ng.NAV_ORDER[0], "Home")

    def test_page_options_zero_keeps_its_fallback_role(self):
        self.assertEqual(_page_options()[0], "Historical Explorer")
        self.assertEqual(_page_options()[-1], "Home")

    def test_section_heading_css_is_well_formed(self):
        css = ng.sidebar_section_css("main_sidebar_page", list(ng.NAV_ORDER))
        self.assertEqual(css.count("{"), css.count("}"))
        import feature_identity as fi

        for section in ("Players", "Insights", "Draft", "My League", "Account"):
            fam = fi.family(section)
            # Each heading: the family icon and name, in the family colour (feature_identity).
            self.assertIn(f'content: "{fam.icon} {section.upper()}"', css)
            self.assertIn(f"color: {fam.color}", css)
        self.assertNotIn('HOME"', css)
        self.assertIn(".st-key-main_sidebar_page", css)

    def test_unregistered_page_is_appended_not_lost(self):
        self.assertEqual(ng.ordered_pages(["Leaderboards", "Brand New Page", "Home"]), ["Home", "Leaderboards", "Brand New Page"])

    def test_labels_only_for_real_pages(self):
        self.assertTrue(set(ng.NAV_LABELS) <= set(_page_options()))


class AppWiringTests(unittest.TestCase):
    def test_sidebar_radio_lists_grouped_order_with_same_key(self):
        block = APP[APP.index("_selected_page = st.sidebar.radio("):][:400]
        self.assertIn("_SIDEBAR_PAGE_ORDER", block)
        self.assertIn("key=MAIN_SIDEBAR_PAGE_KEY", block)

    def test_new_visit_defaults_to_home_only_when_nothing_chose_a_page(self):
        self.assertIn('st.session_state.get("active_page", "Home")', APP)

    def test_home_page_is_dispatched(self):
        self.assertIn('elif active_page == "Home":', APP)
        self.assertIn("render_home(st, st.session_state, navigate=navigate_to_page", APP)

    def test_hero_and_tutorial_prompt_are_off_regular_pages(self):
        chrome = APP[APP.index("def render_global_app_chrome"):APP.index("from stat_helpers import fmt_int")]
        self.assertIn('elif active_page != "Home" and active_page not in DRAFT_FOCUS_PAGES:', chrome)
        self.assertNotIn("app_tutorial.render_tutorial_header_bar()", chrome)
        self.assertIn("render_tutorial_bar=app_tutorial.render_tutorial_header_bar", APP)

    def test_old_and_new_labels_both_resolve_to_the_page_key(self):
        import streamlit_app as app

        self.assertEqual(app.normalize_page_key("🔄 Waiver Wire / Add-Drop Center"), "Waiver Wire / Add-Drop Center")
        self.assertEqual(app.normalize_page_key("🔄 Waiver Wire"), "Waiver Wire / Add-Drop Center")
        self.assertEqual(app.normalize_page_key("🏠 Home"), "Home")
        self.assertEqual(app.normalize_page_key("Home"), "Home")


class SessionNoticeTests(unittest.TestCase):
    def test_restored_session_notice_is_a_toast(self):
        from unittest import mock

        import suite_user_persistence as sup

        st = mock.MagicMock()
        st.session_state = {sup._SESSION_BANNER_KEY: "Loaded your last session"}
        sup.show_persistence_messages(st)
        st.toast.assert_called()
        st.success.assert_not_called()


class LeagueSummaryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _league()  # teams A, B; 3 weeks from 2026-04-06
        self.ctx["league_name"] = "QA League"

    def test_no_calendar(self):
        self.ctx["workflow"].pop("season_ledger", None)
        s = league_summary(self.ctx, "A", is_commissioner=True)
        self.assertEqual(s.next_action, "Set the season calendar")
        s = league_summary(self.ctx, "A", is_commissioner=False)
        self.assertIn("hasn't set", s.next_action)

    def test_before_any_final_week(self):
        early = datetime(2026, 4, 1, 16, tzinfo=timezone.utc)
        s = league_summary(self.ctx, "A", now=early)
        self.assertIsNone(s.place)
        self.assertEqual(s.next_action, "Set your Week 1 lineup")
        self.assertIn("upcoming", s.week_text)

    def test_place_gap_and_next_action_after_week_1(self):
        from fantasy_season_results import finalize_period

        _lineup(self.ctx, 1, "A", {"C": "Cal Raleigh", "OF": "Aaron Judge"}, ["Aaron Judge", "Cal Raleigh", "Bench Guy"])
        _lineup(self.ctx, 1, "B", {"C": "Adley Rutschman", "OF": "Juan Soto"}, ["Juan Soto", "Adley Rutschman"])
        ok, err, _ = finalize_period(self.ctx, 1, stats_df=WEEK1, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
        self.assertTrue(ok, err)
        a = league_summary(self.ctx, "A", is_commissioner=True, now=AFTER_SEASON)
        b = league_summary(self.ctx, "B", is_commissioner=False, now=AFTER_SEASON)
        # Week 1 (hand-checked in test_season_results): A wins R, HR, RBI; SB tied; AVG tied at .350.
        self.assertEqual((a.place, b.place), (1, 2))
        self.assertEqual(a.points - b.points, 3.0)
        self.assertEqual(a.gap_text, "3 points ahead of 2nd")
        self.assertEqual(b.gap_text, "3 points behind 1st")
        self.assertEqual(a.weeks_final, 1)
        # Week 2 has ended (AFTER_SEASON) but isn't final: the commissioner is told to finalize it.
        self.assertEqual(a.next_action, "Finalize Week 2")
        self.assertIn("waiting for the commissioner", b.next_action)

    def test_season_complete(self):
        from fantasy_season_results import finalize_period

        for week, stats in ((1, WEEK1), (2, WEEK2), (3, WEEK2)):
            _lineup(self.ctx, week, "A", {"C": "Cal Raleigh", "OF": "Juan Soto"}, ["Juan Soto", "Cal Raleigh"])
            _lineup(self.ctx, week, "B", {"C": "Adley Rutschman", "OF": "Aaron Judge"}, ["Aaron Judge", "Adley Rutschman"])
            ok, err, _ = finalize_period(self.ctx, week, stats_df=stats, actor=COMM, is_commissioner=True, now=AFTER_SEASON)
            self.assertTrue(ok, err)
        s = league_summary(self.ctx, "A", is_commissioner=True, now=AFTER_SEASON)
        self.assertEqual(s.week_text, "Season complete")
        self.assertEqual(s.weeks_final, 3)

    def test_no_league(self):
        self.assertIsNone(league_summary(None, "A"))
        self.assertIsNone(league_summary({"league_rosters": {}}, "A"))


if __name__ == "__main__":
    unittest.main()
