"""Harness tests for button dispatch scrape and classification."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_button_dispatch_gate_classify import (  # noqa: E402
    ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED,
    ABORTED_BUTTON_DISPATCH_OBSERVABILITY,
    classify_dispatch_gate_report,
)
from stage1_button_dispatch_scrape import (  # noqa: E402
    dispatch_delta,
    scrape_button_dispatch_probe,
)


class DispatchScrapeSemanticsTests(unittest.TestCase):
    def test_missing_probe_not_zero_counts(self) -> None:
        page = MagicMock()
        frame = MagicMock()
        frame.url = "https://example.test/~/+/?active_page=Live"
        frame.evaluate.return_value = {"probe_found": False}
        page.frames = [frame]
        out = scrape_button_dispatch_probe(page, frame=frame)
        self.assertFalse(out.get("probe_found"))
        self.assertNotIn("r0_count", out)

    def test_delta_refuses_missing_before(self) -> None:
        delta = dispatch_delta({"probe_found": False}, {"probe_found": True, "r0_count": 1}, "R0")
        self.assertEqual(delta.get("observability_abort"), "before_probe_missing")

    def test_delta_refuses_missing_after(self) -> None:
        before = {"probe_found": True, "r0_count": 0, "event_count": 0}
        delta = dispatch_delta(before, {"probe_found": False}, "R0")
        self.assertEqual(delta.get("observability_abort"), "after_probe_missing")

    def test_counter_increment_pass_shape(self) -> None:
        before = {
            "probe_found": True,
            "r0_count": 0,
            "event_count": 0,
            "o0_count": 0,
            "o1_count": 0,
            "o2_count": 0,
        }
        after = {
            "probe_found": True,
            "r0_count": 1,
            "event_count": 1,
            "payload": {
                "rows": [
                    {
                        "mode": "R0",
                        "source": "dispatch_r0",
                        "dispatch_kind": "return_value",
                        "event_id": "abc123",
                    }
                ],
                "r0_last_render": {"returned_true": True, "branch_entered": True},
            },
        }
        from stage1_button_dispatch_scrape import evaluate_dispatch_pass

        delta = dispatch_delta(before, after, "R0")
        self.assertIsNone(delta.get("observability_abort"))
        ok, ev = evaluate_dispatch_pass(delta, after, "R0")
        self.assertTrue(ok, ev)


class DispatchClassifyObservabilityTests(unittest.TestCase):
    def test_ledger_not_exposed_before_r0(self) -> None:
        case, note = classify_dispatch_gate_report(
            {},
            [],
            pause_resolved=True,
            ledger_before_r0={"probe_found": False},
        )
        self.assertEqual(case, ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED)
        self.assertIn("ledger", note)

    def test_probe_lost_not_case_a(self) -> None:
        steps = [
            {
                "mode": "R0",
                "click_dispatched": True,
                "trusted_dom_click": True,
                "observability_abort": "DISPATCH_PROBE_LOST_AFTER_RERUN",
                "dispatch_pass": False,
            }
        ]
        case, _ = classify_dispatch_gate_report(
            {},
            steps,
            pause_resolved=True,
            ledger_before_r0={"probe_found": True, "streamlit_session_id": "s", "impl_rev": "stage1_button_dispatch_probe_v1", "r0_count": 0, "o0_count": 0, "o1_count": 0, "o2_count": 0, "event_count": 0},
        )
        self.assertEqual(case, ABORTED_BUTTON_DISPATCH_OBSERVABILITY)

    def test_same_frame_invariant_documented_via_scrape(self) -> None:
        page = MagicMock()
        app = MagicMock()
        app.url = "https://host/~/+/app"
        app.evaluate.return_value = {
            "probe_found": True,
            "r0_count": "0",
            "o0_count": "0",
            "o1_count": "0",
            "o2_count": "0",
            "event_count": "0",
            "streamlit_session_id": "sess",
            "impl_rev": "stage1_button_dispatch_probe_v1",
            "json": "",
        }
        out = scrape_button_dispatch_probe(page, frame=app)
        self.assertTrue(out.get("probe_found"))
        self.assertEqual(out.get("frame_url"), app.url)


if __name__ == "__main__":
    unittest.main()
