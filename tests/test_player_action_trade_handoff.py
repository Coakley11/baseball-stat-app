"""Player Action → Trade Center handoff and active-league eligibility tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_league_context import (
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    activate_league_context,
    apply_pending_league_context_activation,
    consume_trade_acquire_handoff,
    get_active_league_context,
    save_imported_league_context,
    save_simulator_league_context,
    upsert_league_context,
)
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import assign_team_owner_to_context
from fantasy_trade_builder_state import (
    ANY_TRADE_PARTNER,
    TRADE_BUILDER_STATE_SCHEMA_VERSION,
    apply_pending_to_logical_state,
    builder_schema_key,
    builder_widget_keys,
    maybe_migrate_builder_schema,
    prepare_builder_widget_state,
    scope_fingerprint_changed,
)
from player_trade_constants import TRADE_ACTION_ACQUIRE, TRADE_ACTION_TRADE_AWAY
from player_trade_handoff import (
    TRADE_CENTER_HANDOFF_KEY,
    VALIDATION_STALE,
    VALIDATION_TRANSIENT,
    consume_trade_center_handoff_into_pending,
    handoff_diag_key,
    queue_player_action_trade_handoff,
    resolve_active_league_player_trade_eligibility,
    validate_trade_center_handoff,
)
from player_trade_context import start_player_trade_action

SCOPE = "trade_center_state|daniel|league:upload-test"
FINGERPRINT = "weekly_lineup|daniel|ws|league:upload-test|Daniel|week_1"
_SHARED_CFG = {
    "fantasy_format": "5x5 Roto",
    "scoring_type": "Roto (5x5)",
    "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 1},
    "slot_instances": [],
}


def _league_board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1},
            {"Team": "Team 2", "Player": "Aaron Judge", "Pick": 2},
            {"Team": "Team 3", "Player": "Gunnar Henderson", "Pick": 3},
            {"Team": "Team 4", "Player": "Bobby Witt Jr.", "Pick": 4},
        ]
    )


def _roster_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "Mookie Betts", "HR": 20},
            {"Team": "Team 2", "Player": "Aaron Judge", "HR": 31},
            {"Team": "Team 3", "Player": "Gunnar Henderson", "HR": 22},
            {"Team": "Team 4", "Player": "Bobby Witt Jr.", "HR": 18},
        ]
    )


def _seed_shared_league(session: dict, *, my_team: str = "Daniel", user_id: str = "user:daniel") -> dict:
    session["draft_shared_settings"] = dict(_SHARED_CFG)
    _, context = save_imported_league_context(
        session,
        _league_board(),
        my_team_name=my_team,
        draft_name="UPLOAD TEST DEMO",
        league_name="UPLOAD TEST DEMO",
        config=_SHARED_CFG,
        assign_team=False,
    )
    league_context_id = str(context.get("league_context_id") or "").strip()
    loaded = get_active_league_context(session) or context
    loaded = assign_team_owner_to_context(loaded, "Daniel", user_id=user_id, email="daniel@test")
    loaded = assign_team_owner_to_context(loaded, "Team 2", user_id="user:team2", email="team2@test")
    loaded = assign_team_owner_to_context(loaded, "Team 3", user_id="user:team3", email="team3@test")
    loaded = assign_team_owner_to_context(loaded, "Team 4", user_id="user:team4", email="team4@test")
    context = upsert_league_context(session, loaded)
    activate_league_context(session, league_context_id)
    session["_suite_auth_user_id"] = user_id
    return context


def _seed_shared_league_with_split_ids(
    session: dict,
    *,
    league_context_id: str = "archive:3ce50b4f2e8b",
    canonical_league_id: str = "league_upload_test_demo_abc123",
    user_id: str = "user:daniel",
) -> dict:
    context = _seed_shared_league(session, user_id=user_id)
    loaded = get_active_league_context(session) or context
    loaded["league_context_id"] = league_context_id
    meta = dict(loaded.get("metadata") or {})
    meta["league_id"] = canonical_league_id
    loaded["metadata"] = meta
    loaded["league_id"] = canonical_league_id
    context = upsert_league_context(session, loaded)
    activate_league_context(session, league_context_id)
    return context


class PlayerActionTradeEligibilityTests(unittest.TestCase):
    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_aaron_judge_acquire_enabled(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Aaron Judge")
        self.assertTrue(elig["acquire_enabled"])
        self.assertFalse(elig["trade_away_enabled"])
        self.assertEqual(elig["owner_team"], "Team 2")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_mookie_betts_trade_away_enabled(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Mookie Betts")
        self.assertTrue(elig["trade_away_enabled"])
        self.assertFalse(elig["acquire_enabled"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_unrostered_mark_vientos_disables_trade_actions(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        elig = resolve_active_league_player_trade_eligibility(session, "Mark Vientos")
        self.assertTrue(elig["is_unrostered"])
        self.assertFalse(elig["trade_away_enabled"])
        self.assertFalse(elig["acquire_enabled"])
        self.assertTrue(elig["waiver_enabled"])
        self.assertIn("Waiver Wire", elig["block_message"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_simulator_context_blocks_trade_actions(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Sim Player", "Pick": 1}])
        _, sim_ctx = save_simulator_league_context(
            session,
            board,
            my_team_name="Daniel",
            draft_name="Simulator Only",
            config=_SHARED_CFG,
        )
        activate_league_context(session, str(sim_ctx.get("league_context_id") or ""))
        elig = resolve_active_league_player_trade_eligibility(session, "Sim Player")
        self.assertFalse(elig["trade_away_enabled"])
        self.assertFalse(elig["acquire_enabled"])
        self.assertIn("mock", elig["block_message"].lower())

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_switching_active_league_recalculates_ownership(self, _uid: object) -> None:
        session: dict = {}
        ctx_a = _seed_shared_league(session)
        _, ctx_b = save_imported_league_context(
            session,
            pd.DataFrame(
                [
                    {"Team": "Daniel", "Player": "Mookie Betts", "Pick": 1},
                    {"Team": "Team 2", "Player": "Aaron Judge", "Pick": 2},
                ]
            ),
            my_team_name="Daniel",
            draft_name="Other League",
            league_name="Other League",
            config=_SHARED_CFG,
            assign_team=False,
        )
        loaded_b = get_active_league_context(session) or ctx_b
        loaded_b = assign_team_owner_to_context(loaded_b, "Daniel", user_id="user:daniel")
        loaded_b = assign_team_owner_to_context(loaded_b, "Team 2", user_id="user:team2")
        ctx_b = upsert_league_context(session, loaded_b)
        activate_league_context(session, str(ctx_a.get("league_context_id") or ""))
        elig_a = resolve_active_league_player_trade_eligibility(session, "Gunnar Henderson")
        self.assertTrue(elig_a["acquire_enabled"])
        activate_league_context(session, str(ctx_b.get("league_context_id") or ""))
        elig_b = resolve_active_league_player_trade_eligibility(session, "Gunnar Henderson")
        self.assertTrue(elig_b["is_unrostered"])


class PlayerActionTradeHandoffTests(unittest.TestCase):
    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_acquire_populates_receive_and_partner(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, _ = queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        self.assertTrue(ok)
        handoff = session[TRADE_CENTER_HANDOFF_KEY]
        self.assertEqual(handoff["receive_players"], ["Aaron Judge"])
        self.assertEqual(handoff["give_players"], [])
        self.assertEqual(handoff["trade_partner"], "Team 2")
        self.assertEqual(handoff["source"], "player_action_acquire")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_trade_away_populates_give_only(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, _ = queue_player_action_trade_handoff(session, player_name="Mookie Betts", mode=TRADE_ACTION_TRADE_AWAY)
        self.assertTrue(ok)
        handoff = session[TRADE_CENTER_HANDOFF_KEY]
        self.assertEqual(handoff["give_players"], ["Mookie Betts"])
        self.assertEqual(handoff["receive_players"], [])
        self.assertEqual(handoff["trade_partner"], ANY_TRADE_PARTNER)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_acquire_rejects_my_player(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, msg = queue_player_action_trade_handoff(session, player_name="Mookie Betts", mode=TRADE_ACTION_ACQUIRE)
        self.assertFalse(ok)
        self.assertIn("Trade Away", msg)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_trade_away_rejects_opponent_player(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        ok, msg = queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_TRADE_AWAY)
        self.assertFalse(ok)
        self.assertIn("Acquire", msg)


class PlayerActionTradeCenterRerunTests(unittest.TestCase):
    def _active_scope_ids(self, session: dict) -> tuple[str, str]:
        active = get_active_league_context(session) or {}
        return (
            str(active.get("league_context_id") or "").strip(),
            str(resolve_canonical_league_id(active) or "").strip(),
        )

    def _simulate_trade_center_render(self, session: dict, *, schema_version: int = TRADE_BUILDER_STATE_SCHEMA_VERSION) -> dict:
        roster_stats = _roster_stats()
        my_team = "Daniel"
        other_teams = ["Team 2", "Team 3", "Team 4"]
        my_players = ["Mookie Betts"]
        all_other = ["Aaron Judge", "Gunnar Henderson", "Bobby Witt Jr."]
        keys = builder_widget_keys(SCOPE)
        session[builder_schema_key(SCOPE)] = schema_version
        scope_fingerprint_changed(session, SCOPE, FINGERPRINT)

        logical: dict = {}
        logical, schema_migrated = maybe_migrate_builder_schema(session, SCOPE, logical)
        active_context_id, active_canonical_league_id = self._active_scope_ids(session)
        consume_trade_center_handoff_into_pending(
            session,
            SCOPE,
            roster_stats=roster_stats,
            my_team=my_team,
            other_teams=other_teams,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_league_id,
        )
        pool = all_other
        logical, pending_update = apply_pending_to_logical_state(
            session,
            SCOPE,
            logical,
            my_players=my_players,
            receive_options=pool,
            other_teams=other_teams,
        )
        scope_changed, _ = scope_fingerprint_changed(session, SCOPE, FINGERPRINT)
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=my_players,
            receive_options=pool,
            partner_options=[ANY_TRADE_PARTNER, *other_teams],
            force=bool(pending_update) or scope_changed or schema_migrated,
            force_reason="pending_update" if pending_update else "none",
        )
        return {
            "give": list(session.get(keys["give"]) or []),
            "receive": list(session.get(keys["receive"]) or []),
            "partner": str(session.get(keys["partner"]) or ""),
            "schema_migrated": schema_migrated,
            "pending_update": pending_update,
            "handoff_remaining": TRADE_CENTER_HANDOFF_KEY in session,
        }

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_acquire_live_rerun_populates_builder(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        apply_pending_league_context_activation(session)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        consume_trade_acquire_handoff(session)
        result = self._simulate_trade_center_render(session)
        self.assertEqual(result["receive"], ["Aaron Judge"])
        self.assertEqual(result["partner"], "Team 2")
        self.assertEqual(result["give"], [])
        self.assertFalse(result["handoff_remaining"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_second_rerun_keeps_selection_without_reconsuming_handoff(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        first = self._simulate_trade_center_render(session)
        second = self._simulate_trade_center_render(session)
        self.assertEqual(first["receive"], ["Aaron Judge"])
        self.assertEqual(second["receive"], ["Aaron Judge"])
        self.assertFalse(second["handoff_remaining"])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_schema_migration_does_not_erase_new_handoff(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        result = self._simulate_trade_center_render(session, schema_version=0)
        self.assertTrue(result["schema_migrated"])
        self.assertEqual(result["receive"], ["Aaron Judge"])
        self.assertEqual(result["partner"], "Team 2")

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_stale_ownership_rejected_before_builder_population(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league(session)
        session[TRADE_CENTER_HANDOFF_KEY] = {
            "action": "use",
            "source": "player_action_acquire",
            "league_context_id": str(context.get("league_context_id") or ""),
            "give_players": [],
            "receive_players": ["Aaron Judge"],
            "other_team": "Team 3",
            "trade_partner": "Team 3",
            "auto_analyze": False,
        }
        result = self._simulate_trade_center_render(session)
        self.assertEqual(result["receive"], [])
        self.assertEqual(result["give"], [])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_start_player_trade_action_navigation(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        msg = start_player_trade_action(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        self.assertIn("Opening Fantasy Lineup Assistant", msg)
        self.assertEqual(session["_navigate_to_page"], "Fantasy Lineup Assistant")
        self.assertIn(TRADE_CENTER_HANDOFF_KEY, session)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_trade_away_live_rerun_populates_give(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        queue_player_action_trade_handoff(session, player_name="Mookie Betts", mode=TRADE_ACTION_TRADE_AWAY)
        result = self._simulate_trade_center_render(session)
        self.assertEqual(result["give"], ["Mookie Betts"])
        self.assertEqual(result["receive"], [])
        self.assertEqual(result["partner"], ANY_TRADE_PARTNER)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_split_context_and_canonical_ids_do_not_reject_valid_handoff(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league_with_split_ids(session)
        active_context_id = str(context.get("league_context_id") or "")
        active_canonical_id = str(resolve_canonical_league_id(context) or "")
        self.assertNotEqual(active_context_id, active_canonical_id)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        handoff = session[TRADE_CENTER_HANDOFF_KEY]
        self.assertEqual(handoff["league_context_id"], active_context_id)
        self.assertEqual(handoff["canonical_league_id"], active_canonical_id)
        result = self._simulate_trade_center_render(session)
        self.assertEqual(result["receive"], ["Aaron Judge"])
        self.assertEqual(result["partner"], "Team 2")
        self.assertEqual(result["give"], [])

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_old_namespace_mix_rejects_handoff_with_diagnostics(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league_with_split_ids(session)
        handoff = {
            "action": "use",
            "source": "player_action_acquire",
            "league_context_id": str(context.get("league_context_id") or ""),
            "canonical_league_id": str(resolve_canonical_league_id(context) or ""),
            "give_players": [],
            "receive_players": ["Aaron Judge"],
            "trade_partner": "Team 2",
            "other_team": "Team 2",
        }
        session[TRADE_CENTER_HANDOFF_KEY] = handoff
        consume_trade_center_handoff_into_pending(
            session,
            SCOPE,
            roster_stats=_roster_stats(),
            my_team="Daniel",
            other_teams=["Team 2", "Team 3", "Team 4"],
            active_context_id=str(resolve_canonical_league_id(context) or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(context) or ""),
        )
        self.assertNotIn(TRADE_CENTER_HANDOFF_KEY, session)
        diag = session.get(handoff_diag_key(SCOPE)) or {}
        self.assertEqual(diag.get("validation_result"), VALIDATION_STALE)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_canonical_id_mismatch_rejects_stale_handoff(self, _uid: object) -> None:
        session: dict = {}
        context = _seed_shared_league_with_split_ids(session)
        handoff = {
            "action": "use",
            "source": "player_action_acquire",
            "league_context_id": str(context.get("league_context_id") or ""),
            "canonical_league_id": "league_stale_other",
            "give_players": [],
            "receive_players": ["Aaron Judge"],
            "trade_partner": "Team 2",
        }
        validated, err, status = validate_trade_center_handoff(
            handoff,
            session,
            roster_stats=_roster_stats(),
            my_team="Daniel",
            other_teams=["Team 2", "Team 3", "Team 4"],
            active_context_id=str(context.get("league_context_id") or ""),
            active_canonical_league_id=str(resolve_canonical_league_id(context) or ""),
        )
        self.assertIsNone(validated)
        self.assertEqual(status, VALIDATION_STALE)
        self.assertIn("canonical", err.lower())

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_transient_context_not_ready_preserves_handoff(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league_with_split_ids(session)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        session[PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY] = session[TRADE_CENTER_HANDOFF_KEY]["league_context_id"]
        state = session.get("fantasy_league_context_state") or {}
        state["active_league_context_id"] = ""
        session["fantasy_league_context_state"] = state
        consume_trade_center_handoff_into_pending(
            session,
            SCOPE,
            roster_stats=_roster_stats(),
            my_team="Daniel",
            other_teams=["Team 2", "Team 3", "Team 4"],
            active_context_id="",
            active_canonical_league_id="",
        )
        self.assertIn(TRADE_CENTER_HANDOFF_KEY, session)
        diag = session.get(handoff_diag_key(SCOPE)) or {}
        self.assertEqual(diag.get("validation_result"), VALIDATION_TRANSIENT)

    @patch("fantasy_league_team_ownership._resolve_user_id", return_value="user:daniel")
    def test_handoff_removed_only_after_successful_queue(self, _uid: object) -> None:
        session: dict = {}
        _seed_shared_league(session)
        queue_player_action_trade_handoff(session, player_name="Aaron Judge", mode=TRADE_ACTION_ACQUIRE)
        self._simulate_trade_center_render(session)
        self.assertNotIn(TRADE_CENTER_HANDOFF_KEY, session)
        diag = session.get(handoff_diag_key(SCOPE)) or {}
        self.assertTrue(diag.get("pending_update_queued"))
        self.assertEqual(diag.get("pending_get_players"), ["Aaron Judge"])


if __name__ == "__main__":
    unittest.main()
