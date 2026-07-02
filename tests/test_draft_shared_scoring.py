"""Regression tests for shared draft scoring settings across pages."""

from __future__ import annotations

import unittest

from shared_draft_context import (
    CANONICAL_SETTINGS_KEY,
    is_ml_blend_enabled,
    on_draft_settings_changed,
    prepare_canonical_scoring_context,
    read_draft_scoring_settings,
    write_canonical_draft_settings,
)


class DraftSharedScoringTests(unittest.TestCase):
    def test_trend_lag_change_writes_canonical_lookback(self) -> None:
        session = {"trend_lag": 4, "draft_window": 3, "ml_lookback": 3}
        on_draft_settings_changed(session, source_page="Trend Value", lookback_key="trend_lag")
        cur = read_draft_scoring_settings(session)
        self.assertEqual(cur["lookback_window"], 4)
        self.assertEqual(session["draft_window"], 4)
        self.assertEqual(session["ml_lookback"], 4)

    def test_value_lag_change_writes_canonical_lookback(self) -> None:
        session = {"value_lag": 5}
        on_draft_settings_changed(session, source_page="Valuation", lookback_key="value_lag")
        self.assertEqual(read_draft_scoring_settings(session)["lookback_window"], 5)

    def test_draft_assistant_ml_toggle_writes_canonical(self) -> None:
        session = {"draft_use_ml_blend": False, "draft_ml_blend_weight": 0.22, "draft_ml_min_games_signal": 30}
        on_draft_settings_changed(
            session,
            source_page="Draft Assistant Simulator",
            ml_blend_key="draft_use_ml_blend",
            ml_weight_key="draft_ml_blend_weight",
            ml_min_games_key="draft_ml_min_games_signal",
        )
        blob = session[CANONICAL_SETTINGS_KEY]
        self.assertFalse(blob["ml_blend_enabled"])
        self.assertEqual(blob["ml_signal_weight"], 0.22)
        self.assertEqual(blob["ml_min_recent_games"], 30)
        self.assertFalse(is_ml_blend_enabled(session))

    def test_canonical_survives_page_alias_overwrite_on_prepare(self) -> None:
        session = {
            CANONICAL_SETTINGS_KEY: {
                "lookback_window": 5,
                "projection_style": "Conservative",
                "fantasy_format": "5x5 Roto",
                "ml_blend_enabled": True,
                "ml_signal_weight": 0.12,
                "ml_min_recent_games": 50,
            },
            "trend_lag": 3,
            "value_lag": 3,
            "ml_lookback": 3,
            "draft_window": 3,
        }
        prepare_canonical_scoring_context(session, active_page="Comparison Tool")
        self.assertEqual(session["trend_lag"], 5)
        self.assertEqual(session["value_lag"], 5)
        self.assertEqual(session["ml_lookback"], 5)
        self.assertEqual(session["draft_window"], 5)
        self.assertEqual(read_draft_scoring_settings(session)["projection_style"], "Conservative")

    def test_projection_style_from_draft_assistant_propagates_to_ml_page(self) -> None:
        session = {"fantasy_draft_projection_style": "Aggressive", "ml_projection_style": "Balanced"}
        on_draft_settings_changed(
            session,
            source_page="Draft Assistant Simulator",
            style_key="fantasy_draft_projection_style",
        )
        self.assertEqual(session["ml_projection_style"], "Aggressive")
        self.assertEqual(read_draft_scoring_settings(session)["projection_style"], "Aggressive")


if __name__ == "__main__":
    unittest.main()
