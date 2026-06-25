"""Critical draft flow — rec-card binding, pause, auto-pick, timer freeze."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from draft_ui import PENDING_MANUAL_PICK_KEY, MANUAL_CANDIDATE_SNAPSHOT_KEY, queue_manual_draft_pick
from live_draft_autopick import live_draft_auto_pick
from live_draft_pick_timer import (
    PICK_SUBMITTING_KEY,
    TIMER_FROZEN_KEY,
    clear_pick_submit_state,
    display_seconds_with_freeze,
    freeze_timer_for_pick_submit,
    is_pick_submitting,
)
from live_draft_safe_mode import reconcile_live_draft_room
from live_draft_state import LIVE_DRAFT_ROOM_KEY


def _room(**overrides) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Kyle Schwarber", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Bobby Witt", "Primary Position": "SS"},
            {"playerID": "p3", "fullName": "Aaron Judge", "Primary Position": "OF"},
        ]
    )
    room = {
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "picks_per_team": 5,
            "timer_seconds": 60,
            "your_team": "Danny",
            "auto_pick_rule": "best roster need",
        },
        "teams": ["Danny", "Amiel"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Danny"},
            {"Pick": 2, "Round": 1, "Team": "Amiel"},
        ],
        "draft_board": [],
        "rosters": {"Danny": [], "Amiel": []},
        "drafted_player_ids": [],
        "pool": pool,
        "timer_deadline": __import__("time").time() + 45,
        "timer_handled_index": -1,
    }
    room.update(overrides)
    return room


class RecCardQueueTests(unittest.TestCase):
    def test_rec_card_ignores_manual_selectbox_snapshot(self) -> None:
        session = {
            LIVE_DRAFT_ROOM_KEY: _room(),
            MANUAL_CANDIDATE_SNAPSHOT_KEY: {
                "name": "Bobby Witt",
                "id": "p2",
                "widget_key": "live_draft_manual_candidate_i0",
            },
            "live_draft_manual_candidate_i0": "Bobby Witt",
        }
        queue_manual_draft_pick(
            session,
            player_name="Kyle Schwarber",
            player_id="p1",
            candidate_source="rec_card",
            pool_source="recommendation_card",
        )
        pending = session[PENDING_MANUAL_PICK_KEY]
        self.assertEqual(pending["player_name"], "Kyle Schwarber")
        self.assertEqual(pending["selected_player_id"], "p1")
        self.assertTrue(is_pick_submitting(session))

    def test_rec_card_button_key_uses_player_id(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        st = mock.MagicMock()
        session = {LIVE_DRAFT_ROOM_KEY: _room()}
        rec_df = pd.DataFrame(
            [{"fullName": "Kyle Schwarber", "playerID": "p1", "Primary Position": "OF", "Fantasy Edge": 12, "Survival Probability": 0.14}]
        )
        st.container.return_value.__enter__ = mock.Mock(return_value=mock.MagicMock())
        st.container.return_value.__exit__ = mock.Mock(return_value=False)
        st.columns.return_value = [mock.MagicMock(), mock.MagicMock()]

        with mock.patch("draft_actions.resolve_manual_draft_panel_gate") as gate_fn, mock.patch(
            "draft_actions.draft_action_context"
        ), mock.patch("draft_actions._live_player_available", return_value=(True, "")):
            gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
            render_live_draft_rec_cards(st, session, session[LIVE_DRAFT_ROOM_KEY], rec_df, max_cards=1)

        btn_key = st.button.call_args[1].get("key") or st.button.call_args[0]
        key = st.button.call_args[1]["key"]
        self.assertIn("p1", key)
        self.assertNotIn("rec_card_draft_0_1", key)


class PauseDraftTests(unittest.TestCase):
    def test_reconcile_preserves_paused_status(self) -> None:
        session: dict = {}
        room = _room(status="paused", paused_remaining_seconds=37, timer_deadline=None, timer_started_at=None)
        session[LIVE_DRAFT_ROOM_KEY] = room
        result = reconcile_live_draft_room(session, room)
        self.assertEqual(result.room.get("status"), "paused")
        self.assertFalse(result.timer_should_run)

    def test_autopick_blocked_when_paused(self) -> None:
        session: dict = {}
        room = _room(status="paused", paused_remaining_seconds=30)
        ok, msg = live_draft_auto_pick(room, session=session)
        self.assertFalse(ok)
        self.assertIn("paused", msg.lower())


class AutopickRecommendationTests(unittest.TestCase):
    def test_autopick_selects_top_balanced_recommendation(self) -> None:
        session: dict = {}
        room = _room()
        ok, _ = live_draft_auto_pick(room, session=session)
        self.assertTrue(ok)
        board = room.get("draft_board") or []
        self.assertEqual(len(board), 1)
        diag = session.get("_live_draft_autopick_diag") or {}
        self.assertEqual(diag.get("top_recommendation_player"), diag.get("selected_auto_pick_player"))
        self.assertIn("auto_pick_candidate_list", diag)


class TimerFreezeTests(unittest.TestCase):
    def test_freeze_stops_display_seconds(self) -> None:
        session: dict = {}
        room = _room()
        freeze_timer_for_pick_submit(session, room)
        shown = display_seconds_with_freeze(session, room)
        self.assertGreaterEqual(shown, 0)
        self.assertTrue(session.get(PICK_SUBMITTING_KEY))
        clear_pick_submit_state(session)
        self.assertFalse(is_pick_submitting(session))
        self.assertNotIn(TIMER_FROZEN_KEY, session)


if __name__ == "__main__":
    unittest.main()
