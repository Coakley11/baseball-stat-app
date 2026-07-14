"""Survival Probability uses live room pick order / league size / market rank."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from live_draft_pick_scoring import enrich_player_survival_metrics
from live_draft_ux import resolve_next_pick_for_survival


class SurvivalProbabilityInputTests(unittest.TestCase):
    def _room(self) -> dict:
        teams = ["Team 1", "Team 2"]
        pick_order = []
        for rnd in range(1, 6):
            order = teams if rnd % 2 == 1 else list(reversed(teams))
            for i, team in enumerate(order):
                pick_order.append({"Round": rnd, "Pick": (rnd - 1) * 2 + i + 1, "Team": team})
        return {
            "status": "in_progress",
            "current_pick_index": 0,
            "teams": teams,
            "pick_order": pick_order,
            "draft_board": [],
            "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 60},
        }

    def test_next_pick_follows_snake_order_from_room(self) -> None:
        room = self._room()
        nxt = resolve_next_pick_for_survival(
            current_pick=1,
            next_user_pick=None,
            num_teams=2,
            room=room,
            user_team="Team 1",
        )
        # Team 1 picks 1, then again at pick 4 in a 2-team snake (1,2, then 2,1).
        self.assertEqual(nxt, 4)

    def test_survival_uses_market_rank_gap_and_league_size(self) -> None:
        room = self._room()
        scored = pd.DataFrame(
            {
                "fullName": ["Aaron Judge", "Bench Bat"],
                "Market Rank": [1.0, 180.0],
                "Position Scarcity Score": [0.2, 0.05],
                "Decision Score": [90.0, 40.0],
            }
        )
        out = enrich_player_survival_metrics(
            scored,
            current_pick=1,
            next_user_pick=None,
            num_teams=2,
            room=room,
            user_team="Team 1",
        )
        self.assertIn("Survival Probability", out.columns)
        top = float(out.loc[out["fullName"] == "Aaron Judge", "Survival Probability"].iloc[0])
        low = float(out.loc[out["fullName"] == "Bench Bat", "Survival Probability"].iloc[0])
        # Elite ADP with a short gap should outrank deep bench churn.
        self.assertGreater(top, low)
        self.assertGreaterEqual(top, 0.02)
        self.assertLessEqual(top, 0.99)
        # Stale fixed 0.5 placeholder must not be used.
        self.assertFalse(np.allclose(out["Survival Probability"], 0.5))


if __name__ == "__main__":
    unittest.main()
