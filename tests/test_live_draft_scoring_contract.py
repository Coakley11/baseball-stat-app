"""Regression guards for Live Draft Player Grade / Decision Score product contract."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_score_display import fmt_pick_score, fmt_player_grade
from draft_scoring_pool import (
    ensure_draft_scoring_pool_columns,
    ensure_draft_scoring_pool_columns_with_report,
)
from live_draft_pick_scoring import apply_draft_pick_scoring


def _normal_slots() -> dict[str, int]:
    return {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 0, "BN": 5}


def _elite_and_fringe_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playerID": "judge",
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "Expected Fantasy Value": 0.91,
                "Model Rank": 1,
                "Market Rank": 1,
                "Fantasy Edge": 0,
                "Sleeper Score": 0.2,
                "Scarcity Score": 0.5,
                "Trend Signal": 0.1,
                "Expert Std Dev": 3.0,
                "Projection Confidence Score": 0.9,
                "proj_HR": 45,
                "proj_RBI": 110,
                "proj_R": 120,
                "proj_SB": 8,
                "proj_BA": 0.300,
                "proj_OPS": 1.050,
            },
            {
                "playerID": "soto",
                "fullName": "Juan Soto",
                "Primary Position": "OF",
                "Expected Fantasy Value": 0.84,
                "Model Rank": 2,
                "Market Rank": 2,
                "Fantasy Edge": 0,
                "Sleeper Score": 0.2,
                "Scarcity Score": 0.45,
                "Trend Signal": 0.08,
                "Expert Std Dev": 3.5,
                "Projection Confidence Score": 0.88,
                "proj_HR": 35,
                "proj_RBI": 100,
                "proj_R": 110,
                "proj_SB": 10,
                "proj_BA": 0.290,
                "proj_OPS": 0.980,
            },
            {
                "playerID": "fringe",
                "fullName": "Ben Williamson",
                "Primary Position": "3B",
                "Expected Fantasy Value": 0.12,
                "Model Rank": 350,
                "Market Rank": 400,
                "Fantasy Edge": -20,
                "Sleeper Score": 0.4,
                "Scarcity Score": 0.1,
                "Trend Signal": 0.0,
                "Expert Std Dev": 8.0,
                "Projection Confidence Score": 0.4,
                "proj_HR": 8,
                "proj_RBI": 40,
                "proj_R": 45,
                "proj_SB": 5,
                "proj_BA": 0.240,
                "proj_OPS": 0.680,
            },
        ]
    )


class LiveDraftScoringContractTests(unittest.TestCase):
    def test_player_grade_display_is_0_100(self) -> None:
        self.assertEqual(fmt_player_grade(0.91), "91")
        self.assertEqual(fmt_player_grade(0.655), "65.5")
        grade = float(fmt_player_grade(0.91))
        self.assertGreaterEqual(grade, 0.0)
        self.assertLessEqual(grade, 100.0)

    def test_decision_score_display_is_0_100_not_raw_fraction(self) -> None:
        # Product must not show 0.65 for Decision Score.
        self.assertEqual(fmt_pick_score(0.65), "65")
        self.assertNotEqual(fmt_pick_score(0.65), "0.65")
        self.assertEqual(fmt_pick_score(0.97), "97")

    def test_elite_outranks_fringe_on_empty_normal_roster(self) -> None:
        slots = _normal_slots()
        room = {"status": "in_progress", "config": {"slots": slots}, "rosters": {}}
        scored, _ = apply_draft_pick_scoring(
            _elite_and_fringe_pool(),
            pd.DataFrame(),
            target_counts=slots,
            current_pick=1,
            recommendation_mode="decision",
            room=room,
        )
        ranked = scored.sort_values("Decision Score", ascending=False).reset_index(drop=True)
        self.assertEqual(str(ranked.iloc[0]["fullName"]), "Aaron Judge")
        fringe_rank = int(
            ranked.index[ranked["fullName"] == "Ben Williamson"][0] + 1
        )
        self.assertGreater(fringe_rank, 2)
        judge_ds = float(ranked.loc[ranked["fullName"] == "Aaron Judge", "Decision Score"].iloc[0])
        fringe_ds = float(
            ranked.loc[ranked["fullName"] == "Ben Williamson", "Decision Score"].iloc[0]
        )
        self.assertGreater(judge_ds, fringe_ds)
        judge_disp = float(fmt_pick_score(judge_ds))
        self.assertGreaterEqual(judge_disp, 0.0)
        self.assertLessEqual(judge_disp, 100.0)
        # Must not surface raw 0–1 fractions as the product Decision Score.
        self.assertFalse(str(fmt_pick_score(judge_ds)).startswith("0."))

    def test_decision_score_weights_preserve_player_grade_majority(self) -> None:
        slots = _normal_slots()
        room = {"status": "in_progress", "config": {"slots": slots}, "rosters": {}}
        scored, _ = apply_draft_pick_scoring(
            _elite_and_fringe_pool(),
            pd.DataFrame(),
            target_counts=slots,
            current_pick=1,
            room=room,
        )
        judge = scored.loc[scored["fullName"] == "Aaron Judge"].iloc[0]
        self.assertAlmostEqual(float(judge["Decision Value Component"]), float(1.0 * 0.55), places=5)
        self.assertIn("Decision Rank Component", scored.columns)
        self.assertIn("Decision Roster Component", scored.columns)
        self.assertIn("Decision Scarcity Component", scored.columns)

    def test_roster_fit_responds_to_position_need(self) -> None:
        pool = _elite_and_fringe_pool()
        slots = _normal_slots()
        # Fill OF heavily so OF need drops; leave 3B open.
        roster = pd.DataFrame(
            [
                {"Primary Position": "OF", "proj_HR": 40, "proj_RBI": 100, "proj_R": 100, "proj_SB": 5, "proj_BA": 0.28, "proj_OPS": 0.9},
                {"Primary Position": "OF", "proj_HR": 30, "proj_RBI": 90, "proj_R": 90, "proj_SB": 5, "proj_BA": 0.27, "proj_OPS": 0.85},
                {"Primary Position": "OF", "proj_HR": 25, "proj_RBI": 80, "proj_R": 80, "proj_SB": 5, "proj_BA": 0.26, "proj_OPS": 0.8},
            ]
        )
        room = {"status": "in_progress", "config": {"slots": slots}, "rosters": {"You": roster}}
        scored, gaps = apply_draft_pick_scoring(
            pool,
            roster,
            target_counts=slots,
            current_pick=4,
            room=room,
        )
        self.assertIn("3B", gaps)
        self.assertNotIn("OF", gaps)
        judge_need = float(
            scored.loc[scored["fullName"] == "Aaron Judge", "Position Need Bonus"].iloc[0]
        )
        fringe_need = float(
            scored.loc[scored["fullName"] == "Ben Williamson", "Position Need Bonus"].iloc[0]
        )
        self.assertEqual(judge_need, 0.0)
        self.assertGreater(fringe_need, 0.0)
        self.assertGreater(
            float(scored.loc[scored["fullName"] == "Ben Williamson", "Positional Fit"].iloc[0]),
            float(scored.loc[scored["fullName"] == "Aaron Judge", "Positional Fit"].iloc[0]),
        )

    def test_positional_scarcity_uses_replacement_depth(self) -> None:
        slots = _normal_slots()
        room = {"status": "in_progress", "config": {"slots": slots}, "rosters": {}}
        scored, _ = apply_draft_pick_scoring(
            _elite_and_fringe_pool(),
            pd.DataFrame(),
            target_counts=slots,
            current_pick=1,
            room=room,
        )
        self.assertIn("Position Scarcity Score", scored.columns)
        judge_sc = float(
            scored.loc[scored["fullName"] == "Aaron Judge", "Position Scarcity Score"].iloc[0]
        )
        fringe_sc = float(
            scored.loc[scored["fullName"] == "Ben Williamson", "Position Scarcity Score"].iloc[0]
        )
        self.assertGreaterEqual(judge_sc, fringe_sc)

    def test_adp_count_scale_efv_cannot_drive_player_grade(self) -> None:
        """ACTIVE REGRESSION guard: ADP-count EFV must be coerced to 0–1 Player Grade."""
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 739.0,
                    "Market Rank": 1,
                    "Model Rank": 1,
                },
                {
                    "playerID": "p2",
                    "fullName": "Deep Fringe",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 1.0,
                    "Market Rank": 739,
                    "Model Rank": 739,
                },
            ]
        )
        out, report = ensure_draft_scoring_pool_columns_with_report(pool)
        efv = pd.to_numeric(out["Expected Fantasy Value"], errors="coerce")
        self.assertLessEqual(float(efv.max()), 1.0)
        self.assertGreaterEqual(float(efv.min()), 0.0)
        self.assertIn("player_grade", str(report.get("efv_repair", "")).lower())
        judge_pg = float(out.loc[out["fullName"] == "Aaron Judge", "Expected Fantasy Value"].iloc[0])
        fringe_pg = float(out.loc[out["fullName"] == "Deep Fringe", "Expected Fantasy Value"].iloc[0])
        self.assertGreater(judge_pg, fringe_pg)
        self.assertLessEqual(float(fmt_player_grade(judge_pg)), 100.0)

    def test_ensure_does_not_invent_efv_architecture_over_projection_grades(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.91,
                    "Model Rank": 3,
                    "Market Rank": 5,
                    "Fantasy Edge": 2,
                    "proj_HR": 40,
                    "Blended Projection Score": 0.91,
                }
            ]
        )
        out = ensure_draft_scoring_pool_columns(pool)
        self.assertAlmostEqual(float(out.iloc[0]["Expected Fantasy Value"]), 0.91, places=5)
        self.assertEqual(float(out.iloc[0]["Model Rank"]), 3.0)


if __name__ == "__main__":
    unittest.main()
