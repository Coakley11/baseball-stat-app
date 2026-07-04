"""Tests for per-context trade/acquire workflow persistence."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from fantasy_league_context import (
    TRADE_HANDOFF_SESSION_KEY,
    TRADE_MODE_ACQUIRE,
    TRADE_MODE_TRADE_AWAY,
    activate_league_context,
    add_workflow_target,
    consume_trade_acquire_handoff,
    create_league_context_from_live_room,
    get_active_league_context,
    get_league_context,
    get_workflow_targets,
    migrate_global_pending_trade_targets,
    remove_workflow_target,
    set_trade_acquire_handoff,
    workflow_target_player_names,
)
from player_trade_context import (
    TRADE_ACTION_ACQUIRE,
    complete_trade_acquire_flow,
    start_trade_acquire_flow,
)


def _league_room(team_a: str, team_b: str, player_a: str, player_b: str) -> dict:
    return {
        "config": {"league_name": "Test League", "fantasy_format": "5x5 Roto"},
        "rosters": {
            team_a: [{"fullName": player_a, "Primary Position": "OF"}],
            team_b: [{"fullName": player_b, "Primary Position": "OF"}],
        },
        "draft_board": [
            {"Fantasy Team": team_a, "fullName": player_a, "Pick": 1},
            {"Fantasy Team": team_b, "fullName": player_b, "Pick": 2},
        ],
    }


def _seed_league_context(session: dict, room: dict, *, my_team: str, context_id: str, display_name: str = "") -> None:
    create_league_context_from_live_room(
        session,
        room,
        my_team_name=my_team,
        league_context_id=context_id,
        display_name=display_name or context_id,
    )
    activate_league_context(session, context_id)


class WorkflowTargetPersistenceTests(unittest.TestCase):
    def test_acquire_soto_and_judge_isolated_per_context(self) -> None:
        session: dict = {}
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Juan Soto"),
            my_team="Daniel",
            context_id="live:league_a",
        )
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Aaron Judge"),
            my_team="Daniel",
            context_id="live:league_b",
        )
        add_workflow_target(session, "live:league_a", TRADE_MODE_ACQUIRE, "Juan Soto", owner_team="Rivals")
        add_workflow_target(session, "live:league_b", TRADE_MODE_ACQUIRE, "Aaron Judge", owner_team="Rivals")

        ctx_a = get_league_context(session, "live:league_a")
        ctx_b = get_league_context(session, "live:league_b")
        assert ctx_a is not None and ctx_b is not None
        self.assertEqual(workflow_target_player_names(ctx_a, TRADE_MODE_ACQUIRE), ["Juan Soto"])
        self.assertEqual(workflow_target_player_names(ctx_b, TRADE_MODE_ACQUIRE), ["Aaron Judge"])

        activate_league_context(session, "live:league_a")
        active = get_active_league_context(session)
        assert active is not None
        self.assertEqual(workflow_target_player_names(active, TRADE_MODE_ACQUIRE), ["Juan Soto"])

    def test_remove_workflow_target_updates_context(self) -> None:
        session: dict = {}
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Juan Soto"),
            my_team="Daniel",
            context_id="live:remove_test",
        )
        add_workflow_target(session, "live:remove_test", TRADE_MODE_ACQUIRE, "Juan Soto", owner_team="Rivals")
        remove_workflow_target(session, "live:remove_test", TRADE_MODE_ACQUIRE, "Juan Soto")
        ctx = get_league_context(session, "live:remove_test")
        assert ctx is not None
        self.assertEqual(get_workflow_targets(ctx, TRADE_MODE_ACQUIRE), [])

    def test_workflow_persists_through_disk_round_trip(self) -> None:
        st1 = MagicMock()
        st1.session_state = {}
        session = st1.session_state
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Juan Soto"),
            my_team="Daniel",
            context_id="live:persist01",
        )
        add_workflow_target(session, "live:persist01", TRADE_MODE_ACQUIRE, "Juan Soto", owner_team="Rivals")
        blob = build_baseball_disk_state(st1)

        st2 = MagicMock()
        st2.session_state = {}
        apply_baseball_disk_state(st2, blob)
        ctx = get_league_context(st2.session_state, "live:persist01")
        assert ctx is not None
        self.assertEqual(workflow_target_player_names(ctx, TRADE_MODE_ACQUIRE), ["Juan Soto"])

    def test_migrate_global_pending_trade_targets(self) -> None:
        session: dict = {}
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Juan Soto"),
            my_team="Daniel",
            context_id="live:migrate01",
        )
        session["pending_trade_acquire_players"] = ["Juan Soto"]
        session["pending_trade_away_players"] = ["Mike Trout"]
        migrated = migrate_global_pending_trade_targets(session)
        self.assertTrue(migrated)
        ctx = get_league_context(session, "live:migrate01")
        assert ctx is not None
        self.assertIn("Juan Soto", workflow_target_player_names(ctx, TRADE_MODE_ACQUIRE))
        self.assertIn("Mike Trout", workflow_target_player_names(ctx, TRADE_MODE_TRADE_AWAY))
        self.assertNotIn("pending_trade_acquire_players", session)

    def test_trade_acquire_handoff_navigation(self) -> None:
        session: dict = {}
        set_trade_acquire_handoff(
            session,
            league_context_id="live:handoff01",
            mode=TRADE_MODE_ACQUIRE,
            player_name="Juan Soto",
            owner_team="Rivals",
        )
        self.assertEqual(session["_navigate_to_page"], "Fantasy Lineup Assistant")
        self.assertIn(TRADE_HANDOFF_SESSION_KEY, session)
        handoff = consume_trade_acquire_handoff(session)
        assert handoff is not None
        self.assertEqual(handoff["player_name"], "Juan Soto")
        self.assertEqual(session["lineup_trade_other_team"], "Rivals")
        self.assertEqual(session["lineup_trade_get_players"], ["Juan Soto"])


class TradeAcquireFlowPersistenceTests(unittest.TestCase):
    def test_start_trade_acquire_flow_persists_and_handoffs(self) -> None:
        session: dict = {}
        room = _league_room("Daniel", "Rivals", "Mike Trout", "Juan Soto")
        _seed_league_context(session, room, my_team="Daniel", context_id="live:flow01")
        session["live_draft_room"] = {**room, "config": {**room["config"], "your_team": "Daniel"}}
        msg = start_trade_acquire_flow(session, player_name="Juan Soto", key_prefix="test")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Opening Fantasy Lineup Assistant", msg)
        self.assertEqual(session["_navigate_to_page"], "Fantasy Lineup Assistant")
        ctx = get_active_league_context(session)
        assert ctx is not None
        self.assertEqual(workflow_target_player_names(ctx, TRADE_MODE_ACQUIRE), ["Juan Soto"])

    def test_complete_trade_acquire_flow_multi_context_isolation(self) -> None:
        session: dict = {}
        _seed_league_context(
            session,
            _league_room("Daniel", "Rivals", "Mike Trout", "Mookie Betts"),
            my_team="Daniel",
            context_id="live:ctx_a",
            display_name="League A",
        )
        _seed_league_context(
            session,
            _league_room("Daniel", "East", "Mike Trout", "Mookie Betts"),
            my_team="Daniel",
            context_id="live:ctx_b",
            display_name="League B",
        )
        session["live_draft_room"] = {
            "config": {"league_name": "Live", "your_team": "Daniel"},
            "draft_board": [{"Player": "Mookie Betts", "Team": "Rivals"}],
        }
        session["draft_room_table"] = pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])
        msg = start_trade_acquire_flow(session, player_name="Mookie Betts", key_prefix="pick")
        self.assertIsNone(msg)
        flow = session.get("_player_trade_acquire_flow") or {}
        self.assertEqual(flow.get("step"), "choose_context")
        candidates = flow.get("candidates") or []
        ctx_ids = {str(c.get("league_context_id") or "") for c in candidates}
        self.assertIn("live:ctx_a", ctx_ids)
        self.assertIn("live:ctx_b", ctx_ids)

        msg_a = complete_trade_acquire_flow(
            session,
            mode=TRADE_ACTION_ACQUIRE,
            context_id=str(candidates[0].get("context_id")),
        )
        self.assertIn("Opening Fantasy Lineup Assistant", msg_a)
        ctx_a = get_league_context(session, "live:ctx_a")
        ctx_b = get_league_context(session, "live:ctx_b")
        assert ctx_a is not None and ctx_b is not None
        total_acquire = (
            workflow_target_player_names(ctx_a, TRADE_MODE_ACQUIRE)
            + workflow_target_player_names(ctx_b, TRADE_MODE_ACQUIRE)
        )
        self.assertEqual(total_acquire.count("Mookie Betts"), 1)


if __name__ == "__main__":
    unittest.main()
