"""Tests for manual pick state preservation during hydrate."""

from __future__ import annotations

import unittest

from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    mark_live_draft_local_edit,
    prepare_live_draft_state,
    room_to_persist_dict,
    should_prefer_runtime_live_room,
    LIVE_DRAFT_STATE_KEY,
)


def _room(board_size: int, *, pick_index: int | None = None) -> dict:
    board = [{"playerID": f"p{i}"} for i in range(board_size)]
    return {
        "draft_room_id": "ROOM1",
        "status": "in_progress",
        "current_pick_index": pick_index if pick_index is not None else board_size,
        "pick_order": [{"Pick": i + 1, "Team": "A"} for i in range(10)],
        "draft_board": board,
        "drafted_player_ids": [f"p{i}" for i in range(board_size)],
        "teams": ["A", "B"],
        "config": {"picks_per_team": 5},
        "pool_records": [],
        "pool_columns": [],
    }


class ManualPickHydrateTests(unittest.TestCase):
    def test_should_prefer_runtime_when_board_ahead(self) -> None:
        runtime = _room(5)
        canonical = {"draft_room_id": "ROOM1", "draft_board": [{}] * 4, "current_pick_index": 4}
        self.assertTrue(should_prefer_runtime_live_room({}, runtime, canonical))

    def test_prepare_keeps_runtime_room_when_ahead_of_canonical(self) -> None:
        session: dict = {}
        runtime = _room(5)
        stale = _room(4)
        session[LIVE_DRAFT_STATE_KEY] = room_to_persist_dict(stale)
        session[LIVE_DRAFT_ROOM_KEY] = runtime
        mark_live_draft_local_edit(session)
        restored = prepare_live_draft_state(session)
        self.assertIsNotNone(restored)
        self.assertEqual(len(restored.get("draft_board") or []), 5)
        self.assertEqual(int(restored.get("current_pick_index") or 0), 5)


if __name__ == "__main__":
    unittest.main()
