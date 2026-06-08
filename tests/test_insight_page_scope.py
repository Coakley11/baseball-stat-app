"""Applied Math insight renders only on originating page."""

from __future__ import annotations

import unittest

from applied_math_return_insight import insight_page_scope_decision, should_render_insight_on_page


class TestInsightPageScope(unittest.TestCase):
    def test_trend_insight_only_on_trend_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Trend Value", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Trend Value", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Comparison Tool", insight))

    def test_missing_source_page_never_renders(self) -> None:
        insight = {"source_app": "baseball", "conclusion": "test"}
        self.assertFalse(should_render_insight_on_page("baseball", "Trend Value", insight))

    def test_emoji_source_page_renders_only_on_canonical_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "🔥 Trend Value", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Trend Value", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Comparison Tool", insight))

    def test_chart_snapshot_page_used_when_source_page_missing(self) -> None:
        insight = {
            "source_app": "baseball",
            "source_state": {
                "chart_params": {"chart_snapshot": {"page": "Trend Value"}},
            },
        }
        self.assertTrue(should_render_insight_on_page("baseball", "Trend Value", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Comparison Tool", insight))

    def test_valuation_insight_only_on_valuation_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Valuation", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Valuation", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "ML Predictions", insight))
        scope = insight_page_scope_decision("baseball", "Valuation", insight)
        self.assertTrue(scope["should_render_insight_on_page"])
        self.assertEqual(scope["source_page_normalized"], "Valuation")

    def test_ml_predictions_insight_only_on_ml_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "ML Predictions", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "ML Predictions", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Valuation", insight))

    def test_emoji_valuation_source_page_normalizes(self) -> None:
        insight = {"source_app": "baseball", "source_page": "💰 Valuation", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Valuation", insight))

    def test_fantasy_standings_insight_only_on_standings_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Fantasy Standings Tracker", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Fantasy Standings Tracker", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Fantasy Sleepers & Busts", insight))
        scope = insight_page_scope_decision("baseball", "Fantasy Standings Tracker", insight)
        self.assertNotEqual(
            scope.get("render_skip_reason"),
            "current_page_not_eligible ('Fantasy Standings Tracker')",
        )

    def test_fantasy_sleepers_insight_only_on_sleepers_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Fantasy Sleepers & Busts", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Fantasy Sleepers & Busts", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Fantasy Lineup Assistant", insight))

    def test_fantasy_lineup_insight_only_on_lineup_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Fantasy Lineup Assistant", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Fantasy Lineup Assistant", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Leaderboards", insight))

    def test_leaderboards_insight_only_on_leaderboards_page(self) -> None:
        insight = {"source_app": "baseball", "source_page": "Leaderboards", "conclusion": "test"}
        self.assertTrue(should_render_insight_on_page("baseball", "Leaderboards", insight))
        self.assertFalse(should_render_insight_on_page("baseball", "Fantasy Standings Tracker", insight))


if __name__ == "__main__":
    unittest.main()
