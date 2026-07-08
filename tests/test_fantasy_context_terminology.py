"""Draft vs League terminology helper."""

from __future__ import annotations

import unittest

from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_SIMULATOR
from fantasy_context_terminology import (
    BADGE_ACTIVE_DRAFT,
    BADGE_ACTIVE_LEAGUE,
    BADGE_MOCK_DRAFT,
    BADGE_SHARED_LEAGUE,
    BADGE_SIMULATOR_DRAFT,
    BADGE_UPLOADED_LEAGUE,
    TERM_KIND_DRAFT,
    TERM_KIND_LEAGUE,
    active_context_label,
    classify_fantasy_context,
    is_league_context,
    saved_context_type_badge,
)
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    SOURCE_IMPORTED_DRAFT,
)


class FantasyContextTerminologyTests(unittest.TestCase):
    def test_mock_simulator_saved_stays_draft(self) -> None:
        context = {"context_type": CONTEXT_TYPE_MOCK_DRAFT_SIMULATION}
        archive = {"draft_type": DRAFT_TYPE_SIMULATOR}
        classified = classify_fantasy_context(context, archive)
        self.assertEqual(classified["kind"], TERM_KIND_DRAFT)
        self.assertEqual(classified["saved_badge"], BADGE_SIMULATOR_DRAFT)
        self.assertFalse(is_league_context(context, archive))
        self.assertEqual(active_context_label(context, archive), "Active Draft")

    def test_imported_real_league_is_uploaded_league(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "metadata": {"source": SOURCE_IMPORTED_DRAFT},
        }
        archive = {"draft_type": DRAFT_TYPE_IMPORTED}
        self.assertTrue(is_league_context(context, archive))
        self.assertEqual(saved_context_type_badge(context, archive), BADGE_UPLOADED_LEAGUE)
        self.assertEqual(active_context_label(context, archive), "Active League")

    def test_shared_league_with_two_accounts(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "metadata": {"source": SOURCE_IMPORTED_DRAFT},
            "team_ownership": {
                "Daniel": {"user_id": "daniel"},
                "Barry": {"user_id": "barry"},
            },
        }
        self.assertEqual(saved_context_type_badge(context), BADGE_SHARED_LEAGUE)

    def test_live_draft_without_claims_is_draft(self) -> None:
        context = {"context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT}
        self.assertEqual(classify_fantasy_context(context)["kind"], TERM_KIND_DRAFT)
        self.assertEqual(active_context_label(context), "Active Draft")

    def test_live_draft_with_claims_is_league(self) -> None:
        context = {
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "team_ownership": {"Daniel": {"user_id": "daniel"}},
        }
        self.assertEqual(classify_fantasy_context(context)["kind"], TERM_KIND_LEAGUE)
        self.assertEqual(saved_context_type_badge(context), BADGE_SHARED_LEAGUE)

    def test_active_short_labels(self) -> None:
        from fantasy_context_terminology import active_context_short_label

        mock_ctx = {"context_type": CONTEXT_TYPE_MOCK_DRAFT_SIMULATION}
        league_ctx = {"context_type": CONTEXT_TYPE_REAL_LEAGUE}
        self.assertEqual(active_context_short_label(mock_ctx), BADGE_ACTIVE_DRAFT)
        self.assertEqual(active_context_short_label(league_ctx), BADGE_ACTIVE_LEAGUE)


if __name__ == "__main__":
    unittest.main()
