"""Trade Center builder rerun simulations — widget precedence and edit persistence."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_trade_analysis import analysis_matches_selection, build_trade_analysis_package
from fantasy_trade_builder_state import (
    ANY_TRADE_PARTNER,
    apply_pending_to_logical_state,
    builder_widget_keys,
    prepare_builder_widget_state,
    prune_invalid_receive_for_partner,
    queue_pending_builder_update,
    receive_options_for_partner,
    save_logical_state_from_widgets,
    scope_fingerprint_changed,
)
from fantasy_trade_player_index import format_player_option_label, format_player_stat_line, format_position_label
from fantasy_trade_proposals import proposer_view, recipient_view

SCOPE = "trade_center_state|daniel|league:test"
FINGERPRINT = "daniel|league:test"


def _rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Team": "Daniel",
                "Player": "José Ramírez",
                "Primary Position": "3B",
                "HR": 18,
                "RBI": 57,
                "R": 52,
                "SB": 15,
                "BA": 0.284,
                "PA": 310,
            },
            {
                "Team": "Daniel",
                "Player": "Mookie Betts",
                "Primary Position": "SS,OF",
                "HR": 20,
                "RBI": 50,
                "R": 58,
                "SB": 10,
                "BA": 0.290,
                "PA": 320,
            },
            {
                "Team": "Team 2",
                "Player": "Aaron Judge",
                "Primary Position": "OF",
                "HR": 31,
                "RBI": 72,
                "R": 68,
                "SB": 4,
                "BA": 0.291,
                "PA": 330,
            },
            {
                "Team": "Team 3",
                "Player": "Gunnar Henderson",
                "Primary Position": "SS,3B",
                "HR": 22,
                "RBI": 58,
                "R": 61,
                "SB": 11,
                "BA": 0.279,
                "PA": 315,
            },
            {
                "Team": "Team 3",
                "Player": "Bobby Witt Jr.",
                "Primary Position": "SS",
                "HR": 15,
                "RBI": 45,
                "R": 55,
                "SB": 20,
                "BA": 0.285,
                "PA": 300,
            },
        ]
    )


def _simulate_rerun(
    session: dict,
    *,
    logical: dict,
    my_players: list[str],
    all_other: list[str],
    other_teams: list[str],
    force: bool = False,
    roster_stats: pd.DataFrame | None = None,
) -> dict:
    roster_stats = roster_stats if roster_stats is not None else _rosters()
    receive_pool = receive_options_for_partner(
        roster_stats,
        my_team="Daniel",
        partner=ANY_TRADE_PARTNER,
        all_other_players=all_other,
    )
    logical, pending = apply_pending_to_logical_state(
        session,
        SCOPE,
        logical,
        my_players=my_players,
        receive_options=receive_pool,
        other_teams=other_teams,
    )
    scope_fingerprint_changed(session, SCOPE, FINGERPRINT)
    prepare_builder_widget_state(
        session,
        SCOPE,
        logical,
        my_players=my_players,
        receive_options=receive_pool,
        partner_options=[ANY_TRADE_PARTNER, *other_teams],
        force=force or bool(pending),
        force_reason="pending_update" if pending else "none",
    )
    return logical


class TradeBuilderRerunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session: dict = {}
        self.keys = builder_widget_keys(SCOPE)
        self.my_players = ["José Ramírez", "Mookie Betts"]
        self.all_other = ["Aaron Judge", "Gunnar Henderson", "Bobby Witt Jr."]
        self.other_teams = ["Team 2", "Team 3"]

    def test_partner_any_team_persists_after_idea_load(self) -> None:
        queue_pending_builder_update(
            self.session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "other_team": "Team 3",
            },
        )
        logical = _simulate_rerun(
            self.session,
            logical={},
            my_players=self.my_players,
            all_other=self.all_other,
            other_teams=self.other_teams,
            force=True,
        )
        self.assertEqual(self.session[self.keys["partner"]], "Team 3")

        self.session[self.keys["partner"]] = ANY_TRADE_PARTNER
        prepare_builder_widget_state(
            self.session,
            SCOPE,
            logical,
            my_players=self.my_players,
            receive_options=self.all_other,
            partner_options=[ANY_TRADE_PARTNER, *self.other_teams],
            force=False,
        )
        self.assertEqual(self.session[self.keys["partner"]], ANY_TRADE_PARTNER)

    def test_receive_player_change_persists_after_rerun(self) -> None:
        queue_pending_builder_update(
            self.session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "other_team": "Team 3",
            },
        )
        logical = _simulate_rerun(
            self.session,
            logical={},
            my_players=self.my_players,
            all_other=self.all_other,
            other_teams=self.other_teams,
            force=True,
        )
        self.session[self.keys["receive"]] = ["Bobby Witt Jr."]
        prepare_builder_widget_state(
            self.session,
            SCOPE,
            logical,
            my_players=self.my_players,
            receive_options=self.all_other,
            partner_options=[ANY_TRADE_PARTNER, *self.other_teams],
            force=False,
        )
        self.assertEqual(self.session[self.keys["receive"]], ["Bobby Witt Jr."])

    def test_give_player_change_persists_after_rerun(self) -> None:
        queue_pending_builder_update(
            self.session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "other_team": "Team 3",
            },
        )
        logical = _simulate_rerun(
            self.session,
            logical={},
            my_players=self.my_players,
            all_other=self.all_other,
            other_teams=self.other_teams,
            force=True,
        )
        self.session[self.keys["give"]] = ["Mookie Betts"]
        prepare_builder_widget_state(
            self.session,
            SCOPE,
            logical,
            my_players=self.my_players,
            receive_options=self.all_other,
            partner_options=[ANY_TRADE_PARTNER, *self.other_teams],
            force=False,
        )
        self.assertEqual(self.session[self.keys["give"]], ["Mookie Betts"])

    def test_use_this_idea_loads_then_remains_editable(self) -> None:
        queue_pending_builder_update(
            self.session,
            SCOPE,
            {
                "give_players": ["José Ramírez"],
                "get_players": ["Gunnar Henderson"],
                "other_team": "Team 3",
                "auto_analyze": False,
            },
        )
        logical = _simulate_rerun(
            self.session,
            logical={},
            my_players=self.my_players,
            all_other=self.all_other,
            other_teams=self.other_teams,
            force=True,
        )
        self.assertEqual(self.session[self.keys["give"]], ["José Ramírez"])
        self.assertEqual(self.session[self.keys["receive"]], ["Gunnar Henderson"])

        self.session[self.keys["give"]] = ["Mookie Betts"]
        self.session[self.keys["receive"]] = ["Bobby Witt Jr."]
        self.session[self.keys["partner"]] = ANY_TRADE_PARTNER
        prepare_builder_widget_state(
            self.session,
            SCOPE,
            logical,
            my_players=self.my_players,
            receive_options=self.all_other,
            partner_options=[ANY_TRADE_PARTNER, *self.other_teams],
            force=False,
        )
        self.assertEqual(self.session[self.keys["give"]], ["Mookie Betts"])
        self.assertEqual(self.session[self.keys["receive"]], ["Bobby Witt Jr."])
        self.assertEqual(self.session[self.keys["partner"]], ANY_TRADE_PARTNER)

    def test_partner_change_prunes_only_invalid_receive(self) -> None:
        rosters = _rosters()
        self.session[self.keys["partner"]] = "Team 3"
        self.session[self.keys["receive"]] = ["Gunnar Henderson", "Aaron Judge"]
        team3_opts = receive_options_for_partner(
            rosters,
            my_team="Daniel",
            partner="Team 3",
            all_other_players=self.all_other,
        )
        messages = prune_invalid_receive_for_partner(
            self.session,
            SCOPE,
            receive_options=team3_opts,
            roster_stats=rosters,
            my_team="Daniel",
            partner="Team 3",
        )
        self.assertEqual(self.session[self.keys["receive"]], ["Gunnar Henderson"])
        self.assertTrue(any("Aaron Judge" in msg for msg in messages))

    def test_any_team_includes_all_opposing_rosters(self) -> None:
        rosters = _rosters()
        opts = receive_options_for_partner(
            rosters,
            my_team="Daniel",
            partner=ANY_TRADE_PARTNER,
            all_other_players=self.all_other,
        )
        self.assertEqual(set(opts), set(self.all_other))

    def test_positions_appear_in_labels(self) -> None:
        rosters = _rosters()
        self.assertIn("3B", format_position_label(rosters, "José Ramírez"))
        self.assertIn("SS", format_position_label(rosters, "Mookie Betts"))
        label = format_player_option_label(rosters, "Gunnar Henderson", owner="Team 3", include_owner=True)
        self.assertIn("Gunnar Henderson", label)
        self.assertIn("Team 3", label)

    def test_stats_line_uses_unavailable_not_zero(self) -> None:
        rosters = _rosters()
        line = format_player_stat_line(rosters, "José Ramírez")
        self.assertIn("HR 18", line)
        empty = pd.DataFrame([{"Team": "Daniel", "Player": "Ghost"}])
        self.assertIn("Stats unavailable", format_player_stat_line(empty, "Ghost"))

    def test_analysis_persists_for_same_selection(self) -> None:
        rosters = _rosters()

        def _eval(give, receive, *args, **kwargs):
            df = pd.DataFrame(
                [
                    {"Category": "HR", "Give Away": 18, "Receive": 22, "Net Gain": 4},
                    {"Category": "R", "Give Away": 52, "Receive": 61, "Net Gain": 9},
                ]
            )
            return df, "Fair", 0.5

        package = build_trade_analysis_package(
            give_players=["José Ramírez"],
            receive_players=["Gunnar Henderson"],
            roster_stats=rosters,
            standings=None,
            my_team="Daniel",
            evaluate_trade_fn=_eval,
            build_trade_verdict_text_fn=lambda *_a, **_k: "Fair value trade.",
        )
        self.assertTrue(
            analysis_matches_selection(
                package,
                give=["José Ramírez"],
                receive=["Gunnar Henderson"],
            )
        )
        self.assertIn("Analysis:", package["title"])

    def test_incoming_offer_recipient_perspective(self) -> None:
        offer = {
            "proposal_id": "p1",
            "proposer_team": "Daniel",
            "recipient_team": "Team 2",
            "proposer_gives": [{"player_name": "José Ramírez"}],
            "proposer_receives": [{"player_name": "Aaron Judge"}],
        }
        view = recipient_view(offer)
        self.assertEqual(view["give_players"], ["Aaron Judge"])
        self.assertEqual(view["receive_players"], ["José Ramírez"])
        self.assertEqual(view["other_team"], "Daniel")

    def test_incoming_offer_proposer_perspective(self) -> None:
        offer = {
            "proposal_id": "p1",
            "proposer_team": "Daniel",
            "recipient_team": "Team 2",
            "proposer_gives": [{"player_name": "José Ramírez"}],
            "proposer_receives": [{"player_name": "Aaron Judge"}],
        }
        view = proposer_view(offer)
        self.assertEqual(view["give_players"], ["José Ramírez"])
        self.assertEqual(view["receive_players"], ["Aaron Judge"])
        self.assertEqual(view["other_team"], "Team 2")

    def test_logical_state_saved_from_widgets_not_widget_keys(self) -> None:
        saved = save_logical_state_from_widgets(
            {},
            give_players=["Mookie Betts"],
            receive_players=["Gunnar Henderson"],
            trade_partner="Team 3",
            other_team="Team 3",
        )
        self.assertEqual(saved["give_players"], ["Mookie Betts"])
        self.assertEqual(saved["trade_partner"], "Team 3")
        self.assertNotIn(self.keys["give"], saved)

    def test_daniel_and_oakley_scopes_isolated(self) -> None:
        scope_d = "trade_center_state|daniel|league:a"
        scope_o = "trade_center_state|oakley|league:a"
        session: dict = {}
        keys_d = builder_widget_keys(scope_d)
        keys_o = builder_widget_keys(scope_o)
        session[keys_d["give"]] = ["José Ramírez"]
        session[keys_o["give"]] = ["Mookie Betts"]
        self.assertNotEqual(session[keys_d["give"]], session[keys_o["give"]])


if __name__ == "__main__":
    unittest.main()
