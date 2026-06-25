"""Smoke tests for Live Draft Room manual draft panel."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_ui import record_live_draft_ui_diagnostics, render_live_manual_draft_panel


def _live_ctx(**overrides: object) -> dict[str, object]:
    base = {
        "active_draft_source": "live",
        "active_mode": "live_draft_room",
        "draft_status": "in_progress",
        "is_your_pick": True,
        "draft_enabled": True,
        "draft_complete": False,
        "your_team": "Team A",
        "on_clock_team": "Team A",
        "current_pick": 1,
        "live_draft_active": True,
    }
    base.update(overrides)
    return base


def _room(**overrides: object) -> dict[str, object]:
    base = {
        "status": "in_progress",
        "config": {"your_team": "Team A"},
        "teams": ["Team A", "Team B"],
        "pick_order": [{"team": "Team A"}, {"team": "Team B"}],
        "draft_board": [],
        "pool_records": [{"fullName": "Aaron Judge", "Expected Fantasy Value": 1.0, "Model Rank": 1}],
        "pool_columns": ["fullName", "Expected Fantasy Value", "Model Rank"],
    }
    base.update(overrides)
    return base


class RecordLiveDraftUiDiagnosticsTests(unittest.TestCase):
    def test_accepts_merged_dict_without_duplicate_kw_error(self) -> None:
        session: dict = {}
        base = {"draft_button_rendered": False, "draft_action_disable_reason": ""}
        record_live_draft_ui_diagnostics(
            session,
            {**base, "draft_action_disable_reason": "empty_pool", "draft_button_rendered": False},
        )
        diag = session["_live_draft_ui_diag"]
        self.assertEqual(diag["draft_action_disable_reason"], "empty_pool")
        self.assertFalse(diag["draft_button_rendered"])


class RenderLiveManualDraftPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = MagicMock()
        self.session: dict = {"room_your_team": "Team A", "draft_queue": []}

    @patch("draft_actions.draft_action_context", return_value=_live_ctx())
    @patch("live_draft_state.live_draft_get_available", return_value=pd.DataFrame())
    def test_empty_pool_renders_without_crash(self, _avail: MagicMock, _ctx: MagicMock) -> None:
        result = render_live_manual_draft_panel(self.st, self.session, _room(), multiplayer=False)
        self.assertFalse(result)
        self.st.subheader.assert_called()
        self.st.warning.assert_called()
        diag = self.session.get("_live_draft_ui_diag") or {}
        self.assertEqual(diag.get("draft_action_disable_reason"), "empty_pool")
        self.assertEqual(diag.get("available_player_count"), 0)

    @patch("draft_actions.draft_action_context", return_value=_live_ctx())
    @patch("live_draft_state.live_draft_get_available", side_effect=RuntimeError("pool load failed"))
    def test_unavailable_pool_renders_without_draft_button(self, _avail: MagicMock, _ctx: MagicMock) -> None:
        result = render_live_manual_draft_panel(self.st, self.session, _room(), multiplayer=False)
        self.assertFalse(result)
        diag = self.session.get("_live_draft_ui_diag") or {}
        self.assertEqual(diag.get("draft_action_disable_reason"), "pool_unavailable")
        self.assertFalse(diag.get("draft_button_rendered"))

    @patch("draft_actions.draft_action_context", return_value=_live_ctx(is_your_pick=False, on_clock_team="Team B", your_team="Team A"))
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=True)
    @patch("live_draft_state.live_draft_get_available")
    def test_not_your_turn_shows_waiting_message_without_button(
        self,
        mock_get_available: MagicMock,
        _free: MagicMock,
        _ctx: MagicMock,
    ) -> None:
        mock_get_available.return_value = pd.DataFrame(
            [{"fullName": "Aaron Judge", "Expected Fantasy Value": 1.0, "Model Rank": 1}]
        )
        render_live_manual_draft_panel(self.st, self.session, _room(), multiplayer=False)
        self.st.info.assert_called()
        diag = self.session.get("_live_draft_ui_diag") or {}
        self.assertFalse(diag.get("draft_button_rendered"))
        self.assertFalse(diag.get("draft_button_should_render"))

    @patch("draft_ui.can_draft_player", return_value=(True, ""))
    @patch("draft_ui.render_draft_button", return_value=False)
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=True)
    @patch("draft_actions.draft_action_context", return_value=_live_ctx())
    @patch("live_draft_state.live_draft_get_available")
    def test_nonempty_pool_single_user_renders_selectbox(
        self,
        mock_get_available: MagicMock,
        _ctx: MagicMock,
        _free: MagicMock,
        _btn: MagicMock,
        _can: MagicMock,
    ) -> None:
        mock_get_available.return_value = pd.DataFrame(
            [{"fullName": "Aaron Judge", "Expected Fantasy Value": 1.0, "Model Rank": 1}]
        )
        self.st.selectbox.return_value = "Aaron Judge"
        result = render_live_manual_draft_panel(self.st, self.session, _room(), multiplayer=False)
        self.assertFalse(result)
        self.st.selectbox.assert_called()
        diag = self.session.get("_live_draft_ui_diag") or {}
        self.assertTrue(diag.get("draft_button_rendered"))
        self.assertEqual(diag.get("render_path"), "live_draft_room")
        self.assertFalse(diag.get("multiplayer_mode"))

    @patch("draft_ui.can_draft_player", return_value=(True, ""))
    @patch("draft_ui.render_draft_button", return_value=False)
    @patch("draft_source_validation.allowed_draft_player_names", return_value=[])
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=False)
    @patch("draft_actions.draft_action_context", return_value=_live_ctx())
    @patch("live_draft_state.live_draft_get_available")
    def test_multiplayer_restricted_empty_sources_falls_back_to_full_pool(
        self,
        mock_get_available: MagicMock,
        _ctx: MagicMock,
        _free: MagicMock,
        _allowed: MagicMock,
        mock_btn: MagicMock,
        _can: MagicMock,
    ) -> None:
        mock_get_available.return_value = pd.DataFrame(
            [{"fullName": "Aaron Judge", "Expected Fantasy Value": 1.0, "Model Rank": 1}]
        )
        self.st.selectbox.return_value = "Aaron Judge"
        self.session["active_shared_draft_room_code"] = "ABC123"
        render_live_manual_draft_panel(self.st, self.session, _room(), multiplayer=True)
        self.st.selectbox.assert_called()
        mock_btn.assert_called()
        diag = self.session.get("_live_draft_ui_diag") or {}
        self.assertEqual(diag.get("pool_source"), "full_pool_turn_fallback")
        self.assertTrue(diag.get("draft_button_rendered"))
        self.assertEqual(diag.get("candidate_count"), 1)


if __name__ == "__main__":
    unittest.main()
