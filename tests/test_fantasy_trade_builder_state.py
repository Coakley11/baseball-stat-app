"""Trade Center builder widget-state and pending-update regression tests."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from fantasy_trade_builder_state import (
    ANY_TRADE_PARTNER,
    apply_pending_to_logical_state,
    builder_widget_keys,
    clear_builder_widgets,
    migrate_legacy_builder_keys,
    pending_builder_key,
    prepare_builder_widget_state,
    queue_pending_builder_update,
    receive_options_for_partner,
)
from fantasy_trade_ideas import TRADE_CENTER_INTERNAL_TAB_KEY

REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE = "trade_center_state|daniel|league:test"


def _rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Team": "Daniel", "Player": "José Ramírez", "HR": 18, "RBI": 57, "R": 52, "SB": 15, "BA": 0.284},
            {"Team": "Team 2", "Player": "Aaron Judge", "HR": 31, "RBI": 72, "R": 68, "SB": 4, "BA": 0.291},
            {"Team": "Team 3", "Player": "Gunnar Henderson", "HR": 22, "RBI": 60, "R": 61, "SB": 8, "BA": 0.275},
        ]
    )


class FakeRerun(Exception):
    pass


class FakeStreamlit:
    def __init__(self) -> None:
        self.buttons: dict[str, bool] = {}

    def button(self, label: str, key: str, **kwargs: object) -> bool:
        return bool(self.buttons.get(key))

    def rerun(self) -> None:
        raise FakeRerun()


class TradeBuilderStateTests(unittest.TestCase):
    def test_scoped_widget_keys_are_isolated(self) -> None:
        keys_a = builder_widget_keys("trade_center_state|daniel|league:a")
        keys_b = builder_widget_keys("trade_center_state|oakley|league:a")
        self.assertNotEqual(keys_a["give"], keys_b["give"])
        self.assertNotEqual(keys_a["receive"], keys_b["receive"])
        self.assertNotEqual(keys_a["partner"], keys_b["partner"])

    def test_use_this_idea_queues_pending_without_widget_mutation(self) -> None:
        session: dict = {}
        keys = builder_widget_keys(SCOPE)
        session[keys["give"]] = []
        session[keys["receive"]] = []
        queue_pending_builder_update(
            session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Aaron Judge"],
                "other_team": "Team 2",
                "source_idea_id": "idea_0",
                "auto_analyze": False,
            },
        )
        self.assertEqual(session[keys["give"]], [])
        self.assertIn(pending_builder_key(SCOPE), session)

    def test_pending_merge_applies_after_rerun(self) -> None:
        session: dict = {}
        queue_pending_builder_update(
            session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Aaron Judge"],
                "other_team": "Team 2",
                "auto_analyze": True,
            },
        )
        rosters = _rosters()
        my_players = ["José Ramírez"]
        receive_pool = receive_options_for_partner(
            rosters,
            my_team="Daniel",
            partner=ANY_TRADE_PARTNER,
            all_other_players=["Aaron Judge", "Gunnar Henderson"],
        )
        logical, had_pending = apply_pending_to_logical_state(
            session,
            SCOPE,
            {},
            my_players=my_players,
            receive_options=receive_pool,
            other_teams=["Team 2", "Team 3"],
        )
        self.assertTrue(had_pending)
        self.assertEqual(logical["give_players"], ["José Ramírez"])
        self.assertEqual(logical["get_players"], ["Aaron Judge"])
        self.assertTrue(logical["auto_analyze"])
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=my_players,
            receive_options=receive_pool,
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3"],
            force=had_pending,
        )
        keys = builder_widget_keys(SCOPE)
        self.assertEqual(session[keys["give"]], ["José Ramírez"])
        self.assertEqual(session[keys["receive"]], ["Aaron Judge"])

    def test_clear_uses_pending_not_widget_pop(self) -> None:
        session: dict = {}
        keys = builder_widget_keys(SCOPE)
        session[keys["give"]] = ["José Ramírez"]
        session[keys["receive"]] = ["Aaron Judge"]
        queue_pending_builder_update(session, SCOPE, {"clear": True})
        logical, _ = apply_pending_to_logical_state(
            session,
            SCOPE,
            {"give_players": ["José Ramírez"], "get_players": ["Aaron Judge"]},
            my_players=["José Ramírez"],
            receive_options=["Aaron Judge"],
            other_teams=["Team 2"],
        )
        self.assertEqual(logical, {})
        self.assertNotIn(keys["give"], session)
        self.assertNotIn(keys["receive"], session)

    def test_team_partner_filters_receive_options(self) -> None:
        rosters = _rosters()
        team2_only = receive_options_for_partner(
            rosters,
            my_team="Daniel",
            partner="Team 2",
            all_other_players=["Aaron Judge", "Gunnar Henderson"],
        )
        self.assertEqual(team2_only, ["Aaron Judge"])

    def test_legacy_handoff_migrates_before_widgets(self) -> None:
        session: dict = {
            "lineup_trade_give_players": ["José Ramírez"],
            "lineup_trade_get_players": ["Aaron Judge"],
            "lineup_trade_other_team": "Team 2",
        }
        logical = migrate_legacy_builder_keys(session, SCOPE, {})
        self.assertEqual(logical["give_players"], ["José Ramírez"])
        self.assertEqual(logical["get_players"], ["Aaron Judge"])
        self.assertNotIn("lineup_trade_give_players", session)

    def test_idea_card_does_not_assign_legacy_widget_keys(self) -> None:
        source = (REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")
        idea_fn = source.split("def _render_idea_card", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_queue_idea_builder_update", idea_fn)
        self.assertNotIn('session["lineup_trade_give_players"]', idea_fn)
        self.assertNotIn("TRADE_CENTER_INTERNAL_WIDGET_KEY", idea_fn)

    def test_render_build_analyze_preserves_widget_values(self) -> None:
        source = (REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")
        fn = source.split("def _render_build_analyze", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("prepare_builder_widget_state", fn)
        self.assertIn("save_logical_state_from_widgets", fn)
        self.assertNotIn("sync_builder_widgets_from_logical", fn)
        self.assertNotIn('session[widget_keys["receive"]] = [', fn)

    def test_widgets_not_overwritten_on_ordinary_rerun(self) -> None:
        session: dict = {}
        keys = builder_widget_keys(SCOPE)
        logical = {
            "give_players": ["José Ramírez"],
            "get_players": ["Gunnar Henderson"],
            "trade_partner": "Team 3",
            "other_team": "Team 3",
        }
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=["José Ramírez", "Mookie Betts"],
            receive_options=["Gunnar Henderson", "Aaron Judge"],
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3"],
            force=True,
        )
        session[keys["partner"]] = ANY_TRADE_PARTNER
        session[keys["give"]] = ["Mookie Betts"]
        session[keys["receive"]] = ["Aaron Judge"]
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=["José Ramírez", "Mookie Betts"],
            receive_options=["Gunnar Henderson", "Aaron Judge"],
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3"],
            force=False,
        )
        self.assertEqual(session[keys["partner"]], ANY_TRADE_PARTNER)
        self.assertEqual(session[keys["give"]], ["Mookie Betts"])
        self.assertEqual(session[keys["receive"]], ["Aaron Judge"])

    def test_integration_idea_click_then_rerun_applies_selection(self) -> None:
        from fantasy_trade_center_ui import _queue_idea_builder_update

        session: dict = {}
        _queue_idea_builder_update(
            session,
            SCOPE,
            give_list=["José Ramírez"],
            receive_list=["Aaron Judge"],
            other="Team 2",
            idea_id="idea_0",
            auto_analyze=True,
        )
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Build & Analyze")
        keys = builder_widget_keys(SCOPE)
        session[keys["give"]] = []
        logical, had_pending = apply_pending_to_logical_state(
            session,
            SCOPE,
            {},
            my_players=["José Ramírez"],
            receive_options=["Aaron Judge", "Gunnar Henderson"],
            other_teams=["Team 2", "Team 3"],
        )
        prepare_builder_widget_state(
            session,
            SCOPE,
            logical,
            my_players=["José Ramírez"],
            receive_options=["Aaron Judge", "Gunnar Henderson"],
            partner_options=[ANY_TRADE_PARTNER, "Team 2", "Team 3"],
            force=had_pending,
        )
        self.assertEqual(session[keys["give"]], ["José Ramírez"])
        self.assertEqual(session[keys["receive"]], ["Aaron Judge"])

    def test_trade_center_ui_parses(self) -> None:
        ast.parse((REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
