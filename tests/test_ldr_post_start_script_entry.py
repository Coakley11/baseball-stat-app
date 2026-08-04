"""Tests for unconditional ldr_post_start_script_entry predicate checkpoint."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from live_draft_queueui_predicate_audit import (  # noqa: E402
    POST_START_SCRIPT_ENTRY_CHECKPOINT,
    _POST_START_ENTRY_EMITTED_SEQ_KEY,
    emit_ldr_post_start_script_entry,
    emit_queueui_predicate_audit,
)
from queueui_audit_protocol import (  # noqa: E402
    distinct_predicate_script_run_seq,
    evaluate_audit_completion,
)
from queueui_root_classify import classify_queueui_root  # noqa: E402


def _session(**extra: object) -> dict:
    base: dict = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_run_id": "poststart01",
        "_solo_stage1_script_run_seq": 1,
        "active_page": "Live Draft Room",
    }
    base.update(extra)
    return base


class LdrPostStartScriptEntryTests(unittest.TestCase):
    def test_emits_once_per_script_execution(self) -> None:
        session = _session()
        st = mock.Mock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            r1 = emit_ldr_post_start_script_entry(session, st=st)
            r2 = emit_ldr_post_start_script_entry(session, st=st)
        self.assertTrue(r1)
        self.assertEqual(r2, {})
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        rows = [
            r
            for r in merged
            if r.get("event") == "production_stage1_queueui_predicate_audit"
            and r.get("checkpoint") == POST_START_SCRIPT_ENTRY_CHECKPOINT
        ]
        self.assertEqual(len(rows), 1)

    def test_emits_when_no_room_dictionary(self) -> None:
        session = _session(live_draft_room=None)
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            row = emit_ldr_post_start_script_entry(session, st=mock.Mock())
        self.assertEqual(row.get("checkpoint"), POST_START_SCRIPT_ENTRY_CHECKPOINT)
        preds = row.get("predicates") or {}
        self.assertFalse(preds.get("live_draft_room_present"))

    def test_emits_when_authentication_false(self) -> None:
        session = _session(
            live_draft_room={"draft_room_id": "ABCD1234", "status": "in_progress"},
        )
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ), mock.patch("suite_auth.is_auth_enabled", return_value=True), mock.patch(
            "suite_auth.is_authenticated", return_value=False
        ):
            row = emit_ldr_post_start_script_entry(session, st=mock.Mock())
        auth = row.get("auth") or {}
        self.assertFalse(auth.get("authenticated"))

    def test_runs_before_restore_block_branch_candidate(self) -> None:
        session = _session(_live_draft_restore_blocked_reason="auth_required")
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            row = emit_ldr_post_start_script_entry(session, st=mock.Mock())
        self.assertIn("restore_blocked", str(row.get("next_controlling_branch") or ""))
        restore = row.get("restore") or {}
        self.assertEqual(restore.get("restore_blocked_reason"), "auth_required")

    def test_retains_diagnostic_run_and_session_identity(self) -> None:
        session = _session(_solo_stage1_run_id="run_identity_x")
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            row = emit_ldr_post_start_script_entry(session, st=mock.Mock())
        self.assertEqual(row.get("run_id"), "run_identity_x")
        self.assertTrue(str(row.get("streamlit_session_id") or "") == "" or row.get("streamlit_session_id"))

    def test_does_not_mutate_control_state(self) -> None:
        session = _session(
            live_draft_room={"draft_room_id": "R1", "status": "in_progress", "current_pick_index": 0},
            _start_live_draft_pending=True,
            _live_draft_start_in_flight=True,
            _live_draft_restore_blocked_reason="auth_required",
        )
        snap = copy.deepcopy(session)
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            emit_ldr_post_start_script_entry(session, st=mock.Mock())
        for key in (
            "live_draft_room",
            "_start_live_draft_pending",
            "_live_draft_start_in_flight",
            "_live_draft_restore_blocked_reason",
            "active_page",
        ):
            self.assertEqual(session.get(key), snap.get(key))
        self.assertIn(_POST_START_ENTRY_EMITTED_SEQ_KEY, session)

    def test_second_script_execution_emits_again(self) -> None:
        session = _session(_solo_stage1_script_run_seq=2)
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            emit_ldr_post_start_script_entry(session, st=mock.Mock())
            session[_POST_START_ENTRY_EMITTED_SEQ_KEY] = 0
            session["_solo_stage1_script_run_seq"] = 3
            emit_ldr_post_start_script_entry(session, st=mock.Mock())
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        cps = [
            r.get("checkpoint")
            for r in merged
            if r.get("event") == "production_stage1_queueui_predicate_audit"
        ]
        self.assertEqual(cps.count(POST_START_SCRIPT_ENTRY_CHECKPOINT), 2)


class PredicateCompletionCountingTests(unittest.TestCase):
    def test_three_distinct_script_executions_counted(self) -> None:
        rows = [
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 9,
                "checkpoint": "start_handler_after_finish_start",
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 10,
                "checkpoint": POST_START_SCRIPT_ENTRY_CHECKPOINT,
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 11,
                "checkpoint": "ldr_early_room_present",
            },
        ]
        self.assertEqual(distinct_predicate_script_run_seq(rows), [9, 10, 11])

    def test_multiple_checkpoints_one_seq_count_once(self) -> None:
        rows = [
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 9,
                "checkpoint": "start_handler_finally_before_finish",
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 9,
                "checkpoint": "start_handler_after_finish_start",
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 10,
                "checkpoint": POST_START_SCRIPT_ENTRY_CHECKPOINT,
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 11,
                "checkpoint": "ldr_early_room_present",
            },
        ]
        self.assertEqual(distinct_predicate_script_run_seq(rows), [9, 10, 11])

    def test_no_queueuiroot_with_fewer_than_three_sequences(self) -> None:
        rows = [
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 9,
                "checkpoint": "start_handler_after_finish_start",
                "predicates": {"full_body_predicate": False},
                "auth": {"authenticated": False},
                "restore": {"restore_blocked_reason": "auth_required"},
            },
            {
                "event": "production_stage1_queueui_predicate_audit",
                "script_run_seq": 11,
                "checkpoint": "ldr_early_room_present",
                "predicates": {"full_body_predicate": False},
                "auth": {"authenticated": False},
                "restore": {"restore_blocked_reason": "auth_required"},
            },
        ]
        completion = evaluate_audit_completion(
            ledger_rows=rows,
            server_latch={"ok": True, "server_room_id": "R1"},
            room_id="R1",
            protocol_violation=None,
            start_click_observed=True,
            ledger_summary={"handler_entered": True, "handler_exited": True},
        )
        self.assertFalse(completion.get("completed"))
        root = classify_queueui_root(ledger_rows=rows)
        self.assertFalse(root.get("proven"))


if __name__ == "__main__":
    unittest.main()
