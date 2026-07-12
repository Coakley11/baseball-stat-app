"""Fake Streamlit rerun sequence tests for Trade Center builder."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_trade_builder_state import (
    ANY_TRADE_PARTNER,
    TRADE_BUILDER_STATE_SCHEMA_VERSION,
    apply_pending_to_logical_state,
    builder_schema_key,
    builder_widget_keys,
    maybe_migrate_builder_schema,
    prepare_builder_widget_state,
    proposal_confirm_key,
    queue_pending_builder_update,
    receive_options_for_partner,
    save_logical_state_from_widgets,
    scope_fingerprint_changed,
)


SCOPE = "trade_center_state|daniel|league:test"
FINGERPRINT = "weekly_lineup|daniel|ws|league:test|Daniel|week_1"


def _rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "José Ramírez", "Primary Position": "3B", "HR": 18, "RBI": 57, "R": 52, "SB": 15, "BA": 0.284},
            {"Team": "Daniel", "Player": "Mookie Betts", "Primary Position": "SS,OF", "HR": 20, "RBI": 50, "R": 58, "SB": 10, "BA": 0.290},
            {"Team": "Team 2", "Player": "Aaron Judge", "Primary Position": "OF", "HR": 31, "RBI": 72, "R": 68, "SB": 4, "BA": 0.291},
            {"Team": "Team 3", "Player": "Gunnar Henderson", "Primary Position": "SS,3B", "HR": 22, "RBI": 58, "R": 61, "SB": 11, "BA": 0.279},
        ]
    )


class BuilderRerunSimulator:
    def __init__(self) -> None:
        self.session: dict = {}
        self.logical: dict = {}
        self.keys = builder_widget_keys(SCOPE)
        self.my_players = ["José Ramírez", "Mookie Betts"]
        self.all_other = ["Aaron Judge", "Gunnar Henderson"]
        self.other_teams = ["Team 2", "Team 3"]
        self.rosters = _rosters()
        self.session[builder_schema_key(SCOPE)] = TRADE_BUILDER_STATE_SCHEMA_VERSION
        scope_fingerprint_changed(self.session, SCOPE, FINGERPRINT)

    def _receive_pool(self) -> list[str]:
        return receive_options_for_partner(
            self.rosters,
            my_team="Daniel",
            partner=ANY_TRADE_PARTNER,
            all_other_players=self.all_other,
        )

    def rerun(self, *, user_edits: dict | None = None, pending: dict | None = None) -> dict:
        if pending:
            queue_pending_builder_update(self.session, SCOPE, pending)
        if user_edits:
            if "partner" in user_edits:
                self.session[self.keys["partner"]] = user_edits["partner"]
            if "give" in user_edits:
                self.session[self.keys["give"]] = list(user_edits["give"])
            if "receive" in user_edits:
                self.session[self.keys["receive"]] = list(user_edits["receive"])

        self.logical, schema_migrated = maybe_migrate_builder_schema(self.session, SCOPE, self.logical)
        pool = self._receive_pool()
        self.logical, pending_update = apply_pending_to_logical_state(
            self.session,
            SCOPE,
            self.logical,
            my_players=self.my_players,
            receive_options=pool,
            other_teams=self.other_teams,
        )
        scope_changed, _ = scope_fingerprint_changed(self.session, SCOPE, FINGERPRINT)
        force = bool(pending_update) or scope_changed or schema_migrated
        force_reason = "pending_update" if pending_update else ("scope_change" if scope_changed or schema_migrated else "none")
        diag = prepare_builder_widget_state(
            self.session,
            SCOPE,
            self.logical,
            my_players=self.my_players,
            receive_options=pool,
            partner_options=[ANY_TRADE_PARTNER, *self.other_teams],
            force=force,
            force_reason=force_reason,
        )
        give = list(self.session.get(self.keys["give"]) or [])
        receive = list(self.session.get(self.keys["receive"]) or [])
        partner = str(self.session.get(self.keys["partner"]) or ANY_TRADE_PARTNER)
        self.logical = save_logical_state_from_widgets(
            self.logical,
            give_players=give,
            receive_players=receive,
            trade_partner=partner,
            other_team=partner if partner != ANY_TRADE_PARTNER else "",
        )
        return diag


class LiveStyleRerunTests(unittest.TestCase):
    def test_stale_team3_state_then_user_changes_partner(self) -> None:
        sim = BuilderRerunSimulator()
        sim.session[sim.keys["partner"]] = "Team 3"
        sim.session[sim.keys["give"]] = []
        sim.session[sim.keys["receive"]] = ["Gunnar Henderson"]
        sim.logical = {
            "give_players": ["José Ramírez"],
            "get_players": ["Gunnar Henderson"],
            "trade_partner": "Team 3",
        }
        diag = sim.rerun(user_edits={"partner": ANY_TRADE_PARTNER})
        self.assertEqual(sim.session[sim.keys["partner"]], ANY_TRADE_PARTNER)
        self.assertEqual(diag["force_reason"], "none")

        diag2 = sim.rerun()
        self.assertEqual(sim.session[sim.keys["partner"]], ANY_TRADE_PARTNER)
        self.assertEqual(diag2["force_reason"], "none")

    def test_use_this_idea_populates_then_editable(self) -> None:
        sim = BuilderRerunSimulator()
        diag = sim.rerun(
            pending={
                "action": "use",
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "trade_partner": "Team 3",
            }
        )
        self.assertEqual(diag["force_reason"], "pending_update")
        self.assertEqual(sim.session[sim.keys["give"]], ["José Ramírez"])
        self.assertEqual(sim.session[sim.keys["receive"]], ["Gunnar Henderson"])

        diag2 = sim.rerun(user_edits={"give": ["Mookie Betts"], "partner": ANY_TRADE_PARTNER})
        self.assertEqual(diag2["force_reason"], "none")
        self.assertEqual(sim.session[sim.keys["give"]], ["Mookie Betts"])
        self.assertEqual(sim.session[sim.keys["partner"]], ANY_TRADE_PARTNER)

    def test_analyze_action_forces_once(self) -> None:
        sim = BuilderRerunSimulator()
        diag = sim.rerun(
            pending={
                "action": "analyze",
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "trade_partner": "Team 3",
                "auto_analyze": True,
            }
        )
        self.assertEqual(diag["force_reason"], "pending_update")
        self.assertEqual(sim.session[sim.keys["give"]], ["José Ramírez"])
        self.assertEqual(sim.session[sim.keys["receive"]], ["Gunnar Henderson"])
        diag2 = sim.rerun()
        self.assertEqual(diag2["force_reason"], "none")

    def test_propose_action_queues_confirmation_not_send(self) -> None:
        sim = BuilderRerunSimulator()
        sim.rerun(
            pending={
                "action": "propose",
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "trade_partner": "Team 3",
                "await_proposal_confirm": True,
            }
        )
        confirm = sim.session.get(proposal_confirm_key(SCOPE))
        self.assertIsInstance(confirm, dict)
        self.assertEqual(confirm.get("give_players"), ["José Ramírez"])

    def test_schema_migration_clears_stale_team3_widgets_once(self) -> None:
        sim = BuilderRerunSimulator()
        sim.session[sim.keys["partner"]] = "Team 3"
        sim.session[sim.keys["receive"]] = ["Gunnar Henderson"]
        sim.session[builder_schema_key(SCOPE)] = 1
        diag = sim.rerun()
        self.assertEqual(sim.session[builder_schema_key(SCOPE)], TRADE_BUILDER_STATE_SCHEMA_VERSION)
        self.assertEqual(sim.session.get(sim.keys["partner"]), ANY_TRADE_PARTNER)
        self.assertEqual(sim.session.get(sim.keys["receive"]), [])
        self.assertIn(diag["force_reason"], ("scope_change", "missing_widget"))

        diag2 = sim.rerun()
        self.assertEqual(diag2["force_reason"], "none")

    def test_incoming_offer_analyze_offer_action(self) -> None:
        sim = BuilderRerunSimulator()
        sim.rerun(
            pending={
                "action": "analyze_offer",
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "trade_partner": "Team 3",
                "source_offer_id": "offer-1",
                "auto_analyze": True,
            }
        )
        self.assertEqual(sim.session[sim.keys["give"]], ["José Ramírez"])
        self.assertEqual(sim.session[sim.keys["receive"]], ["Gunnar Henderson"])
        self.assertEqual(sim.logical.get("source_offer_id"), "offer-1")


if __name__ == "__main__":
    unittest.main()
