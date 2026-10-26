"""Rate-stat rankings default to a qualified Min AB; counting stats and user-set values are left alone."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import pandas as pd

import page_transfers as pg_xfer
import rate_stat_qualification as rsq
from career_totals_state import is_career_state_key
from historical_state import is_historical_state_key
from leaderboards_state import is_leaderboards_state_key

ROOT = Path(__file__).resolve().parents[1]

# 2020 was a 60-game season; 1981 was strike-shortened.
LENGTHS = {2019: 162, 2020: 60, 2021: 162, 2022: 162, 2023: 162, 2024: 162, 2025: 162, 1981: 111}


class SeasonLengthTests(unittest.TestCase):
    def test_schedule_length_ignores_one_outlier_and_caps_at_162(self):
        df = pd.DataFrame(
            {
                "yearID": [2020] * 5 + [2025] * 6 + [1871] * 2,
                "G": [61, 60, 60, 58, 12, 163, 162, 162, 161, 150, 40, 33, 20],
            }
        )
        self.assertEqual(rsq.season_lengths(df), {2020: 60, 2025: 162, 1871: 33})

    def test_never_more_than_162(self):
        df = pd.DataFrame({"yearID": [1962] * 6, "G": [165, 164, 164, 163, 160, 100]})
        self.assertEqual(rsq.season_lengths(df), {1962: 162})

    def test_missing_games_column_gives_empty_mapping(self):
        self.assertEqual(rsq.season_lengths(pd.DataFrame({"yearID": [2024]})), {})


class QualifiedAbTests(unittest.TestCase):
    def test_single_season_rows_use_a_full_season(self):
        info = rsq.qualified_ab(LENGTHS, (2024, 2024), span=False)
        self.assertEqual(info["value"], 437)  # 2.7 * 162
        self.assertEqual(info["short_seasons"], [])

    def test_single_season_rows_over_a_range_note_shortened_seasons(self):
        info = rsq.qualified_ab(LENGTHS, (2019, 2021), span=False)
        self.assertEqual(info["value"], 437)
        self.assertEqual(info["short_seasons"], [2020])

    def test_span_totals_sum_the_seasons_in_range(self):
        info = rsq.qualified_ab(LENGTHS, (2020, 2025), span=True)
        self.assertEqual(info["value"], round(2.7 * (60 + 162 * 5)))  # 2349
        self.assertFalse(info["capped"])
        self.assertEqual(info["seasons"], 6)

    def test_span_of_one_season_matches_the_season_rule(self):
        self.assertEqual(rsq.qualified_ab(LENGTHS, (2024, 2024), span=True)["value"], 437)

    def test_long_spans_cap_at_a_career_minimum(self):
        info = rsq.qualified_ab({}, (1990, 2025), span=True)
        self.assertEqual(info["value"], rsq.MULTI_SEASON_CAP_AB)
        self.assertTrue(info["capped"])

    def test_reversed_or_bad_ranges_do_not_crash(self):
        self.assertEqual(rsq.qualified_ab(LENGTHS, (2025, 2020), span=True)["value"], 2349)
        self.assertEqual(rsq.qualified_ab(LENGTHS, None, span=False)["value"], 437)


class ResolveAbMinimumTests(unittest.TestCase):
    def test_rate_stat_sets_the_qualified_default(self):
        session = {}
        state = rsq.resolve_ab_minimum(session, "leaders", "BA", 2349)
        self.assertEqual(session["leaders_AB_min"], 2349)
        self.assertEqual(state, {"mode": "auto", "rate": True, "value": 2349, "qualified": 2349})

    def test_every_rate_stat_qualifies_and_counting_stats_do_not(self):
        for stat in ("BA", "OBP", "SLG", "OPS"):
            self.assertEqual(rsq.resolve_ab_minimum({}, "hist", stat, 437)["value"], 437, stat)
        for stat in ("HR", "RBI", "H", "SB", "AB", "score"):
            self.assertEqual(rsq.resolve_ab_minimum({}, "hist", stat, 437)["value"], 0, stat)

    def test_counting_rate_counting_switch_restores_zero(self):
        session = {}
        rsq.resolve_ab_minimum(session, "leaders", "HR", 2349)
        self.assertEqual(session["leaders_AB_min"], 0)
        rsq.resolve_ab_minimum(session, "leaders", "OPS", 2349)
        self.assertEqual(session["leaders_AB_min"], 2349)
        rsq.resolve_ab_minimum(session, "leaders", "RBI", 2349)
        self.assertEqual(session["leaders_AB_min"], 0)

    def test_year_range_change_follows_the_new_qualification(self):
        session = {}
        rsq.resolve_ab_minimum(session, "leaders", "BA", 2349)
        rsq.resolve_ab_minimum(session, "leaders", "BA", 437)
        self.assertEqual(session["leaders_AB_min"], 437)

    def test_manual_value_is_kept_across_sort_changes(self):
        session = {"leaders_AB_min": 150}
        rsq.mark_manual(session, "leaders")
        for stat in ("BA", "HR", "OPS"):
            state = rsq.resolve_ab_minimum(session, "leaders", stat, 2349)
            self.assertEqual(session["leaders_AB_min"], 150)
            self.assertEqual(state["mode"], "manual")

    def test_deliberate_zero_is_respected(self):
        session = {"career_AB_min": 0}
        rsq.mark_manual(session, "career")
        state = rsq.resolve_ab_minimum(session, "career", "BA", 3000)
        self.assertEqual(session["career_AB_min"], 0)
        self.assertEqual(state["value"], 0)
        self.assertIn("No AB minimum", rsq.qualification_caption(state, {"span": True}, "BA"))

    def test_restore_auto_returns_to_the_qualified_default(self):
        session = {"leaders_AB_min": 10}
        rsq.mark_manual(session, "leaders")
        rsq.restore_auto(session, "leaders")
        self.assertEqual(rsq.resolve_ab_minimum(session, "leaders", "SLG", 2349)["value"], 2349)

    def test_unchanged_value_is_not_rewritten(self):
        class Recording(dict):
            writes = 0

            def __setitem__(self, k, v):
                type(self).writes += 1
                super().__setitem__(k, v)

        session = Recording(leaders_AB_min=2349.0)
        rsq.resolve_ab_minimum(session, "leaders", "BA", 2349)
        self.assertEqual(Recording.writes, 0)


class CaptionTests(unittest.TestCase):
    def test_auto_caption_names_the_minimum_and_basis(self):
        info = rsq.qualified_ab(LENGTHS, (2020, 2025), span=True)
        state = rsq.resolve_ab_minimum({}, "leaders", "OPS", info["value"])
        text = rsq.qualification_caption(state, info, "OPS")
        self.assertIn("Qualified hitters only", text)
        self.assertIn("2,349 AB", text)
        self.assertIn("6 season(s)", text)

    def test_shortened_season_note(self):
        info = rsq.qualified_ab(LENGTHS, (1981, 1981), span=False)
        self.assertEqual(info["value"], round(2.7 * 111))
        info = rsq.qualified_ab(LENGTHS, (2019, 2020), span=False)
        state = rsq.resolve_ab_minimum({}, "hist", "BA", info["value"])
        self.assertIn("Shortened seasons in range (2020)", rsq.qualification_caption(state, info, "BA"))

    def test_manual_caption_and_counting_stat_silence(self):
        session = {"hist_AB_min": 200}
        rsq.mark_manual(session, "hist")
        state = rsq.resolve_ab_minimum(session, "hist", "BA", 437)
        self.assertIn("Minimum 200 AB", rsq.qualification_caption(state, {}, "BA"))
        state = rsq.resolve_ab_minimum({}, "hist", "HR", 437)
        self.assertEqual(rsq.qualification_caption(state, {}, "HR"), "")


class PersistenceAndTransferTests(unittest.TestCase):
    def test_mode_key_is_page_state_for_each_ranking_page(self):
        self.assertTrue(is_leaderboards_state_key("leaders_ab_qualification_mode"))
        self.assertTrue(is_historical_state_key("hist_ab_qualification_mode"))
        self.assertTrue(is_career_state_key("career_ab_qualification_mode"))

    def test_automatic_min_ab_does_not_travel_to_another_page(self):
        session = {"hist_AB_min": 437, "hist_HR_min": 20, "hist_ab_qualification_mode": "auto"}
        out = {}
        pg_xfer.copy_prefix_stat_mins(session, "hist", "career", out)
        self.assertNotIn("career_AB_min", out)
        self.assertEqual(out["career_HR_min"], 20)

    def test_user_set_min_ab_travels_and_stays_user_set(self):
        session = {"leaders_AB_min": 0, "leaders_ab_qualification_mode": "manual"}
        out = {}
        pg_xfer.copy_prefix_stat_mins(session, "leaders", "career", out)
        self.assertEqual(out["career_AB_min"], 0)
        self.assertEqual(out["career_ab_qualification_mode"], "manual")
        clean = pg_xfer.sanitize_session_keys(
            {"career_ab_qualification_mode": "bogus"}, {"career_ab_qualification_mode"}
        )
        self.assertEqual(clean, {})

    def test_legacy_sessions_without_mode_still_transfer(self):
        out = {}
        pg_xfer.copy_prefix_stat_mins({"career_AB_min": 300}, "career", "leaders", out)
        self.assertEqual(out["leaders_AB_min"], 300)


class CallSiteTests(unittest.TestCase):
    """The three ranking pages pass their sort stat and qualification; Trend/Valuation do not."""

    def test_ranking_pages_pass_qualification(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        for prefix, sort_var, range_var, span in (
            ("hist", "hist_sort_stat", "hist_year_range", "False"),
            ("career", "sort_stat_career", "range_career", "True"),
            ("leaders", "sort_stat_leaders", "range_leaders", "True"),
        ):
            pattern = (
                r'apply_stat_min_filters\(\s*\w+,\s*"' + prefix + r'",[^)]*?sort_stat=' + sort_var
                + r',\s*qualification=_qualified_ab\(SEASON_GAME_COUNTS, ' + range_var + r', span=' + span
            )
            self.assertRegex(src, re.compile(pattern, re.S), prefix)
        self.assertIn('apply_stat_min_filters(agg_trend, "trend")', src)
        self.assertIn('apply_stat_min_filters(agg_value, "value", on_change=valuation_filter_changed)', src)


if __name__ == "__main__":
    unittest.main()
