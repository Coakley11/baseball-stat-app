"""Auto-pick must ignore the draft queue and use the configured setup rule on legal players."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from draft_state import add_player_to_draft_queue
from live_draft_autopick import live_draft_auto_pick
from live_draft_state import live_draft_get_available


def _minimal_room(*, slots: dict | None = None, rule: str = "best model rank") -> dict:
    slots = slots or {"C": 1, "OF": 0, "1B": 0, "2B": 0, "3B": 0, "SS": 0, "DH": 0, "P": 0, "BN": 0}
    pool = pd.DataFrame(
        [
            {
                "playerID": "c1",
                "fullName": "Catch One",
                "Primary Position": "C",
                "Player Grade": 0.95,
                "Decision Score": 0.5,
            },
            {
                "playerID": "of1",
                "fullName": "Outfield Star",
                "Primary Position": "OF",
                "Player Grade": 0.99,
                "Decision Score": 0.99,
            },
        ]
    )
    return {
        "status": "in_progress",
        "draft_room_id": "AUTOPICKTEST",
        "current_pick_index": 0,
        "config": {
            "slots": slots,
            "auto_pick_rule": rule,
            "queue_auto_pick": True,
            "auto_pick_from_queue": True,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


def _fake_make_pick_advance(room: dict, chosen_dict: dict, **_kwargs) -> tuple[bool, str]:
    board = list(room.get("draft_board") or [])
    board.append({"Pick": len(board) + 1, **chosen_dict})
    room["draft_board"] = board
    room["current_pick_index"] = int(room.get("current_pick_index") or 0) + 1
    pid = str(chosen_dict.get("playerID") or "")
    if pid:
        room.setdefault("drafted_player_ids", []).append(pid)
    return True, "ok"


class LiveDraftAutopickNoQueueTests(unittest.TestCase):
    def test_queued_player_not_selected_because_queued(self) -> None:
        room = _minimal_room(slots={"C": 1, "OF": 1})
        session: dict = {"draft_queue": []}
        add_player_to_draft_queue(session, "Outfield Star")
        self.assertIn("Outfield Star", session.get("draft_queue") or [])

        scored_calls: list[str] = []

        def _score(available, roster_df, rule_key, target_counts, config=None):
            scored_calls.append(str(rule_key))
            scored = available.copy()
            scored["sort_key"] = pd.to_numeric(scored.get("Player Grade", 0), errors="coerce")
            # Deliberately rank catcher above queued outfielder — queue must not override.
            scored.loc[scored["fullName"] == "Catch One", "sort_key"] = 1.0
            scored.loc[scored["fullName"] == "Outfield Star", "sort_key"] = 0.1
            return scored.sort_values("sort_key", ascending=False), []

        with patch("live_draft_autopick.score_available_for_rule", side_effect=_score):
            with patch("live_draft_autopick.live_draft_make_pick", side_effect=_fake_make_pick_advance):
                ok, _msg = live_draft_auto_pick(room, session, finalize=False)
        self.assertTrue(ok)
        self.assertTrue(scored_calls)
        picked = room["draft_board"][-1]
        name = str(picked.get("fullName") or picked.get("Player") or "")
        self.assertNotEqual(name, "Outfield Star")

    def test_only_catcher_open_ignores_queued_outfielder(self) -> None:
        room = _minimal_room(slots={"C": 1, "OF": 0, "1B": 0, "2B": 0, "3B": 0, "SS": 0, "DH": 0, "P": 0, "BN": 0})
        session: dict = {}
        add_player_to_draft_queue(session, "Outfield Star")

        with patch("live_draft_autopick.score_available_for_rule") as score_fn:
            legal = live_draft_get_available(room)
            legal = legal[legal["Primary Position"].astype(str) == "C"]
            score_fn.return_value = (legal, [])
            with patch("live_draft_autopick.live_draft_make_pick", side_effect=_fake_make_pick_advance):
                ok, _ = live_draft_auto_pick(room, session, finalize=False)
        self.assertTrue(ok)
        picked = room["draft_board"][-1]
        self.assertEqual(str(picked.get("fullName")), "Catch One")

    def test_highest_legal_catcher_by_configured_rule(self) -> None:
        room = _minimal_room(
            slots={"C": 1, "OF": 0, "1B": 0, "2B": 0, "3B": 0, "SS": 0, "DH": 0, "P": 0, "BN": 0},
            rule="best model rank",
        )
        room["pool"] = pd.DataFrame(
            [
                {"playerID": "c1", "fullName": "Catch Low", "Primary Position": "C", "Player Grade": 0.4},
                {"playerID": "c2", "fullName": "Catch High", "Primary Position": "C", "Player Grade": 0.92},
            ]
        )
        session: dict = {}

        def _score(available, roster_df, rule_key, target_counts, config=None):
            self.assertEqual(rule_key, "best model rank")
            scored = available.copy()
            scored["_rank"] = pd.to_numeric(scored["Player Grade"], errors="coerce")
            return scored.sort_values("_rank", ascending=False), []

        with patch("live_draft_autopick.score_available_for_rule", side_effect=_score):
            with patch("live_draft_autopick.live_draft_make_pick", side_effect=_fake_make_pick_advance):
                ok, _ = live_draft_auto_pick(room, session, finalize=False)
        self.assertTrue(ok)
        self.assertEqual(str(room["draft_board"][-1].get("fullName")), "Catch High")

    def test_multiple_open_slots_picks_best_legal_any_slot(self) -> None:
        room = _minimal_room(slots={"C": 1, "OF": 1})
        session: dict = {}

        def _score(available, roster_df, rule_key, target_counts, config=None):
            scored = available.copy()
            scored["_rank"] = pd.to_numeric(scored["Decision Score"], errors="coerce")
            return scored.sort_values("_rank", ascending=False), []

        with patch("live_draft_autopick.score_available_for_rule", side_effect=_score):
            with patch("live_draft_autopick.live_draft_make_pick", side_effect=_fake_make_pick_advance):
                ok, _ = live_draft_auto_pick(room, session, finalize=False)
        self.assertTrue(ok)
        self.assertEqual(str(room["draft_board"][-1].get("fullName")), "Outfield Star")

    def test_drafted_players_excluded_from_pool(self) -> None:
        room = _minimal_room()
        room["drafted_player_ids"] = ["of1"]
        room["draft_board"] = [{"Pick": 0, "playerID": "of1", "fullName": "Outfield Star"}]
        session: dict = {}

        with patch("live_draft_autopick.score_available_for_rule") as score_fn:
            def _score(available, roster_df, rule_key, target_counts, config=None):
                names = set(available["fullName"].astype(str))
                self.assertNotIn("Outfield Star", names)
                return (available, [])

            score_fn.side_effect = _score
            with patch("live_draft_autopick.live_draft_make_pick", side_effect=_fake_make_pick_advance):
                ok, _ = live_draft_auto_pick(room, session, finalize=False)
        self.assertTrue(ok)

    def test_queue_still_works_for_manual_add(self) -> None:
        session: dict = {}
        added, was_new = add_player_to_draft_queue(session, "Catch One")
        self.assertTrue(added or was_new)
        self.assertIn("Catch One", session.get("draft_queue") or [])


if __name__ == "__main__":
    unittest.main()
