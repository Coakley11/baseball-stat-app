"""Developer UI audit — ?dev=1 alone must not expose debug panels."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from draft_room_join_trace import join_trace_visible
from draft_room_state import render_board_tab_diagnostics, render_draft_board_diagnostics
from live_draft_state import render_live_draft_save_diagnostics
from page_perf import _dev_mode
from settings_persistence_trace import _dev_trace_enabled
from suite_workspace import (
    can_show_developer_tools,
    developer_ui_visible_from_session,
    set_active_workspace_id,
    set_developer_mode_user,
)


class _FakeSt:
    def __init__(self, workspace: str, *, dev_query: bool = False, session: dict | None = None) -> None:
        self.session_state: dict = dict(session or {})
        self.query_params = {"dev": "1"} if dev_query else {}
        set_active_workspace_id(self, workspace)  # type: ignore[arg-type]


class DeveloperUiAuditTests(unittest.TestCase):
    def test_dev_query_alone_does_not_enable_tools(self) -> None:
        st = _FakeSt("daniel", dev_query=True)
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]
        self.assertFalse(developer_ui_visible_from_session(st.session_state))
        self.assertFalse(_dev_mode(st.session_state))
        self.assertFalse(_dev_trace_enabled(st.session_state))
        self.assertFalse(join_trace_visible(st.session_state))

    def test_checkbox_enables_tools_on_eligible_workspace(self) -> None:
        st = _FakeSt("daniel")
        set_developer_mode_user(st.session_state, True, source="test")
        self.assertTrue(can_show_developer_tools(st=st))  # type: ignore[arg-type]
        self.assertTrue(developer_ui_visible_from_session(st.session_state))

    def test_draft_room_diagnostics_hidden_without_checkbox(self) -> None:
        mock_st = MagicMock()
        mock_st.session_state = {}
        set_active_workspace_id(mock_st, "daniel")
        render_board_tab_diagnostics(mock_st)
        render_draft_board_diagnostics(mock_st)
        render_live_draft_save_diagnostics(mock_st)
        mock_st.container.assert_not_called()
        mock_st.expander.assert_not_called()

    def test_draft_room_diagnostics_render_when_checkbox_on(self) -> None:
        mock_st = MagicMock()
        mock_st.session_state = {"_draft_room_board_tab_diagnostics": {}}
        set_active_workspace_id(mock_st, "daniel")
        set_developer_mode_user(mock_st.session_state, True, source="test")
        with patch("draft_room_state.board_tab_diagnostics", return_value={"deploy_build": "test"}):
            render_board_tab_diagnostics(mock_st)
        mock_st.container.assert_called()


if __name__ == "__main__":
    unittest.main()
