"""Process-global S3 diagnostic routing tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from live_draft_stage1_s3_process_global_diag import (
    append_module_event,
    is_pause_sibling_widget_id,
    is_pause_widget_id,
    module_ledger_rows,
    register_sessionstate_instance,
    resolve_sessionstate_streamlit_session_id,
    scan_widget_states_proto,
)


class ProcessGlobalRoutingTests(unittest.TestCase):
    def test_two_sessions_separate_ledgers(self) -> None:
        append_module_event("session-a", "TEST", marker="a")
        append_module_event("session-b", "TEST", marker="b")
        a_rows = module_ledger_rows("session-a")
        b_rows = module_ledger_rows("session-b")
        self.assertEqual(a_rows[-1].get("marker"), "a")
        self.assertEqual(b_rows[-1].get("marker"), "b")

    def test_sessionstate_instance_routing(self) -> None:
        ss1 = object()
        ss2 = object()
        register_sessionstate_instance(ss1, "sid-one")
        register_sessionstate_instance(ss2, "sid-two")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(ss1), "sid-one")
        self.assertEqual(resolve_sessionstate_streamlit_session_id(ss2), "sid-two")

    def test_widget_id_heuristics(self) -> None:
        self.assertTrue(is_pause_sibling_widget_id("$$ID-x-stage1_pause_sibling_return_ROOM_diag"))
        self.assertTrue(is_pause_widget_id("$$ID-x-live_draft_pause"))

    def test_scan_triggers_without_watch_key(self) -> None:
        ws = SimpleNamespace(
            widgets=[
                SimpleNamespace(id="$$ID-a-stage1_pause_sibling_return_R_diag", trigger_value=True, bool_value=True, string_value=""),
                SimpleNamespace(id="$$ID-b-live_draft_pause", trigger_value=True, bool_value=True, string_value=""),
            ]
        )
        wss = SimpleNamespace(widgets=ws.widgets)
        scan = scan_widget_states_proto(wss)
        self.assertTrue(scan["pause_sibling_present"])
        self.assertTrue(scan["pause_present"])


class ObservabilityClassifyTests(unittest.TestCase):
    def test_r3o0_not_r3(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from stage1_s3_r3_observability_classify import (
            BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
            classify_s3_with_observability,
        )

        case, _, _ = classify_s3_with_observability(
            module_rows=[],
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            sibling_python_effect=False,
            register_widget_result=False,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT)

    def test_r3a(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from stage1_s3_r3_observability_classify import (
            BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH,
            classify_s3_with_observability,
        )

        rows = [
            {"phase": "RUNTIME_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_BACKMSG_ENTRY", "pause_present": True},
            {"phase": "APPSESSION_REQUEST_RERUN_ENTRY", "pause_present": True},
            {"phase": "SAFE_SESSIONSTATE_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_RECEIVE_ENTRY", "pause_present": True},
            {"phase": "SERVER_STATE_APPLIED", "pause_present": True, "pause_trigger_from_deserialized": True},
            {"phase": "APPSESSION_BACKMSG_ENTRY", "pause_sibling_present": True},
        ]
        case, _, _ = classify_s3_with_observability(
            module_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id="$$ID-x-stage1_pause_sibling_return_R_diag",
            sibling_python_effect=False,
            register_widget_result=False,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH)


class AppSessionIdTests(unittest.TestCase):
    def test_appsession_uses_self_id_not_ctx(self) -> None:
        import inspect

        from live_draft_stage1_appsession_ingress_diag import _appsession_streamlit_session_id, _record_request_rerun

        src = inspect.getsource(_record_request_rerun)
        self.assertIn("_appsession_streamlit_session_id", src)
        self.assertIn("register_sessionstate_from_appsession_owner", src)
        self.assertNotIn("get_script_run_ctx", src)
        app = SimpleNamespace(id="streamlit-session-uuid", _fragment_storage=None)
        self.assertEqual(_appsession_streamlit_session_id(app), "streamlit-session-uuid")


if __name__ == "__main__":
    unittest.main()
