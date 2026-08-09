"""Pause-sibling return probe — unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_pause_sibling_gate_classify import (  # noqa: E402
    BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL,
    BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE,
    classify_pause_sibling_run,
)


class PauseSiblingClassifyTests(unittest.TestCase):
    def test_e1(self) -> None:
        case, _ = classify_pause_sibling_run(
            pause_resolved=True,
            sibling_pass=True,
            sibling_trusted_click=True,
            r0_optional_pass=False,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL)

    def test_e2(self) -> None:
        case, _ = classify_pause_sibling_run(
            pause_resolved=True,
            sibling_pass=False,
            sibling_trusted_click=True,
            r0_optional_pass=False,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE)


class PauseSiblingAppTest(unittest.TestCase):
    def test_return_value_increments_once(self) -> None:
        from streamlit.testing.v1 import AppTest

        from live_draft_stage1_pause_sibling_probe import (
            LABEL_PAUSE_SIBLING,
            PAUSE_SIBLING_COUNT_KEY,
            PAUSE_SIBLING_EVENTS_KEY,
            pause_sibling_widget_key,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "stage1_pause_sibling_apptest.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        at.run()
        wk = pause_sibling_widget_key("APPSIB01")
        buttons = [b for b in at.button if b.key == wk]
        self.assertTrue(buttons, wk)
        self.assertTrue(any(b.label == LABEL_PAUSE_SIBLING for b in at.button))
        before = int(at.session_state[PAUSE_SIBLING_COUNT_KEY]) if PAUSE_SIBLING_COUNT_KEY in at.session_state else 0
        buttons[0].click().run()
        after = int(at.session_state[PAUSE_SIBLING_COUNT_KEY])
        self.assertEqual(after, before + 1)
        events = list(at.session_state[PAUSE_SIBLING_EVENTS_KEY])
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].get("returned_true"))
        self.assertTrue(events[0].get("branch_entered"))

    def test_pause_key_unchanged(self) -> None:
        import inspect

        from live_draft_control_center_ui import render_live_draft_control_center

        src = inspect.getsource(render_live_draft_control_center)
        self.assertIn('key="live_draft_pause"', src)
        self.assertIn("live_draft_pause_timer", src)


if __name__ == "__main__":
    unittest.main()
