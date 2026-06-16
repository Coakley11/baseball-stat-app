"""Valuation / Historical Explorer / Career Explorer AMI send hooks."""

from __future__ import annotations

import unittest

from baseball_ami_pages import (
    build_career_send_diagnostics,
    build_historical_send_diagnostics,
    build_valuation_send_diagnostics,
    finalize_career_context_for_send,
    finalize_historical_context_for_send,
    finalize_valuation_context_for_send,
    promote_page_ami_context_at_send,
)


class TestFinalizeValuationContext(unittest.TestCase):
    def test_promotes_snapshot_player_and_routing(self) -> None:
        session = {
            "valuation_selected_player": "Junior Caminero",
            "_ami_valuation_snapshot": {
                "selected_player": "Junior Caminero",
                "valuation_score": 0.88,
                "top_valuation_players": [
                    {"player": "Junior Caminero", "score": 0.88},
                    {"player": "Bobby Witt Jr.", "score": 0.85},
                ],
                "draft_status": {"player": "Junior Caminero", "status": "available"},
            },
        }
        ctx: dict = {}
        finalize_valuation_context_for_send(ctx, session)

        self.assertEqual(ctx.get("player"), "Junior Caminero")
        self.assertEqual(ctx.get("routing_hint"), "valuation_analysis")
        self.assertEqual(ctx.get("intent"), "valuation_analysis")
        snap = ctx.get("valuation_snapshot") or {}
        self.assertEqual(snap.get("selected_player"), "Junior Caminero")
        self.assertEqual(len(ctx.get("players") or []), 2)
        self.assertNotIn("player_a", ctx)
        self.assertNotIn("player_b", ctx)

        diag = build_valuation_send_diagnostics(ctx)
        self.assertTrue(diag.get("valuation_snapshot_present"))
        self.assertEqual(diag.get("player"), "Junior Caminero")
        self.assertEqual(diag.get("top_players_count"), 2)

    def test_dispatch_via_promote_valuation(self) -> None:
        session = {
            "_ami_valuation_snapshot": {"selected_player": "Junior Caminero"},
        }
        ctx: dict = {}
        promote_page_ami_context_at_send(ctx, session, source_page="Valuation")
        self.assertEqual(ctx.get("routing_hint"), "valuation_analysis")
        self.assertIn("valuation_send_diagnostics", ctx)


class TestFinalizeHistoricalContext(unittest.TestCase):
    def test_promotes_snapshot_filters_and_routing(self) -> None:
        session = {
            "historical_year_range_filter": [2000, 2007],
            "historical_sort_stat_filter": "HR",
            "historical_selected_player": "Barry Bonds",
            "_ami_historical_snapshot": {
                "sort_stat": "HR",
                "year_range": "2000-2007",
                "top_players": ["Barry Bonds", "Alex Rodriguez", "Sammy Sosa"],
                "top_rows": [
                    {"player": "Barry Bonds", "HR": 73},
                    {"player": "Alex Rodriguez", "HR": 54},
                ],
            },
        }
        ctx: dict = {}
        finalize_historical_context_for_send(ctx, session)

        self.assertEqual(ctx.get("player"), "Barry Bonds")
        self.assertEqual(ctx.get("routing_hint"), "historical_analysis")
        self.assertEqual(ctx.get("intent"), "historical_analysis")
        snap = ctx.get("historical_snapshot") or {}
        self.assertEqual(len(snap.get("top_rows") or []), 2)
        players = ctx.get("players") or []
        self.assertIn("Barry Bonds", players)
        self.assertEqual(ctx.get("metrics"), ["HR"])
        self.assertNotIn("player_a", ctx)

        diag = build_historical_send_diagnostics(ctx)
        self.assertTrue(diag.get("historical_snapshot_present"))
        self.assertEqual(diag.get("top_rows_count"), 2)
        self.assertEqual(diag.get("player"), "Barry Bonds")

    def test_dispatch_via_promote_historical(self) -> None:
        session = {
            "_ami_historical_snapshot": {"sort_stat": "HR", "top_players": ["Barry Bonds"]},
        }
        ctx: dict = {}
        promote_page_ami_context_at_send(ctx, session, source_page="Historical Explorer")
        self.assertEqual(ctx.get("routing_hint"), "historical_analysis")
        self.assertIn("historical_send_diagnostics", ctx)


class TestFinalizeCareerContext(unittest.TestCase):
    def test_promotes_filters_and_routing(self) -> None:
        session = {
            "career_year_range_filter": [2010, 2024],
            "career_sort_stat_filter": "HR",
            "career_team_filter": "NYY",
            "_ami_career_snapshot": {
                "sort_stat": "HR",
                "top_players": ["Aaron Judge", "Giancarlo Stanton"],
            },
        }
        ctx: dict = {}
        finalize_career_context_for_send(ctx, session)

        self.assertEqual(ctx.get("routing_hint"), "career_analysis")
        self.assertEqual(ctx.get("intent"), "career_analysis")
        self.assertEqual(ctx.get("year_range"), "2010-2024")
        self.assertEqual(ctx.get("metrics"), ["HR"])
        self.assertEqual(ctx.get("team_filter"), "NYY")
        snap = ctx.get("career_snapshot") or {}
        self.assertIn("Aaron Judge", snap.get("top_players") or [])
        self.assertNotIn("player_a", ctx)

        diag = build_career_send_diagnostics(ctx)
        self.assertTrue(diag.get("career_snapshot_present"))
        self.assertEqual(diag.get("year_range"), "2010-2024")

    def test_dispatch_via_promote_career(self) -> None:
        session = {
            "career_sort_stat_filter": "HR",
        }
        ctx: dict = {}
        promote_page_ami_context_at_send(ctx, session, source_page="Career Totals")
        self.assertEqual(ctx.get("routing_hint"), "career_analysis")
        self.assertIn("career_send_diagnostics", ctx)


if __name__ == "__main__":
    unittest.main()
