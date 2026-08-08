"""Unit tests for recommendation-card Add-to-Queue trace (diagnostics — Commit A)."""

from __future__ import annotations

import unittest
from typing import Any

from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue, prepare_draft_workflow
from live_draft_rec_queue_click_trace import (
    WIDGET_REGISTRY_KEY,
    build_rec_card_queue_widget_key,
    classify_rec_queue_trace,
    note_rec_queue_mutation_trace,
    register_rec_queue_widget,
    begin_rec_queue_click_trace,
    note_rec_queue_post_prepare,
)


class RecQueueClickTraceTests(unittest.TestCase):
    def test_legacy_widget_key_registers_canonical_proposal(self) -> None:
        session: dict[str, Any] = {}
        legacy = "rec_card_queue_0_592789"
        canonical = build_rec_card_queue_widget_key(
            room_id="E9648CBC",
            pick_index=0,
            stable_key="592789",
            surface="rec_card",
        )
        register_rec_queue_widget(
            session,
            room_id="E9648CBC",
            pick_index=0,
            player_id="592789",
            player_name="Francisco Lindor",
            widget_key=legacy,
            canonical_widget_key=canonical,
        )
        reg = session[WIDGET_REGISTRY_KEY]
        self.assertEqual(reg[legacy]["widget_key"], legacy)
        self.assertEqual(reg[legacy]["canonical_widget_key"], canonical)
        self.assertNotEqual(legacy, canonical)

    def test_francisco_lindor_add_mutation(self) -> None:
        session: dict[str, Any] = {}
        name = "Francisco Lindor"
        eid = "evt_francisco_01"
        legacy_key = "rec_card_queue_0_592789"
        begin_rec_queue_click_trace(
            session,
            event_id=eid,
            room_id="E9648CBC",
            pick_index=0,
            player_id="592789",
            player_name=name,
            widget_key=legacy_key,
            queue_before=[],
        )
        after, added = add_player_to_draft_queue(session, name)
        note_rec_queue_mutation_trace(
            session,
            event_id=eid,
            mutation_helper_entered=True,
            mutation_result={"added": added},
            queue_after=after,
            added=added,
        )
        self.assertTrue(added)
        self.assertEqual(session[DRAFT_QUEUE_KEY], [name])
        last = session.get("_live_draft_rec_queue_click_trace_last") or {}
        self.assertTrue(last.get("callback_entered"))
        self.assertTrue(last.get("mutation_helper_entered"))

    def test_rerun_prepare_preserves_queue(self) -> None:
        session: dict[str, Any] = {
            "live_draft_room": {"draft_room_id": "E9648CBC", "current_pick_index": 0, "status": "paused"}
        }
        name = "Francisco Lindor"
        eid = "evt_francisco_02"
        begin_rec_queue_click_trace(
            session,
            event_id=eid,
            room_id="E9648CBC",
            pick_index=0,
            player_id="592789",
            player_name=name,
            widget_key="rec_card_queue_0_592789",
            queue_before=[],
        )
        add_player_to_draft_queue(session, name)
        note_rec_queue_mutation_trace(
            session,
            event_id=eid,
            mutation_helper_entered=True,
            mutation_result={"added": True},
            queue_after=[name],
            added=True,
        )
        prepare_draft_workflow(session)
        self.assertEqual(session[DRAFT_QUEUE_KEY], [name])
        note_rec_queue_post_prepare(session, prepare_reason="local_edit_preserve")
        sub = classify_rec_queue_trace(session.get("_live_draft_rec_queue_click_trace_last"))
        self.assertIn(sub, ("QUEUE1C3F", "QUEUE1C3_8"))

    def test_paused_pick_zero_add_permitted(self) -> None:
        session: dict[str, Any] = {
            "live_draft_room": {
                "draft_room_id": "E9648CBC",
                "current_pick_index": 0,
                "status": "paused",
            }
        }
        after, added = add_player_to_draft_queue(session, "Francisco Lindor")
        prepare_draft_workflow(session)
        self.assertTrue(added)
        self.assertEqual(after, ["Francisco Lindor"])

    def test_one_click_one_entry_no_duplicate(self) -> None:
        session: dict[str, Any] = {}
        after1, added1 = add_player_to_draft_queue(session, "Francisco Lindor")
        after2, added2 = add_player_to_draft_queue(session, "Francisco Lindor")
        self.assertTrue(added1)
        self.assertFalse(added2)
        self.assertEqual(after1, after2)
        self.assertEqual(len(after2), 1)

    def test_classify_callback_never_entered(self) -> None:
        self.assertEqual(
            classify_rec_queue_trace({"event_id": "x", "callback_entered": False}),
            "QUEUE1C3A",
        )

    def test_classify_mutation_no_op(self) -> None:
        self.assertEqual(
            classify_rec_queue_trace(
                {
                    "event_id": "x",
                    "callback_entered": True,
                    "mutation_helper_entered": True,
                    "added": False,
                    "queue_immediately_after_mutation": [],
                    "player_name": "Francisco Lindor",
                }
            ),
            "QUEUE1C3C",
        )

    def test_autopick_reads_same_draft_queue_key(self) -> None:
        """add_player_to_draft_queue mutates the same session key autopick helpers read."""
        from draft_state import DRAFT_QUEUE_KEY as CANON

        session: dict[str, Any] = {}
        add_player_to_draft_queue(session, "Francisco Lindor")
        self.assertEqual(session[CANON], ["Francisco Lindor"])
        self.assertEqual(session.get("draft_state", {}).get("queue"), ["Francisco Lindor"])

    def test_trace_probe_requires_solo_component_diag(self) -> None:
        from unittest.mock import MagicMock, patch

        from live_draft_rec_queue_click_trace import render_rec_queue_click_trace_probe

        st = MagicMock()
        session: dict[str, Any] = {}
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=False,
        ):
            render_rec_queue_click_trace_probe(st, session)
        st.markdown.assert_not_called()
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_rec_queue_click_trace_probe(st, session)
        st.markdown.assert_called_once()
        html = str(st.markdown.call_args[0][0])
        self.assertIn("rec-card-queue-click-trace", html)


class RecQueueSimulatedOverwriteTests(unittest.TestCase):
    def test_prepare_restores_after_widget_wipe_when_dirty(self) -> None:
        session: dict[str, Any] = {}
        add_player_to_draft_queue(session, "Francisco Lindor")
        session[DRAFT_QUEUE_KEY] = []
        prepare_draft_workflow(session)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Francisco Lindor"])


if __name__ == "__main__":
    unittest.main()
