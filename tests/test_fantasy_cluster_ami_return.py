"""AMI return render + filter preservation for Fantasy cluster (baseball app)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from applied_math_context import apply_source_state_to_session, build_source_state
from applied_math_return_insight import (
    SESSION_PENDING_KEY,
    render_suite_applied_math_insight_for_page,
    should_render_insight_on_page,
)

_STANDINGS_FILTERS = {
    "standings_scoring_format": "Points League",
    "standings_stats_source": "MLB API Auto-Fetch",
    "standings_api_season": 2025,
}


class TestFantasyClusterAmiReturnBaseball(unittest.TestCase):
    def _insight(self, page: str, filters: dict) -> dict:
        return {
            "insight_id": "ami-fantasy-test",
            "source_app": "baseball",
            "source_page": page,
            "conclusion": "Fantasy insight",
            "source_state": {
                "source_app": "baseball",
                "source_page": page,
                "filter_params": dict(filters),
            },
        }

    def test_navigate_away_hides_card_return_page_shows_it(self) -> None:
        insight = self._insight("Fantasy Standings Tracker", _STANDINGS_FILTERS)
        st = MagicMock()
        st.session_state = {SESSION_PENDING_KEY: insight}

        with patch(
            "applied_math_return_insight.render_applied_math_insight_panel",
            return_value=True,
        ) as mock_panel:
            self.assertFalse(
                render_suite_applied_math_insight_for_page(
                    st,
                    source_app="baseball",
                    source_page="Comparison Tool",
                )
            )
            self.assertTrue(
                render_suite_applied_math_insight_for_page(
                    st,
                    source_app="baseball",
                    source_page="Fantasy Standings Tracker",
                )
            )
        self.assertEqual(mock_panel.call_count, 1)
        self.assertTrue(should_render_insight_on_page("baseball", "Fantasy Standings Tracker", insight))

    def test_standings_filters_preserved_on_ami_return(self) -> None:
        session = {
            "active_page": "Fantasy Standings Tracker",
            "fantasy_state": {"standings": {"filters": dict(_STANDINGS_FILTERS)}},
            **_STANDINGS_FILTERS,
        }
        built = build_source_state("Fantasy Standings Tracker", session)
        self.assertEqual(built["filter_params"]["standings_api_season"], 2025)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["standings_api_season"], 2025)
        self.assertEqual(target["standings_scoring_format"], "Points League")


if __name__ == "__main__":
    unittest.main()
