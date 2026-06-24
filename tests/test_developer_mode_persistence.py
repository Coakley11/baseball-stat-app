"""Developer Mode checkbox persistence across reruns and workspace sync."""

from __future__ import annotations

import unittest

from suite_workspace import (
    DEVELOPER_MODE_DIAG_KEY,
    DEVELOPER_MODE_PERSIST_KEY,
    DEVELOPER_MODE_WIDGET_KEY,
    is_developer_mode_enabled,
    set_active_workspace_id,
    set_developer_mode_user,
    sync_developer_mode_widget,
)


class _FakeSt:
    session_state: dict


class DeveloperModePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = _FakeSt()
        self.st.session_state = {}

    def test_persist_survives_widget_clear(self) -> None:
        set_developer_mode_user(self.st.session_state, True, source="test")
        self.st.session_state.pop(DEVELOPER_MODE_WIDGET_KEY, None)
        sync_developer_mode_widget(self.st.session_state, source="post_sync")
        self.assertTrue(self.st.session_state.get(DEVELOPER_MODE_WIDGET_KEY))
        self.assertTrue(is_developer_mode_enabled(st=self.st))  # type: ignore[arg-type]

    def test_workspace_change_does_not_clear_persist(self) -> None:
        set_developer_mode_user(self.st.session_state, True, source="test")
        set_active_workspace_id(self.st, "daniel")  # type: ignore[arg-type]
        set_active_workspace_id(self.st, "ariel")  # type: ignore[arg-type]
        self.assertTrue(self.st.session_state.get(DEVELOPER_MODE_PERSIST_KEY))

    def test_diagnostics_fields_recorded(self) -> None:
        set_developer_mode_user(self.st.session_state, True, source="checkbox")
        diag = self.st.session_state.get(DEVELOPER_MODE_DIAG_KEY)
        self.assertIsInstance(diag, dict)
        self.assertIn("developer_mode_checkbox_value", diag)
        self.assertIn("developer_mode_session_value", diag)
        self.assertIn("developer_mode_restored_value", diag)
        self.assertIn("developer_mode_reset_reason", diag)
        self.assertIn("developer_mode_source", diag)


if __name__ == "__main__":
    unittest.main()
