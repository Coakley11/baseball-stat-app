"""Guided Draft Strategy planning (2026-10-29): needs, depth, explained targets, backups.

Synthetic scored pool + a simulator board for the active team. The plan must exclude drafted
and queued players, respect the position filter, and only ever suggest (never queue).
"""

from __future__ import annotations

import unittest

import pandas as pd

import draft_room_state as drs
import draft_strategy_plan as plan

POOL = pd.DataFrame([
    {"fullName": "Aaron Judge", "Primary Position": "OF", "Decision Score": 0.95, "ADP": 2, "proj_HR": 45, "proj_SB": 6},
    {"fullName": "Shohei Ohtani", "Primary Position": "DH", "Decision Score": 0.94, "ADP": 1, "proj_HR": 44, "proj_SB": 20},
    {"fullName": "Bobby Witt", "Primary Position": "SS", "Decision Score": 0.93, "ADP": 3, "proj_HR": 28, "proj_SB": 35},
    {"fullName": "Juan Soto", "Primary Position": "OF", "Decision Score": 0.90, "ADP": 5, "proj_HR": 36, "proj_SB": 8},
    {"fullName": "Adley Rutschman", "Primary Position": "C", "Decision Score": 0.70, "ADP": 60, "proj_HR": 20, "proj_SB": 2},
    {"fullName": "Kyle Tucker", "Primary Position": "OF", "Decision Score": 0.85, "ADP": 9, "proj_HR": 30, "proj_SB": 20},
    {"fullName": "Mookie Betts", "Primary Position": "SS", "Decision Score": 0.84, "ADP": 12, "proj_HR": 25, "proj_SB": 14},
])


def _session(picks: dict[int, str], queue: list[str] | None = None) -> dict:
    board = drs.build_snake_board(["Daniel", "Team 2"], rounds=4)
    for pick, name in picks.items():
        board.loc[board["Pick"] == pick, "Player"] = name
    return {
        drs.DRAFT_ROOM_TABLE_KEY: board,
        "room_your_team": "Daniel",
        "room_format": "5x5 Roto",
        "use_simulator_board_as_fantasy_context": True,
        "draft_queue": list(queue or []),
    }


class PlanTests(unittest.TestCase):
    def test_profile_and_available_pool_exclude_every_drafted_player(self) -> None:
        session = _session({1: "Aaron Judge", 2: "Shohei Ohtani"})
        profile = plan.team_profile(session, POOL)
        self.assertEqual(profile["team"], "Daniel")
        self.assertIn("Aaron Judge", profile["drafted"])
        self.assertIn("Shohei Ohtani", profile["drafted"])  # drafted by the other team: still unavailable
        names = plan.available_pool(session, POOL, profile)["fullName"].tolist()
        self.assertNotIn("Aaron Judge", names)
        self.assertNotIn("Shohei Ohtani", names)
        self.assertEqual(names[0], "Bobby Witt")  # best remaining by Decision Score

    def test_targets_skip_queued_players_respect_the_filter_and_explain_themselves(self) -> None:
        session = _session({1: "Aaron Judge"}, queue=["Bobby Witt"])
        profile = plan.team_profile(session, POOL)
        available = plan.available_pool(session, POOL, profile)
        targets = plan.recommended_targets(session, available, profile, queue=["Bobby Witt"])
        names = [t["name"] for t in targets]
        self.assertNotIn("Bobby Witt", names)
        self.assertNotIn("Aaron Judge", names)
        self.assertTrue(all(t["reason"] for t in targets))
        ofs = plan.recommended_targets(session, available, profile, queue=[], position="OF")
        self.assertEqual({t["position"] for t in ofs}, {"OF"})
        self.assertEqual(session["draft_queue"], ["Bobby Witt"])  # suggestions never touch the queue

    def test_cards_never_repeat_the_same_reason(self) -> None:
        sluggers = pd.DataFrame([
            {"fullName": f"Slugger {i}", "Primary Position": "OF", "Decision Score": 0.9 - i / 100, "ADP": 10 + i,
             "proj_HR": 40 - i, "proj_RBI": 100 - i, "proj_R": 90 - i, "proj_SB": 5 + i}
            for i in range(6)
        ])
        session = _session({})
        profile = plan.team_profile(session, sluggers)
        available = plan.available_pool(session, sluggers, profile)
        reasons = [t["reason"] for t in plan.recommended_targets(session, available, profile, queue=[], limit=6)]
        templates = [plan._template(r) for r in reasons]
        self.assertEqual(len(templates), len(set(templates)), reasons)
        self.assertTrue(all(reasons), reasons)

    def test_depth_and_backups(self) -> None:
        session = _session({1: "Aaron Judge"})
        profile = plan.team_profile(session, POOL)
        available = plan.available_pool(session, POOL, profile)
        depth = {d["position"]: d for d in plan.positional_depth(available)}
        self.assertEqual(depth["OF"]["startable_left"], 2)
        self.assertEqual(depth["OF"]["best_available"], "Juan Soto")
        self.assertEqual(depth["1B"]["startable_left"], 0)
        backups = plan.backups_for_queue(available, ["Juan Soto", "Bobby Witt"])
        self.assertEqual(backups["Juan Soto"], ["Kyle Tucker"])
        self.assertEqual(backups["Bobby Witt"], ["Mookie Betts"])

    def test_a_real_roster_frame_gives_roster_and_category_profile(self) -> None:
        from unittest import mock

        import active_team_context as atc

        roster = POOL[POOL["fullName"].isin(["Aaron Judge", "Juan Soto"])].reset_index(drop=True)
        ctx = atc.ActiveTeamContext(source="simulator", active_team="Daniel", fantasy_format="5x5 Roto",
                                    drafted_names=["Aaron Judge", "Juan Soto"], my_roster_df=roster)
        with mock.patch("active_team_context.resolve_active_team_context", return_value=ctx):
            profile = plan.team_profile({}, POOL)
        self.assertEqual(profile["roster"], ["Aaron Judge", "Juan Soto"])
        self.assertIn("SB", [c["label"] for c in profile["category_needs"]])   # two sluggers: speed is the gap

    def test_queue_status_flags_drafted_players(self) -> None:
        session = _session({1: "Aaron Judge"})
        profile = plan.team_profile(session, POOL)
        status = plan.queue_status(["Aaron Judge", "Juan Soto"], profile)
        self.assertEqual([s["drafted"] for s in status], [True, False])


if __name__ == "__main__":
    unittest.main()
