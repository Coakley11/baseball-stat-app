"""Instrumentation-only tests for Live Draft start Stage-1 observability."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from live_draft_stage1_production_ledger import GATE_A_EXPORT_PINNED_EVENTS, ledger_rows_for_export
from live_draft_start_stage1_observability import (
    EVENT_CALLBACK_ENTERED,
    EVENT_CALLBACK_EXITED,
    EVENT_HANDLER_ENTERED,
    EVENT_HANDLER_EXITED,
    EVENT_PENDING_ABSENT,
    EVENT_PENDING_CONSUMED,
    EVENT_PENDING_OBSERVED,
    emit_start_callback_entered,
    emit_start_callback_exited,
    record_pending_start_boundary_after_pop,
    record_pending_start_boundary_before_pop,
)


def _enabled_session(**extra: object) -> dict:
    session: dict = {"_solo_component_diag_enabled": True, "_solo_stage1_run_id": "testrun01", **extra}
    return session


class StartCallbackInstrumentationTests(unittest.TestCase):
    def test_callback_entry_emits_canary_and_ledger_without_mutating_pending(self) -> None:
        session = _enabled_session()
        before_pending = session.get("_start_live_draft_pending")
        buf = io.StringIO()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ), redirect_stdout(buf):
            row = emit_start_callback_entered(session)
        self.assertEqual(session.get("_start_live_draft_pending"), before_pending)
        self.assertEqual(row.get("event"), EVENT_CALLBACK_ENTERED)
        self.assertIn("SOLO_STAGE1_BOUNDARY_CANARY|", buf.getvalue())
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        self.assertTrue(any(r.get("event") == EVENT_CALLBACK_ENTERED for r in merged))

    def test_callback_exit_runs_for_gate_not_armed_path(self) -> None:
        session = _enabled_session()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            emit_start_callback_exited(
                session,
                pending_armed=False,
                exit_reason="gate_not_armed",
                gate_error="setup_invalid",
            )
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        self.assertTrue(any(r.get("event") == EVENT_CALLBACK_EXITED for r in merged))
        exit_row = next(r for r in merged if r.get("event") == EVENT_CALLBACK_EXITED)
        self.assertFalse(exit_row.get("pending_armed"))
        self.assertEqual(exit_row.get("exit_reason"), "gate_not_armed")

    def test_on_start_callback_wrapper_finally_emits_exit_on_early_return(self) -> None:
        import sys
        import types

        from draft_ui import on_start_new_live_draft

        session: dict = _enabled_session()
        st_mod = types.ModuleType("streamlit")
        st_mod.st = mock.Mock()
        st_mod.st.session_state = session
        st_mod.session_state = session
        with mock.patch.dict(sys.modules, {"streamlit": st_mod}), mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ), mock.patch(
            "live_draft_start_setup.gate_start_new_live_draft_click",
            return_value={"armed": False, "ok": False, "error": "blocked", "replace_pending": False},
        ), mock.patch("live_draft_setup_persist.flush_live_draft_setup_persist"), mock.patch(
            "draft_ui.mark_start_live_draft_clicked"
        ):
            on_start_new_live_draft()
        events = [r.get("event") for r in session.get("_solo_stage1_production_ledger_merged") or []]
        self.assertIn(EVENT_CALLBACK_ENTERED, events)
        self.assertIn(EVENT_CALLBACK_EXITED, events)
        self.assertNotIn("_start_live_draft_pending", session)


class PendingStartBoundaryTests(unittest.TestCase):
    def test_absent_when_pending_key_missing(self) -> None:
        session = _enabled_session()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            was_present, raw = record_pending_start_boundary_before_pop(None, session)
        self.assertFalse(was_present)
        self.assertIsNone(raw)
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        self.assertTrue(any(r.get("event") == EVENT_PENDING_ABSENT for r in merged))

    def test_observed_and_consumed_without_changing_pending(self) -> None:
        session = _enabled_session(_start_live_draft_pending=True)
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            was_present, raw = record_pending_start_boundary_before_pop(None, session)
            self.assertTrue(was_present)
            self.assertTrue(raw)
            self.assertTrue(session.get("_start_live_draft_pending"))
            record_pending_start_boundary_after_pop(
                None, session, was_present=True, will_execute=True
            )
        events = [r.get("event") for r in session.get("_solo_stage1_production_ledger_merged") or []]
        self.assertIn(EVENT_PENDING_OBSERVED, events)
        self.assertIn(EVENT_PENDING_CONSUMED, events)


class LateProbeExportTests(unittest.TestCase):
    def test_gate_a_export_includes_new_start_instrumentation_events(self) -> None:
        for name in (
            EVENT_CALLBACK_ENTERED,
            EVENT_CALLBACK_EXITED,
            EVENT_PENDING_OBSERVED,
            EVENT_PENDING_CONSUMED,
            EVENT_PENDING_ABSENT,
        ):
            self.assertIn(name, GATE_A_EXPORT_PINNED_EVENTS)

    def test_late_export_includes_same_run_handler_rows(self) -> None:
        from live_draft_stage1_production_ledger import note_stage1_event, render_stage1_production_ledger_probe

        session = _enabled_session()
        st = mock.Mock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            note_stage1_event(session, EVENT_HANDLER_ENTERED, st=st)
            note_stage1_event(session, EVENT_HANDLER_EXITED, st=st, extra={"handler_success": True})
            render_stage1_production_ledger_probe(st, session)
        exported = ledger_rows_for_export(session)
        names = {r.get("event") for r in exported}
        self.assertIn(EVENT_HANDLER_ENTERED, names)
        self.assertIn(EVENT_HANDLER_EXITED, names)


class EarlyPredicateInstrumentationTests(unittest.TestCase):
    def test_early_predicate_emits_when_room_dict_present(self) -> None:
        from live_draft_queueui_predicate_audit import emit_queueui_predicate_audit

        session = _enabled_session(
            live_draft_room={
                "draft_room_id": "ABCD1234",
                "status": "in_progress",
                "current_pick_index": 0,
            },
            active_page="Live Draft Room",
        )
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            emit_queueui_predicate_audit(
                session,
                st=mock.Mock(),
                checkpoint="ldr_early_room_present",
                room=session["live_draft_room"],
                lifecycle="active_draft",
                extra={"next_controlling_branch": "ldr_main_continue"},
            )
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        row = next(r for r in merged if r.get("event") == "production_stage1_queueui_predicate_audit")
        self.assertEqual(row.get("checkpoint"), "ldr_early_room_present")
        self.assertEqual(row.get("next_controlling_branch"), "ldr_main_continue")
        self.assertNotIn("_start_live_draft_pending", session)


if __name__ == "__main__":
    unittest.main()
