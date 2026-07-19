"""Solo Draft must not complete after Pick 1 — advance through configured total."""

from __future__ import annotations

import unittest

from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
from live_draft_pick_engine import live_draft_make_pick
from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks


def _solo_room(*, total_picks: int = 4, num_teams: int = 2) -> dict:
    picks_per_team = max(1, total_picks // num_teams)
    teams = [f"Team {chr(65 + i)}" for i in range(num_teams)]
    # Truncated pick_order reproduces the production bug (length 1).
    pick_order = [{"Pick": 1, "Round": 1, "Team": teams[0]}]
    return {
        "status": "in_progress",
        "draft_room_id": "SOLO-ADVANCE-1",
        "teams": teams,
        "current_pick_index": 0,
        "pick_order": pick_order,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {t: [] for t in teams},
        "config": {
            "num_teams": num_teams,
            "picks_per_team": picks_per_team,
            "rounds": picks_per_team,
            "your_team": teams[0],
            "teams": teams,
            "timer_seconds": 30,
            "draft_setup_mode": "solo",
        },
        "pool": None,
    }


class SoloPickAdvanceTests(unittest.TestCase):
    def test_total_expected_prefers_config_over_short_pick_order(self) -> None:
        room = _solo_room(total_picks=4, num_teams=2)
        self.assertEqual(len(room["pick_order"]), 1)
        self.assertEqual(total_expected_picks(room), 4)

    def test_pick_1_does_not_complete_four_pick_draft(self) -> None:
        room = _solo_room(total_picks=4, num_teams=2)
        # Expand pick_order so current_slot / team-on-clock can advance after Pick 1.
        teams = room["teams"]
        room["pick_order"] = [
            {"Pick": i + 1, "Round": 1, "Team": teams[i % 2]} for i in range(4)
        ]
        session = {"live_draft_room": room}
        player = {
            "playerID": "p1",
            "fullName": "Player One",
            "Primary Position": "OF",
        }
        live_draft_make_pick(room, player, session=session, pick_source="manual", enrich_pick_context=False)
        self.assertEqual(len(room["draft_board"]), 1)
        self.assertEqual(int(room["current_pick_index"]), 1)
        self.assertNotEqual(str(room.get("status") or ""), "complete")
        self.assertFalse(is_draft_truly_complete(room))
        self.assertIn(str(room.get("status") or ""), ("in_progress", "paused"))
        # Fresh timer deadline for Pick 2.
        self.assertTrue(room.get("timer_deadline"))

    def test_completes_only_after_configured_total(self) -> None:
        room = _solo_room(total_picks=4, num_teams=2)
        teams = room["teams"]
        room["pick_order"] = [
            {"Pick": i + 1, "Round": 1, "Team": teams[i % 2]} for i in range(4)
        ]
        session = {"live_draft_room": room}
        for i in range(4):
            player = {
                "playerID": f"p{i+1}",
                "fullName": f"Player {i+1}",
                "Primary Position": "OF",
            }
            live_draft_make_pick(
                room, player, session=session, pick_source="manual", enrich_pick_context=False
            )
            if i < 3:
                self.assertFalse(is_draft_truly_complete(room), f"completed early at pick {i+1}")
                self.assertNotEqual(str(room.get("status") or ""), "complete")
            else:
                self.assertTrue(is_draft_truly_complete(room))
                self.assertEqual(str(room.get("status") or ""), "complete")

    def test_stale_complete_status_does_not_force_setup(self) -> None:
        room = _solo_room(total_picks=4, num_teams=2)
        room["pick_order"] = [
            {"Pick": i + 1, "Round": 1, "Team": room["teams"][i % 2]} for i in range(4)
        ]
        room["status"] = "complete"
        room["draft_board"] = [{"playerID": "p1"}]
        room["current_pick_index"] = 1
        session = {"live_draft_room": room}
        life = resolve_live_draft_lifecycle(session)
        self.assertEqual(life, LIFECYCLE_ACTIVE_DRAFT)
        self.assertEqual(str(session["live_draft_room"].get("status") or ""), "in_progress")

    def test_short_pick_order_alone_does_not_complete_after_one_pick(self) -> None:
        """Regression: pick_order length 1 must not beat config total of 4."""
        room = _solo_room(total_picks=4, num_teams=2)
        self.assertEqual(len(room["pick_order"]), 1)
        # Still need a next slot for make_pick — expand order but keep prior bug path checked via total.
        room["pick_order"] = [
            {"Pick": i + 1, "Round": 1, "Team": room["teams"][i % 2]} for i in range(1)
        ] + [
            {"Pick": i + 1, "Round": 1, "Team": room["teams"][i % 2]} for i in range(1, 4)
        ]
        session = {"live_draft_room": room}
        live_draft_make_pick(
            room,
            {"playerID": "p1", "fullName": "P1", "Primary Position": "OF"},
            session=session,
            pick_source="autopick",
            enrich_pick_context=False,
        )
        self.assertEqual(len(room["draft_board"]), 1)
        self.assertNotEqual(str(room.get("status") or ""), "complete")


if __name__ == "__main__":
    unittest.main()
