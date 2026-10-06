"""Mobile M5 — Analytics/charts/wide-table wiring contract (presentation only).

Source-regex checks in the style of the M3/M4 wiring tests: confirms the Mobile
M5 treatments (column pinning, matplotlib legibility, filter-row compaction) are
actually attached to the right call sites in ``streamlit_app.py``, without
re-deriving the whole file or requiring a live Streamlit run.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
WAIVER_SRC = (ROOT / "fantasy_waiver_wire_ui.py").read_text(encoding="utf-8")


class RenderOutputTablePinWiringTests(unittest.TestCase):
    """Every wide analytics table identified in the M5 audit pins its leading
    identity columns; narrow/non-identity-leading tables are deliberately left
    unpinned (Stat-by-stat significance tests, advanced trend intelligence,
    ML accuracy/feature-importance/age-curve) — checked here by their absence."""

    def _pin_args_for(self, key: str) -> str:
        """Text between this render_output_table(...) call's key= and its closing paren."""
        idx = APP_SRC.index(f'key="{key}"')
        window = APP_SRC[idx: idx + 400]
        # Calls are short; the first ')' on its own after key= closes this call in
        # every site we wired (none of them embed a nested call after key=).
        return window

    def test_historical_explorer_pins_year_and_player(self) -> None:
        self.assertIn('pin_columns=("Year", "Player")', self._pin_args_for("historical_explorer"))

    def test_career_totals_pins_player(self) -> None:
        self.assertIn('pin_columns=("Player",)', self._pin_args_for("career_totals"))

    def test_leaderboards_pins_player(self) -> None:
        self.assertIn('pin_columns=("Player",)', self._pin_args_for("leaderboards"))

    def test_comparison_yearly_pins_year_and_player(self) -> None:
        self.assertIn('pin_columns=("Year", "Player")', self._pin_args_for("comparison_yearly"))

    def test_comparison_career_pins_player(self) -> None:
        self.assertIn('pin_columns=("Player",)', self._pin_args_for("comparison_career"))

    def test_trend_breakout_and_decline_pin_player_and_position(self) -> None:
        self.assertIn('pin_columns=("Player", "Position")', self._pin_args_for("top_breakouts"))
        self.assertIn('pin_columns=("Player", "Position")', self._pin_args_for("biggest_declines"))

    def test_single_player_trend_snapshot_pins_player(self) -> None:
        self.assertIn('pin_columns=("Player",)', self._pin_args_for("single_player_trend_snapshot"))

    def test_fantasy_sleepers_busts_pin_player_team_position(self) -> None:
        for key in ("fantasy_curve_adjusted_sleepers", "fantasy_market_sleepers", "fantasy_market_busts"):
            self.assertIn('pin_columns=("Player", "Team", "Primary Position")', self._pin_args_for(key))

    def test_valuation_pins_player_and_position(self) -> None:
        self.assertIn('pin_columns=("Player", "Position")', self._pin_args_for("valuation"))

    def test_ml_predictions_pins_player_position_team(self) -> None:
        self.assertIn('pin_columns=("Player", "Position", "Team")', self._pin_args_for("ml_predictions"))

    def test_significance_and_advanced_intelligence_tables_left_unpinned(self) -> None:
        """Player isn't the leading column in these tables (see docs/MOBILE_M5_ANALYTICS.md
        §Wide-table strategy) — pinning would either no-op or require reordering,
        which the M5 brief rules out. Confirmed unpinned rather than silently dropped."""
        for key in ("comparison_significance_tests", "comparison_advanced_trend_intelligence", "trend_advanced_intelligence"):
            self.assertNotIn("pin_columns=", self._pin_args_for(key))

    def test_render_output_table_pin_columns_uses_generic_module(self) -> None:
        start = APP_SRC.index("def render_output_table(")
        body = APP_SRC[start: start + 3500]
        self.assertIn("from mobile_table_layout import pinned_identity_column_config", body)
        self.assertNotIn("from fantasy_mobile_layout import pinned_identity_column_config", body)


class WaiverPoolTablePinWiringTests(unittest.TestCase):
    def test_waiver_available_player_pool_table_is_pinned(self) -> None:
        self.assertIn("from mobile_table_layout import pinned_identity_column_config", WAIVER_SRC)
        self.assertIn('"Player", "MLB Team", "Team", "Primary Position", "Position"', WAIVER_SRC)

    def test_waiver_pool_dataframe_passes_column_config(self) -> None:
        idx = WAIVER_SRC.index("_pool_view_display = pool_view[disp_cols]")
        window = WAIVER_SRC[idx: idx + 600]
        self.assertIn("column_config=_pool_pin_cfg or None", window)


