"""Waiver Wire must exclude all rostered players and respect league position slots."""

from __future__ import annotations

import unittest

import pandas as pd

from fantasy_waiver_wire import build_waiver_pool, recommend_adds_personalized


def _xy_context() -> dict:
    return {
        "context_type": "real_league",
        "league_context_id": "ctx:xy",
        "my_team_name": "Team X",
        "metadata": {"league_id": "league:xy"},
        "roster_settings": {
            "lineup_format": "custom",
            "roster_slots": {"1B": 1, "3B": 1},
            "slot_instances": [
                {"slot_code": "1B", "count": 1},
                {"slot_code": "3B", "count": 1},
            ],
        },
        "league_rosters": {
            "Team X": {
                "players": [
                    {"player_name": "Vladimir Guerrero Jr.", "player_key": "vladimir guerrero jr.", "positions": ["1B"]},
                ]
            },
            "Team Y": {
                "players": [
                    {"player_name": "José Ramírez", "player_key": "josé ramírez", "positions": ["3B"]},
                ]
            },
        },
    }


def _stats_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Player": "José Ramírez", "Primary Position": "3B", "HR": 30, "RBI": 90, "R": 80, "SB": 20, "AVG": 0.280},
            {"Player": "Jose Ramirez", "Primary Position": "3B", "HR": 30, "RBI": 90, "R": 80, "SB": 20, "AVG": 0.280},
            {"Player": "Vladimir Guerrero Jr.", "Primary Position": "1B", "HR": 28, "RBI": 85, "R": 70, "SB": 5, "AVG": 0.290},
            {"Player": "Matt Olson", "Primary Position": "1B", "HR": 35, "RBI": 100, "R": 75, "SB": 1, "AVG": 0.250},
            {"Player": "Aaron Judge", "Primary Position": "OF", "HR": 50, "RBI": 110, "R": 100, "SB": 5, "AVG": 0.300},
            {"Player": "Adley Rutschman", "Primary Position": "C", "HR": 20, "RBI": 70, "R": 60, "SB": 2, "AVG": 0.270},
            {"Player": "Nolan Arenado", "Primary Position": "3B", "HR": 25, "RBI": 80, "R": 65, "SB": 2, "AVG": 0.275},
        ]
    )


class WaiverFreeAgentPoolTests(unittest.TestCase):
    def test_build_waiver_pool_excludes_traded_player_all_teams(self) -> None:
        pool = build_waiver_pool(_stats_pool(), _xy_context())
        names = set(pool["Player"].astype(str))
        self.assertNotIn("José Ramírez", names)
        self.assertNotIn("Jose Ramirez", names)
        self.assertNotIn("Vladimir Guerrero Jr.", names)
        self.assertIn("Matt Olson", names)
        self.assertIn("Nolan Arenado", names)

    def test_personalized_adds_prioritize_league_slots_not_of_c(self) -> None:
        context = _xy_context()
        pool = build_waiver_pool(_stats_pool(), context)
        my_roster = pd.DataFrame(
            [{"Player": "Vladimir Guerrero Jr.", "Primary Position": "1B", "HR": 28, "RBI": 85, "AVG": 0.290}]
        )
        # Empty 3B: recommend corner infield before OF/C.
        adds = recommend_adds_personalized(
            pool,
            {"targets": ["HR", "RBI"]},
            context=context,
            my_roster=my_roster,
            limit=5,
        )
        self.assertFalse(adds.empty)
        top_names = [str(x) for x in adds["Player"].astype(str).tolist()]
        self.assertTrue(any(n in top_names for n in ("Nolan Arenado", "Matt Olson")))
        # OF/C-only stars should not dominate a 1B/3B-only league pool after filtering.
        self.assertNotIn("Aaron Judge", top_names)
        self.assertNotIn("Adley Rutschman", top_names)


if __name__ == "__main__":
    unittest.main()
