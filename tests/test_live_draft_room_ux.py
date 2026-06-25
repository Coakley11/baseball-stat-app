"""Live Draft Room UX — room header, timer, compact rec cards, rec-card draft."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from draft_room_context import create_and_host_shared_room, join_shared_draft_room, poll_shared_draft_room
from draft_room_shared_state import LIVE_DRAFT_ROOM_KEY, LocalFileSharedRoomStore
from draft_ui import PENDING_MANUAL_PICK_KEY, process_pending_manual_draft_pick, queue_manual_draft_pick
from live_draft_on_clock_ui import _render_on_clock_banner_html, render_live_on_clock_banner
from live_draft_room_ui import (
    LIVE_DRAFT_REC_DIAG_KEY,
    record_rec_card_diagnostics,
    render_live_draft_rec_cards,
    render_live_draft_room_header,
)
from live_draft_timer_ui import _mount_js_countdown, record_timer_diagnostics


def _sample_room(**overrides) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    room = {
        "draft_room_id": "UXROOM1",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_deadline": time.time() + 45,
    }
    room.update(overrides)
    return room


class RoomHeaderTests(unittest.TestCase):
    def test_solo_header_shows_mode_not_room_code(self) -> None:
        st = mock.MagicMock()
        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": _sample_room(status="in_progress"),
        }
        render_live_draft_room_header(
            st,
            session,
            session["live_draft_room"],
            multiplayer=False,
            user_team="Danny",
            on_clock_team="Danny",
            pick_label="Pick 1 / 2",
            status_label="In Progress",
            draft_in_progress=True,
        )
        joined = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("Solo Draft", joined)
        self.assertIn("You control all teams", joined)
        st.code.assert_not_called()

    def test_shared_header_shows_code_role_team(self) -> None:
        st = mock.MagicMock()
        session = {
            "active_shared_draft_room_code": "ABC123",
            "live_draft_setup_mode": "shared_multiplayer",
            "live_draft_room": _sample_room(status="in_progress", config={"draft_setup_mode": "shared_multiplayer"}),
            "draft_room_participant_id": "host-1",
        }
        with mock.patch("draft_room_context.get_global_draft_context") as ctx:
            ctx.return_value = {
                "is_room_host": True,
                "participant_team": "Danny",
                "room_code": "ABC123",
            }
            render_live_draft_room_header(
                st,
                session,
                session["live_draft_room"],
                multiplayer=True,
                user_team="Danny",
                on_clock_team="Danny",
                pick_label="Pick 1 / 2",
                status_label="In Progress",
                draft_in_progress=True,
            )
        joined = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("ABC123", joined)
        self.assertIn("Shared Multiplayer", joined)
        st.code.assert_called()


class TimerCountdownTests(unittest.TestCase):
    def test_timer_diagnostics_include_deadline_and_mount(self) -> None:
        session: dict = {}
        room = _sample_room()
        diag = record_timer_diagnostics(session, room, source="test")
        self.assertIsNotNone(diag.get("timer_deadline"))
        self.assertIn("computed_remaining", diag)

    @mock.patch("streamlit.components.v1.html")
    def test_js_countdown_mounts_with_deadline(self, html_mock: mock.MagicMock) -> None:
        st = mock.MagicMock()
        deadline = time.time() + 30
        _mount_js_countdown(st, deadline, pick_index=3, element_id="ld-banner-timer-3", height=0)
        html_mock.assert_called_once()
        script = str(html_mock.call_args)
        self.assertIn(str(deadline), script)
        self.assertIn("ld-banner-timer-3", script)

    @mock.patch("streamlit.components.v1.html")
    def test_on_clock_banner_html_includes_timer_element(self, html_mock: mock.MagicMock) -> None:
        st = mock.MagicMock()
        slot = {"Team": "Team 1", "Round": 1, "Pick": 1}
        _render_on_clock_banner_html(
            st,
            slot,
            40,
            pick_index=0,
            deadline=time.time() + 40,
        )
        html = str(st.markdown.call_args)
        self.assertIn("ld-banner-timer-0", html)
        html_mock.assert_called_once()


class CompactRecCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = mock.MagicMock()
        self.session = {"live_draft_room": _sample_room()}
        self.rec_df = pd.DataFrame(
            [
                {
                    "fullName": "Juan Soto",
                    "playerID": "p1",
                    "Primary Position": "OF",
                    "Fantasy Edge": 12,
                    "Survival Probability": 0.34,
                }
            ]
        )

    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_long_player_name_not_truncated(self, _avail: object, _ctx: object, gate_fn: mock.MagicMock) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        long_df = pd.DataFrame(
            [
                {
                    "fullName": "Shohei Ohtani",
                    "playerID": "sho1",
                    "Primary Position": "DH",
                    "Fantasy Edge": 15,
                    "Survival Probability": 0.42,
                }
            ]
        )
        col_info = mock.MagicMock()
        col_btn = mock.MagicMock()
        col_detail = mock.MagicMock()
        self.st.columns.return_value = [col_info, col_btn, col_detail]

        render_live_draft_rec_cards(
            self.st,
            self.session,
            self.session["live_draft_room"],
            long_df,
            max_cards=1,
        )
        html = str(self.st.markdown.call_args)
        self.assertIn("Shohei Ohtani", html)
        self.assertNotIn("...", html)
        self.assertIn("DH", html)
        self.assertIn("Reason:", html)

    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_stacked_mobile_layout(self, _avail: object, _ctx: object, gate_fn: mock.MagicMock) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        self.st.columns.return_value = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        render_live_draft_rec_cards(
            self.st,
            self.session,
            self.session["live_draft_room"],
            self.rec_df,
            max_cards=1,
            layout="stacked",
        )
        diag = self.session.get(LIVE_DRAFT_REC_DIAG_KEY) or {}
        self.assertEqual(diag.get("recommendation_card_layout_mode"), "stacked")
        html = str(self.st.markdown.call_args)
        self.assertIn("ld-rec-stacked", html)
        self.assertIn("Juan Soto", html)

    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_compact_layout_and_draft_button(self, _avail: object, _ctx: object, gate_fn: mock.MagicMock) -> None:
        gate_fn.return_value = {
            "draft_enabled": True,
            "draft_complete": False,
            "draft_button_disable_reason": None,
        }
        col_info = mock.MagicMock()
        col_btn = mock.MagicMock()
        col_detail = mock.MagicMock()
        self.st.columns.return_value = [col_info, col_btn, col_detail]

        render_live_draft_rec_cards(
            self.st,
            self.session,
            self.session["live_draft_room"],
            self.rec_df,
            max_cards=1,
        )

        diag = self.session.get(LIVE_DRAFT_REC_DIAG_KEY) or {}
        self.assertEqual(diag.get("recommendation_card_layout_mode"), "compact_horizontal")
        html = str(self.st.markdown.call_args)
        self.assertIn("ld-rec-compact-row", html)
        self.assertIn("ld-rec-name", html)
        self.assertIn("Juan Soto", html)
        self.st.button.assert_called_once()
        args, kwargs = self.st.button.call_args
        self.assertIn("Draft Soto", args[0])
        self.assertTrue(kwargs.get("on_click"))

    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_draft_button_disabled_when_not_turn(self, _avail: object, _ctx: object, gate_fn: mock.MagicMock) -> None:
        gate_fn.return_value = {
            "draft_enabled": False,
            "draft_complete": False,
            "draft_button_disable_reason": "not_your_turn",
        }
        col_info = mock.MagicMock()
        col_btn = mock.MagicMock()
        col_detail = mock.MagicMock()
        self.st.columns.return_value = [col_info, col_btn, col_detail]

        render_live_draft_rec_cards(
            self.st,
            self.session,
            self.session["live_draft_room"],
            self.rec_df,
            max_cards=1,
        )
        kwargs = self.st.button.call_args[1]
        self.assertTrue(kwargs.get("disabled"))

    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(False, "already drafted"))
    def test_draft_button_disabled_when_unavailable(self, _avail: object, _ctx: object, gate_fn: mock.MagicMock) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        col_info = mock.MagicMock()
        col_btn = mock.MagicMock()
        col_detail = mock.MagicMock()
        self.st.columns.return_value = [col_info, col_btn, col_detail]

        render_live_draft_rec_cards(
            self.st,
            self.session,
            self.session["live_draft_room"],
            self.rec_df,
            max_cards=1,
        )
        self.assertTrue(self.st.button.call_args[1].get("disabled"))


class RecCardDraftCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = mock.MagicMock()
        self.session = {"live_draft_room": _sample_room()}

    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    @mock.patch("live_draft_state.live_draft_get_available", return_value=None)
    def test_rec_card_queue_uses_same_pending_path(self, _pool: object, _avail: object) -> None:
        queue_manual_draft_pick(
            self.session,
            player_name="Juan Soto",
            player_id="p1",
            candidate_source="rec_card",
            pool_source="recommendation_card",
        )
        pending = self.session.get(PENDING_MANUAL_PICK_KEY)
        self.assertEqual(pending.get("player_name"), "Juan Soto")
        self.assertEqual(pending.get("candidate_source"), "rec_card")
        diag = self.session.get(LIVE_DRAFT_REC_DIAG_KEY) or {}
        self.assertTrue(diag.get("rec_card_draft_click_received"))

    @mock.patch("draft_ui.draft_player", return_value={"ok": True, "message": "Drafted Juan Soto."})
    def test_rec_card_commit_records_optimistic_diag(self, mock_draft: mock.MagicMock) -> None:
        self.session[PENDING_MANUAL_PICK_KEY] = {
            "player_name": "Juan Soto",
            "selected_player_id": "p1",
            "candidate_source": "rec_card",
            "pool_source": "recommendation_card",
            "player_still_available_at_click": True,
        }
        result = process_pending_manual_draft_pick(self.st, self.session)
        self.assertTrue(result.get("ok"))
        self.assertFalse(result.get("should_rerun"))
        mock_draft.assert_called_once_with(self.session, "Juan Soto", source="live_draft_room", st_obj=self.st)
        diag = self.session.get(LIVE_DRAFT_REC_DIAG_KEY) or {}
        self.assertTrue(diag.get("rec_card_commit_success"))


class RecCardRemotePollTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedRoomStore(root=Path(self._tmpdir.name))
        self.host: dict = {"draft_room_participant_id": "host-user", "room_your_team": "Team 1"}
        self.guest: dict = {"draft_room_participant_id": "guest-user", "room_your_team": "Team 2"}
        self._patch = mock.patch("draft_room_shared_state.get_shared_room_store", return_value=self.store)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    @mock.patch("draft_room_membership.shared_room_requires_auth", return_value=False)
    def test_remote_receives_rec_card_pick_by_poll(self, _auth: object) -> None:
        from live_draft_pick_commit import persist_applied_pick
        from live_draft_pick_engine import live_draft_make_pick

        room = _sample_room()
        code, _ = create_and_host_shared_room(self.host, room, store=self.store)
        join_shared_draft_room(self.guest, code, store=self.store)

        host_room = self.host[LIVE_DRAFT_ROOM_KEY]
        row = host_room["pool"].iloc[0].to_dict()
        ok_pick, _ = live_draft_make_pick(host_room, row, verdict="Rec card pick")
        self.assertTrue(ok_pick)
        commit = persist_applied_pick(self.host, host_room, source="rec_card")
        self.assertTrue(commit.ok, commit.message)

        changed = poll_shared_draft_room(self.guest, store=self.store)
        self.assertTrue(changed)
        guest_room = self.guest[LIVE_DRAFT_ROOM_KEY]
        self.assertEqual(len(guest_room.get("draft_board") or []), 1)
        self.assertEqual(int(guest_room.get("current_pick_index") or 0), 1)


if __name__ == "__main__":
    unittest.main()
