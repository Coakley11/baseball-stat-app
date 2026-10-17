"""Comparison Tool guards and the bad-link fallback notice (wiring; behaviour is browser-tested)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


class ComparisonGuardTests(unittest.TestCase):
    def test_no_draft_room_note_without_a_team(self):
        self.assertIn(
            "if comparison_action_team and comparison_teams and comparison_action_team not in comparison_teams:",
            SRC,
        )
        self.assertNotIn("{comparison_action_team or '—'}", SRC)

    def test_significance_needs_two_different_players(self):
        same = SRC.index("if pid_a_preview == pid_b_preview:")
        run = SRC.index("elif sig_player_a_label and sig_player_b_label and sig_stats:")
        self.assertLess(same, run)
        self.assertLess(run - same, 300)

    def test_empty_and_single_player_states_explain_next_step(self):
        self.assertIn("Choose two or three players in the box above", SRC)  # U2: empty-state answer card
        self.assertIn("Add a second player above to compare them side by side.", SRC)
        self.assertIn("Pick two different players", SRC)


class BadLinkTests(unittest.TestCase):
    def test_unknown_page_is_flagged_and_explained_without_echoing_it(self):
        detect = SRC.index("st.session_state[BAD_PAGE_LINK_NOTICE_KEY] = _qp_target")
        self.assertLess(SRC.index('if not st.session_state.get("_qp_active_page_nav_consumed")'), detect)
        notice = SRC[SRC.index("_bad_link_fallback = st.session_state.pop(BAD_PAGE_LINK_NOTICE_KEY"):]
        notice = notice[: notice.index("\n\n")]
        self.assertIn("That page wasn't found.", notice)
        self.assertNotIn("_qp_page_raw", notice)
        # Shown before the page body (and before entitlement/paywall stand-ins).
        self.assertLess(SRC.index("_bad_link_fallback = st.session_state.pop"), SRC.index('active_page = "__ENTITLEMENT_LOADING__"'))


if __name__ == "__main__":
    unittest.main()
