"""Regression: developer UI follows Developer Mode checkbox (any workspace)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_workspace import (
    can_show_developer_tools,
    developer_tools_workspace_eligible,
    set_active_workspace_id,
    set_developer_mode_user,
)


class _FakeSt:
    def __init__(self, workspace: str, *, session: dict | None = None) -> None:
        self.session_state: dict = dict(session or {})
        self.query_params: dict = {}
        set_active_workspace_id(self, workspace)  # type: ignore[arg-type]


class TestDeveloperWorkspaceGating(unittest.TestCase):
    def test_toggle_eligible_on_any_workspace(self) -> None:
        for workspace in ("daniel", "ariel", "guest", "coakley11"):
            st = _FakeSt(workspace)
            self.assertTrue(developer_tools_workspace_eligible(st=st))  # type: ignore[arg-type]

    def test_daniel_dev_query_alone_hidden(self) -> None:
        st = _FakeSt("daniel")
        st.query_params = {"dev": "1"}
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_checkbox_shows_tools_on_any_workspace(self) -> None:
        st = _FakeSt("coakley11")
        set_developer_mode_user(st.session_state, True, source="test")
        self.assertTrue(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_checkbox_off_hides_tools(self) -> None:
        st = _FakeSt("daniel")
        set_developer_mode_user(st.session_state, False, source="test")
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_screenshot_mode_hides_tools_even_when_dev_on(self) -> None:
        st = _FakeSt("daniel")
        set_developer_mode_user(st.session_state, True, source="test")
        st.session_state["portfolio_screenshot_mode"] = True
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_join_trace_follows_developer_mode_gate(self) -> None:
        from draft_room_join_trace import join_trace_visible

        st = _FakeSt(
            "coakley11",
            session={
                "_suite_auth_session": True,
                "_suite_auth_user_id": "uuid-coakley",
            },
        )
        with patch("suite_auth.is_auth_enabled", return_value=True):
            with patch("suite_auth.is_authenticated", return_value=True):
                with patch("suite_auth.resolve_auth_external_id", return_value="coakley11"):
                    self.assertFalse(join_trace_visible(st.session_state))
                    set_developer_mode_user(st.session_state, True, source="test")
                    self.assertTrue(join_trace_visible(st.session_state))


if __name__ == "__main__":
    unittest.main()
