"""Harness tests for E2B sibling vs Pause transport A/B gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_e2b_transport_gate_classify import (  # noqa: E402
    BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT,
    BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION,
    BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING,
    BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED,
    BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY,
    classify_e2b_transport_ab,
)
from stage1_streamlit_click_transport import clear_ws_boundary_log


def _transport(backmsg: bool | None, *, authority: str = "available") -> dict:
    return {
        "transport_authority": authority,
        "streamlit_backmsg_sent": backmsg,
        "outbound_frames_after_click": 1 if backmsg else 0,
        "inbound_frames_after_click": 0,
    }


class E2BTransportClassifyTests(unittest.TestCase):
    def test_t1_sibling_no_backmsg_pause_backmsg(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(False),
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION)

    def test_t2_both_backmsg_no_sibling_effect(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(True),
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING)

    def test_t3_backmsg_execution_no_trigger(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(True),
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
            sibling_server_execution_hint=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED)

    def test_t4_sibling_delivers(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(True),
            sibling_python_effect=True,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY)

    def test_t0_authority_unavailable(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(None, authority="unavailable"),
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT)


class TransportCaptureResetTests(unittest.TestCase):
    def test_ws_clear_invoked(self) -> None:
        page = MagicMock()
        page.evaluate.return_value = {"cleared": True}
        with patch("p8_proven_start_delivery.aggregate_ws_boundary_log", return_value=[]):
            out = clear_ws_boundary_log(page)
        self.assertTrue(out.get("cleared"))
        page.evaluate.assert_called_once()

    def test_sibling_and_pause_independent_ws_clear(self) -> None:
        from stage1_pause_sibling_transport_capture import capture_sibling_pre_pause_transport

        page = MagicMock()
        frame = MagicMock()
        frame.url = "https://host/~/+/"
        clears = []

        def fake_clear(p):
            clears.append("clear")
            return {"cleared": True}

        with patch(
            "stage1_pause_sibling_transport_capture.resolve_streamlit_app_frame",
            return_value=frame,
        ), patch(
            "stage1_pause_sibling_transport_capture.describe_page_frames",
            return_value={},
        ), patch(
            "stage1_pause_sibling_transport_capture.scrape_pause_sibling_probe",
            side_effect=[
                {
                    "probe_found": True,
                    "count": 0,
                    "event_count": 0,
                    "impl_rev": "stage1_pause_sibling_probe_v1",
                    "full_app_run_seq": 5,
                },
                {
                    "probe_found": True,
                    "count": 0,
                    "event_count": 0,
                    "impl_rev": "stage1_pause_sibling_probe_v1",
                    "full_app_run_seq": 5,
                },
            ],
        ), patch(
            "stage1_pause_sibling_transport_capture.scrape_pause_sibling_generation",
            return_value={"generation_found": True},
        ), patch("stage1_pause_sibling_transport_capture.clear_ws_boundary_log", side_effect=fake_clear), patch(
            "stage1_pause_sibling_transport_capture.prepare_isolated_dom_click_capture",
            return_value={"capture_cleared_before_click": True},
        ), patch(
            "stage1_pause_sibling_transport_capture.read_and_summarize_dom_click_capture",
            return_value={"trusted_dom_click": True},
        ), patch(
            "stage1_pause_sibling_transport_capture.capture_streamlit_click_transport",
            return_value={"transport_authority": "available", "streamlit_backmsg_sent": False},
        ):
            loc = MagicMock()
            loc.first.wait_for = MagicMock()
            loc.first.is_enabled.return_value = True
            loc.first.scroll_into_view_if_needed = MagicMock()
            loc.first.click = MagicMock()
            frame.get_by_role.return_value = loc
            page.wait_for_timeout = MagicMock()
            capture_sibling_pre_pause_transport(page)
        self.assertEqual(len(clears), 1)


if __name__ == "__main__":
    unittest.main()
