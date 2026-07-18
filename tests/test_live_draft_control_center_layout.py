"""Control Center layout: live-only controls; commissioner actions beside chat."""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

from live_draft_control_center_ui import (
    render_commissioner_actions_beside_chat,
    render_live_chat_with_commissioner_actions,
    render_live_draft_control_center,
)


class ControlCenterLayoutTests(unittest.TestCase):
    def test_active_control_center_source_has_no_library_or_danger_sections(self) -> None:
        src = inspect.getsource(render_live_draft_control_center)
        self.assertNotIn("Save to Draft Library", src)
        self.assertNotIn("Danger zone", src)
        self.assertNotIn("Danger Zone", src)
        self.assertNotIn("Save and return later", src)
        self.assertIn("Pause Draft", src)
        self.assertIn("Resume Draft", src)

    def test_commissioner_actions_beside_chat_are_compact(self) -> None:
        src = inspect.getsource(render_commissioner_actions_beside_chat)
        self.assertIn("Save & Continue Later", src)
        self.assertIn("End/Delete Draft for Everyone", src)
        self.assertNotIn("Danger Zone", src)
        self.assertNotIn("Save to Draft Library", src)

    def test_guest_does_not_see_commissioner_chat_actions(self) -> None:
        st = mock.MagicMock()
        session = {
            "draft_room_participant_id": "guest-1",
            "active_shared_draft_room_code": "ABC123",
        }
        with mock.patch(
            "live_draft_control_center_ui._resolve_commissioner",
            return_value=(False, {"commissioner_participant_id": "host-1"}),
        ):
            with mock.patch(
                "live_draft_chat_ui.render_live_draft_chat_panel"
            ) as chat:
                render_live_chat_with_commissioner_actions(st, session)
                chat.assert_called_once()
        # Guest path must not render Draft Actions heading / save button.
        labels = [
            str(c.args[0]) if c.args else ""
            for c in st.markdown.call_args_list + st.button.call_args_list
        ]
        joined = " ".join(labels)
        self.assertNotIn("Draft Actions", joined)
        self.assertNotIn("Save & Continue Later", joined)


if __name__ == "__main__":
    unittest.main()
