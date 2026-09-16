"""Solo Draft human-QA pass: timer, ranks, queue sync, MLB Team, completion."""

from __future__ import annotations

import unittest

import pandas as pd


class MlbTeamStampTests(unittest.TestCase):
    def test_stamp_preserves_mlb_team_separately_from_fantasy(self) -> None:
        from live_draft_team_identity import stamp_team_id_on_pick_record

        room = {
            "teams": ["Team A"],
            "config": {"teams": ["Team A"]},
            "team_slots": [{"team_id": "t1", "display_name": "Team A"}],
        }
        pick = {
            "playerID": "p1",
            "fullName": "Vlad Guerrero Jr.",
            "Team": "TOR",
            "Primary Position": "1B",
        }
        stamp_team_id_on_pick_record(room, pick, "Team A")
        self.assertEqual(pick.get("Fantasy Team"), "Team A")
        self.assertEqual(pick.get("Team"), "Team A")
        self.assertEqual(pick.get("MLB Team"), "TOR")

    def test_rosters_df_shows_mlb_not_fantasy_under_mlb_column(self) -> None:
        from streamlit_app import live_draft_rosters_df

        room = {
            "rosters": {
                "Team A": [
                    {
                        "playerID": "p1",
                        "fullName": "Player One",
                        "Team": "Team A",
                        "MLB Team": "NYY",
                        "Primary Position": "OF",
                        "Model Rank": 10,
                        "Market Rank": 20,
                        "Fantasy Edge": 10,
                    }
                ]
            },
            "pool": pd.DataFrame(
                [
                    {
                        "playerID": "p1",
                        "Team": "NYY",
                        "Model Rank": 5,
                        "Market Rank": 20,
                        "Fantasy Edge": 15,
                        "Expected Fantasy Value": 0.8,
                    }
                ]
            ),
        }
        df = live_draft_rosters_df(room)
        self.assertFalse(df.empty)
        self.assertEqual(str(df.iloc[0]["MLB Team"]), "NYY")
        self.assertNotEqual(str(df.iloc[0]["MLB Team"]), "Team A")
        # Pool backfill prefers real Model Rank
        self.assertEqual(float(df.iloc[0]["Model Rank"]), 5.0)
        self.assertEqual(float(df.iloc[0]["Fantasy Edge"]), 15.0)


class QueueSidebarSyncTests(unittest.TestCase):
    def test_resolve_visible_queue_recovers_from_draft_state(self) -> None:
        from draft_ui import _resolve_visible_draft_queue

        session = {
            "draft_queue": [],
            "live_queue": [],
            "draft_state": {"queue": ["Vladimir Guerrero Jr."]},
        }
        names, src = _resolve_visible_draft_queue(session, qkey="live_queue")
        self.assertEqual(names, ["Vladimir Guerrero Jr."])
        self.assertIn("draft_state", src)


class QueueFitScoringTests(unittest.TestCase):
    def test_queue_fit_scores_even_when_position_not_open(self) -> None:
        from draft_ui import score_queue_player_for_on_clock_team

        pool_row = {
            "playerID": "of1",
            "fullName": "OF Star",
            "Primary Position": "OF",
            "Expected Fantasy Value": 0.8,
            "Market Rank": 5,
            "Model Rank": 8,
            "Decision Score": 0.7,
            "Draft Fit Score": 0.5,
        }
        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "teams": ["Team A"],
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
            "draft_board": [],
            "drafted_player_ids": [],
            "rosters": {
                "Team A": [
                    {"playerID": f"f{i}", "fullName": f"F{i}", "Primary Position": p}
                    for i, p in enumerate(
                        ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "SP", "SP"]
                    )
                ]
            },
            "config": {
                "slots": {
                    "C": 1,
                    "1B": 1,
                    "2B": 1,
                    "3B": 1,
                    "SS": 1,
                    "OF": 3,
                    "DH": 1,
                    "P": 2,
                    "BN": 2,
                },
                "auto_pick_rule": "balanced recommendation",
                "fantasy_format": "5x5 Roto",
            },
            "pool": pd.DataFrame([pool_row]),
        }
        # Only BN open — OF not a required gap; display scoring must still return fit.
        session = {
            "live_draft_room": room,
            "_live_draft_paint_snapshot": {
                "team_on_clock": "Team A",
                "current_pick": 1,
            },
        }
        scored = score_queue_player_for_on_clock_team(session, pool_row, room=room)
        self.assertIsNotNone(scored)
        self.assertIn("Draft Fit Score", scored or {})


