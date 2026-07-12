"""Tests for per-context trade/acquire workflow persistence."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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
    save_imported_league_context,
    set_trade_acquire_handoff,
    upsert_league_context,
    workflow_target_player_names,
)
from fantasy_league_team_ownership import assign_team_owner_to_context
from player_trade_context import (
    TRADE_ACTION_ACQUIRE,
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


_SHARED_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


def _seed_shared_league(
    session: dict,
    *,
    my_team: str = "Daniel",
    user_id: str = "user:daniel",
    board_rows: list[dict] | None = None,
    draft_name: str = "UPLOAD TEST DEMO",
) -> dict:
    rows = board_rows or [
        {"Team": "Daniel", "Player": "Mike Trout", "Pick": 1},
        {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
    ]
    session["draft_shared_settings"] = dict(_SHARED_CFG)
    _, context = save_imported_league_context(
        session,
        pd.DataFrame(rows),
        my_team_name=my_team,
        draft_name=draft_name,
        league_name=draft_name,
        config=_SHARED_CFG,
        assign_team=False,
    )
    league_context_id = str(context.get("league_context_id") or "").strip()
    loaded = get_active_league_context(session) or context
    teams = sorted({str(row.get("Team") or "").strip() for row in rows if str(row.get("Team") or "").strip()})
    for idx, team in enumerate(teams):
        owner_id = user_id if team == my_team else f"user:team{idx}"
        loaded = assign_team_owner_to_context(
            loaded,
            team,
            user_id=owner_id,
            email=f"{team.lower().replace(' ', '')}@test",
        )
    context = upsert_league_context(session, loaded)
    activate_league_context(session, league_context_id)
    session["_suite_auth_user_id"] = user_id
    return context


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
        trade_handoff = session.get("_trade_center_handoff") or {}
        self.assertEqual(trade_handoff.get("receive_players"), ["Juan Soto"])
        self.assertEqual(trade_handoff.get("trade_partner"), "Rivals")
        self.assertEqual(trade_handoff.get("give_players"), [])


class TradeAcquireFlowPersistenceTests(unittest.TestCase):
    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_start_trade_acquire_flow_persists_and_handoffs(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        msg = start_trade_acquire_flow(session, player_name="Juan Soto", key_prefix="test")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Opening Fantasy Lineup Assistant", msg)
        self.assertEqual(session["_navigate_to_page"], "Fantasy Lineup Assistant")
        ctx = get_active_league_context(session)
        assert ctx is not None
        self.assertEqual(workflow_target_player_names(ctx, TRADE_MODE_ACQUIRE), ["Juan Soto"])
        trade_handoff = session.get("_trade_center_handoff") or {}
        self.assertEqual(trade_handoff.get("receive_players"), ["Juan Soto"])
        self.assertEqual(trade_handoff.get("trade_partner"), "Rivals")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_start_trade_acquire_flow_uses_active_league_only(self, _uid: object) -> None:
        session: dict = {}
        ctx_a = _seed_shared_league(
            session,
            board_rows=[
                {"Team": "Daniel", "Player": "Mike Trout", "Pick": 1},
                {"Team": "Rivals", "Player": "Mookie Betts", "Pick": 2},
            ],
            draft_name="League A",
        )
        _, ctx_b = save_imported_league_context(
            session,
            pd.DataFrame(
                [
                    {"Team": "Daniel", "Player": "Mike Trout", "Pick": 1},
                    {"Team": "East", "Player": "Mookie Betts", "Pick": 2},
                ]
            ),
            my_team_name="Daniel",
            draft_name="League B",
            league_name="League B",
            config=_SHARED_CFG,
            assign_team=False,
        )
        loaded_b = get_active_league_context(session) or ctx_b
        loaded_b = assign_team_owner_to_context(loaded_b, "Daniel", user_id="user:daniel")
        loaded_b = assign_team_owner_to_context(loaded_b, "East", user_id="user:east")
        upsert_league_context(session, loaded_b)
        activate_league_context(session, str(ctx_a.get("league_context_id") or ""))
        session["live_draft_room"] = {
            "config": {"league_name": "Live", "your_team": "Daniel"},
            "draft_board": [{"Player": "Mookie Betts", "Team": "Rivals"}],
        }
        session["draft_room_table"] = pd.DataFrame(columns=["Round", "Pick", "Team", "Player"])

        msg = start_trade_acquire_flow(session, player_name="Mookie Betts", key_prefix="pick")
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Opening Fantasy Lineup Assistant", msg)
        self.assertNotIn("_player_trade_acquire_flow", session)
        ctx_a_loaded = get_league_context(session, str(ctx_a.get("league_context_id") or ""))
        ctx_b_loaded = get_league_context(session, str(ctx_b.get("league_context_id") or ""))
        assert ctx_a_loaded is not None and ctx_b_loaded is not None
        self.assertEqual(workflow_target_player_names(ctx_a_loaded, TRADE_MODE_ACQUIRE), ["Mookie Betts"])
        self.assertEqual(workflow_target_player_names(ctx_b_loaded, TRADE_MODE_ACQUIRE), [])
        trade_handoff = session.get("_trade_center_handoff") or {}
        self.assertEqual(trade_handoff.get("receive_players"), ["Mookie Betts"])
        self.assertEqual(trade_handoff.get("trade_partner"), "Rivals")


if __name__ == "__main__":
    unittest.main()
