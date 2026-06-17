"""Live Draft format sync after page snapshot restore."""
from __future__ import annotations

import unittest

from global_fantasy_settings_state import CANONICAL_ROTO, LIVE_SCORING_ROTO
from live_draft_state import LIVE_DRAFT_PAGE_BLOCK, restore_live_draft_page_filters


class TestLiveDraftFormatRestore(unittest.TestCase):
    def test_restore_overwrites_stale_scoring_from_canonical(self) -> None:
        session = {"room_format": CANONICAL_ROTO}
        store = {
            LIVE_DRAFT_PAGE_BLOCK: {
                "live_draft_scoring": "Points League",
                "live_draft_team_count": 12,
            }
        }
        restore_live_draft_page_filters(session, store)
        self.assertEqual(session["live_draft_scoring"], LIVE_SCORING_ROTO)
        self.assertEqual(session["live_draft_team_count"], 12)


if __name__ == "__main__":
    unittest.main()
