"""Applied Math insight renders only on originating page."""

from __future__ import annotations

import unittest

from applied_math_return_insight import should_render_insight_on_page


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


if __name__ == "__main__":
    unittest.main()
