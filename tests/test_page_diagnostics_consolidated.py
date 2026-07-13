"""Consolidated developer diagnostics presentation tests."""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

import page_diagnostics


class PageDiagnosticsConsolidatedTests(unittest.TestCase):
    def test_developer_mode_off_suppresses_footer(self) -> None:
        st = mock.MagicMock()
        session: dict = {"_suite_auth_user_id": "user:test"}
        page_diagnostics.render_consolidated_diagnostics(
            st,
            session,
            "Live Draft Room",
            developer_mode=False,
        )
        st.expander.assert_not_called()

    def test_developer_mode_on_single_expander(self) -> None:
        st = mock.MagicMock()
        session: dict = {"_suite_auth_user_id": "user:test", "_live_draft_timer_diag": {"seconds_remaining": 42}}
        page_diagnostics.render_consolidated_diagnostics(
            st,
            session,
            "Live Draft Room",
            developer_mode=True,
        )
        labels = [call.args[0] for call in st.expander.call_args_list if call.args]
        self.assertEqual(labels[0], "Developer diagnostics")
        self.assertNotIn("Pick commit diagnostics", labels)
        self.assertNotIn("Persistence diagnostics", labels)

    def test_inline_diagnostics_disabled_when_consolidated(self) -> None:
        self.assertFalse(page_diagnostics.inline_diagnostics_enabled(True))
        self.assertTrue(page_diagnostics.suppress_inline_diagnostics(True))

    def test_pick_commit_diagnostics_suppressed_inline(self) -> None:
        from draft_commit_diagnostics import DRAFT_COMMIT_DIAG_KEY
        from draft_commit_diagnostics_ui import render_draft_commit_diagnostics

        st = mock.MagicMock()
        session = {DRAFT_COMMIT_DIAG_KEY: {"draft_player_called": True}}
        render_draft_commit_diagnostics(st, session, developer_mode=True)
        st.expander.assert_not_called()

    def test_library_persistence_panel_suppressed(self) -> None:
        from draft_archive_ui import render_persistence_probe_panel

        st = mock.MagicMock()
        render_persistence_probe_panel(st, {}, developer_mode=True)
        st.info.assert_not_called()
        st.error.assert_not_called()

    def test_diagnostic_modules_use_suppress_helper(self) -> None:
        from draft_commit_diagnostics_ui import render_draft_commit_diagnostics
        from live_draft_poll_ui import render_live_poll_diagnostics

        for fn in (render_draft_commit_diagnostics, render_live_poll_diagnostics):
            self.assertIn("suppress_inline_diagnostics", inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()
