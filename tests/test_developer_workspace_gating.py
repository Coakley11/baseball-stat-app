"""Regression: developer UI on eligible workspace with dev mode enabled."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_workspace import (
    can_show_developer_tools,
    developer_tools_workspace_eligible,
    set_active_workspace_id,
)


class _FakeSt:
    def __init__(self, workspace: str, *, dev_query: bool = False, session: dict | None = None) -> None:
        self.session_state: dict = dict(session or {})
        self.query_params = {"dev": "1"} if dev_query else {}
        set_active_workspace_id(self, workspace)  # type: ignore[arg-type]


class TestDeveloperWorkspaceGating(unittest.TestCase):
    def test_ariel_dev_query_hidden(self) -> None:
        st = _FakeSt("ariel", dev_query=True)
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_daniel_dev_query_visible(self) -> None:
        st = _FakeSt("daniel", dev_query=True)
        self.assertTrue(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_guest_dev_query_hidden(self) -> None:
        st = _FakeSt("guest", dev_query=True)
        self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_auth_own_workspace_eligible(self) -> None:
        st = _FakeSt(
            "coakley11",
            session={
                "_suite_auth_session": True,
                "_suite_auth_user_id": "uuid-coakley",
                "_suite_auth_user_email": "coakley11@aol.com",
                "app_developer_mode": True,
            },
        )
        with patch("suite_auth.is_auth_enabled", return_value=True):
            with patch("suite_auth.is_authenticated", return_value=True):
                with patch("suite_auth.resolve_auth_external_id", return_value="coakley11"):
                    self.assertTrue(developer_tools_workspace_eligible(st=st))  # type: ignore[arg-type]
                    self.assertTrue(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_auth_own_workspace_dev_off_hidden(self) -> None:
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
                    self.assertTrue(developer_tools_workspace_eligible(st=st))  # type: ignore[arg-type]
                    self.assertFalse(can_show_developer_tools(st=st))  # type: ignore[arg-type]

    def test_join_trace_follows_developer_mode_gate(self) -> None:
        from draft_room_join_trace import join_trace_visible

        st = _FakeSt(
            "coakley11",
            session={
                "_suite_auth_session": True,
                "_suite_auth_user_id": "uuid-coakley",
                "app_developer_mode": True,
            },
        )
        with patch("suite_auth.is_auth_enabled", return_value=True):
            with patch("suite_auth.is_authenticated", return_value=True):
                with patch("suite_auth.resolve_auth_external_id", return_value="coakley11"):
                    self.assertTrue(join_trace_visible(st.session_state))

        guest_st = _FakeSt("guest", session={"app_developer_mode": True})
        self.assertFalse(join_trace_visible(guest_st.session_state))


if __name__ == "__main__":
    unittest.main()
