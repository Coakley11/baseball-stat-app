"""Paywall navigation through the REAL streamlit_app.py.

Both defects fixed here were invisible to M3's isolated fixture and only exist
in the full app:

1. schedule_page() wrote the live radio key "main_sidebar_page" after the radio
   was instantiated -> StreamlitAPIException, both gate buttons dead.
2. begin_page_run() stores the gate sentinel in session["active_page"], and the
   same-page guard in _consume_scheduled_navigation() coerced that unknown value
   to PAGE_OPTIONS[0] -- so "Back to Historical Explorer" was silently dropped as a
   redundant same-page schedule, while "View Pricing & Upgrade" still worked.

Slow (~2 min): it boots the whole app. That is the point -- nothing smaller
reproduces either bug.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _titles(at) -> str:
    return " | ".join(t.value for t in at.title)


class PaywallNavigationRealAppTests(unittest.TestCase):
    def test_gate_back_and_pricing_buttons_navigate_in_the_real_app(self) -> None:
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=900)
            at.session_state["main_sidebar_page"] = "Draft Lab / Simulation"
            at.run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertIn("Draft Lab is a Pro feature", _titles(at))
            # The sentinel really is in session -- the precondition for defect 2.
            self.assertEqual(at.session_state["active_page"], "__MONETIZATION_GATE__")

            back = [b for b in at.button if b.key == "monetization_gate_back"]
            self.assertEqual(len(back), 1)
            back[0].click().run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertEqual(at.session_state["main_sidebar_page"], "Historical Explorer")
            self.assertEqual(at.session_state["active_page"], "Historical Explorer")
            self.assertNotIn("is a Pro feature", _titles(at))

            at.radio(key="main_sidebar_page").set_value("ML Predictions").run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertIn("ML Predictions is a Pro feature", _titles(at))

            pricing = [b for b in at.button if b.key == "monetization_gate_pricing"]
            self.assertEqual(len(pricing), 1)
            pricing[0].click().run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertEqual(at.session_state["main_sidebar_page"], "Pricing & Upgrade")
            self.assertIn("Baseball Free & Pro", _titles(at))
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
