"""Regression tests for Draft Lab QA fixes (Oct 2026).

Issue 2: Missing projected statistics for Team B (all zeros).
Issue 3: Contradictory strengths and weaknesses (same cats in both lists).
Issue 4: Recommendation cards ignoring filled roster slots in 2-position draft.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


class TestProjectionBackfill(unittest.TestCase):
    """Issue 2: Board rows missing projection stats should be backfilled from pool."""

    def _make_pool(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Alice", "Primary Position": "1B",
                 "proj_HR": 30.0, "proj_RBI": 100.0, "proj_R": 90.0, "proj_SB": 5.0,
                 "proj_BA": 0.280, "proj_OPS": 0.820, "proj_AB": 550.0,
                 "Expected Fantasy Value": 0.75, "Decision Score": 0.80},
                {"playerID": "p2", "fullName": "Bob", "Primary Position": "C",
                 "proj_HR": 20.0, "proj_RBI": 65.0, "proj_R": 55.0, "proj_SB": 2.0,
                 "proj_BA": 0.250, "proj_OPS": 0.740, "proj_AB": 450.0,
                 "Expected Fantasy Value": 0.60, "Decision Score": 0.65},
                {"playerID": "p3", "fullName": "Carol", "Primary Position": "OF",
                 "proj_HR": 25.0, "proj_RBI": 80.0, "proj_R": 85.0, "proj_SB": 15.0,
                 "proj_BA": 0.270, "proj_OPS": 0.790, "proj_AB": 520.0,
                 "Expected Fantasy Value": 0.70, "Decision Score": 0.72},
                {"playerID": "p4", "fullName": "Dave", "Primary Position": "SS",
                 "proj_HR": 15.0, "proj_RBI": 60.0, "proj_R": 70.0, "proj_SB": 20.0,
                 "proj_BA": 0.265, "proj_OPS": 0.760, "proj_AB": 500.0,
                 "Expected Fantasy Value": 0.65, "Decision Score": 0.68},
            ]
        )

    def _make_board_with_missing_projections(self) -> pd.DataFrame:
        """Team A has projections, Team B doesn't (simulates auto-pick without pool data)."""
        return pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Alice", "Primary Position": "1B",
                 "Fantasy Team": "Team A", "Pick": 1,
                 "proj_HR": 30.0, "proj_RBI": 100.0, "proj_R": 90.0, "proj_SB": 5.0,
                 "proj_BA": 0.280, "proj_OPS": 0.820, "proj_AB": 550.0,
                 "Expected Fantasy Value": 0.75},
                {"playerID": "p3", "fullName": "Carol", "Primary Position": "OF",
                 "Fantasy Team": "Team A", "Pick": 4,
                 "proj_HR": 25.0, "proj_RBI": 80.0, "proj_R": 85.0, "proj_SB": 15.0,
                 "proj_BA": 0.270, "proj_OPS": 0.790, "proj_AB": 520.0,
                 "Expected Fantasy Value": 0.70},
                {"playerID": "p2", "fullName": "Bob", "Primary Position": "C",
                 "Fantasy Team": "Team B", "Pick": 2},
                {"playerID": "p4", "fullName": "Dave", "Primary Position": "SS",
                 "Fantasy Team": "Team B", "Pick": 3},
            ]
        )

    def test_backfill_fills_missing_projections_from_pool(self):
        from draft_lab_analysis import _backfill_projection_stats_from_pool

        board = self._make_board_with_missing_projections()
        pool = self._make_pool()
        result = _backfill_projection_stats_from_pool(board, pool)

        bob = result[result["fullName"] == "Bob"].iloc[0]
        self.assertAlmostEqual(float(bob["proj_HR"]), 20.0)
        self.assertAlmostEqual(float(bob["proj_RBI"]), 65.0)
        self.assertAlmostEqual(float(bob["proj_BA"]), 0.250)
        self.assertAlmostEqual(float(bob["proj_OPS"]), 0.740)

        dave = result[result["fullName"] == "Dave"].iloc[0]
        self.assertAlmostEqual(float(dave["proj_HR"]), 15.0)
        self.assertAlmostEqual(float(dave["proj_SB"]), 20.0)

    def test_backfill_does_not_overwrite_existing_projections(self):
        from draft_lab_analysis import _backfill_projection_stats_from_pool

        board = self._make_board_with_missing_projections()
        pool = self._make_pool()
        result = _backfill_projection_stats_from_pool(board, pool)

        alice = result[result["fullName"] == "Alice"].iloc[0]
        self.assertAlmostEqual(float(alice["proj_HR"]), 30.0)

    def test_analysis_produces_nonzero_stats_for_all_teams(self):
        from draft_lab_analysis import analyze_draft_lab_results, _backfill_projection_stats_from_pool

        board = self._make_board_with_missing_projections()
        pool = self._make_pool()
        board = _backfill_projection_stats_from_pool(board, pool)

        team_summary, strengths, _, _, _ = analyze_draft_lab_results(
            board, pd.DataFrame(), context={"config": {}, "teams": ["Team A", "Team B"]}
        )
        team_b = team_summary[team_summary["Fantasy Team"] == "Team B"].iloc[0]
        self.assertGreater(float(team_b["Projected HR"]), 0)
        self.assertGreater(float(team_b["Projected RBI"]), 0)
        self.assertTrue(pd.notna(team_b["Projected AVG"]))
        self.assertGreater(float(team_b["Projected AVG"]), 0)


