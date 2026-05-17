"""Unit tests for draft pick before/after simulation helpers."""

import unittest

import pandas as pd

from draft_simulation import build_draft_pick_simulation


class TestDraftPickSimulation(unittest.TestCase):
    def test_adds_player_and_shows_category_delta(self):
        draft_room = pd.DataFrame(
            [
                {"Pick": 1, "Team": "Daniel", "Player": "Aaron Judge"},
                {"Pick": 2, "Team": "Other", "Player": "Mookie Betts"},
                {"Pick": 3, "Team": "Daniel", "Player": ""},
            ]
        )
        projections = pd.DataFrame(
            [
                {
                    "fullName": "Aaron Judge",
                    "proj_HR": 40,
                    "proj_RBI": 100,
                    "proj_R": 95,
                    "proj_SB": 6,
                    "proj_BA": 0.275,
                    "Expected Fantasy Value": 0.90,
                },
                {
                    "fullName": "Juan Soto",
                    "proj_HR": 37,
                    "proj_RBI": 105,
                    "proj_R": 110,
                    "proj_SB": 12,
                    "proj_BA": 0.290,
                    "Expected Fantasy Value": 0.95,
                },
            ]
        )

        report = build_draft_pick_simulation(draft_room, "Juan Soto", "Daniel", projections)

        self.assertIn("Juan Soto", report["after_roster"]["Player"].tolist())
        hr = report["category_table"][report["category_table"]["Category"] == "HR"].iloc[0]
        self.assertEqual(hr["Before"], 40)
        self.assertEqual(hr["After"], 77)
        self.assertEqual(hr["Change"], 37)
        value = report["value_table"][report["value_table"]["Value Metric"] == "Expected Fantasy Value"].iloc[0]
        self.assertAlmostEqual(value["Before"], 0.90)
        self.assertAlmostEqual(value["After"], 1.85)
        self.assertAlmostEqual(value["Change"], 0.95)
        self.assertIn("projected team impact", report["status"])

    def test_already_drafted_elsewhere_does_not_add_player(self):
        draft_room = pd.DataFrame(
            [
                {"Pick": 1, "Team": "Daniel", "Player": "Aaron Judge"},
                {"Pick": 2, "Team": "Other", "Player": "Juan Soto"},
            ]
        )
        projections = pd.DataFrame(
            [
                {"fullName": "Aaron Judge", "proj_HR": 40},
                {"fullName": "Juan Soto", "proj_HR": 37},
            ]
        )

        report = build_draft_pick_simulation(draft_room, "Juan Soto", "Daniel", projections)

        self.assertNotIn("Juan Soto", report["after_roster"]["Player"].tolist())
        self.assertTrue(report["already_elsewhere"])
        self.assertIn("already drafted by another team", report["status"])


if __name__ == "__main__":
    unittest.main()
