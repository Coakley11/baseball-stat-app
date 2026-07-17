"""Room codes remain visible once per page state — no duplicate Streamlit widget keys."""

from __future__ import annotations

import unittest
from unittest import mock

from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY
from live_draft_room_ui import (
    render_draft_room_code_panel,
    render_live_draft_room_code_header,
    render_live_draft_room_header,
)
from live_draft_setup_mode import SETUP_MODE_SHARED


def _button_keys(st: mock.MagicMock) -> list[str]:
    keys: list[str] = []
    for call in st.button.call_args_list:
        kwargs = call.kwargs or {}
        key = kwargs.get("key")
        if key:
            keys.append(str(key))
    return keys


class RoomCodeVisibilityTests(unittest.TestCase):
    def test_panel_renders_code_and_copy_button(self) -> None:
        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        render_draft_room_code_panel(st, "AB12CD", key_prefix="live_draft_waiting_header")
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("AB12CD", md)
        self.assertIn("ld-room-code-value", md)
        st.code.assert_called()
        self.assertEqual(_button_keys(st), ["live_draft_waiting_header_copy_AB12CD"])

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
                key_prefix="live_draft_active_header",
            )
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("ZZ99YY", md)
        self.assertEqual(_button_keys(st), ["live_draft_active_header_copy_ZZ99YY"])

    def test_legacy_panel_hide_does_not_render_second_room_code_panel(self) -> None:
        """Legacy shared panel must not duplicate the canonical lobby/live room-code panel."""
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
        self.assertEqual(_button_keys(st), [])
        self.assertFalse(st.code.called)

    def test_ready_card_does_not_emit_copy_button(self) -> None:
        """Waiting-room ready card must not host a second Copy room code widget."""
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
        self.assertFalse(any(k.endswith("_copy_JOINME") for k in _button_keys(st)))

    def test_waiting_room_path_has_single_copy_key(self) -> None:
        """Canonical waiting header + ready + summary must not collide on Copy keys."""
        from live_draft_setup_ui import render_draft_status_summary_card, render_shared_draft_ready_card

        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "WAIT01",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
        }
        room = {"status": "not_started", "teams": ["A", "B"], "config": {"your_team": "A"}}
        with mock.patch("draft_room_context.resolve_shared_room_code", return_value="WAIT01"):
            render_live_draft_room_code_header(
                st,
                session,
                multiplayer=True,
                draft_in_progress=False,
                key_prefix="live_draft_waiting_header",
            )
        with mock.patch("live_draft_setup_ui._is_room_host", return_value=True):
            with mock.patch("live_draft_setup_ui.start_button_disabled", return_value=(False, "")):
                with mock.patch(
                    "live_draft_presence.count_required_joined",
                    return_value=(1, 2, []),
                ):
                    with mock.patch("live_draft_setup_ui.shared_room_code", return_value="WAIT01"):
                        with mock.patch("live_draft_setup_ui.is_shared_multiplayer_intent", return_value=True):
                            with mock.patch("live_draft_setup_ui.distinct_claimed_owner_count", return_value=1):
                                with mock.patch("live_draft_setup_ui.count_joined_teams", return_value=(1, 2)):
                                    render_shared_draft_ready_card(st, session, room, on_start=lambda: None)
                                    render_draft_status_summary_card(st, session, room)
        copy_keys = [k for k in _button_keys(st) if "_copy_" in k]
        self.assertEqual(copy_keys, ["live_draft_waiting_header_copy_WAIT01"])
        self.assertEqual(len(copy_keys), len(set(copy_keys)))

    def test_active_draft_path_has_single_copy_key(self) -> None:
        """Active room header + status summary must not collide on Copy keys."""
        from live_draft_setup_ui import render_draft_status_summary_card

        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "LIVE99",
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "draft_room_participant_id": "host-1",
        }
        room = {
            "status": "in_progress",
            "teams": ["Daniel", "Team B"],
            "config": {"draft_setup_mode": SETUP_MODE_SHARED, "your_team": "Daniel"},
        }
        with mock.patch("draft_room_context.get_global_draft_context") as ctx:
            ctx.return_value = {
                "is_room_host": True,
                "participant_team": "Daniel",
                "room_code": "LIVE99",
            }
            with mock.patch("live_draft_setup_mode.is_solo_draft_mode", return_value=False):
                with mock.patch("live_draft_setup_mode.is_shared_multiplayer_intent", return_value=True):
                    with mock.patch("live_draft_setup_mode.shared_room_code", return_value="LIVE99"):
                        with mock.patch(
                            "draft_room_context.resolve_shared_room_code", return_value="LIVE99"
                        ):
                            render_live_draft_room_header(
                                st,
                                session,
                                room,
                                multiplayer=True,
                                user_team="Daniel",
                                on_clock_team="Daniel",
                                pick_label="Pick 1 / 2",
                                status_label="In Progress",
                                draft_in_progress=True,
                            )
        with mock.patch("live_draft_setup_ui._is_room_host", return_value=True):
            with mock.patch("live_draft_setup_ui.shared_room_code", return_value="LIVE99"):
                with mock.patch("live_draft_setup_ui.count_joined_teams", return_value=(2, 2)):
                    render_draft_status_summary_card(
                        st,
                        session,
                        room,
                        on_clock_team="Daniel",
                        pick_label="Pick 1 / 2",
                    )
        copy_keys = [k for k in _button_keys(st) if "_copy_" in k]
        self.assertEqual(copy_keys, ["live_draft_active_header_copy_LIVE99"])
        self.assertEqual(len(copy_keys), len(set(copy_keys)))
        md = " ".join(str(c.args[0]) for c in st.markdown.call_args_list if c.args)
        self.assertIn("LIVE99", md)

    def test_two_panels_with_different_prefixes_do_not_collide(self) -> None:
        st = mock.MagicMock()
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        render_draft_room_code_panel(st, "SAME01", key_prefix="live_draft_waiting_header")
        render_draft_room_code_panel(st, "SAME01", key_prefix="live_draft_active_header")
        keys = _button_keys(st)
        self.assertEqual(
            keys,
            [
                "live_draft_waiting_header_copy_SAME01",
                "live_draft_active_header_copy_SAME01",
            ],
        )
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