class MatplotlibChartLegibilityWiringTests(unittest.TestCase):
    def test_every_plt_subplots_call_site_is_inside_the_legible_context(self) -> None:
        """Every ad hoc matplotlib chart (fig, ax = plt.subplots(...)) in the app must
        be wrapped in legible_matplotlib_chart() so phone-scaled text stays readable —
        checked by requiring the import to appear shortly before each subplots() call."""
        count = 0
        for m in re.finditer(r"fig, ax = plt\.subplots\(", APP_SRC):
            count += 1
            preceding = APP_SRC[max(0, m.start() - 250): m.start()]
            self.assertIn(
                "from mobile_chart_layout import legible_matplotlib_chart",
                preceding,
                f"plt.subplots() call at offset {m.start()} is not wrapped",
            )
        self.assertGreaterEqual(count, 4, "expected at least the 4 known matplotlib chart call sites")

    def test_legible_context_wraps_the_st_pyplot_call_not_just_the_figure(self) -> None:
        """A context that closes before st.pyplot() renders would not affect the
        rendered image (rc_context only affects draw-time, not figure creation)."""
        for m in re.finditer(r"with legible_matplotlib_chart\(\):", APP_SRC):
            # The next ~2500 chars from this `with` must contain its own st.pyplot call
            # (generous: one of these blocks branches on an if/else before plotting).
            window = APP_SRC[m.start(): m.start() + 2500]
            self.assertIn("st.pyplot(", window)


class FilterRowWrapWiringTests(unittest.TestCase):
    """Phone-only filter-row compaction (M1's mobile_wrap_row) around existing
    st.columns(...) calls — wraps the call itself, never restructures the columns,
    so desktop layout is byte-for-byte unchanged (same pattern as M3/M4)."""

    EXPECTED_KEYS = (
        "historical-top-filters",
        "historical-advanced-filters",
        "career-top-filters",
        "career-advanced-filters",
        "leaderboards-top-filters",
        "leaderboards-weights",
        "comparison-action-cols",
        "comparison-sig-players",
        "comparison-sig-actions",
        "trend-top-filters",
        "trend-dash-mode",
        "sleepers-top-filters",
        "sleepers-rank-cutoffs",
        "sleepers-points-p1",
        "sleepers-points-p2",
        "sleepers-pos-age",
        "valuation-top-filters",
        "valuation-weights",
        "ml-top-filters",
        "ml-tuning",
        "ml-table-controls",
    )

    def test_every_expected_wrap_key_is_present_exactly_once(self) -> None:
        for key in self.EXPECTED_KEYS:
            needle = f'with mobile_wrap_row(st, "{key}"):'
            self.assertEqual(APP_SRC.count(needle), 1, f"expected exactly one wrap for {key!r}")

    def test_wrap_immediately_precedes_its_columns_call(self) -> None:
        """The wrapped line must be `st.columns(...)` on the very next line — the
        wrap is around the columns() call itself, not some other statement."""
        for key in self.EXPECTED_KEYS:
            needle = f'with mobile_wrap_row(st, "{key}"):'
            idx = APP_SRC.index(needle)
            next_line = APP_SRC[idx:].split("\n", 2)[1]
            self.assertIn("st.columns(", next_line, f"{key!r} wrap body is not a columns() call: {next_line!r}")

    def test_metric_only_rows_are_not_wrapped(self) -> None:
        """Rows made only of st.metric calls are already 2-up on phones via M1's
        generic _METRIC_ROW CSS — wrapping them too would double-apply compaction."""
        for metric_vars in ("c7, c8, c9", "c5, c6, c7", "c12, c13, c14", "c4, c5, c6", "m1, m2, m3, m4"):
            idx = APP_SRC.find(f"{metric_vars} = st.columns(3)")
            if idx == -1:
                idx = APP_SRC.find(f"{metric_vars} = st.columns(4)")
            if idx == -1:
                continue
            preceding = APP_SRC[max(0, idx - 80): idx]
            self.assertNotIn("mobile_wrap_row", preceding)

    def test_side_by_side_table_columns_are_not_wrapped(self) -> None:
        """c8/c9 hold full sleeper/bust tables side by side — must stack full-width
        on phones (Streamlit's own <=640px rule), not be forced into 2-up tiles."""
        idx = APP_SRC.index("c8, c9 = st.columns(2)")
        preceding = APP_SRC[max(0, idx - 80): idx]
        self.assertNotIn("mobile_wrap_row", preceding)


if __name__ == "__main__":
    unittest.main()
