"""Live Draft setup values survive runs that do not draw the form (QA 2026-11-05).

In QA, after "Create Shared Draft Room" sent the page to Home (and a creation timed out), the retry
created room UHN7MM with "My Fantasy League", teams "Team A"/"Team B" and a 30 s timer, which the user
never chose: Streamlit drops an undrawn widget's value, and the form re-seeded from defaults.
"""

from __future__ import annotations

import unittest

from live_draft_setup_memory import MEMORY_KEY, remember_and_restore_live_draft_setup

ENTERED = {
    "live_draft_league_name": "QA League Two",
    "live_draft_team_name_1": "Danny",
    "live_draft_team_name_2": "Barry",
    "live_draft_timer": "20 min",
    "live_draft_picks_per_team": 2,
    "live_slot_C": 1,
}


class SetupMemoryTests(unittest.TestCase):
    def test_values_dropped_by_a_run_that_did_not_draw_the_form_come_back(self) -> None:
        session = dict(ENTERED)
        remember_and_restore_live_draft_setup(session)  # a run on the Live Draft page
        for key in ENTERED:
            session.pop(key)  # Streamlit's end-of-run cleanup after a run on Home
        restored = remember_and_restore_live_draft_setup(session)  # back on Live Draft
        self.assertEqual(sorted(restored), sorted(ENTERED))
        self.assertEqual({k: session[k] for k in ENTERED}, ENTERED)

    def test_a_value_the_session_holds_is_never_overwritten(self) -> None:
        session = dict(ENTERED)
        remember_and_restore_live_draft_setup(session)
        session["live_draft_league_name"] = "Renamed"
        remember_and_restore_live_draft_setup(session)
        self.assertEqual(session["live_draft_league_name"], "Renamed")
        self.assertEqual(session[MEMORY_KEY]["live_draft_league_name"], "Renamed")

    def test_unrelated_keys_are_not_remembered(self) -> None:
        session = {"active_page": "Home", **ENTERED}
        remember_and_restore_live_draft_setup(session)
        self.assertNotIn("active_page", session[MEMORY_KEY])

    def test_reset_to_defaults_is_not_undone(self) -> None:
        from unittest.mock import patch

        from user_page_preferences import reset_live_draft_setup_to_defaults

        session = dict(ENTERED)
        remember_and_restore_live_draft_setup(session)
        with patch("user_page_preferences.reset_user_page_preferences", return_value={}):
            reset_live_draft_setup_to_defaults(session)
        self.assertNotIn(MEMORY_KEY, session)
        remember_and_restore_live_draft_setup(session)
        self.assertNotIn("live_draft_team_name_1", session)  # Reset cleared it; nothing puts it back


if __name__ == "__main__":
    unittest.main()