class TestStrengthsWeaknesses(unittest.TestCase):
    """Issue 3: Same category must not appear in both strengths and weaknesses."""

    def _make_board_with_projections(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Alice", "Primary Position": "1B",
                 "Fantasy Team": "Team A", "Pick": 1,
                 "proj_HR": 35.0, "proj_RBI": 110.0, "proj_R": 95.0, "proj_SB": 5.0,
                 "proj_BA": 0.290, "proj_OPS": 0.850, "proj_AB": 550.0,
                 "Expected Fantasy Value": 0.80},
                {"playerID": "p2", "fullName": "Bob", "Primary Position": "C",
                 "Fantasy Team": "Team A", "Pick": 4,
                 "proj_HR": 25.0, "proj_RBI": 75.0, "proj_R": 60.0, "proj_SB": 3.0,
                 "proj_BA": 0.260, "proj_OPS": 0.780, "proj_AB": 450.0,
                 "Expected Fantasy Value": 0.65},
                {"playerID": "p3", "fullName": "Carol", "Primary Position": "OF",
                 "Fantasy Team": "Team B", "Pick": 2,
                 "proj_HR": 15.0, "proj_RBI": 55.0, "proj_R": 80.0, "proj_SB": 25.0,
                 "proj_BA": 0.275, "proj_OPS": 0.760, "proj_AB": 520.0,
                 "Expected Fantasy Value": 0.60},
                {"playerID": "p4", "fullName": "Dave", "Primary Position": "SS",
                 "Fantasy Team": "Team B", "Pick": 3,
                 "proj_HR": 10.0, "proj_RBI": 45.0, "proj_R": 70.0, "proj_SB": 30.0,
                 "proj_BA": 0.265, "proj_OPS": 0.720, "proj_AB": 500.0,
                 "Expected Fantasy Value": 0.55},
            ]
        )

    def test_no_overlap_between_strengths_and_weaknesses(self):
        from draft_lab_analysis import analyze_draft_lab_results

        board = self._make_board_with_projections()
        _, strengths, _, _, _ = analyze_draft_lab_results(
            board, pd.DataFrame(), context={"config": {}, "teams": ["Team A", "Team B"]}
        )
        for _, row in strengths.iterrows():
            s = set(str(row["Team Strengths"]).split(", "))
            w = set(str(row["Team Weaknesses"]).split(", "))
            overlap = s & w - {"Insufficient projections", "None identified"}
            self.assertEqual(
                overlap, set(),
                f"{row['Fantasy Team']}: strengths={s}, weaknesses={w} overlap={overlap}",
            )

    def test_zero_projection_team_gets_insufficient_label(self):
        from draft_lab_analysis import analyze_draft_lab_results

        board = pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "Alice", "Primary Position": "1B",
                 "Fantasy Team": "Team A", "Pick": 1,
                 "proj_HR": 30.0, "proj_RBI": 100.0, "proj_R": 90.0, "proj_SB": 5.0,
                 "proj_BA": 0.280, "proj_OPS": 0.820, "proj_AB": 550.0,
                 "Expected Fantasy Value": 0.75},
                {"playerID": "p2", "fullName": "Bob", "Primary Position": "C",
                 "Fantasy Team": "Team B", "Pick": 2,
                 "Expected Fantasy Value": 0.60},
            ]
        )
        _, strengths, _, _, _ = analyze_draft_lab_results(
            board, pd.DataFrame(), context={"config": {}, "teams": ["Team A", "Team B"]}
        )
        team_b_row = strengths[strengths["Fantasy Team"] == "Team B"].iloc[0]
        self.assertEqual(team_b_row["Team Strengths"], "Insufficient projections")
        self.assertEqual(team_b_row["Team Weaknesses"], "Insufficient projections")


