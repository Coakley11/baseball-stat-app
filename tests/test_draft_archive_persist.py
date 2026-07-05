"""Tests for archive persist autosave unblock."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from draft_archive_ui import _persist_archive


class ArchivePersistAutosaveTests(unittest.TestCase):
    @patch("baseball_persistent_state.force_save_baseball_state", return_value=True)
    def test_persist_archive_clears_autosave_block(self, mock_force: MagicMock) -> None:
        session: dict = {"draft_archive_teams": [{"draft_id": "a1"}]}
        st = MagicMock()
        st.session_state = session
        session["_suite_autosave_blocked::baseball"] = True
        ok = _persist_archive(session, st, reason="simulator_league_context_saved")
        self.assertTrue(ok)
        self.assertNotIn("_suite_autosave_blocked::baseball", session)
