"""Target-widget BackMsg correlation harness tests (sibling false-R2A capture race repair)."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_r2_subclassify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED,
    BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET,
    classify_sibling_oob_r2_from_snapshot,
    classify_s3_r2_subclass,
    wire_target_in_preclick_storage,
)
from stage1_strict_backmsg_decode import (  # noqa: E402
    correlate_target_trigger_backmsg,
    summarize_strict_backmsg_evidence,
)
from run_production_bridge_s3_server_registry_gate import _wire_from_sibling_step  # noqa: E402

SIBLING_WID = "$$ID-e2dc822b92d71e4c11c622ae2ebe2f27-stage1_pause_sibling_return_AEB2509F_diag"
OWNER = "1c9cb8b65ec1d31bee602ff761f72826"
STALE = "315dc5507ea8b1bec953567a36922eb4"
LIVE_OTHER = "6d38c210b43a693587cac46dce3bc6d0"


def _decoded_frame(
    *,
    fragment_id: str,
    wall_ts_ms: float,
    widgets: list[dict] | None = None,
) -> dict:
    wlist = list(widgets or [])
    return {
        "wall_ts_ms": wall_ts_ms,
        "has_payload_base64": True,
        "decode": {
            "parsed": True,
            "backmsg_oneof_type": "rerun_script",
            "client_state": {"fragment_id": fragment_id},
            "widget_state_count": len(wlist),
            "widget_states": wlist,
        },
    }


def _summary(frames: list[dict], *, expected: str = "", click_ts: float = 1786569254.804) -> dict:
    return summarize_strict_backmsg_evidence(
        [],
        click_ts=click_ts,
        expected_widget_id=expected,
        decoded_outbound_frames=frames,
    )


class TargetBackmsgCorrelationTests(unittest.TestCase):
    def test_a_historical_race_selects_owner_not_stale(self) -> None:
        frames = [
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1786569254776.0, widgets=[]),
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1786569254798.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertTrue(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertEqual(out["first_rerun_fragment_id"], STALE)
        self.assertIn(STALE, out["all_rerun_fragment_ids"])
        self.assertEqual(out["target_backmsg_consistency"]["unrelated_rerun_count_before_target"], 1)

    def test_b_target_frame_is_first(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1000.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1100.0, widgets=[]),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertEqual(out["target_trigger_frame_index"], 0)

    def test_c_several_unrelated_before_target(self) -> None:
        frames = [
            _decoded_frame(fragment_id="aaa", wall_ts_ms=1.0),
            _decoded_frame(fragment_id="bbb", wall_ts_ms=2.0),
            _decoded_frame(fragment_id="ccc", wall_ts_ms=3.0),
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=4.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertEqual(out["target_backmsg_consistency"]["unrelated_rerun_count_before_target"], 3)

    def test_d_several_unrelated_after_target(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
            _decoded_frame(fragment_id="ddd", wall_ts_ms=2.0),
            _decoded_frame(fragment_id="eee", wall_ts_ms=3.0),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertEqual(out["target_backmsg_consistency"]["unrelated_rerun_count_after_target"], 2)

    def test_e_no_target_widget_trigger(self) -> None:
        frames = [
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1.0),
            _decoded_frame(fragment_id=OWNER, wall_ts_ms=2.0),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertFalse(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], "")
        self.assertEqual(out["first_rerun_fragment_id"], STALE)

    def test_f_target_present_trigger_false(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": False}],
            )
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertFalse(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], "")

    def test_g_multiple_activated_widgets_in_target_frame(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1.0,
                widgets=[
                    {"id": "other-wid", "trigger_value": True},
                    {"id": SIBLING_WID, "trigger_value": True},
                ],
            )
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertTrue(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertIn(SIBLING_WID, out["target_trigger_activated_widget_ids"])
        self.assertIn("other-wid", out["activated_widget_ids"])

    def test_h_true_r2a_still_detectable(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=STALE,
                wall_ts_ms=1.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            )
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertTrue(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], STALE)
        post = {
            "registered_widget_id": SIBLING_WID,
            "thread_state_fragment_id": OWNER,
            "fragment_storage": {"stored_fragment_ids": [OWNER, LIVE_OTHER]},
        }
        self.assertFalse(wire_target_in_preclick_storage(STALE, post))
        case, note, _ev = classify_s3_r2_subclass(
            wire_widget_id=SIBLING_WID,
            wire_rerun_target_fragment_id=STALE,
            post_registration=post,
            strict_backmsg={"activated_widget_state_present": True, "rerun_script_backmsg_seen": True},
            s3_ledger_rows=[{"phase": "REGISTER_ENTRY", "fragment_id": OWNER}],
            appsession_ingress_rows=[],
            sibling_click_ts=None,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED)
        # OOB path also remains available.
        oob = classify_sibling_oob_r2_from_snapshot(
            oob_snapshot={
                "snapshot_generation": 25,
                "module_ledger_rows": [
                    {"phase": "RUNTIME_BACKMSG_ENTRY"},
                    {"phase": "APPSESSION_BACKMSG_ENTRY"},
                    {"phase": "APPSESSION_REQUEST_RERUN_ENTRY"},
                ],
                "critical_ledger_rows": [],
            },
            wire_rerun_target_fragment_id=STALE,
            owner_fragment_id=OWNER,
            wire_target_in_preclick_fragment_storage=False,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=SIBLING_WID,
            post_registration=post,
        )
        self.assertIsNotNone(oob)
        self.assertEqual(oob[0], BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED)

    def test_i_true_r2b_still_detectable(self) -> None:
        frames = [
            _decoded_frame(
                fragment_id=LIVE_OTHER,
                wall_ts_ms=1.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            )
        ]
        out = _summary(frames, expected=SIBLING_WID)
        self.assertEqual(out["wire_rerun_target_fragment_id"], LIVE_OTHER)
        post = {
            "registered_widget_id": SIBLING_WID,
            "thread_state_fragment_id": OWNER,
            "fragment_storage": {"stored_fragment_ids": [OWNER, LIVE_OTHER]},
        }
        case, _, _ = classify_s3_r2_subclass(
            wire_widget_id=SIBLING_WID,
            wire_rerun_target_fragment_id=LIVE_OTHER,
            post_registration=post,
            strict_backmsg={"activated_widget_state_present": True},
            s3_ledger_rows=[{"phase": "REGISTER_ENTRY", "fragment_id": OWNER}],
            appsession_ingress_rows=[],
            sibling_click_ts=None,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET)

    def test_j_legacy_caller_first_rerun(self) -> None:
        frames = [
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1.0),
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=2.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
        ]
        out = _summary(frames, expected="")
        self.assertFalse(out["target_correlation_requested"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], STALE)

    def test_k_gate_fallback_does_not_pick_unrelated(self) -> None:
        sibling_step = {
            "expected_widget_id": SIBLING_WID,
            "streamlit_transport": {
                "strict_backmsg": {
                    "expected_widget_id": SIBLING_WID,
                    "target_correlation_requested": True,
                    "target_trigger_backmsg_seen": False,
                    "wire_rerun_target_fragment_id": "",
                    "first_rerun_fragment_id": STALE,
                    "activated_widget_ids": [],
                    "decoded_outbound_frames": [
                        _decoded_frame(fragment_id=STALE, wall_ts_ms=1.0),
                        _decoded_frame(fragment_id=OWNER, wall_ts_ms=2.0),
                    ],
                }
            },
        }
        wire, wire_target, strict = _wire_from_sibling_step(sibling_step)
        self.assertEqual(wire, SIBLING_WID)
        self.assertEqual(wire_target, "")
        self.assertFalse(strict.get("target_trigger_backmsg_seen"))

    def test_l_historical_fixture_wire_equals_owner_in_storage(self) -> None:
        frames = [
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1786569254776.0, widgets=[]),
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=1786569254798.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
            _decoded_frame(fragment_id="5a8b8c0723c6423e30b16b9b817b4692", wall_ts_ms=1786569255210.0),
            _decoded_frame(fragment_id="77c6fcb93c637a75a45a3ad326d2d094", wall_ts_ms=1786569255376.0),
        ]
        out = _summary(frames, expected=SIBLING_WID)
        sibling_step = {
            "expected_widget_id": SIBLING_WID,
            "streamlit_transport": {"strict_backmsg": out},
        }
        wire, wire_target, _strict = _wire_from_sibling_step(sibling_step)
        self.assertEqual(wire, SIBLING_WID)
        self.assertEqual(wire_target, OWNER)
        post = {
            "registered_widget_id": SIBLING_WID,
            "thread_state_fragment_id": OWNER,
            "fragment_storage": {"stored_fragment_ids": [OWNER, LIVE_OTHER]},
        }
        self.assertTrue(wire_target_in_preclick_storage(wire_target, post))
        self.assertEqual(wire_target, OWNER)

    def test_correlate_helper_direct(self) -> None:
        frames = [
            _decoded_frame(fragment_id=STALE, wall_ts_ms=1.0),
            _decoded_frame(
                fragment_id=OWNER,
                wall_ts_ms=2.0,
                widgets=[{"id": SIBLING_WID, "trigger_value": True}],
            ),
        ]
        corr = correlate_target_trigger_backmsg(frames, expected_widget_id=SIBLING_WID)
        self.assertTrue(corr["target_trigger_backmsg_seen"])
        self.assertEqual(corr["wire_rerun_target_fragment_id"], OWNER)

    def test_gate_wires_expected_widget_into_capture(self) -> None:
        import inspect

        from run_production_bridge_s3_server_registry_gate import main

        src = inspect.getsource(main)
        self.assertIn("expected_widget_id=sibling_expected_widget_id", src)
        self.assertIn("sibling_target_trigger_backmsg_not_observed", src)
        self.assertIn("target_trigger_backmsg_seen", src)


class ProtobufTargetCorrelationTests(unittest.TestCase):
    def _make_rerun(self, *, fragment_id: str, widget_id: str, trigger: bool) -> bytes:
        from streamlit.proto.BackMsg_pb2 import BackMsg
        from streamlit.proto.ClientState_pb2 import ClientState

        bm = BackMsg()
        cs = ClientState()
        cs.fragment_id = fragment_id
        ws = cs.widget_states.widgets.add()
        ws.id = widget_id
        if trigger:
            ws.trigger_value = True
        bm.rerun_script.CopyFrom(cs)
        return bm.SerializeToString()

    def _entry(self, data: bytes, wall_ms: float) -> dict:
        return {
            "direction": "outbound",
            "wall_ts_ms": wall_ms,
            "byte_len": len(data),
            "payload_base64": base64.b64encode(data).decode("ascii"),
        }

    def test_protobuf_race_pattern(self) -> None:
        click_ts = 1000.0
        raw = [
            self._entry(self._make_rerun(fragment_id=STALE, widget_id="x", trigger=False), 1000_000.0 - 20),
            self._entry(self._make_rerun(fragment_id=OWNER, widget_id=SIBLING_WID, trigger=True), 1000_000.0 + 5),
        ]
        out = summarize_strict_backmsg_evidence(raw, click_ts=click_ts, expected_widget_id=SIBLING_WID)
        self.assertTrue(out["target_trigger_backmsg_seen"])
        self.assertEqual(out["wire_rerun_target_fragment_id"], OWNER)
        self.assertEqual(out["first_rerun_fragment_id"], STALE)


if __name__ == "__main__":
    unittest.main()