class TestRecommendationSlotFiltering(unittest.TestCase):
    """Issue 4: Recs must respect filled roster slots in 2-position draft."""

    def _make_pool(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"playerID": "p1", "fullName": "1B Player 1", "Primary Position": "1B",
                 "proj_HR": 30.0, "Expected Fantasy Value": 0.80},
                {"playerID": "p2", "fullName": "1B Player 2", "Primary Position": "1B",
                 "proj_HR": 28.0, "Expected Fantasy Value": 0.75},
                {"playerID": "p3", "fullName": "C Player 1", "Primary Position": "C",
                 "proj_HR": 20.0, "Expected Fantasy Value": 0.65},
                {"playerID": "p4", "fullName": "C Player 2", "Primary Position": "C",
                 "proj_HR": 18.0, "Expected Fantasy Value": 0.60},
                {"playerID": "p5", "fullName": "1B/C Dual", "Primary Position": "1B",
                 "Eligible Positions": "1B,C",
                 "proj_HR": 22.0, "Expected Fantasy Value": 0.68},
            ]
        )

    def test_slot_assignment_with_1b_filled_leaves_c_gap(self):
        from live_draft_roster_slots import assign_roster_to_slot_instances

        roster = pd.DataFrame(
            [{"playerID": "p1", "fullName": "1B Player 1", "Primary Position": "1B"}]
        )
        config = {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 0, "OF": 0, "DH": 0, "P": 0, "BN": 0}}
        result = assign_roster_to_slot_instances(roster, config)
        gaps = result["gaps"]
        self.assertEqual(gaps, ["C"])
        self.assertEqual(result["filled"], 1)

    def test_remaining_position_needs_with_1b_filled(self):
        from live_draft_roster_slots import get_remaining_position_needs

        roster = pd.DataFrame(
            [{"playerID": "p1", "fullName": "1B Player 1", "Primary Position": "1B"}]
        )
        config = {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 0, "OF": 0, "DH": 0, "P": 0, "BN": 0}}
        needs = get_remaining_position_needs(roster, config)
        self.assertEqual(needs, ["C"])

    def test_normalize_position_needs_keeps_c(self):
        from draft_needs import normalize_position_needs_for_scoring

        result = normalize_position_needs_for_scoring(["C"])
        self.assertEqual(result, ["C"])

    def test_team_open_positions_filter_excludes_1b_only_players(self):
        from live_draft_roster_slots import filter_candidates_to_team_open_positions

        pool = self._make_pool()
        roster = pd.DataFrame(
            [{"playerID": "p1", "fullName": "1B Player 1", "Primary Position": "1B"}]
        )
        config = {"slots": {"C": 1, "1B": 1, "2B": 0, "3B": 0, "SS": 0, "OF": 0, "DH": 0, "P": 0, "BN": 0}}
        available = pool[pool["playerID"] != "p1"].copy()
        filtered = filter_candidates_to_team_open_positions(available, roster, config=config)

        names = set(filtered["fullName"].tolist())
        self.assertIn("C Player 1", names)
        self.assertIn("C Player 2", names)
        self.assertIn("1B/C Dual", names, "Dual-eligible 1B/C should pass C filter")
        self.assertNotIn("1B Player 2", names, "1B-only should be excluded when 1B is filled")

    def test_dual_eligible_player_passes_c_filter(self):
        from live_draft_roster_slots import _player_position_tokens, _eligible_for_open_need_recommendation

        row = pd.Series({"Primary Position": "1B", "Eligible Positions": "1B,C"})
        tokens = _player_position_tokens(row)
        self.assertIn("C", tokens, f"Dual-eligible should have C in tokens: {tokens}")
        self.assertTrue(_eligible_for_open_need_recommendation(tokens, "C"))


