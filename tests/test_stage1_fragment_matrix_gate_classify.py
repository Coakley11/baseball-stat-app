"""Regression tests for fragment matrix gate classification ordering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_fragment_matrix_gate_classify import (  # noqa: E402
    ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY,
    ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED,
    classify_matrix_steps,
)


def _step(
    control: str,
    *,
    click_dispatched: bool = False,
    trusted_dom_click: bool = False,
    callback_entered: bool = False,
    target_visible: bool = True,
    setup_abort: str = "",
) -> dict:
    return {
        "control": control,
        "click_dispatched": click_dispatched,
        "trusted_dom_click": trusted_dom_click,
        "callback_entered": callback_entered,
        "target_visible": target_visible,
        "setup_abort": setup_abort,
    }


class FragmentMatrixGateClassifyTests(unittest.TestCase):
    def test_s0_not_visible_aborts_not_case_v(self) -> None:
        steps = [
            _step("S0", click_dispatched=False, target_visible=False, setup_abort="UI_NOT_EXPOSED"),
        ]
        case, note = classify_matrix_steps(steps, expander={"matrix_expander_found": True, "matrix_expander_open_after": True})
        self.assertEqual(case, ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED)
        self.assertIn("S0", note)

    def test_s0_no_click_not_case_v(self) -> None:
        steps = [_step("S0", click_dispatched=False)]
        case, _ = classify_matrix_steps(
            steps,
            expander={"matrix_expander_found": True, "matrix_expander_open_after": True},
        )
        self.assertEqual(case, ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED)

    def test_expander_not_open_aborts(self) -> None:
        case, note = classify_matrix_steps([], expander={"matrix_expander_found": True, "matrix_expander_open_after": False})
        self.assertEqual(case, ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED)
        self.assertEqual(note, "matrix_expander_not_open")

    def test_s0_visible_no_trusted_click_observability_abort(self) -> None:
        steps = [
            _step("S0", click_dispatched=True, trusted_dom_click=False, target_visible=True),
            _step("S1", click_dispatched=True, trusted_dom_click=True),
            _step("D0", click_dispatched=True, trusted_dom_click=True),
            _step("D1", click_dispatched=True, trusted_dom_click=True),
        ]
        case, note = classify_matrix_steps(
            steps,
            expander={"matrix_expander_found": True, "matrix_expander_open_after": True},
        )
        self.assertEqual(case, ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY)
        self.assertIn("S0", note)

    def test_s0_trusted_click_no_callback_case_v(self) -> None:
        steps = [
            _step("S0", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
            _step("S1", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
            _step("D0", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
            _step("D1", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
        ]
        case, _ = classify_matrix_steps(
            steps,
            expander={"matrix_expander_found": True, "matrix_expander_open_after": True},
        )
        self.assertEqual(case, "FRAGMENT_MATRIX_CASE_V_S0_FAIL")

    def test_case_i_when_s0_s1_pass_d0_d1_fail(self) -> None:
        steps = [
            _step("S0", click_dispatched=True, trusted_dom_click=True, callback_entered=True),
            _step("S1", click_dispatched=True, trusted_dom_click=True, callback_entered=True),
            _step("D0", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
            _step("D1", click_dispatched=True, trusted_dom_click=True, callback_entered=False),
        ]
        case, _ = classify_matrix_steps(
            steps,
            expander={"matrix_expander_found": True, "matrix_expander_open_after": True},
        )
        self.assertEqual(case, "FRAGMENT_MATRIX_CASE_I_DYNAMIC_CONSTRUCTION")


if __name__ == "__main__":
    unittest.main()
