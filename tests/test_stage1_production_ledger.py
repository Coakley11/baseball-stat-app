"""Tests for Stage 1A production diagnostic ledger and return-value session bind."""

from __future__ import annotations

import unittest
from unittest import mock

from live_draft_stage1_production_ledger import (
    bump_stage1_script_run_seq,
    note_stage1_event,
    stage1_production_ledger_enabled,
)


class Stage1ProductionLedgerTests(unittest.TestCase):
    def test_ledger_enabled_when_component_diag_not_rv3(self) -> None:
        session: dict = {"_solo_component_diag_enabled": True}
        st = mock.Mock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            self.assertTrue(stage1_production_ledger_enabled(st, session))
        session["_solo_rv_ladder_step"] = "RV3"
        self.assertFalse(stage1_production_ledger_enabled(st, session))

    def test_script_run_seq_increments(self) -> None:
        session: dict = {"_solo_component_diag_enabled": True}
        st = mock.Mock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            self.assertEqual(bump_stage1_script_run_seq(session), 1)
            note_stage1_event(session, "production_stage1_script_begin", st=st)
            rows = session.get("_solo_stage1_production_ledger") or []
            self.assertEqual(rows[-1]["event"], "production_stage1_script_begin")
            self.assertEqual(rows[-1]["script_run_seq"], 1)
            self.assertTrue(str(rows[-1].get("event_id") or ""))

    def test_merged_ledger_dedupes_event_id_across_notes(self) -> None:
        session: dict = {"_solo_component_diag_enabled": True}
        st = mock.Mock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            note_stage1_event(session, "production_stage1_flush_persistent_wake_delivery_entry", st=st)
            note_stage1_event(session, "production_stage1_flush_persistent_wake_delivery_entry", st=st)
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        self.assertEqual(len(merged), 2)
        eids = [str(r.get("event_id")) for r in merged]
        self.assertEqual(len(set(eids)), 2)


class ReturnValueSessionBindFlushTests(unittest.TestCase):
    def test_flush_delivers_when_return_value_mode_and_session_has_token(self) -> None:
        from live_draft_solo_persistent_wake import (
            SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY,
            SOLO_PERSISTENT_WAKE_LATCH_KEY,
            SOLO_PERSISTENT_WAKE_WIDGET_KEY,
            flush_persistent_wake_delivery,
            production_return_value_delivery_active,
        )

        session: dict = {
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
            SOLO_PERSISTENT_RETURN_VALUE_DELIVERY_KEY: True,
            "live_draft_room": {
                "status": "in_progress",
                "draft_room_id": "ABCD1234",
                "current_pick_index": 0,
                "config": {"timer_seconds": 10},
            },
            "_solo_persistent_wake_last_token": "ABCD1234|0|100.0",
        }
        st = mock.Mock()
        st.session_state = {SOLO_PERSISTENT_WAKE_WIDGET_KEY: "ABCD1234|0|100.0"}

        with mock.patch(
            "live_draft_solo_expire_chain.solo_expire_owner",
            return_value="wake",
        ), mock.patch(
            "live_draft_solo_persistent_wake.process_production_expire_token",
            return_value=True,
        ) as proc:
            self.assertTrue(production_return_value_delivery_active(session))
            flush_persistent_wake_delivery(st, session)
            proc.assert_called_once()
            self.assertEqual(proc.call_args.kwargs.get("source"), "return_value_session_bind")


if __name__ == "__main__":
    unittest.main()
