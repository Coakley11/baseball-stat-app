"""Harness auth observability: Start surface vs ledger session binding."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from playwright_auth_observability import (  # noqa: E402
    AUTH_OBSERVABILITY1,
    AUTH_OBSERVABILITY2,
    AUTH_OBSERVABILITY3,
    AUTH_OBSERVABILITY4,
    CAPTURE_FAIL_OBSERVABILITY,
    classify_auth_observability,
    gather_page_observability,
    observability_aware_preflight_failure,
    session_binding_report,
)
from playwright_auth_capture_diag import classify_auth_login  # noqa: E402
from playwright_auth_capture_strict import evaluate_strict_capture  # noqa: E402


class TestObservabilityClassification(unittest.TestCase):
    def test_start_enabled_empty_ledger_is_observability1(self):
        ss = {"enabled": True, "visible": True, "frame_index": 0, "page_url": "https://x/?suite_sid=abc"}
        cp = {
            "start_enabled": True,
            "streamlit_session_id": "st-1",
            "diagnostic_run_id": "run-1",
            "diagnostic_query_flags": {
                "suite_sid_present": True,
                "solo_component_diag": True,
                "solo_stage1_parent_boundary": True,
                "live_draft_room_active": True,
            },
        }
        lb = {"auth_row_count": 0, "row_count": 0, "ledger_same_frame_as_start": True}
        binding = session_binding_report(cp, lb, harness_sid="abc-def")
        code, detail, _ = classify_auth_observability(
            start_surface=ss, checkpoint=cp, ledger_bind=lb, binding=binding
        )
        self.assertEqual(code, AUTH_OBSERVABILITY1)
        self.assertIn("empty", detail)

    def test_start_in_iframe_ledger_other_frame_observability2(self):
        ss = {"enabled": True, "frame_index": 2, "page_url": "https://x/?suite_sid=sid"}
        cp = {
            "start_enabled": True,
            "start_frame_index": 2,
            "streamlit_session_id": "",
            "diagnostic_run_id": "",
            "diagnostic_query_flags": {"suite_sid_present": True, "solo_component_diag": True},
        }
        lb = {"auth_row_count": 0, "row_count": 0, "ledger_same_frame_as_start": False}
        binding = session_binding_report(cp, lb, harness_sid="sid")
        code, _, _ = classify_auth_observability(
            start_surface=ss, checkpoint=cp, ledger_bind=lb, binding=binding
        )
        self.assertEqual(code, AUTH_OBSERVABILITY2)

    def test_missing_diag_flags_observability3(self):
        ss = {"enabled": True, "frame_index": 0}
        cp = {
            "start_enabled": True,
            "diagnostic_query_flags": {"suite_sid_present": False, "solo_component_diag": False},
        }
        lb = {"auth_row_count": 0, "row_count": 0}
        binding = session_binding_report(cp, lb, harness_sid="abc")
        code, _, _ = classify_auth_observability(
            start_surface=ss, checkpoint=cp, ledger_bind=lb, binding=binding
        )
        self.assertEqual(code, AUTH_OBSERVABILITY3)

    def test_ledger_rows_wrong_session_observability4(self):
        ss = {"enabled": True, "frame_index": 0}
        cp = {
            "start_enabled": True,
            "streamlit_session_id": "dom-st",
            "diagnostic_run_id": "dom-run",
            "diagnostic_query_flags": {"suite_sid_present": True, "solo_component_diag": True},
        }
        lb = {
            "auth_row_count": 0,
            "row_count": 5,
            "ledger_same_frame_as_start": True,
            "ledger_streamlit_session_id": "other-st",
            "ledger_diagnostic_run_id": "other-run",
        }
        binding = session_binding_report(cp, lb, harness_sid="full-suite-sid")
        binding["ui_ledger_streamlit_session_match"] = False
        binding["ui_ledger_run_match"] = False
        code, _, _ = classify_auth_observability(
            start_surface=ss, checkpoint=cp, ledger_bind=lb, binding=binding
        )
        self.assertEqual(code, AUTH_OBSERVABILITY4)

    def test_preflight_failure_not_streamlit_when_start_and_no_auth_rows(self):
        fail = observability_aware_preflight_failure(
            start_enabled=True,
            ledger_bind={"auth_row_count": 0},
            binding={},
            prior_failure="streamlit_auth_incomplete",
        )
        self.assertEqual(fail, CAPTURE_FAIL_OBSERVABILITY)


class TestMissingLedgerNotFalseAuth(unittest.TestCase):
    def test_strict_capture_empty_ledger_leaves_auth_unobserved(self):
        ev = evaluate_strict_capture(
            target_sid="0412e15d-7de8-428f-8973-9ebb3ff31564",
            url_sid="0412e15d-7de8-428f-8973-9ebb3ff31564",
            ledger_rows=[],
            start_enabled=True,
            start_visible=True,
            paired_authenticated=None,
        )
        self.assertEqual(ev.get("failure"), "streamlit_auth_incomplete")
        self.assertIsNone(ev.get("is_authenticated"))
        self.assertEqual(ev.get("auth_state_observability"), "not_observed")

    def test_no_auth_login1_when_start_enabled_and_harness_blind(self):
        state = {
            "steps": {"5_suite_sid_matches_target": True},
            "first_missing_transition": "1_sign_in_initiated",
            "strict_failure": "streamlit_auth_incomplete",
        }
        self.assertEqual(classify_auth_login(state, start_enabled=True), "")


class TestGatherPageObservability(unittest.TestCase):
    def test_gather_prefers_start_frame_for_ledger(self):
        from unittest.mock import patch

        page = MagicMock()
        page.url = (
            "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
            "?active_page=Live+Draft+Room&solo_component_diag=1&suite_sid=0412e15d-7de8-428f-8973-9ebb3ff31564"
        )
        main = MagicMock()
        main.url = page.url
        iframe = MagicMock()
        iframe.url = "https://embed.streamlit.app/"
        main.evaluate = MagicMock(
            return_value={"visible": False, "disabled": True},
        )
        iframe.evaluate = MagicMock(
            side_effect=[
                {"visible": True, "disabled": False},
                {
                    "streamlit_session_id": "969ef4d4",
                    "diagnostic_run_id": "8177ee38",
                    "script_run_seq": 3,
                    "row_count_attr": 0,
                    "probe_checkpoint": "pre_start",
                    "deploy_sha": "c3b2749",
                },
            ]
        )
        page.frames = [main, iframe]

        extract_payload = {
            "rows": [],
            "candidates": [{"frame_index": 1, "data_streamlit_session_id": "969ef4d4"}],
            "selected_frame_index": 1,
            "selected_frame_url": iframe.url,
            "selected_source": "dom#solo-stage1-production-ledger",
            "first_scrape_boundary": "empty",
            "pipeline_canary_present": False,
            "diagnostic_run_ids": [],
            "run_id": "",
        }
        with patch(
            "stage1_ledger_browser_extract.extract_stage1_ledger_from_page",
            return_value=extract_payload,
        ):
            obs = gather_page_observability(
                page,
                harness_sid="0412e15d-7de8-428f-8973-9ebb3ff31564",
                strict_failure="streamlit_auth_incomplete",
            )
        self.assertTrue(obs["start_surface"]["enabled"])
        self.assertEqual(obs["auth_observability_classification"], AUTH_OBSERVABILITY1)
        self.assertEqual(obs["override_failure"], CAPTURE_FAIL_OBSERVABILITY)


if __name__ == "__main__":
    unittest.main()