class DebugCaptionTests(unittest.TestCase):
    def test_table_view_expander_removed_from_decision_panel(self) -> None:
        import inspect

        from live_draft_room_ui import render_draft_decision_panel

        src = inspect.getsource(render_draft_decision_panel)
        self.assertNotIn('expander("Table view"', src)
        self.assertNotIn("expander('Table view'", src)


class FantasyEdgeFormulaTests(unittest.TestCase):
    def test_backfill_recomputes_edge_from_pool_ranks(self) -> None:
        from live_draft_fast_solo_start import _backfill_drafted_analytics_from_pool

        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "Team": "LAD",
                    "Model Rank": 3,
                    "Market Rank": 10,
                    "Fantasy Edge": 0,
                    "Expected Fantasy Value": 0.9,
                    "Scarcity Score": 0.4,
                }
            ]
        )
        room = {
            "draft_board": [
                {
                    "playerID": "p1",
                    "fullName": "Star",
                    "Team": "Team A",
                    "Fantasy Team": "Team A",
                    "Model Rank": 10,
                    "Market Rank": 10,
                    "Fantasy Edge": 0,
                }
            ],
            "rosters": {
                "Team A": [
                    {
                        "playerID": "p1",
                        "fullName": "Star",
                        "Team": "Team A",
                        "Fantasy Team": "Team A",
                        "Model Rank": 10,
                        "Market Rank": 10,
                        "Fantasy Edge": 0,
                    }
                ]
            },
        }
        n = _backfill_drafted_analytics_from_pool(room, pool)
        self.assertGreaterEqual(n, 1)
        board = room["draft_board"][0]
        self.assertEqual(float(board["Model Rank"]), 3.0)
        self.assertEqual(float(board["Market Rank"]), 10.0)
        self.assertEqual(float(board["Fantasy Edge"]), 7.0)
        self.assertEqual(board.get("MLB Team"), "LAD")


class CompletionPendingClearTests(unittest.TestCase):
    def test_make_pick_applies_completion_on_final_pick(self) -> None:
        from live_draft_pick_engine import live_draft_make_pick

        teams = ["Team A", "Team B"]
        room = {
            "status": "in_progress",
            "draft_room_id": "FIN-1",
            "teams": teams,
            "current_pick_index": 1,
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team A"},
                {"Pick": 2, "Round": 1, "Team": "Team B"},
            ],
            "draft_board": [
                {
                    "playerID": "p0",
                    "fullName": "First",
                    "Primary Position": "OF",
                    "Team": "Team A",
                }
            ],
            "drafted_player_ids": ["p0"],
            "rosters": {"Team A": [{"playerID": "p0"}], "Team B": []},
            "config": {
                "num_teams": 2,
                "picks_per_team": 1,
                "rounds": 1,
                "slots": {"OF": 1, "BN": 0},
                "timer_seconds": 30,
            },
            "pool": pd.DataFrame(
                [{"playerID": "p1", "fullName": "Second", "Primary Position": "OF", "Team": "BOS"}]
            ),
        }
        session = {"live_draft_room": room, "_pending_manual_draft_pick": {"x": 1}}
        ok, msg = live_draft_make_pick(
            room,
            {"playerID": "p1", "fullName": "Second", "Primary Position": "OF", "Team": "BOS"},
            session=session,
            pick_source="manual",
            enrich_pick_context=False,
        )
        self.assertTrue(ok, msg)
        self.assertEqual(str(room.get("status") or ""), "complete")
        self.assertIsNone(session.get("_pending_manual_draft_pick"))
        record = room.get("live_draft_completion_record")
        self.assertIsInstance(record, dict)
        self.assertEqual(record.get("draft_status"), "complete")


