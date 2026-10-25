"""U2 page wiring: each analytics page leads with its answer (reserved slot filled after the
rows are computed), keeps every existing widget key, and labels the rest "Explore more"."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def _branch(page_expr: str) -> str:
    start = APP.index(f"elif active_page == {page_expr}:")
    nxt = re.compile(r"^elif active_page ==|^if developer_mode_enabled\(\):", re.M).search(APP, start + 10)
    return APP[start:nxt.start()]


PAGES = {
    '"Comparison Tool"': ("compare_answer_slot", "_render_u2_comparison_answer",
                          ("compare_players", "compare_stat", "compare_x_axis_mode", "compare_year_range", "compare_age_range",
                           "compare_trend_mode", "compare_smooth_window", "sig_player_a_clean", "sig_player_b_clean", "sig_stats", "sig_alpha")),
    '"Career Totals"': ("career_answer_slot", "_render_u2_career_answer",
                        ("career_year_range_filter", "career_sort_stat_filter", "career_batting_hand_filter", "career_position_filter_mode",
                         "career_position_filter", "career_team_filter", "career_by_team_toggle_filter", "career_hof_case_analyze_btn")),
    '"Trend Value"': ("trend_answer_slot", "_render_u2_trend_answer",
                      ("trend_lag", "trend_min_g", "trend_position_filter", "trend_sort_col", "trend_use_draft_room_sync",
                       "trend_breakout_decline_selected_player")),
    '"Valuation"': ("value_answer_slot", "_render_u2_valuation_answer",
                    ("value_lag", "value_min_g", "value_position_filter", "value_use_draft_room_sync", "value_w_current",
                     "value_w_trend", "valuation_selected_player")),
    '"Fantasy Sleepers & Busts"': ("sleepers_answer_slot", "_render_u2_sleeper_answer",
                                   ("fantasy_market_window", "fantasy_market_format", "fantasy_market_min_g", "fantasy_market_min_ab",
                                    "fantasy_draft_projection_style", "fantasy_market_top_n", "fantasy_market_scatter_color")),
    '"ML Predictions"': ("ml_answer_slot", "_render_u2_ml_answer",
                         ("ml_lookback", "ml_min_games", "ml_max_players", "ml_min_ab", "ml_projection_style", "ml_regression_strength",
                          "ml_position_filter", "ml_sort_by", "ml_predictions_refresh_button", "ml_apply_tuning_button")),
}


class U2PageWiringTests(unittest.TestCase):
    def test_answer_first_order_and_keys_kept(self):
        for page, (slot, renderer, keys) in PAGES.items():
            body = _branch(page)
            with self.subTest(page=page):
                self.assertIn("u1.page_head(st,", body)
                self.assertNotIn("render_section_header(", body)
                self.assertLess(body.index(f"{slot} = st.container()"), body.index('u1.section_label(st, "Explore more'))
                self.assertIn(f"with {slot}:", body)
                self.assertIn(renderer, body)
                for key in keys:
                    self.assertIn(f'"{key}"', body, f"{page} lost widget key {key}")

    def test_one_default_chart_without_a_checkbox(self):
        for name in ("_render_u2_career_answer", "_render_u2_valuation_answer"):
            fn = APP[APP.index(f"def {name}("):]
            fn = fn[:fn.index("\ndef ", 10)]
            self.assertEqual(fn.count("top_bar_chart("), 1)
            self.assertIn("always_show=True", fn)
        trend = APP[APP.index("def _render_u2_trend_answer("):]
        self.assertIn("_u2_season_line_chart(", trend[:trend.index("\ndef ", 10)])

    def test_answer_actions_only_navigate(self):
        for name in ("_render_u2_comparison_answer", "_render_u2_career_answer", "_render_u2_trend_answer",
                     "_render_u2_valuation_answer", "_render_u2_sleeper_answer", "_render_u2_ml_answer"):
            fn = APP[APP.index(f"def {name}("):]
            fn = fn[:fn.index("\ndef ", 10)]
            for forbidden in ("draft_player(", "save_", "force_save", "persist_"):
                self.assertNotIn(forbidden, fn, f"{name} must not {forbidden}")

    def test_compare_pair_replaces_selection_and_navigates(self):
        fn = APP[APP.index("def _u2_compare_pair_cb("):]
        fn = fn[:fn.index("\ndef ", 10)]
        self.assertIn("write_canonical_comparison_state", fn)
        self.assertIn('_schedule_player_action_page_nav("Comparison Tool")', fn)

    def test_trend_focus_captured_before_trend_state_consumes_it(self):
        body = _branch('"Trend Value"')
        self.assertLess(body.index('st.session_state["_u2_trend_focus"]'), body.index("prepare_trend_value_page("))

    def test_monetization_gating_untouched(self):
        import baseball_monetization as bm

        self.assertIn("ML Predictions", bm.PAGE_FEATURES)
        self.assertEqual(dict(bm.ENFORCED_PAGE_FEATURES), {})

    def test_renamed_labels_keep_page_keys(self):
        from nav_groups import NAV_LABELS

        self.assertEqual(NAV_LABELS["Comparison Tool"], "⚖️ Compare Players")  # 📈 read as "trend"
        self.assertEqual(NAV_LABELS["Fantasy Sleepers & Busts"], "💎 Sleepers & Busts")
        self.assertIn('"Comparison Tool": "📈 Comparison Tool"', APP, "old label still maps to the key for saved sessions")
        self.assertIn('"Fantasy Sleepers & Busts": "💎 Fantasy Sleepers & Busts"', APP)


if __name__ == "__main__":
    unittest.main()
