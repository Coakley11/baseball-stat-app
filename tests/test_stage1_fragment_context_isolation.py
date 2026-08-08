"""Stage1 fragment context isolation — unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_fragment_context_gate_classify import (  # noqa: E402
    ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED,
    classify_context_steps,
)


class ContextGateClassifyTests(unittest.TestCase):
    def test_case_a_expander_fragment_only_fails(self) -> None:
        steps = [
            {"control": "C3", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
            {"control": "C0", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
            {"control": "C2", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
            {"control": "C1", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": False},
        ]
        case, _ = classify_context_steps(steps, expander={"matrix_expander_open_after": True})
        self.assertEqual(case, "FRAGMENT_CONTEXT_CASE_A_EXPANDER_FRAGMENT")

    def test_case_c_top_fragment_fail(self) -> None:
        steps = [
            {"control": "C3", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
            {"control": "C0", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": False},
            {"control": "C2", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
            {"control": "C1", "click_dispatched": True, "trusted_dom_click": True, "callback_entered": True},
        ]
        case, _ = classify_context_steps(steps, expander={"matrix_expander_open_after": True})
        self.assertEqual(case, "FRAGMENT_CONTEXT_CASE_C_TOP_FRAGMENT_FAIL")

    def test_ui_abort_not_case_c(self) -> None:
        steps = [{"control": "C3", "click_dispatched": False, "target_visible": False, "setup_abort": "UI_NOT_EXPOSED"}]
        case, _ = classify_context_steps(steps, expander={"matrix_expander_open_after": True})
        self.assertEqual(case, ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED)


class ContextIsolationAppTest(unittest.TestCase):
    def test_c0_top_level_callback_ledger(self) -> None:
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        from live_draft_rec_fragment_exec_diag import FRAGMENT_CALLBACK_LEDGER_KEY
        from live_draft_stage1_fragment_context_isolation import LABEL_C0, context_widget_key

        fixture = Path(__file__).resolve().parent / "fixtures" / "stage1_fragment_context_apptest.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        at.run()
        wk = context_widget_key("C0", "APPTESTCTX")
        buttons = [b for b in at.button if b.key == wk]
        self.assertTrue(buttons, wk)
        buttons[0].click().run()
        ledger = (
            at.session_state[FRAGMENT_CALLBACK_LEDGER_KEY]
            if FRAGMENT_CALLBACK_LEDGER_KEY in at.session_state
            else []
        )
        self.assertGreaterEqual(len(ledger), 1)
        self.assertEqual(ledger[-1].get("source"), "fragment_context_c0")
        self.assertEqual(ledger[-1].get("context_id"), "C0")


if __name__ == "__main__":
    unittest.main()
