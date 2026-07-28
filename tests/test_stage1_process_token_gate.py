"""Stage 1A process-token gate ledger and claim call-site instrumentation."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from live_draft_stage1_process_token_gate import (
    build_process_token_gate_context,
    classify_claim_diagnostic,
    note_process_token_gate,
    note_try_claim_about_to_call,
    note_try_claim_result,
)
from live_draft_stage1_production_ledger import bump_stage1_script_run_seq, ledger_rows_for_export
from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
    process_production_expire_token,
)
from live_draft_stage1_expire_audit import try_claim_token_delivery
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0, draft_id: str = "ROOM1234") -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": draft_id,
        "draft_id": draft_id,
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }


def _ledger_on(session: dict) -> None:
    session["_solo_component_diag_enabled"] = True


class ProcessTokenGateLedgerTests(unittest.TestCase):
    def test_exact_token_emits_try_claim_about_to_call(self) -> None:
        room = _room()
        token = build_solo_expire_token(room)
        session = {
            SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
            "live_draft_room": room,
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
            SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        }
        _ledger_on(session)
        st = mock.MagicMock()
        st.session_state = {}
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            bump_stage1_script_run_seq(session)
            process_production_expire_token(
                st,
                session,
                raw_token=token,
                widget_key=SOLO_PERSISTENT_WAKE_WIDGET_KEY,
                source="native_component_return",
            )
        events = [r.get("event") for r in ledger_rows_for_export(session)]
        self.assertIn("production_stage1_try_claim_about_to_call", events)
        self.assertIn("production_stage1_token_claim_result", events)

    def test_coerce_empty_emits_gate_and_skips_claim(self) -> None:
        session: dict = {"live_draft_room": _room(), SOLO_PERSISTENT_WAKE_LATCH_KEY: True}
        _ledger_on(session)
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            process_production_expire_token(st, session, raw_token=None, widget_key="k")
        gates = [
            r
            for r in ledger_rows_for_export(session)
            if r.get("event") == "production_stage1_process_token_gate"
        ]
        self.assertTrue(any(g.get("gate_name") == "coerce_wake_token" for g in gates))
        self.assertFalse(
            any(r.get("event") == "production_stage1_try_claim_about_to_call" for r in ledger_rows_for_export(session))
        )

    def test_room_mismatch_gate_before_claim(self) -> None:
        room = _room(draft_id="ROOMAAAA")
        token = build_solo_expire_token(_room(draft_id="ROOMBBBB"))
        session = {
            SOLO_PERSISTENT_WAKE_TOKEN_KEY: token,
            "live_draft_room": room,
            SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
        }
        _ledger_on(session)
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            process_production_expire_token(st, session, raw_token=token, widget_key="k")
        gates = [
            r
            for r in ledger_rows_for_export(session)
            if r.get("event") == "production_stage1_process_token_gate" and r.get("decision") == "return"
        ]
        self.assertTrue(any(g.get("gate_name") == "expire_token_matches_state" for g in gates))
        self.assertEqual(classify_claim_diagnostic(session), "C5")

    def test_delivery_only_flag_in_gate_context(self) -> None:
        session = {"live_draft_room": _room(), "_solo_stage1_last_delivery_only": True}
        _ledger_on(session)
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            ctx = build_process_token_gate_context(
                st,
                session,
                raw_token="x",
                normalized_token="",
                widget_key="k",
                source="native_component_return",
            )
        self.assertTrue(ctx.get("delivery_only"))

    def test_already_claimed_classified_c7(self) -> None:
        session: dict = {}
        token = build_solo_expire_token(_room())
        try_claim_token_delivery(session, token, "native_component_return")
        _ledger_on(session)
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            note_try_claim_about_to_call(
                session,
                st=st,
                token=token,
                delivery_via="native_component_return",
                widget_key="k",
                live=_room(),
            )
            note_try_claim_result(
                session,
                st=st,
                token=token,
                delivery_via="native_component_return",
                accepted=False,
                reject_code="already_consumed",
                widget_key="k",
                live=_room(),
            )
        self.assertEqual(classify_claim_diagnostic(session), "C7")

    def test_merged_ledger_survives_script_run_bump(self) -> None:
        session: dict = {}
        _ledger_on(session)
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            bump_stage1_script_run_seq(session)
            note_process_token_gate(
                session,
                st=st,
                gate_name="test_gate",
                gate_result="ok",
                decision="continue",
                widget_key="k",
            )
            bump_stage1_script_run_seq(session)
            note_process_token_gate(
                session,
                st=st,
                gate_name="test_gate_2",
                gate_result="ok",
                decision="continue",
                widget_key="k",
            )
        merged = session.get("_solo_stage1_production_ledger_merged") or []
        self.assertGreaterEqual(len(merged), 2)

    def test_rv3_and_production_use_same_try_claim_helper(self) -> None:
        session: dict = {}
        token = build_solo_expire_token(_room())
        ok_prod, _ = try_claim_token_delivery(session, token, "native_component_return")
        session2: dict = {}
        session2["_solo_rv_ladder_step"] = "RV3"
        ok_rv3, _ = try_claim_token_delivery(session2, token, "native_component_return")
        self.assertTrue(ok_prod)
        self.assertTrue(ok_rv3)


if __name__ == "__main__":
    unittest.main()
