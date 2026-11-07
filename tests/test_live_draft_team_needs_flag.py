"""``_live_draft_team_needs_rendered`` is a per-run flag.

It is set only when Team Needs paints in the early (Solo) viewport, and the later rec-column
Team Needs is skipped while it is set. It used to survive across runs, so after a Solo draft a
Shared draft in the same session never showed Team Needs.
"""

from __future__ import annotations

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")
FLAG = '"_live_draft_team_needs_rendered"'


class TeamNeedsFlagIsPerRunTests(unittest.TestCase):
    def test_flag_is_cleared_before_it_is_set_or_read_in_the_live_draft_body(self) -> None:
        body = APP[APP.index('elif active_page == "Live Draft Room":'):]
        clear = body.index(f"st.session_state.pop({FLAG}, None)")
        first_set = body.index(f"st.session_state[{FLAG}] = True")
        first_use = body.index(FLAG)
        self.assertEqual(first_use, clear + len("st.session_state.pop("), "flag used before the per-run clear")
        self.assertLess(clear, first_set)
        # Cleared with the other per-run early-viewport flags, not inside the Solo-only branch.
        window = body[clear - 400 : clear]
        self.assertIn('st.session_state.pop("_live_draft_manual_panel_early", None)', window)
        self.assertLess(clear, body.index("if _solo_recs_here:"))


if __name__ == "__main__":
    unittest.main()
