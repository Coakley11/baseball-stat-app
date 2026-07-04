"""Tests for deferred league context activation and waiver wire."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_league_context import (
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    activate_league_context,
    apply_pending_league_context_activation,
    context_id_for_archive,
    create_league_context_from_live_room,
    get_active_league_context,
    save_simulator_league_context,
    schedule_active_context_resync,
    schedule_league_context_activation,
)
from fantasy_waiver_wire import (
    TRADE_MODE_ADD,
    TRADE_MODE_DROP,
    add_pending_move,
    add_pending_move_pair,
    analyze_current_team_needs,
    analyze_team_needs,
    build_category_standings_table,
    build_waiver_pool,
    build_weakness_narrative,
    compute_add_drop_category_impact,
    get_pending_add_targets,
    get_pending_move_pairs,
    recommend_adds_current,
    record_league_activity,
    recommend_adds,
    rostered_player_names,
)


def _live_room() -> dict:
    return {
        "config": {"league_name": "Home", "fantasy_format": "5x5 Roto"},
        "rosters": {
            "Daniel": [{"fullName": "Aaron Judge", "Primary Position": "OF"}],
            "Rivals": [{"fullName": "Juan Soto", "Primary Position": "OF"}],
        },
        "draft_board": [
            {"Fantasy Team": "Daniel", "fullName": "Aaron Judge", "Pick": 1},
            {"Fantasy Team": "Rivals", "fullName": "Juan Soto", "Pick": 2},
        ],
    }


class DeferredActivationTests(unittest.TestCase):
    def test_schedule_does_not_set_room_your_team_until_apply(self) -> None:
        session: dict = {"room_your_team": "Old Team"}
        create_league_context_from_live_room(
            session,
            _live_room(),
            my_team_name="Daniel",
            league_context_id="live:defer01",
        )
        schedule_league_context_activation(session, "live:defer01")
        self.assertEqual(session.get("room_your_team"), "Old Team")
        self.assertEqual(session[PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY], "live:defer01")
        self.assertTrue(apply_pending_league_context_activation(session))
        self.assertEqual(session.get("room_your_team"), "Daniel")
        self.assertNotIn(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, session)

    def test_save_simulator_deferred_activation(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        entry, context = save_simulator_league_context(
            session,
            board,
            my_team_name="Daniel",
            defer_activation=True,
        )
        self.assertIn(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, session)
        self.assertIsNone(get_active_league_context(session))
        from fantasy_league_context import apply_pending_league_context_activation

        apply_pending_league_context_activation(session)
        active = get_active_league_context(session)
        assert active is not None
        self.assertEqual(active["league_context_id"], context["league_context_id"])
        self.assertEqual(session.get("room_your_team"), "Daniel")

    def test_schedule_active_context_resync(self) -> None:
        session: dict = {}
        create_league_context_from_live_room(
            session,
            _live_room(),
            my_team_name="Daniel",
            league_context_id="live:defer01",
        )
        activate_league_context(session, "live:defer01")
        session["room_your_team"] = "Stale"
        self.assertTrue(schedule_active_context_resync(session))
        apply_pending_league_context_activation(session)
        self.assertEqual(session.get("room_your_team"), "Daniel")


class WaiverWireTests(unittest.TestCase):
    def test_waiver_pool_excludes_rostered_players(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        _, context = save_simulator_league_context(session, board, my_team_name="Daniel")
        pool = pd.DataFrame(
            [
                {"Player": "Aaron Judge", "proj_HR": 45},
                {"Player": "Juan Soto", "proj_HR": 35},
                {"Player": "Mike Trout", "proj_HR": 40},
            ]
        )
        waiver = build_waiver_pool(pool, context)
        names = set(waiver["Player"].astype(str))
        self.assertIn("Mike Trout", names)
        self.assertNotIn("Aaron Judge", names)
        self.assertNotIn("Juan Soto", names)

    def test_pending_add_and_league_activity_drop(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        self.assertTrue(add_pending_move(session, TRADE_MODE_ADD, "Mike Trout"))
        adds = get_pending_add_targets(session)
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0]["player_name"], "Mike Trout")

        context = get_active_league_context(session)
        assert context is not None
        record_league_activity(session, team_name="Rivals", action="drop", player_name="Juan Soto")
        context = get_active_league_context(session)
        assert context is not None
        self.assertNotIn("juan soto", rostered_player_names(context))

    def test_recommend_adds_returns_explanations(self) -> None:
        pool = pd.DataFrame(
            [
                {"Player": "Mike Trout", "proj_HR": 40, "proj_RBI": 90, "proj_OPS": 1.0},
                {"Player": "Pete Alonso", "proj_HR": 35, "proj_RBI": 100, "proj_OPS": 0.9},
            ]
        )
        needs = {"targets": ["HR", "RBI"], "weaknesses": ["HR"]}
        rec = recommend_adds(pool, needs, limit=2)
        self.assertFalse(rec.empty)
        self.assertIn("Why Add", rec.columns)


class CurrentStatsWaiverTests(unittest.TestCase):
    def test_analyze_current_team_needs_uses_hr_not_proj(self) -> None:
        league = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Judge", "HR": 20, "RBI": 50, "R": 40, "SB": 5, "BA": 0.290},
                {"Team": "Rivals", "Player": "Soto", "HR": 30, "RBI": 70, "R": 55, "SB": 8, "BA": 0.310},
            ]
        )
        my_team = league[league["Team"] == "Daniel"]
        needs = analyze_current_team_needs(my_team, league)
        self.assertIn("HR", needs["category_ranks"])
        self.assertIn("HR", needs["weaknesses"])

    def test_recommend_adds_current_prefers_power_for_hr_need(self) -> None:
        pool = pd.DataFrame(
            [
                {"Player": "Mike Trout", "HR": 25, "RBI": 60, "BA": 0.285},
                {"Player": "Fast Guy", "HR": 3, "RBI": 20, "SB": 30, "BA": 0.260},
            ]
        )
        needs = {"targets": ["HR", "RBI"], "weaknesses": ["HR"]}
        rec = recommend_adds_current(pool, needs, limit=1)
        self.assertEqual(str(rec.iloc[0]["Player"]), "Mike Trout")

    def test_pending_move_pair_requires_add_and_drop(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        self.assertFalse(add_pending_move_pair(session, add_player="Mike Trout", drop_player=""))
        self.assertTrue(add_pending_move_pair(session, add_player="Mike Trout", drop_player="Aaron Judge"))
        pairs = get_pending_move_pairs(session)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["add_player"], "Mike Trout")
        self.assertEqual(pairs[0]["drop_player"], "Aaron Judge")

    def test_category_impact_positive_for_hr_upgrade(self) -> None:
        add_row = pd.Series({"HR": 25, "RBI": 70})
        drop_row = pd.Series({"HR": 10, "RBI": 40})
        impact = compute_add_drop_category_impact(add_row, drop_row, categories=["HR", "RBI"])
        self.assertIn("+HR", impact)
        self.assertIn("+RBI", impact)

    def test_weakness_narrative_mentions_rank(self) -> None:
        needs = {
            "category_ranks": {"HR": 5, "RBI": 6, "SB": 2},
            "weaknesses": ["HR", "RBI"],
            "strengths": ["SB"],
            "targets": ["HR"],
            "n_teams": 8,
        }
        lines = build_weakness_narrative(needs)
        self.assertTrue(any("HR" in line for line in lines))

    def test_category_standings_table_builds(self) -> None:
        needs = {"category_ranks": {"HR": 3, "RBI": 5}, "strengths": ["HR"], "weaknesses": ["RBI"], "n_teams": 6}
        table = build_category_standings_table(needs)
        self.assertEqual(len(table), 2)


class WaiverFilterPersistenceTests(unittest.TestCase):
    def test_waiver_filter_in_workflow_disk_roundtrip(self) -> None:
        from unittest.mock import MagicMock

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        st = MagicMock()
        st.session_state = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "page_filter_state": {},
            "use_active_league_context_waiver_filter": True,
        }
        blob = build_baseball_disk_state(st)
        self.assertTrue(blob.get("use_active_league_context_waiver_filter"))

        st2 = MagicMock()
        st2.session_state = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "page_filter_state": {},
        }
        apply_baseball_disk_state(st2, blob)
        self.assertTrue(st2.session_state.get("use_active_league_context_waiver_filter"))


if __name__ == "__main__":
    unittest.main()
