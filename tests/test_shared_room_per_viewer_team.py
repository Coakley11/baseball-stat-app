"""A Shared Draft room stores no single "your team" (QA 2026-11-05).

The shared room's config.your_team was whatever the last writer had (the guest, Barry), and the
host's sidebar showed "Your team: Barry". Each participant's team is their seat; the shared record
never stores one viewer's team, and each session fills it from its own seat when it loads the room.
"""

from __future__ import annotations

import unittest
from unittest import mock

from draft_room_shared_state import PER_VIEWER_CONFIG_KEYS, publish_shared_room_runtime, strip_shared_room_heavy_payload


def _document(your_team: str = "Barry") -> dict:
    return {
        "room_code": "QAROOM",
        "draft_room_id": "QAROOM",
        "revision": 4,
        "status": "in_progress",
        "participants": {},
        "room": {
            "status": "in_progress",
            "teams": ["Danny", "Barry"],
            "config": {"league_name": "QA League", "teams": ["Danny", "Barry"], "your_team": your_team,
                       "user_team": your_team, "picks_per_team": 2},
            "pick_order": [], "draft_board": [], "rosters": {"Danny": [], "Barry": []},
        },
    }


class PerViewerTeamTests(unittest.TestCase):
    def test_the_shared_record_never_keeps_a_viewer_team(self) -> None:
        out = strip_shared_room_heavy_payload(_document()["room"])
        self.assertFalse(PER_VIEWER_CONFIG_KEYS & set(out["config"]))
        self.assertEqual(out["config"]["league_name"], "QA League")  # everything else is kept
        self.assertEqual(out["config"]["teams"], ["Danny", "Barry"])

    def _publish(self, seat: str) -> dict:
        session: dict = {}
        with mock.patch("draft_room_participant_state.active_participant_team", return_value=seat):
            publish_shared_room_runtime(session, _document(your_team="Barry"), reason="test")
        return session.get("live_draft_room") or {}

    def test_each_session_sees_its_own_seat(self) -> None:
        self.assertEqual(self._publish("Danny")["config"].get("your_team"), "Danny")
        self.assertEqual(self._publish("Barry")["config"].get("your_team"), "Barry")

    def test_a_session_without_a_seat_inherits_nobody(self) -> None:
        cfg = self._publish("")["config"]
        self.assertNotIn("your_team", cfg)
        self.assertNotIn("user_team", cfg)


if __name__ == "__main__":
    unittest.main()
