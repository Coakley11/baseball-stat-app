"""Harness tests for E2B sibling vs Pause transport A/B gate (legacy relaxed path)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_e2b_strict_backmsg_classify import BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED  # noqa: E402
from stage1_e2b_transport_gate_classify import (  # noqa: E402
    BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT,
    classify_e2b_transport_ab,
)


def _transport(backmsg: bool | None, *, authority: str = "available") -> dict:
    return {
        "transport_authority": authority,
        "streamlit_backmsg_sent": backmsg,
        "outbound_frames_after_click": 1 if backmsg else 0,
        "inbound_frames_after_click": 0,
    }


class E2BTransportClassifyTests(unittest.TestCase):
    def test_relaxed_defers_to_strict_unresolved(self) -> None:
        case, _ = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=_transport(False),
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=_transport(True),
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED)

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
        from stage1_streamlit_click_transport import clear_ws_boundary_log

        page = MagicMock()
        page.evaluate.return_value = {"cleared": True}
        with patch("p8_proven_start_delivery.aggregate_ws_boundary_log", return_value=[]):
            out = clear_ws_boundary_log(page)
        self.assertTrue(out.get("cleared"))


if __name__ == "__main__":
    unittest.main()