class ModelRankIndependentOfMarketTests(unittest.TestCase):
    def test_blended_pool_overwrites_market_aligned_model_rank(self) -> None:
        from draft_scoring_pool import (
            POOL_KIND_VALID_PROJECTION,
            POOL_VALUE_KIND_KEY,
            ensure_draft_scoring_pool_columns_with_report,
        )

        # Fast-start residue: Model Rank copied from Market Rank.
        pool = pd.DataFrame(
            [
                {
                    "fullName": f"P{i}",
                    "playerID": f"id{i}",
                    "Primary Position": "OF",
                    "Market Rank": 10 + i,
                    "Model Rank": 10 + i,
                    "Fantasy Edge": 0,
                    "Expected Fantasy Value": 0.5,
                    "Blended Projection Score": 100.0 - i * 7.5,
                }
                for i in range(12)
            ]
        )
        pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_VALID_PROJECTION
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        self.assertEqual(report.get("model_rank_repair"), "blended_projection_rank")
        model = pd.to_numeric(out["Model Rank"], errors="coerce")
        market = pd.to_numeric(out["Market Rank"], errors="coerce")
        edge = pd.to_numeric(out["Fantasy Edge"], errors="coerce")
        differ = int((model != market).fillna(False).sum())
        self.assertGreaterEqual(differ, 8, "Model Rank must differ from Market Rank")
        self.assertTrue(bool((edge.abs() > 0).any()), "Fantasy Edge must not be mechanically zero")
        self.assertEqual(float(model.iloc[0]), 1.0)


class OpenStarterPositionFilterTests(unittest.TestCase):
    def test_ss_filled_excludes_ss_only_from_recommendations(self) -> None:
        from live_draft_roster_slots import filter_candidates_to_team_open_positions

        roster = pd.DataFrame(
            [
                {"fullName": "Filled SS", "Primary Position": "SS", "playerID": "ss1"},
            ]
        )
        pool = pd.DataFrame(
            [
                {"fullName": "SS Only Star", "Primary Position": "SS", "playerID": "ss2"},
                {"fullName": "Catcher Need", "Primary Position": "C", "playerID": "c1"},
                {"fullName": "First Base", "Primary Position": "1B", "playerID": "fb1"},
                {"fullName": "SS/2B Multi", "Primary Position": "SS", "Eligible Positions": "SS,2B", "playerID": "m1"},
            ]
        )
        cfg = {
            "slots": {
                "C": 1,
                "1B": 1,
                "2B": 1,
                "3B": 1,
                "SS": 1,
                "OF": 3,
                "DH": 1,
                "P": 2,
                "BN": 2,
            }
        }
        filtered = filter_candidates_to_team_open_positions(pool, roster, config=cfg)
        names = set(filtered["fullName"].astype(str))
        self.assertNotIn("SS Only Star", names)
        self.assertIn("Catcher Need", names)
        self.assertIn("First Base", names)
        # Multi-position SS/2B still fills open 2B.
        self.assertIn("SS/2B Multi", names)

    def test_normalize_excludes_util_while_starters_open(self) -> None:
        from draft_needs import normalize_position_needs_for_scoring

        needs = normalize_position_needs_for_scoring(["C", "1B", "UTIL", "BN"])
        self.assertEqual(needs, ["C", "1B"])
        self.assertEqual(normalize_position_needs_for_scoring(["UTIL", "DH"]), [])


class CompletionWordingTests(unittest.TestCase):
    def test_mode_aware_ended_message(self) -> None:
        from live_draft_room_ui import draft_ended_message

        self.assertEqual(draft_ended_message(solo=True), "This solo draft has ended.")
        self.assertEqual(draft_ended_message(solo=False), "This shared draft has ended.")

    def test_solo_static_timer_always_repaints(self) -> None:
        import inspect

        from live_draft_on_clock_ui import render_live_on_clock_banner

        src = inspect.getsource(render_live_on_clock_banner)
        self.assertIn("force=True", src)
        self.assertNotIn("_mark_on_clock_done()\n                    return", src.replace("\r\n", "\n"))


class QueueSidebarMirrorTests(unittest.TestCase):
    def test_queue_click_sets_sidebar_rerun_flag(self) -> None:
        from live_draft_room_ui import execute_rec_card_queue_click

        session: dict = {"draft_queue": []}
        execute_rec_card_queue_click(
            session,
            name="Test Player",
            event_id="e1",
            widget_key="k1",
            room_id="r1",
            pick_idx=0,
            player_id="p1",
        )
        self.assertIn("Test Player", session.get("draft_queue") or [])
        self.assertEqual(session.get("_live_draft_queue_sidebar_mirror"), session.get("draft_queue"))
        self.assertTrue(session.get("_live_draft_queue_sidebar_rerun"))


if __name__ == "__main__":
    unittest.main()
