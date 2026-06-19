"""Regression: developer UI only on Daniel workspace with dev mode enabled."""

from __future__ import annotations

import unittest

from suite_workspace import can_show_developer_tools, set_active_workspace_id


class _FakeSt:
    def __init__(self, workspace: str, *, dev_query: bool = False) -> None:
        self.session_state: dict = {}
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


if __name__ == "__main__":
    unittest.main()
