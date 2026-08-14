"""Local harness tests for the Francisco Add-to-Queue callback-only pre-mutation fence.

These tests are not production Francisco callback proof.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_state import DRAFT_QUEUE_KEY
from live_draft_francisco_callback_only_gate import (
    CLASSIFICATION_NOT_PROVEN,
    CLASSIFICATION_PROVEN_PREMUTATION,
    FRANCISCO_LINDOR_PLAYER_NAME,
    FRANCISCO_LINDOR_TEST_PLAYER_ID,
    PHASE_GATE_CONSUMED_BLOCKED,
    PHASE_PREMUTATION_MISMATCH,
    PHASE_PREMUTATION_STOP,
    REASON_ALREADY_CONSUMED,
    STATE_ARMED,
    STATE_CONSUMED_LOCKED,
    STATE_UNARMED,
    arm_francisco_callback_only_gate,
    classify_francisco_callback_only_proof,
    clear_francisco_callback_only_gate,
    find_premutation_stop_event,
    gate_is_armed,
    gate_is_consumed_locked,
    gate_lifecycle,
    last_gate_event,
)
from live_draft_queue_fragment import QUEUE_ADD_DIAG_KEY
from live_draft_queue_persist import DRAFT_QUEUE_PERSIST_DIRTY_KEY
from live_draft_queue_survival import QUEUE_SURVIVAL_LOG_KEY
from live_draft_rec_fragment_exec_diag import FRAGMENT_CALLBACK_LEDGER_KEY
from live_draft_rec_queue_click_trace import TRACE_LAST_KEY, build_rec_card_queue_widget_key
from live_draft_rerun_scope import QUEUE_TICK_KEY
from live_draft_room_ui import execute_rec_card_queue_click, render_live_draft_rec_cards
from live_draft_stage1_s3_process_global_diag import (
    CRITICAL_SERVER_PHASES,
    critical_ledger_by_phase,
)


ROOM_ID = "E9648CBC"
PICK_INDEX = 0
WIDGET_KEY = build_rec_card_queue_widget_key(
    room_id=ROOM_ID,
    pick_index=PICK_INDEX,
    stable_key=FRANCISCO_LINDOR_TEST_PLAYER_ID,
    surface="rec_card",
)
JUDGE_ID = "592206"
JUDGE_KEY = build_rec_card_queue_widget_key(
    room_id=ROOM_ID,
    pick_index=PICK_INDEX,
    stable_key=JUDGE_ID,
    surface="rec_card",
)
TEST_SID = "francisco-callback-only-test-sid"


def _diag_session(**extra: Any) -> dict[str, Any]:
    session: dict[str, Any] = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_run_id": "local_francisco_callback_only",
        "_solo_stage1_script_run_seq": 4,
        "_solo_stage1_recommendation_fragment_run_seq": 2,
        DRAFT_QUEUE_KEY: [],
        "draft_state": {"queue": []},
    }
    session.update(extra)
    return session


def _click(
    session: dict[str, Any],
    *,
    name: str = FRANCISCO_LINDOR_PLAYER_NAME,
    player_id: str = FRANCISCO_LINDOR_TEST_PLAYER_ID,
    widget_key: str = WIDGET_KEY,
    event_id: str = "evt_francisco_cb",
) -> None:
    execute_rec_card_queue_click(
        session,
        name=name,
        event_id=event_id,
        widget_key=widget_key,
        room_id=ROOM_ID,
        pick_idx=PICK_INDEX,
        player_id=player_id,
    )


def _arm(session: dict[str, Any]) -> dict[str, Any]:
    return arm_francisco_callback_only_gate(
        session,
        room_id=ROOM_ID,
        pick_index=PICK_INDEX,
        player_id=FRANCISCO_LINDOR_TEST_PLAYER_ID,
        player_name=FRANCISCO_LINDOR_PLAYER_NAME,
        widget_key=WIDGET_KEY,
    )


class FranciscoCallbackOnlyGateTests(unittest.TestCase):
    def test_critical_phases_registered(self) -> None:
        self.assertIn(PHASE_PREMUTATION_STOP, CRITICAL_SERVER_PHASES)
        self.assertIn(PHASE_PREMUTATION_MISMATCH, CRITICAL_SERVER_PHASES)
        self.assertIn(PHASE_GATE_CONSUMED_BLOCKED, CRITICAL_SERVER_PHASES)

    def test_arm_refuses_without_solo_diag(self) -> None:
        session: dict[str, Any] = {DRAFT_QUEUE_KEY: []}
        out = _arm(session)
        self.assertFalse(out["armed"])
        self.assertFalse(gate_is_armed(session))
        self.assertEqual(gate_lifecycle(session), STATE_UNARMED)

    def test_arm_refuses_non_francisco_name(self) -> None:
        session = _diag_session()
        out = arm_francisco_callback_only_gate(
            session,
            room_id=ROOM_ID,
            pick_index=PICK_INDEX,
            player_id=JUDGE_ID,
            player_name="Aaron Judge",
            widget_key=JUDGE_KEY,
        )
        self.assertFalse(out["armed"])
        self.assertFalse(gate_is_armed(session))

    def test_unarmed_normal_path_mutates_queue(self) -> None:
        session = _diag_session()
        with patch("draft_state.add_player_to_draft_queue", wraps=__import__("draft_state").add_player_to_draft_queue) as mut:
            _click(session)
            self.assertTrue(mut.called)
        self.assertEqual(session[DRAFT_QUEUE_KEY], [FRANCISCO_LINDOR_PLAYER_NAME])
        self.assertEqual(session["draft_state"]["queue"], [FRANCISCO_LINDOR_PLAYER_NAME])
        entry = (session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])[-1]
        self.assertTrue(entry.get("callback_entered"))
        self.assertEqual(entry.get("player_name"), FRANCISCO_LINDOR_PLAYER_NAME)
        self.assertTrue(session.get(QUEUE_ADD_DIAG_KEY, {}).get("added"))
        self.assertTrue(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY))
        self.assertTrue(session.get(QUEUE_TICK_KEY))
        survival = session.get(QUEUE_SURVIVAL_LOG_KEY) or []
        self.assertTrue(survival)
        trace = session.get(TRACE_LAST_KEY) or {}
        self.assertTrue(trace.get("mutation_helper_entered"))
        self.assertTrue(trace.get("added"))
        classified = classify_francisco_callback_only_proof(session, expected_widget_key=WIDGET_KEY)
        self.assertEqual(classified["classification"], CLASSIFICATION_NOT_PROVEN)
        self.assertEqual(gate_lifecycle(session), STATE_UNARMED)

    def test_francisco_callback_only_stops_before_mutation(self) -> None:
        session = _diag_session()
        dirty_before = session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY)
        queue_before = list(session[DRAFT_QUEUE_KEY])
        ds_before = list(session["draft_state"]["queue"])
        armed = _arm(session)
        self.assertTrue(armed["armed"])
        self.assertEqual(gate_lifecycle(session), STATE_ARMED)
        with patch(
            "live_draft_francisco_callback_only_gate._streamlit_session_id",
            return_value=TEST_SID,
        ):
            with patch("draft_state.add_player_to_draft_queue") as mut:
                with patch("live_draft_rerun_scope.mark_live_draft_queue_tick") as tick:
                    _click(session)
                    mut.assert_not_called()
                    tick.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], queue_before)
        self.assertEqual(session["draft_state"]["queue"], ds_before)
        self.assertEqual(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY), dirty_before)
        self.assertFalse(session.get(QUEUE_TICK_KEY))
        self.assertNotIn(QUEUE_ADD_DIAG_KEY, session)
        survival = session.get(QUEUE_SURVIVAL_LOG_KEY) or []
        self.assertFalse(any(str(e.get("point") or "") == "A" for e in survival if isinstance(e, dict)))
        trace = session.get(TRACE_LAST_KEY) or {}
        self.assertTrue(trace.get("callback_entered"))
        self.assertFalse(trace.get("mutation_helper_entered"))
        self.assertFalse(trace.get("added"))
        entry = (session.get(FRAGMENT_CALLBACK_LEDGER_KEY) or [])[-1]
        self.assertTrue(entry.get("callback_entered"))
        self.assertEqual(entry.get("player_name"), FRANCISCO_LINDOR_PLAYER_NAME)
        self.assertEqual(entry.get("player_id"), FRANCISCO_LINDOR_TEST_PLAYER_ID)
        self.assertEqual(entry.get("widget_key"), WIDGET_KEY)
        stop = last_gate_event(session)
        self.assertEqual(stop.get("phase"), PHASE_PREMUTATION_STOP)
        self.assertTrue(stop.get("target_match"))
        self.assertFalse(stop.get("mutation_attempted"))
        self.assertFalse(stop.get("mutation_completed"))
        self.assertTrue(stop.get("gate_consumed"))
        self.assertEqual(stop.get("lifecycle_state"), STATE_CONSUMED_LOCKED)
        self.assertFalse(gate_is_armed(session))
        self.assertTrue(gate_is_consumed_locked(session))
        self.assertEqual(gate_lifecycle(session), STATE_CONSUMED_LOCKED)
        crit = critical_ledger_by_phase(TEST_SID)
        self.assertTrue(crit.get(PHASE_PREMUTATION_STOP))
        classified = classify_francisco_callback_only_proof(
            session,
            expected_widget_key=WIDGET_KEY,
            expected_player_id=FRANCISCO_LINDOR_TEST_PLAYER_ID,
            expected_room_id=ROOM_ID,
        )
        self.assertEqual(classified["classification"], CLASSIFICATION_PROVEN_PREMUTATION)
        self.assertFalse(classified["production_proof"])

    def test_second_francisco_click_fail_closed_consumed_locked(self) -> None:
        session = _diag_session()
        dirty_before = session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY)
        _arm(session)
        with patch("live_draft_francisco_callback_only_gate._streamlit_session_id", return_value=TEST_SID + "-second"):
            with patch("draft_state.add_player_to_draft_queue") as mut:
                _click(session, event_id="evt_first")
                mut.assert_not_called()
                self.assertEqual(gate_lifecycle(session), STATE_CONSUMED_LOCKED)
                self.assertEqual(session[DRAFT_QUEUE_KEY], [])
                _click(session, event_id="evt_second")
                mut.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertEqual(session["draft_state"]["queue"], [])
        self.assertEqual(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY), dirty_before)
        self.assertNotIn(QUEUE_ADD_DIAG_KEY, session)
        last = last_gate_event(session)
        self.assertEqual(last.get("phase"), PHASE_GATE_CONSUMED_BLOCKED)
        self.assertEqual(last.get("lifecycle_state"), STATE_CONSUMED_LOCKED)
        self.assertEqual(last.get("reason"), REASON_ALREADY_CONSUMED)
        self.assertTrue(last.get("gate_consumed"))
        self.assertFalse(last.get("mutation_attempted"))
        self.assertFalse(last.get("mutation_completed"))
        self.assertTrue(gate_is_consumed_locked(session))
        stop = find_premutation_stop_event(session)
        self.assertEqual(stop.get("phase"), PHASE_PREMUTATION_STOP)
        classified = classify_francisco_callback_only_proof(
            session,
            expected_widget_key=WIDGET_KEY,
            expected_player_id=FRANCISCO_LINDOR_TEST_PLAYER_ID,
            expected_room_id=ROOM_ID,
        )
        self.assertEqual(classified["classification"], CLASSIFICATION_PROVEN_PREMUTATION)
        self.assertFalse(classified["production_proof"])
        crit = critical_ledger_by_phase(TEST_SID + "-second")
        self.assertTrue(crit.get(PHASE_GATE_CONSUMED_BLOCKED))

    def test_other_player_while_consumed_locked_fail_closed(self) -> None:
        session = _diag_session()
        _arm(session)
        with patch("live_draft_francisco_callback_only_gate._streamlit_session_id", return_value=TEST_SID + "-other"):
            with patch("draft_state.add_player_to_draft_queue") as mut:
                _click(session, event_id="evt_first")
                mut.assert_not_called()
                _click(
                    session,
                    name="Aaron Judge",
                    player_id=JUDGE_ID,
                    widget_key=JUDGE_KEY,
                    event_id="evt_judge_locked",
                )
                mut.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertEqual(session["draft_state"]["queue"], [])
        last = last_gate_event(session)
        self.assertEqual(last.get("phase"), PHASE_GATE_CONSUMED_BLOCKED)
        self.assertEqual(last.get("player_name"), "Aaron Judge")
        self.assertTrue(gate_is_consumed_locked(session))

    def test_explicit_release_restores_normal_mutation(self) -> None:
        session = _diag_session()
        _arm(session)
        with patch("live_draft_francisco_callback_only_gate._streamlit_session_id", return_value=TEST_SID + "-rel"):
            with patch("draft_state.add_player_to_draft_queue") as mut:
                _click(session, event_id="evt_first")
                mut.assert_not_called()
        self.assertEqual(gate_lifecycle(session), STATE_CONSUMED_LOCKED)
        released = clear_francisco_callback_only_gate(session)
        self.assertEqual(released["state"], STATE_UNARMED)
        self.assertEqual(gate_lifecycle(session), STATE_UNARMED)
        self.assertFalse(gate_is_armed(session))
        self.assertFalse(gate_is_consumed_locked(session))
        with patch("draft_state.add_player_to_draft_queue", wraps=__import__("draft_state").add_player_to_draft_queue) as mut:
            _click(session, event_id="evt_after_release")
            self.assertTrue(mut.called)
        self.assertEqual(session[DRAFT_QUEUE_KEY], [FRANCISCO_LINDOR_PLAYER_NAME])
        self.assertEqual(session["draft_state"]["queue"], [FRANCISCO_LINDOR_PLAYER_NAME])

    def test_wrong_player_fail_closed_no_francisco_success(self) -> None:
        session = _diag_session()
        _arm(session)
        with patch("live_draft_francisco_callback_only_gate._streamlit_session_id", return_value=TEST_SID + "-mm"):
            with patch("draft_state.add_player_to_draft_queue") as mut:
                _click(
                    session,
                    name="Aaron Judge",
                    player_id=JUDGE_ID,
                    widget_key=JUDGE_KEY,
                    event_id="evt_judge",
                )
                mut.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertEqual(session["draft_state"]["queue"], [])
        last = last_gate_event(session)
        self.assertEqual(last.get("phase"), PHASE_PREMUTATION_MISMATCH)
        self.assertFalse(last.get("target_match"))
        self.assertFalse(last.get("gate_consumed"))
        self.assertTrue(gate_is_armed(session))
        self.assertEqual(gate_lifecycle(session), STATE_ARMED)
        classified = classify_francisco_callback_only_proof(session, expected_widget_key=WIDGET_KEY)
        self.assertEqual(classified["classification"], CLASSIFICATION_NOT_PROVEN)
        self.assertNotEqual(last.get("phase"), PHASE_PREMUTATION_STOP)

    def test_already_queued_ui_uses_disabled_queued_button(self) -> None:
        st = MagicMock()
        st.container.return_value.__enter__ = MagicMock(return_value=MagicMock())
        st.container.return_value.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        rec_df = pd.DataFrame(
            [
                {
                    "fullName": FRANCISCO_LINDOR_PLAYER_NAME,
                    "playerID": FRANCISCO_LINDOR_TEST_PLAYER_ID,
                    "Primary Position": "SS",
                    "Fantasy Edge": 1.0,
                    "Survival Probability": 0.5,
                }
            ]
        )
        session = _diag_session()
        session[DRAFT_QUEUE_KEY] = [FRANCISCO_LINDOR_PLAYER_NAME]
        room = {
            "draft_room_id": ROOM_ID,
            "current_pick_index": PICK_INDEX,
            "status": "paused",
            "pool": rec_df,
            "config": {},
        }
        with patch("draft_actions.resolve_player_draft_gate", return_value={"allowed": True, "disable_message": ""}):
            with patch("draft_actions.resolve_manual_draft_panel_gate", return_value={"draft_enabled": False, "draft_complete": False}):
                with patch("draft_actions.draft_action_context", return_value={}):
                    render_live_draft_rec_cards(st, session, room, rec_df, max_cards=1)
        labels = [str(c.args[0]) for c in st.button.call_args_list if c.args]
        self.assertIn("Queued", labels)
        self.assertFalse(any("Add to Queue" in lbl for lbl in labels))
        queued = [c for c in st.button.call_args_list if c.args and str(c.args[0]) == "Queued"]
        self.assertTrue(queued)
        self.assertTrue(queued[0].kwargs.get("disabled"))

    def test_nested_on_click_is_execute_rec_card_queue_click(self) -> None:
        st = MagicMock()
        st.container.return_value.__enter__ = MagicMock(return_value=MagicMock())
        st.container.return_value.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        rec_df = pd.DataFrame(
            [
                {
                    "fullName": FRANCISCO_LINDOR_PLAYER_NAME,
                    "playerID": FRANCISCO_LINDOR_TEST_PLAYER_ID,
                    "Primary Position": "SS",
                    "Fantasy Edge": 1.0,
                    "Survival Probability": 0.5,
                }
            ]
        )
        session = _diag_session()
        room = {
            "draft_room_id": ROOM_ID,
            "current_pick_index": PICK_INDEX,
            "status": "paused",
            "pool": rec_df,
            "config": {},
        }
        with patch("draft_actions.resolve_player_draft_gate", return_value={"allowed": True, "disable_message": ""}):
            with patch("draft_actions.resolve_manual_draft_panel_gate", return_value={"draft_enabled": False, "draft_complete": False}):
                with patch("draft_actions.draft_action_context", return_value={}):
                    render_live_draft_rec_cards(st, session, room, rec_df, max_cards=1)
        queue_calls = [
            c
            for c in st.button.call_args_list
            if c.args and "Add to Queue" in str(c.args[0])
        ]
        self.assertEqual(len(queue_calls), 1)
        cb = queue_calls[0].kwargs.get("on_click")
        self.assertTrue(callable(cb))
        _arm(session)
        with patch("draft_state.add_player_to_draft_queue") as mut:
            cb()
            mut.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertEqual(last_gate_event(session).get("phase"), PHASE_PREMUTATION_STOP)
        self.assertEqual(gate_lifecycle(session), STATE_CONSUMED_LOCKED)


if __name__ == "__main__":
    unittest.main()
