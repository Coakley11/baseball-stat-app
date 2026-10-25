"""Tests for deferred league context activation and waiver wire."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

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
    WAIVER_PLANNER_ADD_KEY,
    WAIVER_PLANNER_DROP_KEY,
    add_pending_move,
    add_pending_move_pair,
    apply_waiver_move_pairs,
    analyze_current_team_needs,
    analyze_team_needs,
    build_add_recommendation_explanation,
    build_category_standings_table,
    build_waiver_pool,
    build_weakness_narrative,
    compute_add_drop_category_impact,
    compute_waiver_transaction_impact,
    filter_waiver_names_by_search,
    format_current_stat_line,
    format_league_rank_lines,
    fantasy_format_includes_pitching,
    get_pending_add_targets,
    get_pending_move_pairs,
    merge_current_season_stats,
    recommend_adds_current,
    record_league_activity,
    recommend_adds,
    recommend_adds_personalized,
    rostered_player_names,
    waiver_categories_for_context,
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

    def test_waiver_tx_flash_roundtrip(self) -> None:
        from fantasy_waiver_wire import pop_waiver_tx_flash, set_waiver_tx_flash

        session: dict = {}
        self.assertIsNone(pop_waiver_tx_flash(session))
        set_waiver_tx_flash(session, level="success", message="Added Mike Trout")
        flash = pop_waiver_tx_flash(session)
        self.assertEqual(flash, {"level": "success", "message": "Added Mike Trout"})
        self.assertIsNone(pop_waiver_tx_flash(session))

    def test_apply_waiver_move_pairs_swaps_roster(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        stats_pool = pd.DataFrame(
            [
                {"Player": "Aaron Judge", "HR": 20},
                {"Player": "Juan Soto", "HR": 18},
                {"Player": "Mike Trout", "HR": 25, "Primary Position": "OF"},
            ]
        )
        result = apply_waiver_move_pairs(
            session,
            [{"add_player": "Mike Trout", "drop_player": "Aaron Judge"}],
            stats_pool=stats_pool,
        )
        self.assertTrue(result.get("ok"))
        self.assertEqual(int(result.get("applied") or 0), 1)
        context = get_active_league_context(session)
        assert context is not None
        names = rostered_player_names(context)
        self.assertIn("Mike Trout", names)
        self.assertNotIn("Aaron Judge", names)
        self.assertIn("Juan Soto", names)
        self.assertEqual(result.get("added_players"), ["Mike Trout"])
        self.assertEqual(result.get("dropped_players"), ["Aaron Judge"])

    def test_apply_waiver_move_pairs_matches_drop_by_normalized_name(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Primary Position": "OF"},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2, "Primary Position": "OF"},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        context = get_active_league_context(session)
        assert context is not None
        my_team = str(context.get("my_team_name") or "Daniel")
        players = context["league_rosters"][my_team]["players"]
        players[0]["player_name"] = "Aaron Judge Jr."
        context["league_rosters"][my_team]["players"] = players
        from fantasy_league_context import upsert_league_context

        upsert_league_context(session, context)
        stats_pool = pd.DataFrame(
            [
                {"Player": "Aaron Judge Jr.", "HR": 20},
                {"Player": "Mike Trout", "HR": 25, "Primary Position": "OF"},
            ]
        )
        result = apply_waiver_move_pairs(
            session,
            [{"add_player": "Mike Trout", "drop_player": "Aaron Judge"}],
            stats_pool=stats_pool,
        )
        self.assertTrue(result.get("ok"))
        names = rostered_player_names(get_active_league_context(session))
        self.assertIn("Mike Trout", names)
        self.assertNotIn("Aaron Judge Jr.", names)

    def test_sync_waiver_roster_views_refreshes_cached_roster(self) -> None:
        from fantasy_waiver_wire import sync_waiver_roster_views

        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        stats_pool = pd.DataFrame(
            [
                {"Player": "Aaron Judge", "Team": "Daniel", "HR": 20},
                {"Player": "Juan Soto", "Team": "Rivals", "HR": 18},
                {"Player": "Mike Trout", "HR": 25},
            ]
        )
        apply_waiver_move_pairs(
            session,
            [{"add_player": "Mike Trout", "drop_player": "Aaron Judge"}],
            stats_pool=stats_pool,
        )
        sync_waiver_roster_views(session, stats_pool=stats_pool)
        roster_df = session.get("fantasy_current_roster_stats")
        self.assertIsInstance(roster_df, pd.DataFrame)
        assert roster_df is not None
        daniel_rows = roster_df[roster_df["Team"].astype(str) == "Daniel"]
        names = set(daniel_rows["Player"].astype(str).tolist())
        self.assertIn("Mike Trout", names)
        self.assertNotIn("Aaron Judge", names)

    def test_apply_waiver_move_pairs_rejects_more_than_two(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        pairs = [
            {"add_player": "Mike Trout", "drop_player": "Aaron Judge"},
            {"add_player": "Mookie Betts", "drop_player": "Juan Soto"},
            {"add_player": "Ronald Acuna", "drop_player": "Aaron Judge"},
        ]
        result = apply_waiver_move_pairs(session, pairs)
        self.assertFalse(result.get("ok"))
        self.assertTrue(any("2 add/drop pairs" in str(e) for e in result.get("errors") or []))

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

    def test_format_league_rank_lines(self) -> None:
        needs = {"category_ranks": {"HR": 6, "RBI": 5, "SB": 2}}
        lines = format_league_rank_lines(needs)
        self.assertTrue(any("HR" in line and "6th" in line for line in lines))
        self.assertTrue(any("RBI" in line and "5th" in line for line in lines))

    def test_merge_current_season_stats_combines_pitchers(self) -> None:
        hitters = pd.DataFrame([{"Player Key": "judge", "Player": "Aaron Judge", "HR": 20}])
        pitchers = pd.DataFrame([{"Player Key": "cole", "Player": "Gerrit Cole", "W": 5, "K": 80}])
        merged = merge_current_season_stats(hitters, pitchers)
        self.assertEqual(len(merged), 2)
        self.assertIn("W", merged.columns)

    def test_hitter_only_format_excludes_pitching(self) -> None:
        ctx = {"fantasy_format": "5x5 Roto"}
        cats = waiver_categories_for_context(ctx)
        self.assertIn("HR", cats)
        self.assertNotIn("SV", cats)
        self.assertFalse(fantasy_format_includes_pitching("5x5 Roto", ctx))

    def test_pitcher_categories_only_when_format_includes_pitching(self) -> None:
        ctx = {"fantasy_format": "9x9 Roto", "metadata": {"includes_pitching": True}}
        cats = waiver_categories_for_context(ctx)
        self.assertIn("SV", cats)
        league = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Cole", "W": 2, "SV": 0, "K": 40, "ERA": 4.50, "WHIP": 1.30},
                {"Team": "Rivals", "Player": "Ohtani", "W": 6, "SV": 0, "K": 90, "ERA": 2.80, "WHIP": 0.95},
            ]
        )
        my_team = league[league["Team"] == "Daniel"]
        needs = analyze_current_team_needs(my_team, league, categories=cats)
        self.assertIn("W", needs["category_ranks"])
        self.assertIn("W", needs["weaknesses"])

    def test_recommend_adds_current_pitching_explanation(self) -> None:
        pool = pd.DataFrame(
            [
                {"Player": "Closer Ace", "SV": 12, "K": 30, "ERA": 2.10, "WHIP": 0.90},
                {"Player": "Weak Arm", "SV": 1, "K": 10, "ERA": 5.50, "WHIP": 1.60},
            ]
        )
        needs = {
            "targets": ["SV", "K"],
            "weaknesses": ["SV"],
            "category_ranks": {"SV": 6, "K": 5},
            "n_teams": 8,
        }
        rec = recommend_adds_current(pool, needs, limit=1)
        self.assertEqual(str(rec.iloc[0]["Player"]), "Closer Ace")
        explanation = build_add_recommendation_explanation(rec.iloc[0], needs)
        self.assertIn("SV", explanation)
        self.assertIn("Improves", explanation)

    def test_add_explanation_clarifies_small_league_rank(self) -> None:
        row = pd.Series({"Player": "Nasim Nuñez", "SB": 12})
        needs = {
            "targets": ["SB"],
            "weaknesses": ["SB"],
            "category_ranks": {"SB": 2},
            "n_teams": 2,
        }
        explanation = build_add_recommendation_explanation(row, needs)
        self.assertIn("SB", explanation)
        self.assertIn("Improves", explanation)

    def test_drop_explanation_uses_player_grade_not_current_stats(self) -> None:
        from fantasy_waiver_wire import _build_drop_explanation, recommend_drops_current

        roster = pd.DataFrame(
            [
                {
                    "Player": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.92,
                    "HR": 5,
                    "proj_OPS": 1.050,
                },
                {
                    "Player": "Bench Guy",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.55,
                    "HR": 2,
                    "proj_OPS": 0.680,
                },
            ]
        )
        drops = recommend_drops_current(roster, limit=1)
        self.assertEqual(str(drops.iloc[0]["Player"]), "Bench Guy")
        why = str(drops.iloc[0]["Why Drop"])
        self.assertNotIn("Weakest current-season", why)
        self.assertNotIn("low current", why)

    def test_recommend_drops_protects_stars(self) -> None:
        from fantasy_waiver_wire import recommend_drops_current

        roster = pd.DataFrame(
            [
                {
                    "Player": "Ketel Marte",
                    "Primary Position": "2B",
                    "Expected Fantasy Value": 0.90,
                    "HR": 18,
                    "RBI": 55,
                    "proj_OPS": 0.920,
                },
                {
                    "Player": "Matt Olson",
                    "Primary Position": "1B",
                    "Expected Fantasy Value": 0.88,
                    "HR": 22,
                    "RBI": 60,
                    "proj_OPS": 0.910,
                },
                {
                    "Player": "Deep Bench",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.42,
                    "HR": 1,
                    "RBI": 4,
                    "proj_OPS": 0.620,
                    "Fantasy Edge": -4,
                },
            ]
        )
        drops = recommend_drops_current(roster, limit=3)
        drop_names = drops["Player"].astype(str).tolist()
        self.assertIn("Deep Bench", drop_names)
        self.assertNotIn("Ketel Marte", drop_names[:1])
        self.assertNotIn("Matt Olson", drop_names[:1])

    def test_compute_waiver_transaction_impact(self) -> None:
        roster = pd.DataFrame(
            [
                {"Player": "Drop Me", "Team": "Daniel", "HR": 2, "RBI": 8, "R": 10, "SB": 1, "BA": 0.220},
                {"Player": "Keep Me", "Team": "Daniel", "HR": 20, "RBI": 60, "R": 55, "SB": 7, "BA": 0.280},
            ]
        )
        pool = pd.DataFrame(
            [{"Player": "Add Me", "HR": 12, "RBI": 40, "R": 35, "SB": 15, "BA": 0.265}]
        )
        needs = {
            "category_values": {"HR": 22.0, "RBI": 68.0, "R": 65.0, "SB": 8.0, "BA": 0.250},
            "category_ranks": {"HR": 4, "RBI": 4, "R": 4, "SB": 6, "BA": 5},
            "team_totals_by_category": {
                "HR": [30.0, 28.0, 25.0, 22.0],
                "RBI": [80.0, 75.0, 70.0, 68.0],
                "R": [78.0, 72.0, 68.0, 65.0],
                "SB": [20.0, 18.0, 12.0, 8.0],
                "BA": [0.270, 0.265, 0.258, 0.250],
            },
            "available_categories": ["HR", "RBI", "R", "SB", "BA"],
        }
        impact = compute_waiver_transaction_impact(
            roster,
            ["Add Me"],
            ["Drop Me"],
            stats_pool=pool,
            needs=needs,
            categories=("HR", "RBI", "R", "SB", "BA"),
        )
        rows = impact.get("rows") or []
        self.assertTrue(rows)
        sb_row = next(row for row in rows if row["Category"] == "SB")
        self.assertIn("+", sb_row["Change"])
        self.assertIn(impact.get("biggest_gain"), {"SB", "RBI", "R", "HR"})

    def test_waiver_transaction_impact_ranks_clamped_to_league_size(self) -> None:
        roster = pd.DataFrame(
            [
                {"Player": "Drop Me", "Team": "Daniel", "HR": 2, "RBI": 8, "R": 10, "SB": 1, "BA": 0.220},
                {"Player": "Keep Me", "Team": "Daniel", "HR": 20, "RBI": 60, "R": 55, "SB": 7, "BA": 0.280},
            ]
        )
        pool = pd.DataFrame(
            [{"Player": "Add Me", "HR": 12, "RBI": 40, "R": 35, "SB": 15, "BA": 0.265}]
        )
        needs = {
            "n_teams": 2,
            "my_team_name": "Daniel",
            "team_category_totals": {
                "Daniel": {"HR": 22.0, "RBI": 68.0, "R": 65.0, "SB": 8.0, "BA": 0.250},
                "Rival": {"HR": 30.0, "RBI": 80.0, "R": 78.0, "SB": 20.0, "BA": 0.270},
            },
            "category_values": {"HR": 22.0, "RBI": 68.0, "R": 65.0, "SB": 8.0, "BA": 0.250},
            "category_ranks": {"HR": 2, "RBI": 2, "R": 2, "SB": 2, "BA": 2},
            "team_totals_by_category": {
                "HR": [30.0, 22.0],
                "RBI": [80.0, 68.0],
                "R": [78.0, 65.0],
                "SB": [20.0, 8.0],
                "BA": [0.270, 0.250],
            },
            "available_categories": ["HR", "RBI", "R", "SB", "BA"],
        }
        impact = compute_waiver_transaction_impact(
            roster,
            ["Add Me"],
            ["Drop Me"],
            stats_pool=pool,
            needs=needs,
            categories=("HR", "RBI", "R", "SB", "BA"),
        )
        for row in impact.get("rows") or []:
            for col in ("Rank Before", "Rank After"):
                val = str(row.get(col) or "").strip()
                if val and val != "—":
                    self.assertIn(val, {"1", "2"}, msg=f"{row['Category']} {col}={val}")

    def test_analyze_current_team_needs_filters_extra_teams(self) -> None:
        my_roster = pd.DataFrame(
            [{"Player": "A", "Team": "Daniel", "HR": 20, "RBI": 60, "R": 55, "SB": 7, "BA": 0.280}]
        )
        league_df = pd.DataFrame(
            [
                {"Player": "A", "Team": "Daniel", "HR": 20, "RBI": 60, "R": 55, "SB": 7, "BA": 0.280},
                {"Player": "B", "Team": "Rival", "HR": 30, "RBI": 80, "R": 78, "SB": 20, "BA": 0.270},
                {"Player": "C", "Team": "Ghost", "HR": 40, "RBI": 90, "R": 88, "SB": 25, "BA": 0.290},
            ]
        )
        from fantasy_league_context import filter_roster_stats_to_league_teams

        context = {"league_rosters": {"Daniel": {}, "Rival": {}}}
        filtered = filter_roster_stats_to_league_teams(league_df, context)
        needs = analyze_current_team_needs(my_roster, filtered)
        self.assertEqual(needs.get("n_teams"), 2)
        self.assertLessEqual(max((needs.get("category_ranks") or {}).values(), default=1), 2)

    def test_format_category_display_value(self) -> None:
        from fantasy_waiver_wire import format_category_display_value

        self.assertEqual(format_category_display_value("HR", 105.0), "105")
        self.assertEqual(format_category_display_value("AVG", 0.245), ".245")
        self.assertEqual(format_category_display_value("OPS", 0.783), ".783")

    def test_filter_waiver_names_by_search(self) -> None:
        names = ["Aaron Judge", "Juan Soto", "Mike Trout"]
        self.assertEqual(filter_waiver_names_by_search(names, "judge"), ["Aaron Judge"])
        self.assertEqual(filter_waiver_names_by_search(names, ""), names)

    def test_format_current_stat_line_includes_obp(self) -> None:
        row = pd.Series({"OBP": 0.410, "OPS": 0.950, "HR": 20, "RBI": 55, "R": 60, "SB": 5, "BA": 0.290})
        line = format_current_stat_line(row)
        self.assertIn("OBP", line)
        self.assertIn("OPS", line)
        self.assertIn("HR", line)

    def test_format_projected_stat_line_reads_proj_columns(self) -> None:
        from fantasy_waiver_wire import format_projected_stat_line

        row = pd.Series(
            {
                "proj_BA": 0.285,
                "proj_OBP": 0.380,
                "proj_OPS": 0.900,
                "proj_HR": 35,
                "proj_RBI": 90,
                "proj_R": 95,
                "proj_SB": 12,
            }
        )
        line = format_projected_stat_line(row)
        self.assertIn("AVG", line)
        self.assertIn("OBP", line)
        self.assertIn("HR", line)


class WaiverPlannerPersistenceTests(unittest.TestCase):
    def test_planner_picks_in_workflow_disk_roundtrip(self) -> None:
        from unittest.mock import MagicMock

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        st = MagicMock()
        st.session_state = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "page_filter_state": {},
            WAIVER_PLANNER_ADD_KEY: "Mike Trout",
            WAIVER_PLANNER_DROP_KEY: "Aaron Judge",
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get(WAIVER_PLANNER_ADD_KEY), "Mike Trout")
        self.assertEqual(blob.get(WAIVER_PLANNER_DROP_KEY), "Aaron Judge")

        st2 = MagicMock()
        st2.session_state = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "page_filter_state": {},
        }
        apply_baseball_disk_state(st2, blob)
        self.assertEqual(st2.session_state.get(WAIVER_PLANNER_ADD_KEY), "Mike Trout")
        self.assertEqual(st2.session_state.get(WAIVER_PLANNER_DROP_KEY), "Aaron Judge")


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


class WaiverWireUiRenderTests(unittest.TestCase):
    def _stats_pool(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"Player": "Mike Trout", "HR": 15, "RBI": 40, "R": 35, "SB": 5, "BA": 0.280},
                {"Player": "Aaron Judge", "HR": 20, "RBI": 50, "R": 40, "SB": 3, "BA": 0.290},
            ]
        )

    def _mock_st(self) -> MagicMock:
        from unittest.mock import MagicMock

        st = MagicMock()
        st.warning = MagicMock()
        st.caption = MagicMock()
        st.markdown = MagicMock()
        st.info = MagicMock()
        st.dataframe = MagicMock()
        st.expander = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.container = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
        )
        st.columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
        st.button = MagicMock(return_value=False)
        st.rerun = MagicMock()
        return st

    def test_render_with_active_context_without_roster_slots(self) -> None:
        from unittest.mock import MagicMock, patch

        from fantasy_context_ui import active_league_context_badge_text
        from fantasy_waiver_wire_ui import render_waiver_wire_page

        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2},
            ]
        )
        save_simulator_league_context(session, board, my_team_name="Daniel")
        st = self._mock_st()
        with patch("fantasy_waiver_wire_ui.recommend_adds_current", return_value=pd.DataFrame()), patch(
            "fantasy_waiver_wire_ui.recommend_drops_current", return_value=pd.DataFrame()
        ):
            render_waiver_wire_page(st, session, current_stats_pool=self._stats_pool())
        badge = active_league_context_badge_text(session)
        self.assertIn("Active", badge)

    def test_render_with_roster_slots_context(self) -> None:
        from unittest.mock import patch

        from fantasy_league_context import context_has_roster_slots
        from fantasy_waiver_wire_ui import render_waiver_wire_page

        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        _, context = save_simulator_league_context(session, board, my_team_name="Daniel")
        context["roster_settings"] = {"roster_slots": {"OF": 3, "1B": 1}}
        from fantasy_league_context import ensure_fantasy_league_context_state

        store = ensure_fantasy_league_context_state(session)
        ctx_id = str(context.get("league_context_id") or "")
        store["contexts"][ctx_id] = context
        self.assertTrue(context_has_roster_slots(context))
        st = self._mock_st()
        with patch("fantasy_waiver_wire_ui.recommend_adds_current", return_value=pd.DataFrame()), patch(
            "fantasy_waiver_wire_ui.recommend_drops_current", return_value=pd.DataFrame()
        ):
            render_waiver_wire_page(st, session, current_stats_pool=self._stats_pool())


class WaiverNeedsAndPitcherFilterTests(unittest.TestCase):
    def test_build_waiver_pool_excludes_pitchers_without_p_slots(self) -> None:
        context = {
            "league_rosters": {
                "Mine": {"players": [{"player_name": "Aaron Judge"}]},
                "Other": {"players": [{"player_name": "Juan Soto"}]},
            },
            "ownership_map": {},
            "fantasy_format": "5x5 Roto",
            "roster_settings": {"roster_slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "P": 0}},
        }
        pool = pd.DataFrame(
            [
                {"Player": "Free Catcher", "Primary Position": "C", "HR": 8},
                {"Player": "Free Pitcher", "Primary Position": "P", "W": 4, "K": 40},
            ]
        )
        waiver = build_waiver_pool(pool, context)
        names = set(waiver["Player"].astype(str))
        self.assertIn("Free Catcher", names)
        self.assertNotIn("Free Pitcher", names)

    def test_personalized_adds_prioritize_missing_positions(self) -> None:
        context = {
            "fantasy_format": "5x5 Roto",
            "roster_settings": {"roster_slots": {"C": 1, "1B": 1, "2B": 1, "SS": 1, "OF": 3, "P": 0}},
        }
        my_roster = pd.DataFrame(
            [
                {"Player": "Only OF", "Primary Position": "OF", "HR": 20, "Expected Fantasy Value": 0.80},
            ]
        )
        waiver_pool = pd.DataFrame(
            [
                {"Player": "Elite OF", "Primary Position": "OF", "HR": 30, "Expected Fantasy Value": 0.95},
                {"Player": "Weak C", "Primary Position": "C", "HR": 6, "Expected Fantasy Value": 0.45},
            ]
        )
        needs = {"targets": ["HR"], "weaknesses": ["HR"]}
        rec = recommend_adds_personalized(
            waiver_pool,
            needs,
            context=context,
            my_roster=my_roster,
            limit=1,
        )
        self.assertEqual(str(rec.iloc[0]["Player"]), "Weak C")


if __name__ == "__main__":
    unittest.main()
