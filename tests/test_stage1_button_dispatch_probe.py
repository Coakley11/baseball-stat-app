"""Stage1 button dispatch probe — unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_button_dispatch_gate_classify import (  # noqa: E402
    ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED,
    classify_dispatch_steps,
)


class DispatchGateClassifyTests(unittest.TestCase):
    def test_case_a_on_click_fail(self) -> None:
        steps = [
            {"mode": "R0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O1", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O2", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
        ]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, "BUTTON_DISPATCH_CASE_A_ON_CLICK_FAIL")

    def test_case_b_closure_fail(self) -> None:
        steps = [
            {"mode": "R0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O1", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O2", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
        ]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, "BUTTON_DISPATCH_CASE_B_CLOSURE_FAIL")

    def test_case_c_args_fail(self) -> None:
        steps = [
            {"mode": "R0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
            {"mode": "O1", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O2", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True},
        ]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, "BUTTON_DISPATCH_CASE_C_ARGS_FAIL")

    def test_case_d_all_pass(self) -> None:
        steps = [
            {"mode": m, "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": True}
            for m in ("R0", "O0", "O1", "O2")
        ]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, "BUTTON_DISPATCH_CASE_D_ALL_PASS")

    def test_case_e_r0_fail_pause_pass(self) -> None:
        steps = [
            {"mode": "R0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O0", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O1", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
            {"mode": "O2", "click_dispatched": True, "trusted_dom_click": True, "dispatch_pass": False},
        ]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, "BUTTON_DISPATCH_CASE_E_R0_FAIL_PAUSE_PASS")

    def test_ui_abort(self) -> None:
        steps = [{"mode": "R0", "click_dispatched": False, "target_visible": False, "setup_abort": "UI_NOT_EXPOSED"}]
        case, _ = classify_dispatch_steps(steps, pause_resolved=True)
        self.assertEqual(case, ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED)


class DispatchProbeAppTest(unittest.TestCase):
    def test_modes_use_dedicated_ledger_not_rec_fragment(self) -> None:
        from streamlit.testing.v1 import AppTest

        from live_draft_rec_fragment_exec_diag import FRAGMENT_CALLBACK_LEDGER_KEY
        from live_draft_stage1_button_dispatch_probe import (
            COUNT_KEY_BY_MODE,
            DISPATCH_EVENTS_KEY,
            LABEL_O0,
            LABEL_O1,
            LABEL_O2,
            LABEL_R0,
            dispatch_widget_key,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "stage1_button_dispatch_apptest.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        at.run()
        room = "APPTESTDSP"
        cases = [
            ("R0", LABEL_R0),
            ("O0", LABEL_O0),
            ("O1", LABEL_O1),
            ("O2", LABEL_O2),
        ]
        for mode, label in cases:
            wk = dispatch_widget_key(mode, room)
            buttons = [b for b in at.button if b.key == wk]
            self.assertTrue(buttons, f"missing {mode} {wk}")
            before = int(at.session_state[COUNT_KEY_BY_MODE[mode]]) if COUNT_KEY_BY_MODE[mode] in at.session_state else 0
            buttons[0].click().run()
            after = int(at.session_state[COUNT_KEY_BY_MODE[mode]]) if COUNT_KEY_BY_MODE[mode] in at.session_state else 0
            self.assertEqual(after, before + 1, mode)
            events = list(at.session_state[DISPATCH_EVENTS_KEY]) if DISPATCH_EVENTS_KEY in at.session_state else []
            self.assertGreaterEqual(len(events), 1)
            self.assertEqual(events[-1].get("mode"), mode)
        rec_book = list(at.session_state[FRAGMENT_CALLBACK_LEDGER_KEY]) if FRAGMENT_CALLBACK_LEDGER_KEY in at.session_state else []
        self.assertEqual(rec_book, [])


if __name__ == "__main__":
    unittest.main()
