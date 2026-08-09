"""Harness tests for Pause-sibling PRE/POST order gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_pause_sibling_order_gate_classify import (  # noqa: E402
    BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL,
    BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC,
    BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN,
    BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT,
    BUTTON_DISPATCH_E2E_SETUP_ABORT,
    classify_pause_sibling_order,
)
from stage1_pause_sibling_scrape import (  # noqa: E402
    evaluate_sibling_click_pass,
    scrape_pause_sibling_probe,
    sibling_delta,
)


class PauseSiblingOrderClassifyTests(unittest.TestCase):
    def test_order_a_pre_pass_post_fail(self) -> None:
        case, note = classify_pause_sibling_order(pre_pass=True, pause_resolved=True, post_pass=False)
        self.assertEqual(case, BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL)
        self.assertEqual(note, "pre_pass_post_fail")

    def test_order_b_pre_fail_post_fail(self) -> None:
        case, _ = classify_pause_sibling_order(pre_pass=False, pause_resolved=True, post_pass=False)
        self.assertEqual(case, BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC)

    def test_order_c_both_pass(self) -> None:
        case, _ = classify_pause_sibling_order(pre_pass=True, pause_resolved=True, post_pass=True)
        self.assertEqual(case, BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN)

    def test_order_d_pre_pass_pause_fail(self) -> None:
        case, _ = classify_pause_sibling_order(
            pre_pass=True, pause_resolved=False, post_pass=None, post_evaluated=False
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT)

    def test_order_e_pre_fail_pause_fail(self) -> None:
        case, _ = classify_pause_sibling_order(
            pre_pass=False, pause_resolved=False, post_pass=None, post_evaluated=False
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2E_SETUP_ABORT)


class PauseSiblingCounterProgressionTests(unittest.TestCase):
    def test_zero_to_one_to_two(self) -> None:
        steps = []
        count = 0
        for _phase in ("pre", "post"):
            before = {"probe_found": True, "count": count, "event_count": count, "full_app_run_seq": 10}
            count += 1
            after = {
                "probe_found": True,
                "count": count,
                "event_count": count,
                "full_app_run_seq": 11,
                "payload": {
                    "rows": [
                        {
                            "event_id": f"ev{count}",
                            "returned_true": True,
                            "branch_entered": True,
                        }
                    ]
                },
            }
            delta = sibling_delta(before, after)
            ok, _ = evaluate_sibling_click_pass(delta)
            steps.append(ok)
        self.assertEqual(steps, [True, True])

    def test_missing_ledger_not_zero(self) -> None:
        page = MagicMock()
        frame = MagicMock()
        frame.url = "https://example.test/~/+/"
        frame.evaluate.return_value = {"probe_found": False}
        out = scrape_pause_sibling_probe(page, frame=frame)
        self.assertFalse(out.get("probe_found"))
        self.assertNotIn("count", out)

    def test_post_fail_shape(self) -> None:
        before = {
            "probe_found": True,
            "count": 1,
            "event_count": 1,
            "full_app_run_seq": 12,
            "payload": {"rows": [{"event_id": "a"}]},
        }
        after = {
            "probe_found": True,
            "count": 1,
            "event_count": 1,
            "full_app_run_seq": 12,
            "payload": {"rows": [{"event_id": "a"}]},
        }
        delta = sibling_delta(before, after)
        ok, ev = evaluate_sibling_click_pass(delta)
        self.assertFalse(ok)
        self.assertEqual(ev.get("count_delta"), 0)


class PauseSiblingClickStepLocatorTests(unittest.TestCase):
    def test_fresh_frame_each_click(self) -> None:
        from stage1_pause_sibling_click_step import execute_pause_sibling_click

        page = MagicMock()
        frame = MagicMock()
        frame.url = "https://host/~/+/"
        ledger_seq = [
            {"probe_found": True, "count": "0", "event_count": "0", "impl_rev": "stage1_pause_sibling_probe_v1", "streamlit_session_id": "s1", "full_app_run_seq": "5", "json": ""},
            {"probe_found": True, "count": "1", "event_count": "1", "impl_rev": "stage1_pause_sibling_probe_v1", "streamlit_session_id": "s1", "full_app_run_seq": "6", "json": '{"rows":[{"event_id":"x","returned_true":true,"branch_entered":true}]}'},
        ]
        gen = {"generation_found": True, "ledger_found": True, "button_found": True}

        def eval_side_effect(js):
            if "pause-sibling-ledger" in js or "solo-stage1-pause-sibling-ledger" in js:
                return dict(ledger_seq.pop(0))
            return dict(gen)

        frame.evaluate.side_effect = eval_side_effect
        loc = MagicMock()
        loc.first.wait_for = MagicMock()
        loc.first.is_enabled.return_value = True
        loc.first.scroll_into_view_if_needed = MagicMock()
        loc.first.click = MagicMock()
        frame.get_by_role.return_value = loc

        with patch("stage1_pause_sibling_click_step.resolve_streamlit_app_frame", return_value=frame), patch(
            "stage1_pause_sibling_click_step.describe_page_frames", return_value={}
        ), patch(
            "stage1_pause_sibling_click_step.prepare_isolated_dom_click_capture", return_value={}
        ), patch(
            "stage1_pause_sibling_click_step.read_and_summarize_dom_click_capture",
            return_value={"trusted_dom_click": True},
        ), patch(
            "stage1_pause_sibling_click_step.wait_for_pause_sibling_probe",
            side_effect=lambda *a, **k: {"ready": True, "scrape": ledger_seq[0] if ledger_seq else {"probe_found": True, "count": 1, "event_count": 1, "impl_rev": "stage1_pause_sibling_probe_v1", "streamlit_session_id": "s1", "full_app_run_seq": "6", "payload": {"rows": [{"event_id": "x", "returned_true": True, "branch_entered": True}]}}},
        ):
            # Fix wait to return proper after scrape
            pass

        # Simpler: just verify resolve called twice on two execute calls
        call_count = {"n": 0}

        def resolve(_page):
            call_count["n"] += 1
            return frame

        with patch("stage1_pause_sibling_click_step.resolve_streamlit_app_frame", side_effect=resolve), patch(
            "stage1_pause_sibling_click_step.describe_page_frames", return_value={}
        ), patch("stage1_pause_sibling_click_step.scrape_pause_sibling_probe") as scrape, patch(
            "stage1_pause_sibling_click_step.scrape_pause_sibling_generation", return_value=gen
        ), patch(
            "stage1_pause_sibling_click_step.prepare_isolated_dom_click_capture", return_value={}
        ), patch(
            "stage1_pause_sibling_click_step.read_and_summarize_dom_click_capture",
            return_value={"trusted_dom_click": True},
        ), patch("stage1_pause_sibling_click_step.wait_for_pause_sibling_probe") as wait:
            scrape.side_effect = [
                {"probe_found": True, "count": 0, "event_count": 0, "impl_rev": "stage1_pause_sibling_probe_v1", "streamlit_session_id": "s1", "full_app_run_seq": 5},
                {"probe_found": True, "count": 1, "event_count": 1, "impl_rev": "stage1_pause_sibling_probe_v1", "streamlit_session_id": "s1", "full_app_run_seq": 6, "payload": {"rows": [{"event_id": "x", "returned_true": True, "branch_entered": True}]}},
            ]
            wait.return_value = {
                "ready": True,
                "scrape": {
                    "probe_found": True,
                    "count": 1,
                    "event_count": 1,
                    "impl_rev": "stage1_pause_sibling_probe_v1",
                    "streamlit_session_id": "s1",
                    "full_app_run_seq": 6,
                    "payload": {"rows": [{"event_id": "x", "returned_true": True, "branch_entered": True}]},
                },
            }
            execute_pause_sibling_click(page, phase="sibling_pre_pause", require_count_baseline=0)
            execute_pause_sibling_click(page, phase="sibling_post_pause", require_count_baseline=1)
        self.assertGreaterEqual(call_count["n"], 2)


if __name__ == "__main__":
    unittest.main()
