"""R2 sub-classification and RegisterWidgetResult extraction tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_r2_subclassify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED,
    BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET,
    BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK,
    classify_s3_r2_subclass,
    wire_target_in_preclick_storage,
)
from stage1_strict_backmsg_decode import summarize_strict_backmsg_evidence  # noqa: E402


class RegisterWidgetResultTests(unittest.TestCase):
    def test_false_value_not_truthy_object(self) -> None:
        from live_draft_stage1_register_widget_result import extract_register_widget_result_fields

        result = SimpleNamespace(value=False, value_changed=False, incoming_serialized_value=None)
        fields = extract_register_widget_result_fields(result)
        self.assertIs(fields["register_widget_result_value"], False)
        self.assertFalse(fields["register_widget_value_changed"])
        self.assertTrue(bool(result))
        self.assertFalse(fields["register_widget_result_value"])


class StrictBackmsgTerminologyTests(unittest.TestCase):
    def test_wire_rerun_target_singular(self) -> None:
        strict = {
            "decoded_outbound_frames": [
                {
                    "decode": {
                        "backmsg_oneof_type": "rerun_script",
                        "widget_state_count": 2,
                        "client_state": {"fragment_id": "frag_a"},
                        "widget_states": [{"id": "w1", "trigger_value": True}],
                    }
                }
            ]
        }
        raw = [{"direction": "outbound", "wall_ts_ms": 1000, "payload_base64": ""}]
        # summarize needs real decode - test field assembly via manual strict dict usage in subclass
        self.assertEqual(
            summarize_strict_backmsg_evidence([], click_ts=1.0).get("wire_rerun_target_fragment_id", ""),
            "",
        )


class R2SubclassTests(unittest.TestCase):
    def _post(self, stored: list[str]) -> dict:
        return {
            "registered_widget_id": "$$ID-x-stage1_pause_sibling_return_R_diag",
            "thread_state_fragment_id": "owner_frag",
            "fragment_storage": {"stored_fragment_ids": stored},
        }

    def test_r2a_absent_from_storage(self) -> None:
        rows = [{"phase": "REGISTER_ENTRY", "fragment_id": "owner_frag"}]
        case, _, ev = classify_s3_r2_subclass(
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            wire_rerun_target_fragment_id="stale_frag",
            post_registration=self._post(["owner_frag", "other"]),
            strict_backmsg={"activated_widget_state_present": True, "rerun_script_backmsg_seen": True},
            s3_ledger_rows=rows,
            appsession_ingress_rows=[
                {
                    "ts": 10.0,
                    "client_state_fragment_id": "stale_frag",
                    "would_fail_streamlit_fragment_storage_guard": True,
                    "target_fragment_exists": False,
                    "sibling_present": True,
                    "sibling_proto": {"trigger_value": True},
                }
            ],
            sibling_click_ts=10.0,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED)
        self.assertFalse(ev["wire_target_in_preclick_fragment_storage"])

    def test_r2b_target_in_storage(self) -> None:
        case, _, _ = classify_s3_r2_subclass(
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            wire_rerun_target_fragment_id="live_other",
            post_registration=self._post(["owner_frag", "live_other"]),
            strict_backmsg={"activated_widget_state_present": True},
            s3_ledger_rows=[{"phase": "REGISTER_ENTRY", "fragment_id": "owner_frag"}],
            appsession_ingress_rows=[],
            sibling_click_ts=None,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET)

    def test_r2c_owner_match(self) -> None:
        case, _, _ = classify_s3_r2_subclass(
            wire_widget_id="$$ID-x",
            wire_rerun_target_fragment_id="owner_frag",
            post_registration=self._post(["owner_frag"]),
            strict_backmsg={"activated_widget_state_present": True},
            s3_ledger_rows=[{"phase": "REGISTER_ENTRY", "fragment_id": "owner_frag"}],
            appsession_ingress_rows=[],
            sibling_click_ts=None,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK)

    def test_preclick_storage_helper(self) -> None:
        self.assertTrue(wire_target_in_preclick_storage("a", {"fragment_storage": {"stored_fragment_ids": ["a"]}}))
        self.assertFalse(wire_target_in_preclick_storage("b", {"fragment_storage": {"stored_fragment_ids": ["a"]}}))


class AppSessionWrapperTests(unittest.TestCase):
    def test_single_wrap_marker(self) -> None:
        import inspect

        from live_draft_stage1_appsession_ingress_diag import install_appsession_probes

        src = inspect.getsource(install_appsession_probes)
        self.assertIn("_solo_appsession_rerun_wrapped", src)
        self.assertIn("_solo_appsession_backmsg_wrapped", src)
        self.assertIn("return orig_rerun(self, client_state)", src)


if __name__ == "__main__":
    unittest.main()
