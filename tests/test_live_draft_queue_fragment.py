"""Queue mount contracts — fragment isolation currently disabled (USE_QUEUE_FRAGMENT=False)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class LiveDraftQueueFragmentTests(unittest.TestCase):
    def test_queue_mount_paints_without_fragment_rerun(self) -> None:
        from live_draft_queue_fragment import (
            QUEUE_FRAGMENT_MUTATE_KEY,
            QUEUE_PAINT_DIAG_KEY,
            USE_QUEUE_FRAGMENT,
            render_live_draft_queue_fragment,
        )

        self.assertFalse(USE_QUEUE_FRAGMENT)
        session: dict[str, Any] = {
            "draft_queue": ["Aaron Judge"],
            "live_draft_room": {"draft_board": [], "status": "in_progress", "config": {}},
        }
        st = MagicMock()

        with patch("draft_ui.render_draft_queue_panel", return_value=False) as panel:
            render_live_draft_queue_fragment(st, session)

        panel.assert_called_once()
        self.assertFalse(bool(session.get(QUEUE_FRAGMENT_MUTATE_KEY)))
        st.rerun.assert_not_called()
        paint = session.get(QUEUE_PAINT_DIAG_KEY) or {}
        self.assertEqual(paint.get("before_panel", {}).get("names"), ["Aaron Judge"])

    def test_draft_from_queue_escalates_to_app_rerun(self) -> None:
        from live_draft_queue_fragment import (
            QUEUE_FRAGMENT_PICK_KEY,
            render_live_draft_queue_fragment,
        )

        session: dict[str, Any] = {
            "draft_queue": ["Player A"],
            "live_draft_room": {"draft_board": [], "status": "in_progress", "config": {}},
            "_pending_manual_draft_pick": {"player_name": "Player A"},
        }
        st = MagicMock()
        calls: list[dict[str, Any]] = []

        def _rerun(**kwargs):
            calls.append(dict(kwargs))

        st.rerun.side_effect = _rerun

        with patch("draft_ui.render_draft_queue_panel", return_value=True):
            render_live_draft_queue_fragment(st, session)

        self.assertTrue(session.get(QUEUE_FRAGMENT_PICK_KEY))
        self.assertEqual(calls, [{"scope": "app"}])

    def test_record_queue_add_diag(self) -> None:
        from live_draft_queue_fragment import QUEUE_ADD_DIAG_KEY, record_queue_add_diag

        session: dict[str, Any] = {}
        record_queue_add_diag(
            session,
            name="Julio Rodriguez",
            before=[],
            after=["Julio Rodriguez"],
            added=True,
        )
        diag = session[QUEUE_ADD_DIAG_KEY]
        self.assertEqual(diag["after_len"], 1)
        self.assertTrue(diag["mutated"])
        self.assertTrue(diag["added"])


class PrepareQueueWidgetRestoreTests(unittest.TestCase):
    def test_prepare_restores_widget_when_canonical_has_queue_after_wipe(self) -> None:
        """Regression: participant wipe + sync_widget_keys=False left Empty UI."""
        from draft_state import (
            DRAFT_QUEUE_KEY,
            mark_draft_local_edit,
            prepare_draft_workflow,
            write_canonical_draft_state,
        )

        session: dict[str, Any] = {}
        write_canonical_draft_state(
            session,
            queue=["Aaron Judge"],
            reason="add_to_queue",
            local_edit=True,
            sync_participant=False,
        )
        mark_draft_local_edit(session)
        # Simulate load_participant wiping the widget key while canonical kept Judge.
        session[DRAFT_QUEUE_KEY] = []
        prepare_draft_workflow(session)
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Aaron Judge"])
        self.assertEqual(session["draft_state"]["queue"], ["Aaron Judge"])

    def test_prepare_skips_participant_load_when_queue_persist_dirty(self) -> None:
        from draft_state import DRAFT_QUEUE_KEY, add_player_to_draft_queue, prepare_draft_workflow
        from live_draft_queue_persist import is_draft_queue_persist_dirty

        session: dict[str, Any] = {
            "active_shared_draft_room_code": "ABCD12",
            "draft_room_participant_membership": {"ABCD12": {"p1": {"assigned_team": "Team 1"}}},
        }
        add_player_to_draft_queue(session, "Aaron Judge")
        self.assertTrue(is_draft_queue_persist_dirty(session))

        with patch(
            "draft_room_context.is_multiplayer_draft_active",
            return_value=True,
        ), patch(
            "draft_room_participant_state.load_participant_workflow_into_session",
            side_effect=lambda s, _code: s.__setitem__(DRAFT_QUEUE_KEY, []),
        ) as load:
            prepare_draft_workflow(session)

        load.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Aaron Judge"])
        self.assertEqual(session.get("_live_draft_queue_hydrate_skipped"), "local_dirty_or_pending")


if __name__ == "__main__":
    unittest.main()