class TestProjectionSettingsHandoff(unittest.TestCase):
    """Issue 1: Projection settings should persist through the handoff chain."""

    def test_handoff_extracts_projection_settings(self):
        from draft_lab_handoff import extract_live_room_lab_settings

        room = {
            "config": {
                "projection_window": 5,
                "projection_style": "Conservative",
                "scoring_type": "5x5 Roto",
            },
            "teams": ["Team A", "Team B"],
        }
        extracted = extract_live_room_lab_settings(room)
        self.assertEqual(extracted["draft_lab_window"], 5)
        self.assertEqual(extracted["draft_lab_projection_style"], "Conservative")

    def test_canonical_settings_roundtrip(self):
        from shared_draft_context import read_canonical_draft_settings, write_canonical_draft_settings

        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            source_page="Live Draft Room",
            reason="test",
        )
        cur = read_canonical_draft_settings(session)
        self.assertEqual(cur["lookback_window"], 5)
        self.assertEqual(cur["projection_style"], "Conservative")

    def test_alias_mirrors_after_write(self):
        from shared_draft_context import write_canonical_draft_settings

        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            source_page="test",
            reason="test",
        )
        self.assertEqual(session.get("draft_lab_window"), 5)
        self.assertEqual(session.get("live_draft_proj_window"), 5)
        self.assertEqual(session.get("draft_lab_projection_style"), "Conservative")
        self.assertEqual(session.get("live_draft_proj_style"), "Conservative")

    def test_handoff_propagates_to_canonical_blob(self):
        from draft_lab_handoff import apply_live_draft_handoff_to_session
        from shared_draft_context import CANONICAL_SETTINGS_KEY, read_canonical_draft_settings

        session: dict = {}
        room = {
            "config": {
                "projection_window": 5,
                "projection_style": "Conservative",
                "scoring_type": "5x5 Roto",
                "num_teams": 2,
                "picks_per_team": 2,
            },
            "teams": ["Team A", "Team B"],
            "draft_board": [],
        }
        apply_live_draft_handoff_to_session(session, room)
        self.assertIn(CANONICAL_SETTINGS_KEY, session, "Handoff must write the canonical blob")
        cur = read_canonical_draft_settings(session)
        self.assertEqual(cur["lookback_window"], 5)
        self.assertEqual(cur["projection_style"], "Conservative")


