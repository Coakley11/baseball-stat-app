"""Tests for deferred Live Draft setup persistence."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from live_draft_setup_persist import (
    LIVE_DRAFT_SETUP_DIRTY_KEY,
    clear_live_draft_setup_dirty,
    flush_live_draft_setup_persist,
    is_live_draft_pre_pick_setup,
    is_live_draft_setup_dirty,
    mark_live_draft_setup_dirty,
    on_live_draft_setup_widget_changed,
    should_skip_draft_room_prep_for_live_setup,
    should_skip_live_draft_recommendations,
)


class LiveDraftSetupPersistTests(unittest.TestCase):
    def test_pre_pick_setup_when_room_none(self) -> None:
        session = {"active_page": "Live Draft Room", "live_draft_room": None}
        self.assertTrue(is_live_draft_pre_pick_setup(session))
        self.assertTrue(should_skip_draft_room_prep_for_live_setup(session))
        self.assertTrue(should_skip_live_draft_recommendations(session))

    def test_not_pre_pick_when_in_progress(self) -> None:
        session = {
            "active_page": "Live Draft Room",
            "live_draft_room": {
                "draft_room_id": "r1",
                "status": "in_progress",
                "draft_board": [{"Player": "A"}],
            },
        }
        self.assertFalse(is_live_draft_pre_pick_setup(session))
        self.assertFalse(should_skip_draft_room_prep_for_live_setup(session))

    def test_widget_change_marks_dirty_without_force_save(self) -> None:
        session: dict = {
            "live_draft_proj_window": 3,
            "live_draft_proj_style": "Balanced",
            "live_draft_scoring": "Roto (5x5)",
        }
        with patch("shared_draft_context.on_draft_settings_changed") as mock_canon, patch(
            "baseball_persistent_state.force_save_baseball_state"
        ) as mock_save:
            on_live_draft_setup_widget_changed(session)
        mock_canon.assert_called_once()
        mock_save.assert_not_called()
        self.assertTrue(is_live_draft_setup_dirty(session))

    def test_flush_clears_dirty_and_saves(self) -> None:
        session: dict = {LIVE_DRAFT_SETUP_DIRTY_KEY: True}
        st = MagicMock()
        st.session_state = session
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_save:
            ok = flush_live_draft_setup_persist(st, session, reason="live_draft_setup_save")
        self.assertTrue(ok)
        mock_save.assert_called_once()
        self.assertFalse(is_live_draft_setup_dirty(session))

    def test_flush_noop_when_clean(self) -> None:
        session: dict = {}
        st = MagicMock()
        st.session_state = session
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            ok = flush_live_draft_setup_persist(st, session, reason="live_draft_setup_save")
        self.assertFalse(ok)
        mock_save.assert_not_called()

    def test_clear_dirty(self) -> None:
        session = {LIVE_DRAFT_SETUP_DIRTY_KEY: True}
        clear_live_draft_setup_dirty(session)
        self.assertFalse(is_live_draft_setup_dirty(session))

    def test_get_canonical_board_skips_prepare_during_setup(self) -> None:
        session = {"active_page": "Live Draft Room", "live_draft_room": None}
        with patch("draft_room_state.prepare_draft_room_state") as mock_prepare:
            from draft_room_state import get_canonical_draft_board

            get_canonical_draft_board(session)
        mock_prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
