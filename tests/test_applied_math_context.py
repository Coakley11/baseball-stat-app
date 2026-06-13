"""Tests for Baseball Applied Math context extractors."""

from __future__ import annotations

import unittest
from unittest import mock

from applied_math_context import (
    apply_source_state_to_session,
    build_baseball_applied_math_context,
    build_source_state,
    record_trend_intel,
)


class TestBaseballSourceState(unittest.TestCase):
    def test_build_source_state_captures_full_comparison_labels(self) -> None:
        session = {
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Aaron Judge (NYY)",
            "compare_players": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            "compare_stat": "OPS",
            "compare_year_range": [2019, 2024],
        }
        ss = build_source_state("Comparison Tool", session)
        self.assertEqual(ss["source_page"], "Comparison Tool")
        self.assertEqual(ss["entity_params"]["player_a_label"], "Juan Soto (NYY)")
        self.assertEqual(ss["widget_params"]["sig_player_a_clean"], "Juan Soto (NYY)")
        self.assertEqual(ss["filter_params"]["compare_stat"], "OPS")

    def test_apply_source_state_restores_compare_chart_controls(self) -> None:
        session: dict = {
            "compare_stat": "OPS",
            "compare_x_axis_mode": "Season",
        }
        source = build_source_state(
            "Comparison Tool",
            {
                "sig_player_a_clean": "Miguel Cabrera (DET)",
                "sig_player_b_clean": "Juan Soto (NYY)",
                "compare_players": ["Miguel Cabrera (DET)", "Juan Soto (NYY)"],
                "compare_stat": "HR",
                "compare_x_axis_mode": "Age",
                "compare_age_range": [20, 40],
            },
        )
        apply_source_state_to_session(session, source)
        self.assertEqual(session["compare_stat"], "HR")
        self.assertEqual(session["compare_stat_saved"], "HR")
        self.assertEqual(session["compare_x_axis_mode"], "Age")
        self.assertEqual(session["sig_player_a_clean"], "Miguel Cabrera (DET)")

    def test_apply_source_state_sets_canonical_comparison_keys(self) -> None:
        session: dict = {}
        source = build_source_state(
            "Comparison Tool",
            {
                "sig_player_a_clean": "Juan Soto (NYY)",
                "sig_player_b_clean": "Aaron Judge (NYY)",
                "compare_players": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            },
        )
        apply_source_state_to_session(session, source)
        self.assertEqual(session["sig_player_a_clean"], "Juan Soto (NYY)")
        self.assertEqual(session["compare_players"], ["Juan Soto (NYY)", "Aaron Judge (NYY)"])
        self.assertNotIn("pending_compare_players", session)
        self.assertEqual(session["_navigate_to_page"], "Comparison Tool")
        self.assertEqual(session["_ami_return_restore_page"], "Comparison Tool")

    def test_trend_source_state_captures_multi_player_chart(self) -> None:
        session = {
            "single_trend_dashboard_player": "Aaron Judge (NYY)",
            "trend_players_multi": ["Aaron Judge (NYY)", "Juan Soto (NYY)"],
            "trend_plot_stat": "R",
            "trend_lag": 5,
            "trend_chart_mode": "Line",
        }
        ss = build_source_state("Trend Value", session)
        self.assertEqual(len(ss["entity_params"]["trend_players_multi"]), 2)
        self.assertEqual(ss["chart_params"]["chart_snapshot"]["metric"], "R")
        restored: dict = {}
        apply_source_state_to_session(restored, ss)
        self.assertEqual(restored["trend_players_multi"], ["Aaron Judge (NYY)", "Juan Soto (NYY)"])


