"""Player Action → Waiver Wire handoff tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_league_context import (
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    activate_league_context,
    apply_pending_league_context_activation,
    get_active_league_context,
    save_imported_league_context,
    upsert_league_context,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import assign_team_owner_to_context
from fantasy_waiver_wire import WAIVER_PLANNER_ADD_KEY, WAIVER_PLANNER_DROP_KEY, WAIVER_WIRE_PAGE
from player_trade_constants import (
    TRADE_ACTION_ACQUIRE,
    TRADE_ACTION_TRADE_AWAY,
    WAIVER_ACTION_PLAN_ADD,
    WAIVER_ACTION_PLAN_DROP,
)
from player_trade_handoff import (
    TRADE_CENTER_HANDOFF_KEY,
    VALIDATION_STALE,
    VALIDATION_TRANSIENT,
    queue_player_action_trade_handoff,
    resolve_active_league_player_trade_eligibility,
)
from player_waiver_handoff import (
    WAIVER_WIRE_HANDOFF_KEY,
    consume_waiver_wire_handoff_into_planner,
    handoff_diag_key,
    queue_player_action_waiver_handoff,
    validate_waiver_wire_handoff,
)
from tests.test_player_action_trade_handoff import (
    _league_board,
    _roster_stats,
    _seed_shared_league,
    _seed_shared_league_with_split_ids,
)

_SHARED_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


class PlayerActionWaiverEligibilityTests(unittest.TestCase):
    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_mark_vientos_plan_add_enabled(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Mark Vientos")
        self.assertTrue(elig["plan_add_enabled"])
        self.assertFalse(elig["plan_drop_enabled"])
        self.assertFalse(elig["acquire_enabled"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_mookie_betts_plan_drop_enabled(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Mookie Betts")
        self.assertTrue(elig["plan_drop_enabled"])
        self.assertFalse(elig["plan_add_enabled"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_aaron_judge_waiver_actions_disabled(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Aaron Judge")
        self.assertTrue(elig["acquire_enabled"])
        self.assertFalse(elig["plan_add_enabled"])
        self.assertFalse(elig["plan_drop_enabled"])
        self.assertIn("Acquire", elig["plan_add_help"])


class PlayerActionWaiverHandoffTests(unittest.TestCase):
    def _active_scope_ids(self, session: dict) -> tuple[str, str]:
        active = get_active_league_context(session) or {}
        return (
            str(active.get("league_context_id") or "").strip(),
            str(resolve_canonical_league_id(active) or "").strip(),
        )

    def _simulate_waiver_render(self, session: dict) -> dict:
        active_context_id, active_canonical_id = self._active_scope_ids(session)
        consume_waiver_wire_handoff_into_planner(
            session,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_id,
        )
        return {
            "plan_add": str(session.get(WAIVER_PLANNER_ADD_KEY) or "").strip(),
            "plan_drop": str(session.get(WAIVER_PLANNER_DROP_KEY) or "").strip(),
            "handoff_remaining": WAIVER_WIRE_HANDOFF_KEY in session,
        }

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_plan_add_populates_add_only(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, _ = queue_player_action_waiver_handoff(session, player_name="Mark Vientos", mode=WAIVER_ACTION_PLAN_ADD)
        self.assertTrue(ok)
        self.assertEqual(session["_navigate_to_page"], WAIVER_WIRE_PAGE)
        handoff = session[WAIVER_WIRE_HANDOFF_KEY]
        self.assertEqual(handoff["action"], "plan_add")
        self.assertEqual(handoff["player_name"], "Mark Vientos")
        result = self._simulate_waiver_render(session)
        self.assertEqual(result["plan_add"], "Mark Vientos")
        self.assertEqual(result["plan_drop"], "")
        self.assertFalse(result["handoff_remaining"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_plan_drop_populates_drop_only(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, _ = queue_player_action_waiver_handoff(session, player_name="Mookie Betts", mode=WAIVER_ACTION_PLAN_DROP)
        self.assertTrue(ok)
        result = self._simulate_waiver_render(session)
        self.assertEqual(result["plan_drop"], "Mookie Betts")
        self.assertEqual(result["plan_add"], "")
        self.assertFalse(result["handoff_remaining"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_opponent_plan_add_rejected_at_queue(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, msg = queue_player_action_waiver_handoff(session, player_name="Aaron Judge", mode=WAIVER_ACTION_PLAN_ADD)
        self.assertFalse(ok)
        self.assertIn("Acquire", msg)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_split_ids_do_not_reject_valid_waiver_handoff(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league_with_split_ids(session)
        active_context_id = str(context.get("league_context_id") or "")
        active_canonical_id = str(resolve_canonical_league_id(context) or "")
        self.assertNotEqual(active_context_id, active_canonical_id)
        queue_player_action_waiver_handoff(session, player_name="Mark Vientos", mode=WAIVER_ACTION_PLAN_ADD)
        handoff = session[WAIVER_WIRE_HANDOFF_KEY]
        self.assertEqual(handoff["league_context_id"], active_context_id)
        self.assertEqual(handoff["canonical_league_id"], active_canonical_id)
        result = self._simulate_waiver_render(session)
        self.assertEqual(result["plan_add"], "Mark Vientos")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_transient_context_preserves_waiver_handoff(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league_with_split_ids(session)
        queue_player_action_waiver_handoff(session, player_name="Mark Vientos", mode=WAIVER_ACTION_PLAN_ADD)
        session[PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY] = session[WAIVER_WIRE_HANDOFF_KEY]["league_context_id"]
        state = session.get("fantasy_league_context_state") or {}
        state["active_league_context_id"] = ""
        session["fantasy_league_context_state"] = state
        consume_waiver_wire_handoff_into_planner(session, active_context_id="", active_canonical_league_id="")
        self.assertIn(WAIVER_WIRE_HANDOFF_KEY, session)
        diag = session.get(handoff_diag_key()) or {}
        self.assertEqual(diag.get("validation_result"), VALIDATION_TRANSIENT)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_stale_waiver_handoff_rejected_with_reason(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league(session)
        handoff = {
            "action": "plan_add",
            "source": "player_action",
            "player_name": "Aaron Judge",
            "league_context_id": str(context.get("league_context_id") or ""),
            "canonical_league_id": str(resolve_canonical_league_id(context) or ""),
            "my_team": "Daniel",
        }
        validated, err, status = validate_waiver_wire_handoff(
            handoff,
            session,
            active_context_id=str(context.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(context) or ""),
        )
        self.assertIsNone(validated)
        self.assertEqual(status, VALIDATION_STALE)
        self.assertIn("Team 2", err)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_plan_add_preserves_valid_existing_drop(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        session[WAIVER_PLANNER_DROP_KEY] = "Mookie Betts"
        queue_player_action_waiver_handoff(session, player_name="Mark Vientos", mode=WAIVER_ACTION_PLAN_ADD)
        self._simulate_waiver_render(session)
        self.assertEqual(session.get(WAIVER_PLANNER_ADD_KEY), "Mark Vientos")
        self.assertEqual(session.get(WAIVER_PLANNER_DROP_KEY), "Mookie Betts")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_second_waiver_render_keeps_planner_without_reconsuming(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        queue_player_action_waiver_handoff(session, player_name="Mookie Betts", mode=WAIVER_ACTION_PLAN_DROP)
        first = self._simulate_waiver_render(session)
        second = self._simulate_waiver_render(session)
        self.assertEqual(first["plan_drop"], "Mookie Betts")
        self.assertEqual(second["plan_drop"], "Mookie Betts")


class CombinedPlayerActionRegressionTests(unittest.TestCase):
    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_all_four_actions_from_same_active_league(self, _uid: object) -> None:
        from fantasy_trade_builder_state import (
            ANY_TRADE_PARTNER,
            apply_pending_to_logical_state,
            builder_widget_keys,
            maybe_migrate_builder_schema,
            prepare_builder_widget_state,
            scope_fingerprint_changed,
        )
        from player_trade_handoff import consume_trade_center_handoff_into_pending
        from tests.test_player_action_trade_handoff import FINGERPRINT, SCOPE

        session: dict = {}
        _seed_shared_league(session)
        apply_pending_league_context_activation(session)

        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        keys = builder_widget_keys(SCOPE)
        scope_fingerprint_changed(session, SCOPE, FINGERPRINT)
        logical: dict = {}
        logical, _ = maybe_migrate_builder_schema(session, SCOPE, logical)
        active = get_active_league_context(session) or {}
        consume_trade_center_handoff_into_pending(
            session,
            SCOPE,
            roster_stats=_roster_stats(),
            my_team="Daniel",
            other_teams=["Team 2", "Team 3", "Team 4"],
            active_context_id=str(active.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(active) or ""),
        )
        pool = ["Aaron Judge", "Gunnar Henderson", "Bobby Witt Jr."]
        logical, _ = apply_pending_to_logical_state(
            session,
            SCOPE,
            logical,
            my_players=["Mookie Betts"],
            receive_options=pool,
            other_teams=["Team 2", "Team 3", "Team 4"],
        )
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=["Mookie Betts"],
            receive_options=pool,
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3", "Team 4"],
            force=True,
            force_reason="pending_update",
        )
        acquire_widgets = {
            "receive": list(session.get(keys["receive"]) or []),
            "give": list(session.get(keys["give"]) or []),
            "partner": str(session.get(keys["partner"]) or ""),
        }
        self.assertEqual(acquire_widgets["receive"], ["Aaron Judge"])
        self.assertEqual(acquire_widgets["partner"], "Team 2")
        self.assertEqual(acquire_widgets["give"], [])

        queue_player_action_trade_handoff(session, player_name="Mookie Betts", mode=TRADE_ACTION_TRADE_AWAY)
        logical = {}
        logical, _ = maybe_migrate_builder_schema(session, SCOPE, logical)
        consume_trade_center_handoff_into_pending(
            session,
            SCOPE,
            roster_stats=_roster_stats(),
            my_team="Daniel",
            other_teams=["Team 2", "Team 3", "Team 4"],
            active_context_id=str(active.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(active) or ""),
        )
        logical, _ = apply_pending_to_logical_state(
            session,
            SCOPE,
            logical,
            my_players=["Mookie Betts"],
            receive_options=pool,
            other_teams=["Team 2", "Team 3", "Team 4"],
        )
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=["Mookie Betts"],
            receive_options=pool,
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3", "Team 4"],
            force=True,
            force_reason="pending_update",
        )
        trade_away_widgets = {
            "give": list(session.get(keys["give"]) or []),
            "receive": list(session.get(keys["receive"]) or []),
            "partner": str(session.get(keys["partner"]) or ""),
        }
        self.assertEqual(trade_away_widgets["give"], ["Mookie Betts"])
        self.assertEqual(trade_away_widgets["receive"], [])
        self.assertEqual(trade_away_widgets["partner"], ANY_TRADE_PARTNER)

        queue_player_action_waiver_handoff(session, player_name="Mark Vientos", mode=WAIVER_ACTION_PLAN_ADD)
        consume_waiver_wire_handoff_into_planner(
            session,
            active_context_id=str(active.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(active) or ""),
        )
        self.assertEqual(session.get(WAIVER_PLANNER_ADD_KEY), "Mark Vientos")
        self.assertNotIn(WAIVER_PLANNER_DROP_KEY, session)

        queue_player_action_waiver_handoff(session, player_name="Mookie Betts", mode=WAIVER_ACTION_PLAN_DROP)
        consume_waiver_wire_handoff_into_planner(
            session,
            active_context_id=str(active.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(active) or ""),
        )
        self.assertEqual(session.get(WAIVER_PLANNER_DROP_KEY), "Mookie Betts")
        self.assertNotIn(TRADE_CENTER_HANDOFF_KEY, session)
        self.assertNotIn(WAIVER_WIRE_HANDOFF_KEY, session)


if __name__ == "__main__":
    unittest.main()
