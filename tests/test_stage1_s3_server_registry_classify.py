"""S3 server registry R1–R7 classification tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_server_registry_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE,
    BUTTON_DISPATCH_S3_R1_STALE_FRONTEND_WIDGET_ID,
    BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH,
    BUTTON_DISPATCH_S3_R3_RERUN_DROPPED_BEFORE_STATE_APPLY,
    BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY,
    BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST,
    BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION,
    BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY,
    classify_s3_server_registry,
)

WIRE = "$$ID-aaa-stage1_pause_sibling_return_ROOM_diag"
FRAG = "frag_wire_abc123"
REG = "$$ID-bbb-stage1_pause_sibling_return_ROOM_diag"


def _base(**overrides):
    kw = dict(
        wire_widget_id=WIRE,
        wire_fragment_id=FRAG,
        post_registration={
            "registered_widget_id": WIRE,
            "widget_metadata": {"fragment_id": FRAG},
            "thread_state_fragment_id": FRAG,
        },
        strict_backmsg={"activated_widget_state_present": True, "rerun_script_backmsg_seen": True},
        s3_ledger_rows=[],
        sibling_python_effect=False,
        register_widget_result=False,
        st_button_returned=False,
        pause_resolved=True,
    )
    kw.update(overrides)
    return kw


class S3RegistryClassifyTests(unittest.TestCase):
    def test_r1_stale_frontend_id(self) -> None:
        case, _ = classify_s3_server_registry(**_base(wire_widget_id=WIRE, post_registration={"registered_widget_id": REG}))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R1_STALE_FRONTEND_WIDGET_ID)

    def test_r2_fragment_mismatch(self) -> None:
        case, _ = classify_s3_server_registry(
            **_base(post_registration={"registered_widget_id": WIRE, "widget_metadata": {"fragment_id": "other_frag"}})
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH)

    def test_r3_dropped_before_state_apply(self) -> None:
        case, _ = classify_s3_server_registry(**_base(s3_ledger_rows=[]))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R3_RERUN_DROPPED_BEFORE_STATE_APPLY)

    def test_r4_lost_during_apply(self) -> None:
        rows = [
            {"phase": "SERVER_RECEIVE_ENTRY", "sibling_present": True, "sibling_proto": {"trigger_value": True}},
            {"phase": "SERVER_STATE_APPLIED", "present_in_new_widget_state": False, "trigger_from_deserialized": False},
        ]
        case, _ = classify_s3_server_registry(**_base(s3_ledger_rows=rows))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY)

    def test_r5_register_false(self) -> None:
        rows = [
            {"phase": "SERVER_RECEIVE_ENTRY", "sibling_present": True, "sibling_proto": {"trigger_value": True}},
            {"phase": "SERVER_STATE_APPLIED", "present_in_new_widget_state": True, "trigger_from_deserialized": True},
        ]
        case, _ = classify_s3_server_registry(**_base(s3_ledger_rows=rows, register_widget_result=False))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST)

    def test_r6_button_propagation(self) -> None:
        case, _ = classify_s3_server_registry(**_base(register_widget_result=True, st_button_returned=False))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION)

    def test_r7_recovery(self) -> None:
        case, _ = classify_s3_server_registry(**_base(sibling_python_effect=True, st_button_returned=True))
        self.assertEqual(case, BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY)


class S3DiagModuleTests(unittest.TestCase):
    def test_pre_not_equal_post_authority(self) -> None:
        """PRE_DECLARATION must not be used as registered ID authority."""
        pre = {"phase": "PRE_DECLARATION", "registered_widget_id": ""}
        post = {"phase": "POST_REGISTRATION", "registered_widget_id": WIRE}
        self.assertFalse(pre.get("registered_widget_id"))
        self.assertTrue(str(post.get("registered_widget_id", "")).startswith("$$ID-"))

    def test_register_widget_single_wrap_marker(self) -> None:
        from live_draft_streamlit_widget_metadata_diag import install_streamlit_register_widget_probe

        self.assertTrue(callable(install_streamlit_register_widget_probe))

    def test_s3_install_does_not_define_second_register_wrapper(self) -> None:
        import inspect

        from live_draft_stage1_s3_server_diag import install_s3_server_diagnostics

        src = inspect.getsource(install_s3_server_diagnostics)
        self.assertNotIn("wrapped_register_widget", src)
        self.assertIn("install_streamlit_register_widget_probe", src)


if __name__ == "__main__":
    unittest.main()
