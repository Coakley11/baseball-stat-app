"""Strict BackMsg decode and S0–S4 classification tests."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_e2b_strict_backmsg_classify import (  # noqa: E402
    BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT,
    BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT,
    BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED,
    BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED,
    BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY,
    BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED,
    classify_strict_backmsg_ab,
)
from stage1_e2b_transport_gate_classify import classify_e2b_transport_ab  # noqa: E402
from stage1_strict_backmsg_decode import decode_outbound_frame_entry, summarize_strict_backmsg_evidence  # noqa: E402


def _make_rerun_backmsg(*, trigger: bool, widget_id: str = "w1") -> bytes:
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from streamlit.proto.ClientState_pb2 import ClientState

    bm = BackMsg()
    cs = ClientState()
    cs.fragment_id = "frag-test"
    cs.page_script_hash = "abc123"
    ws = cs.widget_states.widgets.add()
    ws.id = widget_id
    if trigger:
        ws.trigger_value = True
    bm.rerun_script.CopyFrom(cs)
    return bm.SerializeToString()


def _log_entry(data: bytes, *, wall_ms: float = 1_000_000.0) -> dict:
    return {
        "direction": "outbound",
        "wall_ts_ms": wall_ms,
        "byte_len": len(data),
        "frame_type_hint": "component_value_hint",
        "payload_base64": base64.b64encode(data).decode("ascii"),
    }


class StrictBackmsgDecodeTests(unittest.TestCase):
    def test_component_only_no_rerun_script(self) -> None:
        # Non-protobuf garbage with component-ish size — heuristic would be wrong.
        data = b"x" * 3041 + b"component"
        entry = _log_entry(data)
        dec = decode_outbound_frame_entry(entry)
        self.assertFalse((dec.get("decode") or {}).get("parsed"))

        summary = summarize_strict_backmsg_evidence(
            [entry],
            click_ts=999.9,
            relaxed_ws_sample=[{"direction": "outbound", "byte_len": 3041, "frame_type_hint": "component_value_hint"}],
        )
        self.assertTrue(summary.get("websocket_outbound_seen"))
        self.assertFalse(summary.get("rerun_script_backmsg_seen"))
        self.assertFalse(summary.get("activated_widget_state_present"))

    def test_rerun_without_trigger(self) -> None:
        data = _make_rerun_backmsg(trigger=False)
        summary = summarize_strict_backmsg_evidence([_log_entry(data)], click_ts=999.9)
        self.assertTrue(summary.get("rerun_script_backmsg_seen"))
        self.assertFalse(summary.get("activated_widget_state_present"))

    def test_rerun_with_trigger(self) -> None:
        data = _make_rerun_backmsg(trigger=True, widget_id="sibling-wid")
        summary = summarize_strict_backmsg_evidence([_log_entry(data)], click_ts=999.9)
        self.assertTrue(summary.get("activated_widget_state_present"))
        self.assertIn("sibling-wid", summary.get("activated_widget_ids") or [])

    def test_malformed_frame(self) -> None:
        entry = _log_entry(b"\x00\x01not-protobuf")
        dec = decode_outbound_frame_entry(entry)
        self.assertFalse((dec.get("decode") or {}).get("parsed"))


class StrictClassifyTests(unittest.TestCase):
    def _strict(self, *, rerun: bool, trigger: bool) -> dict:
        return {
            "protobuf_decode_available": True,
            "rerun_script_backmsg_seen": rerun,
            "activated_widget_state_present": trigger,
            "widget_states_present": rerun,
        }

    def test_s1(self) -> None:
        case, _ = classify_strict_backmsg_ab(
            sibling_strict=self._strict(rerun=False, trigger=False),
            pause_strict=self._strict(rerun=True, trigger=True),
            sibling_python_effect=False,
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT)

    def test_s2(self) -> None:
        case, _ = classify_strict_backmsg_ab(
            sibling_strict=self._strict(rerun=True, trigger=False),
            pause_strict=self._strict(rerun=True, trigger=True),
            sibling_python_effect=False,
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED)

    def test_s3(self) -> None:
        case, _ = classify_strict_backmsg_ab(
            sibling_strict=self._strict(rerun=True, trigger=True),
            pause_strict=self._strict(rerun=True, trigger=True),
            sibling_python_effect=False,
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED)

    def test_s4(self) -> None:
        case, _ = classify_strict_backmsg_ab(
            sibling_strict=self._strict(rerun=True, trigger=True),
            pause_strict=self._strict(rerun=True, trigger=True),
            sibling_python_effect=True,
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY)

    def test_s0_missing_payload(self) -> None:
        case, _ = classify_strict_backmsg_ab(
            sibling_strict={"protobuf_decode_available": False},
            pause_strict={"protobuf_decode_available": True, "rerun_script_backmsg_seen": True},
            sibling_python_effect=False,
            pause_resolved=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT)


class RelaxedClassifierRegressionTests(unittest.TestCase):
    def test_component_hint_cannot_classify_t2_or_t3(self) -> None:
        relaxed_sibling = {
            "streamlit_backmsg_sent": True,
            "transport_authority": "available",
            "outbound_frames_after_click": 1,
            "ws_log_sample": [{"frame_type_hint": "component_value_hint", "byte_len": 3041}],
        }
        relaxed_pause = {
            "streamlit_backmsg_sent": True,
            "transport_authority": "available",
            "outbound_frames_after_click": 2,
        }
        case, note = classify_e2b_transport_ab(
            sibling_trusted_click=True,
            sibling_transport=relaxed_sibling,
            sibling_python_effect=False,
            pause_trusted_click=True,
            pause_transport=relaxed_pause,
            pause_resolved=True,
            sibling_server_execution_hint=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED)
        self.assertIn("strict", note)


if __name__ == "__main__":
    unittest.main()