class TestBaseballAppliedMathContext(unittest.TestCase):
    def test_trend_page_includes_slope_delta_r2(self) -> None:
        session = {
            "single_trend_dashboard_player": "Lorenzo Cain (KC)",
            "single_trend_dashboard_stats": ["HR"],
            "trend_plot_stat": "HR",
            "_ami_trend_summary": {
                "stat": "HR",
                "player": "Lorenzo Cain",
                "latest": 15,
                "delta": 6,
                "slope": 1.2,
                "r2": 0.64,
                "summary": "upward but noisy trend",
            },
        }
        ctx = build_baseball_applied_math_context("Trend Value", session)
        ts = ctx.get("trend_summary")
        self.assertIsInstance(ts, dict)
        self.assertEqual(ts.get("slope"), 1.2)
        self.assertEqual(ts.get("r2"), 0.64)
        self.assertEqual(ts.get("delta"), 6)

    def test_comparison_includes_both_players(self) -> None:
        session = {
            "sig_player_a_clean": "Mike Piazza (NYM)",
            "sig_player_b_clean": "Jeff Bagwell (HOU)",
            "_ami_comparison_context": {"comparison_stats": ["OPS"]},
        }
        ctx = build_baseball_applied_math_context("Comparison Tool", session)
        self.assertEqual(ctx["player_a"], "Mike Piazza")
        self.assertEqual(ctx["player_b"], "Jeff Bagwell")

    def test_record_trend_intel_caches_summary(self) -> None:
        session: dict = {}
        record_trend_intel(
            session,
            player="Lorenzo Cain",
            stat="HR",
            intel_row={"Slope": 1.2, "R²": 0.64, "Net Change": 6, "Trend Direction": "Up"},
            year_start=2018,
            year_end=2022,
        )
        self.assertIn("_ami_trend_summary", session)
        self.assertEqual(session["_ami_trend_summary"]["slope"], 1.2)


    def test_draft_source_state_includes_ami_snapshot_and_trace(self) -> None:
        session = {
            "draft_queue": ["Juan Soto (NYY)", "Aaron Judge (NYY)"],
            "draft_assistant_focus_players": ["Corbin Carroll (ARI)"],
            "draft_format": "Rotisserie",
            "room_your_team": "Team Daniel",
            "room_team_count": 12,
        }
        ss = build_source_state("Draft Assistant Simulator", session)
        snap = ss["entity_params"].get("draft_snapshot")
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap.get("draft_queue"), ["Juan Soto (NYY)", "Aaron Judge (NYY)"])
        self.assertIn("scoring_settings", snap)
        trace = ss.get("ami_trace")
        self.assertIsInstance(trace, dict)
        self.assertEqual(trace.get("source_app"), "baseball")
        self.assertTrue(trace.get("source_state_has_selected_players"))
        self.assertIn("source_state_keys", trace)


    def test_draft_applied_math_context_includes_snapshot_and_guidance(self) -> None:
        session = {
            "draft_queue": ["Corbin Carroll (ARI)"],
            "_ami_draft_snapshot": {
                "current_pick": 18,
                "draft_round": 2,
                "user_roster": ["Aaron Judge", "Juan Soto"],
                "recommended_players": [
                    {"player": "Corbin Carroll"},
                    {"player": "Elly De La Cruz"},
                ],
                "sleepers": [{"player": "Junior Caminero"}],
                "scoring_settings": {"draft_format": "Rotisserie"},
            },
        }
        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        self.assertIn("draft_snapshot", ctx)
        self.assertEqual(ctx.get("current_pick"), 18)
        self.assertIn("ami_guidance", ctx)
        self.assertIn("Corbin Carroll", ctx.get("recommended_players", []))
        self.assertEqual(len(ctx.get("roster", [])), 2)

    def test_cache_draft_assistant_ami_context_populates_projection(self) -> None:
        import pandas as pd

        from applied_math_context import build_baseball_applied_math_context, cache_draft_assistant_ami_context

        session: dict = {
            "room_your_team": "Daniel",
            "room_team_count": 2,
            "room_rounds": 5,
            "room_team_names": "Daniel\nTeam 2",
            "draft_room_table": pd.DataFrame(
                [
                    {"Round": 1, "Pick": 1, "Team": "Daniel", "Player": "Aaron Judge"},
                    {"Round": 1, "Pick": 2, "Team": "Team 2", "Player": ""},
                ]
            ),
        }
        recs = pd.DataFrame(
            [
                {
                    "fullName": "Corbin Carroll",
                    "Primary Position": "OF",
                    "Model Rank": 12,
                    "Market Rank": 18,
                    "Expected Fantasy Value": 0.82,
                    "Draft Fit Score": 0.91,
                    "Reason": "Pick note: strong fit.",
                }
            ]
        )
        cache_draft_assistant_ami_context(
            session,
            page="Draft Assistant Simulator",
            recs_df=recs,
            current_pick=3,
            my_roster=["Aaron Judge"],
            drafted_total=1,
            draft_format="5x5 Roto",
            assistant_team="Daniel",
            needed_positions=["OF", "SS"],
            category_needs=["HR", "SB"],
            drafted_players=["Aaron Judge"],
            best_available_df=recs,
            position_scarcity=2.5,
        )
        proj = session.get("_ami_draft_projection")
        self.assertIsInstance(proj, dict)
        self.assertEqual(proj.get("top_pick"), "Corbin Carroll")
        self.assertEqual(proj.get("current_pick"), 3)
        self.assertEqual(proj.get("needed_positions"), ["OF", "SS"])
        self.assertIn("best_available", proj)
        ctx = build_baseball_applied_math_context("Draft Assistant Simulator", session)
        self.assertIn("draft_projection", ctx)
        self.assertEqual(ctx["draft_projection"]["top_pick"], "Corbin Carroll")
        self.assertIn("needed_positions", ctx.get("draft_snapshot", {}))
        self.assertIn("ami_guidance", ctx)

    def test_cache_fantasy_sleepers_ami_context(self) -> None:
        import pandas as pd

        from applied_math_context import (
            build_baseball_applied_math_context,
            build_source_state,
            cache_fantasy_sleepers_ami_context,
        )

        sleepers = pd.DataFrame(
            [
                {
                    "fullName": "Junior Caminero",
                    "Primary Position": "3B",
                    "Market Rank": 120,
                    "Model Rank": 45,
                    "Fantasy Edge": 75,
                    "Reason": "Model ranks him much higher than ADP.",
                }
            ]
        )
        busts = pd.DataFrame(
            [
                {
                    "fullName": "Overrated Player",
                    "Primary Position": "OF",
                    "Market Rank": 30,
                    "Model Rank": 90,
                    "Fantasy Edge": -60,
                    "Reason": "Market ahead of model.",
                }
            ]
        )
        session: dict = {
            "fantasy_market_format": "5x5 Roto",
            "sleeper_use_draft_room_needs": True,
            "sleeper_sync_team": "Daniel",
        }
        cache_fantasy_sleepers_ami_context(
            session,
            sleepers_df=sleepers,
            busts_df=busts,
            synced_roster=["Aaron Judge"],
            drafted_exclusions=["Aaron Judge", "Juan Soto"],
            needed_positions=["3B", "SS"],
            fantasy_format="5x5 Roto",
        )
        snap = session.get("_ami_sleepers_snapshot")
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap["sleeper_candidates"][0]["player"], "Junior Caminero")
        self.assertEqual(snap["drafted_exclusions"], ["Aaron Judge", "Juan Soto"])
        ss = build_source_state("Fantasy Sleepers & Busts", session)
        self.assertIn("sleepers_snapshot", ss["entity_params"])
        ctx = build_baseball_applied_math_context("Fantasy Sleepers & Busts", session)
        self.assertIn("sleepers_snapshot", ctx)
        self.assertIn("Junior Caminero", ctx.get("sleeper_candidates", []))
        self.assertIn("ami_guidance", ctx)
        self.assertIn("ami_answer_template", ctx)
        self.assertIn("ami_acceptance_questions", ctx)

    def test_cache_live_draft_ami_context(self) -> None:
        from applied_math_context import build_baseball_applied_math_context, cache_live_draft_ami_context
        import pandas as pd

        recs = pd.DataFrame(
            [{"fullName": "Elly De La Cruz", "Primary Position": "SS", "Expected Fantasy Value": 0.77}]
        )
        session: dict = {
            "live_draft_room": {
                "status": "in_progress",
                "current_pick_index": 2,
                "config": {"num_teams": 2, "your_team": "Daniel", "timer_seconds": 60},
                "teams": ["Daniel", "Team 2"],
                "pick_order": [
                    {"Round": 1, "Pick": 1, "Team": "Daniel"},
                    {"Round": 1, "Pick": 2, "Team": "Team 2"},
                    {"Round": 2, "Pick": 3, "Team": "Team 2"},
                ],
                "rosters": {"Daniel": [{"fullName": "Aaron Judge"}]},
                "draft_board": [
                    {"Round": 1, "Pick": 1, "Draft Team": "Daniel", "Player": "Aaron Judge"},
                ],
            },
            "_ami_draft_snapshot": {
                "current_pick": 2,
                "draft_round": 1,
                "user_roster": ["Aaron Judge"],
            },
        }
        with mock.patch(
            "draft_ami_helpers.gather_live_draft_ami_section",
            return_value={
                "current_pick": 2,
                "draft_round": 1,
                "my_next_pick": 3,
                "recommended_players": [{"player": "Elly De La Cruz"}],
                "available_players": [{"player": "Elly De La Cruz"}],
            },
        ):
            cache_live_draft_ami_context(
                session,
                top_rec_df=recs,
                best_avail_df=recs,
            )
        proj = session.get("_ami_draft_projection")
        self.assertIsInstance(proj, dict)
        self.assertEqual(proj.get("my_next_pick"), 3)
        ctx = build_baseball_applied_math_context("Live Draft Room", session)
        self.assertIn("draft_projection", ctx)
        self.assertIn("ami_guidance", ctx)
        self.assertIn("ami_answer_template", ctx)

    def test_cache_valuation_ami_context(self) -> None:
        import pandas as pd

        from applied_math_context import build_baseball_applied_math_context, cache_valuation_ami_context

        df = pd.DataFrame(
            [
                {"fullName": "Juan Soto", "Valuation_Score": 0.92, "Perf_Score": 80, "Trend_Score": 12},
                {"fullName": "Aaron Judge", "Valuation_Score": 0.88, "Perf_Score": 75, "Trend_Score": 10},
            ]
        )
        session: dict = {"valuation_selected_player": "Juan Soto"}
        cache_valuation_ami_context(session, valuation_df=df, selected_player="Juan Soto")
        snap = session.get("_ami_valuation_snapshot")
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap.get("selected_player"), "Juan Soto")
        self.assertEqual(len(snap.get("top_valuation_players", [])), 2)
        ctx = build_baseball_applied_math_context("Valuation", session)
        self.assertIn("valuation_snapshot", ctx)
        self.assertIn("ami_acceptance_questions", ctx)


if __name__ == "__main__":
    unittest.main()