class TestHistoricalProjectionSnapshot(unittest.TestCase):
    """Issue 1 completion: completed drafts preserve the projection settings used."""

    def test_sync_saves_projection_settings_snapshot(self):
        from draft_lab_state import DRAFT_LAB_PERSISTED_STATE_KEY, sync_draft_lab_results_state
        from shared_draft_context import write_canonical_draft_settings

        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            projection_style="Conservative",
            fantasy_format="Points League",
            source_page="test",
            reason="test",
        )
        session["draft_lab_results"] = {
            "draft": pd.DataFrame([{"playerID": "p1", "Fantasy Team": "A"}]),
            "team_summary": pd.DataFrame(),
            "strengths": pd.DataFrame(),
            "pick_analysis": pd.DataFrame(),
            "gaps": pd.DataFrame(),
            "actual_summary": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "analysis_context": {},
            "handoff": {},
            "source": "test",
        }
        sync_draft_lab_results_state(session)
        blob = session[DRAFT_LAB_PERSISTED_STATE_KEY]
        snap = blob.get("projection_settings_snapshot")
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap["lookback_window"], 5)
        self.assertEqual(snap["projection_style"], "Conservative")
        self.assertEqual(snap["fantasy_format"], "Points League")

    def test_hydrate_restores_historical_settings_to_canonical(self):
        from draft_lab_state import DRAFT_LAB_PERSISTED_STATE_KEY, hydrate_draft_lab_results_state
        from shared_draft_context import read_canonical_draft_settings, write_canonical_draft_settings

        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=3,
            projection_style="Balanced",
            source_page="test",
            reason="test_current",
        )
        self.assertEqual(read_canonical_draft_settings(session)["lookback_window"], 3)

        session[DRAFT_LAB_PERSISTED_STATE_KEY] = {
            "schema_version": 2,
            "draft_records": [{"playerID": "p1", "Fantasy Team": "A"}],
            "projection_settings_snapshot": {
                "lookback_window": 5,
                "projection_style": "Conservative",
                "fantasy_format": "Points League",
            },
            "widget_settings": {},
        }
        session.pop("draft_lab_results", None)
        hydrate_draft_lab_results_state(session)
        cur = read_canonical_draft_settings(session)
        self.assertEqual(cur["lookback_window"], 5, "Historical snapshot must override current settings")
        self.assertEqual(cur["projection_style"], "Conservative")

    def test_hydrate_without_snapshot_preserves_current_settings(self):
        from draft_lab_state import DRAFT_LAB_PERSISTED_STATE_KEY, hydrate_draft_lab_results_state
        from shared_draft_context import read_canonical_draft_settings, write_canonical_draft_settings

        session: dict = {}
        write_canonical_draft_settings(
            session,
            lookback_window=3,
            projection_style="Balanced",
            source_page="test",
            reason="test",
        )
        session[DRAFT_LAB_PERSISTED_STATE_KEY] = {
            "schema_version": 2,
            "draft_records": [{"playerID": "p1", "Fantasy Team": "A"}],
            "widget_settings": {},
        }
        session.pop("draft_lab_results", None)
        hydrate_draft_lab_results_state(session)
        cur = read_canonical_draft_settings(session)
        self.assertEqual(cur["lookback_window"], 3, "No snapshot — current settings stay")


class TestRecommendationCacheInvalidation(unittest.TestCase):
    """Issue 4 supplement: rec cache is invalidated after a pick so recs rescore with updated roster."""

    def test_cache_marked_stale_after_pick(self):
        from live_draft_ui_cache import REC_CACHE_KEY, patch_live_draft_caches_after_pick

        room = {
            "draft_room_id": "test",
            "current_pick_index": 1,
            "draft_board": [{"playerID": "p1", "fullName": "1B Player", "Primary Position": "1B"}],
            "config": {"slots": {"C": 1, "1B": 1}},
            "teams": ["Team A"],
            "rosters": {"Team A": [{"playerID": "p1", "fullName": "1B Player", "Primary Position": "1B"}]},
        }
        session: dict = {
            REC_CACHE_KEY: {
                "key": ("old",),
                "top_rec": pd.DataFrame([
                    {"playerID": "p2", "fullName": "1B Only", "Primary Position": "1B"},
                    {"playerID": "p3", "fullName": "C Player", "Primary Position": "C"},
                ]),
            }
        }
        patch_live_draft_caches_after_pick(
            session, room, player_id="p1", player_name="1B Player"
        )
        entry = session.get(REC_CACHE_KEY)
        self.assertIsInstance(entry, dict)
        self.assertTrue(entry.get("eligibility_pending"), "Cache must be marked eligibility_pending for rescore")

    def test_eligibility_pending_cache_not_current(self):
        from live_draft_rec_live_paint import _rec_cache_entry_current
        from live_draft_ui_cache import REC_CACHE_KEY

        room = {
            "draft_room_id": "test",
            "current_pick_index": 1,
            "draft_board": [{"playerID": "p1"}],
            "config": {},
            "teams": ["Team A"],
        }
        session = {
            REC_CACHE_KEY: {
                "key": ("any",),
                "top_rec": pd.DataFrame([{"playerID": "p2"}]),
                "eligibility_pending": True,
            }
        }
        self.assertFalse(
            _rec_cache_entry_current(session, room),
            "eligibility_pending entry must not be considered current"
        )


if __name__ == "__main__":
    unittest.main()
