"""Manual Draft panel turn gate — aligned with page-level draft_button_diagnostics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_actions import compute_draft_turn_enabled, draft_action_context, resolve_manual_draft_panel_gate
from draft_ui import render_live_manual_draft_panel


def _live_ctx(**overrides: object) -> dict[str, object]:
    base = {
        "active_draft_source": "live",
        "active_mode": "live_draft_room",
        "draft_status": "in_progress",
        "draft_complete": False,
        "is_your_pick": True,
        "your_team": "Team 2",
        "on_clock_team": "Team 2",
        "current_pick": 3,
        "current_pick_index": 2,
        "total_picks": 24,
        "live_draft_active": True,
    }
    base.update(overrides)
    base["draft_enabled"] = compute_draft_turn_enabled(base)
    return base


class ComputeDraftTurnEnabledTests(unittest.TestCase):
    def test_enabled_on_your_pick_in_progress(self) -> None:
        self.assertTrue(compute_draft_turn_enabled(_live_ctx()))

    def test_disabled_when_missing_draft_enabled_key_but_pick_true(self) -> None:
        ctx = _live_ctx()
        ctx.pop("draft_enabled", None)
        self.assertTrue(compute_draft_turn_enabled(ctx))


class ResolveManualDraftPanelGateTests(unittest.TestCase):
    def test_should_render_matches_page_diagnostics(self) -> None:
        gate = resolve_manual_draft_panel_gate({}, _live_ctx(), multiplayer=False)
        self.assertTrue(gate["draft_enabled"])
        self.assertTrue(gate["draft_button_should_render"])
        self.assertIsNone(gate.get("draft_button_disable_reason"))

    def test_not_your_turn_reason(self) -> None:
        gate = resolve_manual_draft_panel_gate(
            {},
            _live_ctx(is_your_pick=False, on_clock_team="", your_team="Team 2"),
            multiplayer=False,
        )
        self.assertFalse(gate["draft_button_should_render"])
        self.assertEqual(gate["draft_button_disable_reason"], "not_your_turn")

    def test_turn_team_mismatch_reason(self) -> None:
        gate = resolve_manual_draft_panel_gate(
            {},
            _live_ctx(is_your_pick=False, your_team="Team 2", on_clock_team="Team 1"),
            multiplayer=False,
        )
        self.assertEqual(gate["draft_button_disable_reason"], "turn_team_mismatch")

    def test_draft_not_in_progress_reason(self) -> None:
        gate = resolve_manual_draft_panel_gate(
            {},
            _live_ctx(draft_status="not_started", is_your_pick=False),
            multiplayer=False,
        )
        self.assertEqual(gate["draft_button_disable_reason"], "draft_not_in_progress")

    @patch("draft_room_context.active_participant_team", return_value="")
    @patch("draft_room_context.is_multiplayer_draft_active", return_value=True)
    def test_multiplayer_assignment_missing(self, _mp: object, _team: object) -> None:
        gate = resolve_manual_draft_panel_gate(
            {"active_shared_draft_room_code": "ABC123"},
            _live_ctx(is_your_pick=False, your_team=""),
            multiplayer=True,
        )
        self.assertEqual(gate["draft_button_disable_reason"], "multiplayer_assignment_missing")


class RenderPanelGateAlignmentTests(unittest.TestCase):
    @patch("draft_ui.can_draft_player", return_value=(True, ""))
    @patch("draft_ui.render_draft_button", return_value=False)
    @patch("draft_source_validation.allow_free_pool_drafting", return_value=True)
    @patch("live_draft_state.live_draft_get_available")
    @patch("draft_actions.draft_action_context")
    def test_renders_selectbox_when_turn_enabled_without_stale_gate(
        self,
        mock_ctx: MagicMock,
        mock_pool: MagicMock,
        _free: object,
        _btn: object,
        _can: object,
    ) -> None:
        ctx = _live_ctx()
        ctx.pop("draft_enabled", None)
        mock_ctx.return_value = ctx
        mock_pool.return_value = pd.DataFrame([{"fullName": "Aaron Judge", "Expected Fantasy Value": 1.0, "Model Rank": 1}])
        st = MagicMock()
        st.selectbox.return_value = "Aaron Judge"
        session: dict = {"room_your_team": "Team 2"}
        render_live_manual_draft_panel(st, session, {"status": "in_progress"}, multiplayer=False)
        st.selectbox.assert_called()
        diag = session.get("_live_draft_ui_diag") or {}
        self.assertTrue(diag.get("draft_button_should_render"))
        self.assertTrue(diag.get("draft_button_rendered"))


if __name__ == "__main__":
    unittest.main()
