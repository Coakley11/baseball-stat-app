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


class MonetizationAcceptanceRealAppTests(unittest.TestCase):
    def test_candidate_pro_pages_remain_available_and_pricing_is_reachable(self) -> None:
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=900)
            at.session_state["main_sidebar_page"] = "Draft Lab / Simulation"
            at.run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertEqual(at.session_state["main_sidebar_page"], "Draft Lab / Simulation")
            self.assertEqual(at.session_state["active_page"], "Draft Lab / Simulation")
            self.assertNotEqual(at.session_state["active_page"], "__MONETIZATION_GATE__")
            self.assertNotIn("is a Pro feature", _titles(at))

            at.radio(key="main_sidebar_page").set_value("ML Predictions").run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertEqual(at.session_state["active_page"], "ML Predictions")
            self.assertNotEqual(at.session_state["active_page"], "__MONETIZATION_GATE__")
            self.assertNotIn("is a Pro feature", _titles(at))

            at.radio(key="main_sidebar_page").set_value("Pricing & Upgrade").run()
            self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
            self.assertEqual(at.session_state["main_sidebar_page"], "Pricing & Upgrade")
            self.assertIn("Baseball Free & Pro", _titles(at))
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
