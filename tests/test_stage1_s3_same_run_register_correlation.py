"""Same-run sibling REGISTER / button / fragment correlation harness tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from stage1_s3_r3_observability_classify import (  # noqa: E402
    BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST,
    BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION,
    BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY,
    classify_s3_with_observability,
)
from stage1_s3_same_run_register_correlation import (  # noqa: E402
    S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED,
    correlate_sibling_same_run_registration,
    register_result_for_classifier,
    st_button_for_classifier,
)

WID = "$$ID-6718bb162c71346c5a37319c79907822-stage1_pause_sibling_return_762E97F1_diag"
KEY = "stage1_pause_sibling_return_762E97F1_diag"
FRAG = "1c9cb8b65ec1d31bee602ff761f72826"
SID = "306476dc-2ccc-458f-8d94-8a1dd1c4bf2f"


def _row(phase: str, ts: float, **extra):
    r = {
        "event_id": f"e{phase[:6]}{int(ts * 1000) % 100000}",
        "ts": ts,
        "phase": phase,
        "streamlit_session_id": SID,
        "script_run_seq": extra.pop("script_run_seq", 20),
        "full_app_run_seq": extra.pop("full_app_run_seq", 20),
    }
    r.update(extra)
    return r


def _pause_obs_rows(seq: int = 20, base_ts: float = 900.0) -> list[dict]:
    """Minimal Pause chain so classify_s3_with_observability can reach R5/R6."""
    return [
        _row("RUNTIME_BACKMSG_ENTRY", base_ts, script_run_seq=seq, pause_present=True),
        _row("APPSESSION_BACKMSG_ENTRY", base_ts + 0.001, script_run_seq=seq, pause_present=True),
        _row("APPSESSION_REQUEST_RERUN_ENTRY", base_ts + 0.002, script_run_seq=seq, pause_present=True),
        _row("SAFE_SESSIONSTATE_RECEIVE_ENTRY", base_ts + 0.003, script_run_seq=seq, pause_present=True),
        _row("SERVER_RECEIVE_ENTRY", base_ts + 0.004, script_run_seq=seq, pause_present=True, sibling_present=True),
        _row(
            "SERVER_STATE_APPLIED",
            base_ts + 0.005,
            script_run_seq=seq,
            pause_present=True,
            pause_trigger_from_deserialized=True,
        ),
    ]


def _complete_same_run(*, reg_value: bool, button: bool, seq: int = 20, base_ts: float = 1000.0):
    return _pause_obs_rows(seq=seq, base_ts=base_ts - 50.0) + [
        _row(
            "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
            base_ts,
            script_run_seq=seq,
            pause_sibling_present=True,
            activated_triggers=[{"id": WID, "trigger_value": True}],
            fragment_id_queue=[FRAG],
        ),
        _row(
            "SERVER_STATE_APPLIED",
            base_ts + 0.01,
            script_run_seq=seq,
            sibling_present=True,
            trigger_from_deserialized=True,
            exact_widget_id=WID,
            deserialized_value_repr="True",
            present_in_new_widget_state=True,
            pause_present=True,
        ),
        _row(
            "CONTROL_CENTER_FRAGMENT_ENTRY",
            base_ts + 0.02,
            script_run_seq=seq,
            fragment_id=FRAG,
            current_fragment_id_ctx=FRAG,
            fragment_ids_this_run=[FRAG],
        ),
        _row(
            "SIBLING_RENDER_ENTRY",
            base_ts + 0.03,
            script_run_seq=seq,
            widget_user_key=KEY,
            user_key=KEY,
            fragment_id=FRAG,
            thread_state_fragment_id=FRAG,
        ),
        _row(
            "SIBLING_BUTTON_DECLARATION_ENTRY",
            base_ts + 0.04,
            script_run_seq=seq,
            user_key=KEY,
            widget_key=KEY,
            declaration_invocation_id="inv-same",
            declaration_reached=True,
        ),
        _row(
            "REGISTER_ENTRY",
            base_ts + 0.05,
            script_run_seq=seq,
            user_key=KEY,
            metadata_id=WID,
            declaration_invocation_id="inv-same",
            fragment_id=FRAG,
        ),
        _row(
            "REGISTER_RESULT",
            base_ts + 0.06,
            script_run_seq=seq,
            user_key=KEY,
            metadata_id=WID,
            declaration_invocation_id="inv-same",
            register_widget_result_value=reg_value,
            register_widget_value_changed=reg_value,
        ),
        _row(
            "SIBLING_BUTTON_CALL_RETURNED",
            base_ts + 0.07,
            script_run_seq=seq,
            user_key=KEY,
            widget_key=KEY,
            declaration_invocation_id="inv-same",
            st_button_returned=button,
            returned_value=button,
            registered_widget_id=WID,
        ),
    ]


class SameRunRegisterCorrelationTests(unittest.TestCase):
    def test_a_genuine_r5_same_run_complete(self) -> None:
        rows = _complete_same_run(reg_value=False, button=False)
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["correlation_complete"])
        self.assertIs(corr["register_widget_result_value"], False)
        self.assertIs(corr["st_button_returned"], False)
        case, note, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=WID,
            sibling_python_effect=False,
            register_widget_result=register_result_for_classifier(corr),
            st_button_returned=st_button_for_classifier(corr),
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST)
        self.assertEqual(note, "apply_true_register_false")

    def test_b_genuine_r6(self) -> None:
        rows = _complete_same_run(reg_value=True, button=False)
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["correlation_complete"])
        self.assertIs(corr["register_widget_result_value"], True)
        case, note, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=WID,
            sibling_python_effect=False,
            register_widget_result=register_result_for_classifier(corr),
            st_button_returned=st_button_for_classifier(corr),
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION)
        self.assertEqual(note, "register_true_button_false")

    def test_c_successful_delivery_r7(self) -> None:
        rows = _complete_same_run(reg_value=True, button=True)
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["correlation_complete"])
        case, note, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=WID,
            sibling_python_effect=True,
            register_widget_result=register_result_for_classifier(corr),
            st_button_returned=st_button_for_classifier(corr),
            binding_ok=True,
        )
        self.assertEqual(case, BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY)

    def test_d_historical_9c5b5aab_pattern_no_r5(self) -> None:
        rows = [
            _row(
                "REGISTER_RESULT",
                1786572538.3356748,
                script_run_seq=12,
                user_key=KEY,
                metadata_id=WID,
                register_widget_result_value=False,
                register_widget_value_changed=False,
            ),
            _row(
                "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
                1786572548.9394305,
                script_run_seq=20,
                pause_sibling_present=True,
                pause_present=True,
                activated_triggers=[{"id": WID, "trigger_value": True}],
            ),
            _row(
                "SERVER_STATE_APPLIED",
                1786572548.9561124,
                script_run_seq=20,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
                deserialized_value_repr="True",
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["server_applied_sibling"])
        self.assertFalse(corr["correlation_complete"])
        self.assertIsNone(corr["register_widget_result_value"])
        self.assertIsNone(register_result_for_classifier(corr))
        self.assertNotEqual(corr["first_missing_boundary"], "")
        # Setup false must not feed R5.
        case, _, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=WID,
            sibling_python_effect=False,
            register_widget_result=register_result_for_classifier(corr),
            st_button_returned=None,
            binding_ok=True,
        )
        self.assertNotEqual(case, BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST)

    def test_e_later_trigger_reset_keeps_same_run_true(self) -> None:
        rows = _complete_same_run(reg_value=True, button=True, seq=20, base_ts=1000.0)
        rows.append(
            _row(
                "REGISTER_RESULT",
                2000.0,
                script_run_seq=21,
                user_key=KEY,
                metadata_id=WID,
                register_widget_result_value=False,
                register_widget_value_changed=False,
                declaration_invocation_id="inv-later",
            )
        )
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertIs(corr["register_widget_result_value"], True)
        self.assertEqual(corr["declaration_invocation_id"], "inv-same")

    def test_f_fragment_never_executes(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertEqual(corr["first_missing_boundary"], "target_fragment_not_executed")
        self.assertIsNone(register_result_for_classifier(corr))

    def test_g_fragment_executes_sibling_render_not_reached(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row(
                "CONTROL_CENTER_FRAGMENT_ENTRY",
                1000.02,
                script_run_seq=5,
                fragment_id=FRAG,
                current_fragment_id_ctx=FRAG,
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["target_fragment_executed"])
        self.assertEqual(corr["first_missing_boundary"], "sibling_render_not_entered")

    def test_h_render_without_declaration(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row("CONTROL_CENTER_FRAGMENT_ENTRY", 1000.02, script_run_seq=5, fragment_id=FRAG),
            _row("SIBLING_RENDER_ENTRY", 1000.03, script_run_seq=5, widget_user_key=KEY, fragment_id=FRAG),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertEqual(corr["first_missing_boundary"], "sibling_declaration_not_entered")

    def test_i_declaration_without_register_entry(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row("CONTROL_CENTER_FRAGMENT_ENTRY", 1000.02, script_run_seq=5, fragment_id=FRAG),
            _row("SIBLING_RENDER_ENTRY", 1000.03, script_run_seq=5, widget_user_key=KEY, fragment_id=FRAG),
            _row(
                "SIBLING_BUTTON_DECLARATION_ENTRY",
                1000.04,
                script_run_seq=5,
                user_key=KEY,
                declaration_invocation_id="inv-x",
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertEqual(corr["first_missing_boundary"], "register_entry_absent")

    def test_j_register_entry_without_result(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row("CONTROL_CENTER_FRAGMENT_ENTRY", 1000.02, script_run_seq=5, fragment_id=FRAG),
            _row("SIBLING_RENDER_ENTRY", 1000.03, script_run_seq=5, widget_user_key=KEY, fragment_id=FRAG),
            _row(
                "SIBLING_BUTTON_DECLARATION_ENTRY",
                1000.04,
                script_run_seq=5,
                user_key=KEY,
                declaration_invocation_id="inv-x",
            ),
            _row(
                "REGISTER_ENTRY",
                1000.05,
                script_run_seq=5,
                user_key=KEY,
                metadata_id=WID,
                declaration_invocation_id="inv-x",
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertEqual(corr["first_missing_boundary"], "register_result_absent")

    def test_k_register_result_without_button_return(self) -> None:
        rows = [
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 1000.0, script_run_seq=5),
            _row(
                "SERVER_STATE_APPLIED",
                1000.01,
                script_run_seq=5,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row("CONTROL_CENTER_FRAGMENT_ENTRY", 1000.02, script_run_seq=5, fragment_id=FRAG),
            _row("SIBLING_RENDER_ENTRY", 1000.03, script_run_seq=5, widget_user_key=KEY, fragment_id=FRAG),
            _row(
                "SIBLING_BUTTON_DECLARATION_ENTRY",
                1000.04,
                script_run_seq=5,
                user_key=KEY,
                declaration_invocation_id="inv-x",
            ),
            _row(
                "REGISTER_ENTRY",
                1000.05,
                script_run_seq=5,
                user_key=KEY,
                metadata_id=WID,
                declaration_invocation_id="inv-x",
            ),
            _row(
                "REGISTER_RESULT",
                1000.06,
                script_run_seq=5,
                user_key=KEY,
                metadata_id=WID,
                declaration_invocation_id="inv-x",
                register_widget_result_value=True,
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertIs(corr["register_widget_result_value"], True)
        self.assertIsNone(corr["st_button_returned"])
        self.assertEqual(corr["first_missing_boundary"], "button_return_absent")
        self.assertFalse(corr["correlation_complete"])

    def test_l_coalesced_sibling_plus_pause_uses_consumed_run(self) -> None:
        rows = [
            _row(
                "SCRIPTREQUESTS_RERUN_STORED",
                10.0,
                script_run_seq=19,
                pause_sibling_present=True,
                activated_triggers=[{"id": WID, "trigger_value": True}],
            ),
            _row(
                "SCRIPTREQUESTS_RERUN_COALESCED",
                12.0,
                script_run_seq=19,
                pause_sibling_present=True,
                pause_present=True,
            ),
            _row(
                "SCRIPTRUNNER_RUN_SCRIPT_ENTRY",
                20.0,
                script_run_seq=20,
                pause_sibling_present=True,
                pause_present=True,
                activated_triggers=[
                    {"id": "$$ID-pause", "trigger_value": True},
                    {"id": WID, "trigger_value": True},
                ],
            ),
            _row(
                "SERVER_STATE_APPLIED",
                20.02,
                script_run_seq=20,
                sibling_present=True,
                pause_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
            _row("CONTROL_CENTER_FRAGMENT_ENTRY", 20.03, script_run_seq=20, fragment_id=FRAG),
            _row("SIBLING_RENDER_ENTRY", 20.04, script_run_seq=20, widget_user_key=KEY, fragment_id=FRAG),
            _row(
                "SIBLING_BUTTON_DECLARATION_ENTRY",
                20.05,
                script_run_seq=20,
                user_key=KEY,
                declaration_invocation_id="inv-coal",
            ),
            _row(
                "REGISTER_ENTRY",
                20.06,
                script_run_seq=20,
                user_key=KEY,
                metadata_id=WID,
                declaration_invocation_id="inv-coal",
            ),
            _row(
                "REGISTER_RESULT",
                20.07,
                script_run_seq=20,
                user_key=KEY,
                metadata_id=WID,
                declaration_invocation_id="inv-coal",
                register_widget_result_value=True,
            ),
            _row(
                "SIBLING_BUTTON_CALL_RETURNED",
                20.08,
                script_run_seq=20,
                user_key=KEY,
                declaration_invocation_id="inv-coal",
                st_button_returned=True,
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertTrue(corr["correlation_complete"])
        self.assertEqual(corr["script_run_seq"], 20)
        self.assertIs(corr["register_widget_result_value"], True)

    def test_m_run_identity_wins_over_list_order(self) -> None:
        rows = _complete_same_run(reg_value=True, button=False, seq=20, base_ts=1000.0)
        # Insert an earlier false AFTER in list order but older seq — must not win.
        rows.insert(
            0,
            _row(
                "REGISTER_RESULT",
                999.0,
                script_run_seq=12,
                user_key=KEY,
                metadata_id=WID,
                register_widget_result_value=False,
            ),
        )
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        self.assertIs(corr["register_widget_result_value"], True)

    def test_n_gate_regression_setup_false_cannot_produce_r5(self) -> None:
        """Historical LWW would select setup false; same-run helper must yield None → no R5."""
        rows = [
            _row(
                "REGISTER_RESULT",
                1.0,
                script_run_seq=12,
                user_key=KEY,
                metadata_id=WID,
                register_widget_result_value=False,
            ),
            _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", 10.0, script_run_seq=20),
            _row(
                "SERVER_STATE_APPLIED",
                10.01,
                script_run_seq=20,
                sibling_present=True,
                trigger_from_deserialized=True,
                exact_widget_id=WID,
            ),
        ]
        corr = correlate_sibling_same_run_registration(rows, wire_widget_id=WID, user_key=KEY, target_fragment_id=FRAG)
        reg = register_result_for_classifier(corr)
        self.assertIsNone(reg)
        # Emulate gate abort path label.
        self.assertTrue(corr["server_applied_sibling"] and reg is None)
        self.assertEqual(S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED, "S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED")
        # Legacy LWW simulation would incorrectly be False:
        lww = None
        for r in rows:
            if r.get("phase") == "REGISTER_RESULT" and isinstance(r.get("register_widget_result_value"), bool):
                lww = r.get("register_widget_result_value")
        self.assertIs(lww, False)
        case, _, _ = classify_s3_with_observability(
            module_rows=rows,
            authoritative_rows=rows,
            pause_resolved=True,
            strict_backmsg={"activated_widget_state_present": True},
            wire_widget_id=WID,
            sibling_python_effect=False,
            register_widget_result=reg,
            st_button_returned=False,
            binding_ok=True,
        )
        self.assertNotEqual(case, BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST)

    def test_critical_phases_include_register_and_sibling(self) -> None:
        from live_draft_stage1_s3_process_global_diag import CRITICAL_SERVER_PHASES

        for ph in (
            "REGISTER_ENTRY",
            "REGISTER_RESULT",
            "SIBLING_RENDER_ENTRY",
            "SIBLING_BUTTON_DECLARATION_ENTRY",
            "SIBLING_BUTTON_CALL_RETURNED",
            "CONTROL_CENTER_FRAGMENT_ENTRY",
        ):
            self.assertIn(ph, CRITICAL_SERVER_PHASES)

    def test_gate_source_no_longer_last_write_wins_authority(self) -> None:
        text = (SCRIPTS / "run_production_bridge_s3_server_registry_gate.py").read_text(encoding="utf-8")
        self.assertIn("correlate_sibling_same_run_registration", text)
        self.assertIn("S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED", text)
        self.assertIn("register_result_telemetry", text)
        # Old LWW scalar assignment pattern should not be the authority path.
        self.assertNotIn(
            'if isinstance(v, bool):\n                    reg_result = v',
            text,
        )


if __name__ == "__main__":
    unittest.main()
