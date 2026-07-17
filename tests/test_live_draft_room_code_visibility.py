"""Room codes remain visible in Shared Multiplayer waiting room and live draft."""

from __future__ import annotations

import unittest
from unittest import mock

from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY
from live_draft_room_ui import render_draft_room_code_panel, render_live_draft_room_code_header
from live_draft_setup_mode import SETUP_MODE_SHARED


class RoomCodeVisibilityTests(unittest.TestCase):
    def test_panel_renders_code_and_copy_button(self) -> None:
        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        render_draft_room_code_panel(st, "AB12CD")
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("AB12CD", md)
        self.assertIn("ld-room-code-value", md)
        st.code.assert_called()
        st.button.assert_called()

    def test_header_shows_code_during_active_draft(self) -> None:
        """Regression: draft_in_progress must not hide the room code."""
        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {ACTIVE_SHARED_ROOM_CODE_KEY: "ZZ99YY", "live_draft_setup_mode": SETUP_MODE_SHARED}
        with mock.patch("draft_room_context.resolve_shared_room_code", return_value="ZZ99YY"):
            render_live_draft_room_code_header(
                st,
                session,
                multiplayer=True,
                draft_in_progress=True,
            )
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("ZZ99YY", md)

    def test_legacy_panel_hide_still_surfaces_code(self) -> None:
        from draft_ui_multiplayer import render_shared_draft_room_panel

        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "ROOM01",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_room": {"status": "not_started", "teams": ["A", "B"]},
        }
        with mock.patch("live_draft_setup_mode.should_hide_legacy_shared_panel", return_value=True):
            with mock.patch("draft_room_context.resolve_shared_room_code", return_value="ROOM01"):
                with mock.patch("live_draft_setup_mode.is_solo_draft_mode", return_value=False):
                    rerun = render_shared_draft_room_panel(st, session)
        self.assertFalse(rerun)
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("ROOM01", md)

    def test_ready_card_includes_room_code_panel(self) -> None:
        from live_draft_setup_ui import render_shared_draft_ready_card

        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {"live_draft_setup_mode": SETUP_MODE_SHARED}
        room = {"status": "not_started", "teams": ["A", "B"], "config": {}}
        with mock.patch("live_draft_setup_ui._is_room_host", return_value=True):
            with mock.patch("live_draft_setup_ui.start_button_disabled", return_value=(False, "")):
                with mock.patch(
                    "live_draft_presence.count_required_joined",
                    return_value=(1, 2, []),
                ):
                    with mock.patch("live_draft_setup_ui.shared_room_code", return_value="JOINME"):
                        with mock.patch("live_draft_setup_ui.is_shared_multiplayer_intent", return_value=True):
                            with mock.patch("live_draft_setup_ui.distinct_claimed_owner_count", return_value=1):
                                render_shared_draft_ready_card(st, session, room, on_start=lambda: None)
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("JOINME", md)


if __name__ == "__main__":
    unittest.main()
