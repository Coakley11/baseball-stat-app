"""Canonical projection attach + completed roster schema for Live Draft."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd


class CanonicalLiveDraftPoolTests(unittest.TestCase):
    def test_collapse_identity_columns_unique(self) -> None:
        from live_draft_canonical_pool import collapse_identity_columns

        df = pd.DataFrame(
            {
                "Player": ["Juan Soto", "Aaron Judge"],
                "fullName": ["Juan Soto", "Aaron Judge"],
                "proj_HR": [40.0, 50.0],
            }
        )
        # Force duplicate Player labels the way a bad merge would.
        bad = pd.concat([df, df[["Player"]]], axis=1)
        self.assertTrue(bad.columns.duplicated().any())
        clean = collapse_identity_columns(bad)
        self.assertTrue(bool(clean.columns.is_unique))
        self.assertEqual(list(clean.columns).count("Player"), 1)
        self.assertEqual(list(clean.columns).count("fullName"), 1)
        self.assertEqual(len(clean), 2)

    def test_completed_recap_assignment_does_not_raise(self) -> None:
        from live_draft_canonical_pool import collapse_identity_columns

        roster_df = pd.DataFrame(
            [
                {
                    "Fantasy Team": "Team A",
                    "Player": "Juan Soto",
                    "fullName": "Juan Soto",
                    "MLB Team": "NYM",
                    "Team": "Team A",
                    "Primary Position": "OF",
                    "playerID": "sotoj001",
                    "proj_HR": 40.0,
                }
            ]
        )
        # Duplicate Player columns — the prior crash shape.
        roster_df = pd.concat([roster_df, roster_df[["Player"]]], axis=1)
        team_recap = roster_df[roster_df["Fantasy Team"].astype(str).eq("Team A")].copy()
        team_recap = collapse_identity_columns(team_recap)
        self.assertTrue(bool(team_recap.columns.is_unique))
        # This assignment previously raised ValueError when Player was multi-column.
        team_recap["fullName"] = team_recap["Player"]
        self.assertEqual(str(team_recap.iloc[0]["fullName"]), "Juan Soto")

    def test_team_totals_from_canonical_projections(self) -> None:
        from streamlit_app import live_draft_team_totals

        pool = pd.DataFrame(
            [
                {
                    "playerID": "a",
                    "fullName": "Player A",
                    "proj_HR": 30.0,
                    "proj_RBI": 90.0,
                    "proj_R": 80.0,
                    "proj_SB": 10.0,
                    "proj_BA": 0.280,
                    "proj_OPS": 0.850,
                    "proj_AB": 500.0,
                    "AB": 500.0,
                    "Expected Fantasy Value": 0.9,
                    "Model Rank": 5,
                    "Market Rank": 12,
                    "Blended Projection Score": 0.8,
                },
                {
                    "playerID": "b",
                    "fullName": "Player B",
                    "proj_HR": 20.0,
                    "proj_RBI": 70.0,
                    "proj_R": 60.0,
                    "proj_SB": 25.0,
                    "proj_BA": 0.260,
                    "proj_OPS": 0.780,
                    "proj_AB": 480.0,
                    "AB": 480.0,
                    "Expected Fantasy Value": 0.7,
                    "Model Rank": 20,
                    "Market Rank": 18,
                    "Blended Projection Score": 0.6,
                },
            ]
        )
        room = {
            "status": "complete",
            "teams": ["Team A"],
            "config": {"scoring_type": "5x5 Roto", "projection_style": "Balanced"},
            "pool": pool,
            "rosters": {
                "Team A": [
                    {"playerID": "a", "fullName": "Player A", "Primary Position": "OF"},
                    {"playerID": "b", "fullName": "Player B", "Primary Position": "SS"},
                ]
            },
        }
        session = {"live_draft_room": room}
        with patch(
            "live_draft_canonical_pool.attach_canonical_pool_to_room",
            return_value={"ok": True, "attached": False, "reason": "already_has_projections"},
        ):
            totals = live_draft_team_totals(room, session=session)
        self.assertFalse(totals.empty)
        row = totals.iloc[0]
        self.assertEqual(int(row["Players"]), 2)
        self.assertAlmostEqual(float(row["Projected HR"]), 50.0, places=1)
        self.assertAlmostEqual(float(row["Projected RBI"]), 160.0, places=1)
        self.assertAlmostEqual(float(row["Projected R"]), 140.0, places=1)
        self.assertAlmostEqual(float(row["Projected SB"]), 35.0, places=1)
        self.assertIsNotNone(row["Projected AVG"])
        self.assertGreater(float(row["Projected AVG"]), 0.0)
        self.assertNotEqual(str(row["Projected AVG"]).lower(), "none")

    def test_pool_has_projection_rejects_fast_market(self) -> None:
        from draft_scoring_pool import POOL_KIND_FAST_MARKET_FALLBACK, POOL_VALUE_KIND_KEY
        from live_draft_fast_solo_start import _pool_has_projection_player_grades

        df = pd.DataFrame(
            {
                "fullName": ["A"],
                "Market Rank": [1],
                "Expected Fantasy Value": [0.9],
                "proj_HR": [0.0],
                "proj_RBI": [0.0],
            }
        )
        df.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_FAST_MARKET_FALLBACK
        self.assertFalse(_pool_has_projection_player_grades(df))

    def test_team_needs_no_balanced_category(self) -> None:
        from live_draft_room_ui import render_roster_tracker_panel

        class _St:
            def __init__(self) -> None:
                self.html = ""

            def markdown(self, body, unsafe_allow_html=False):  # noqa: ANN001
                self.html += str(body)

            def caption(self, text):  # noqa: ANN001
                self.html += str(text)

        tracker = {
            "lines": [
                {"label": "SS", "position": "SS", "filled": False},
                {"label": "BN 1", "position": "BN", "filled": False},
                {"label": "BN 2", "position": "BN", "filled": False},
                {"label": "OF", "position": "OF", "filled": True},
            ],
            "filled": 1,
            "target": 4,
            "gaps": ["SS", "BN"],
            "open_positions": ["BN 1", "BN 2", "SS"],
        }
        st = _St()
        render_roster_tracker_panel(
            st,
            tracker,
            category_needs=["SB", "R", "Balanced"],
            category_levels={"SB": "Low", "R": "Moderate"},
        )
        self.assertIn("Team Needs", st.html)
        self.assertIn("Bench", st.html)
        self.assertIn("2 spots open", st.html)
        self.assertNotIn("BN 1", st.html)
        self.assertNotIn("BN 2", st.html)
        self.assertIn("SB — Low", st.html)
        self.assertIn("R — Moderate", st.html)
        self.assertNotIn("Balanced", st.html)


if __name__ == "__main__":
    unittest.main()
