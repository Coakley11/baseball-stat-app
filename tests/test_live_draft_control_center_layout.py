"""Control Center layout: 2×2 live controls; chat beside; commissioner actions near rosters."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest import mock

from live_draft_control_center_ui import (
    render_commissioner_draft_actions,
    render_control_center_with_live_chat,
    render_live_draft_control_center,
)

_REPO = Path(__file__).resolve().parents[1]


class ControlCenterLayoutTests(unittest.TestCase):
    def test_active_control_center_source_has_no_library_or_danger_sections(self) -> None:
        src = inspect.getsource(render_live_draft_control_center)
        self.assertNotIn("Save to Draft Library", src)
        self.assertNotIn("Danger zone", src)
        self.assertNotIn("Danger Zone", src)
        self.assertNotIn("Save and return later", src)
        self.assertNotIn("Save & Continue Later", src)
        self.assertNotIn("End/Delete Draft for Everyone", src)
        self.assertIn("Pause Draft", src)
        self.assertIn("Resume Draft", src)
        self.assertIn("Auto Pick Now", src)
        self.assertIn("Reset Timer", src)

    def test_control_center_uses_two_by_two_grid(self) -> None:
        src = inspect.getsource(render_live_draft_control_center)
        self.assertIn("top1, top2 = st.columns(2)", src)
        self.assertIn("bot1, bot2 = st.columns(2)", src)
        self.assertNotIn("st.columns(4)", src)

    def test_control_center_with_chat_is_side_by_side(self) -> None:
        src = inspect.getsource(render_control_center_with_live_chat)
        self.assertIn("ctrl_col, chat_col = st.columns", src)
        self.assertIn("render_live_draft_control_center", src)
        self.assertIn("render_live_draft_chat_panel", src)
        self.assertNotIn("Save & Continue Later", src)
        self.assertNotIn("End/Delete", src)

    def test_commissioner_actions_are_compact_and_separate(self) -> None:
        src = inspect.getsource(render_commissioner_draft_actions)
        self.assertIn("Save & Continue Later", src)
        self.assertIn("End/Delete Draft for Everyone", src)
        self.assertNotIn("Danger Zone", src)
        self.assertNotIn("Save to Draft Library", src)
        self.assertNotIn("Pause Draft", src)

    def test_page_places_controls_and_chat_above_timer(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        combo = text.find("render_control_center_with_live_chat")
        timer_call = text.find("render_live_draft_timer_bar(st, st.session_state, room)")
        actions = text.find("render_commissioner_draft_actions(")
        # Live Draft Room roster heading follows commissioner actions.
        rosters = text.find('st.subheader("Team Rosters")', actions)
        self.assertGreater(combo, 0)
        self.assertGreater(timer_call, combo)
        self.assertGreater(actions, timer_call)
        self.assertGreater(rosters, actions)

    def test_guest_does_not_see_commissioner_draft_actions(self) -> None:
        st = mock.MagicMock()
        session = {
            "draft_room_participant_id": "guest-1",
            "active_shared_draft_room_code": "ABC123",
        }
        with mock.patch(
            "live_draft_control_center_ui._resolve_commissioner",
            return_value=(False, {"commissioner_participant_id": "host-1"}),
        ):
            render_commissioner_draft_actions(st, session)
        labels = [
            str(c.args[0]) if c.args else ""
            for c in st.markdown.call_args_list + st.button.call_args_list
        ]
        joined = " ".join(labels)
        self.assertNotIn("Draft Actions", joined)
        self.assertNotIn("Save & Continue Later", joined)


if __name__ == "__main__":
    unittest.main()
