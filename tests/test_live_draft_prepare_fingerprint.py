"""Regression: live_draft_prepare_fingerprint must tolerate legacy/malformed config."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    live_draft_prepare_fingerprint,
    prepare_live_draft_state,
)


def _minimal_room(*, config: object) -> dict:
    return {
        "draft_room_id": "room-legacy-1",
        "status": "in_progress",
        "current_pick_index": 0,
        "draft_board": [],
        "config": config,
        "pool": pd.DataFrame(
            [{"playerID": "p1", "fullName": "Player One", "Primary Position": "OF"}]
        ),
    }


class LiveDraftPrepareFingerprintTests(unittest.TestCase):
    def test_fingerprint_normal_dict_with_slots_block(self) -> None:
        room = _minimal_room(config={"slots": {"C": 1, "OF": 3, "BN": 5}})
        fp = live_draft_prepare_fingerprint(room)
        self.assertIn(("C", 1), fp[4])
        self.assertIn(("OF", 3), fp[4])

    def test_fingerprint_flat_slot_keys(self) -> None:
        room = _minimal_room(config={"slot_c": 1, "slot_of": 3, "num_teams": 10})
        fp = live_draft_prepare_fingerprint(room)
        self.assertIn(("slot_c", 1), fp[4])
        self.assertIn(("slot_of", 3), fp[4])

    def test_fingerprint_cfg_none(self) -> None:
        room = _minimal_room(config=None)
        fp = live_draft_prepare_fingerprint(room)
        self.assertEqual(fp[4], ())

    def test_fingerprint_cfg_list_of_strings(self) -> None:
        room = _minimal_room(config=["slot_c", "slot_1b"])
        fp = live_draft_prepare_fingerprint(room)
        self.assertEqual(fp[4], (("slot_1b", 1), ("slot_c", 1)))

    def test_fingerprint_cfg_list_of_slot_instances(self) -> None:
        room = _minimal_room(
            config=[
                {"position": "C", "label": "C", "slot_index": 0},
                {"position": "OF", "label": "OF 1", "slot_index": 1},
                {"position": "OF", "label": "OF 2", "slot_index": 2},
            ]
        )
        fp = live_draft_prepare_fingerprint(room)
        self.assertIn(("C", 1), fp[4])
        self.assertIn(("OF", 2), fp[4])

    def test_fingerprint_cfg_string(self) -> None:
        room = _minimal_room(config="legacy-string-config")
        fp = live_draft_prepare_fingerprint(room)
        self.assertEqual(fp[4], ())

    def test_fingerprint_meta_not_dict(self) -> None:
        room = _minimal_room(config={"slots": {"C": 1}})
        room["meta"] = ["not", "a", "dict"]
        fp = live_draft_prepare_fingerprint(room)
        self.assertEqual(fp[5], 0)

    def test_prepare_live_draft_state_legacy_list_config(self) -> None:
        session = {
            LIVE_DRAFT_ROOM_KEY: _minimal_room(
                config=[
                    {"position": "SS", "label": "SS", "slot_index": 0},
                ]
            ),
        }
        out = prepare_live_draft_state(session)
        self.assertIsInstance(out, dict)
        self.assertEqual(str(out.get("draft_room_id") or ""), "room-legacy-1")

    def test_prepare_live_draft_state_malformed_config_types(self) -> None:
        for bad_config in (None, [], "bad", ("slot_c",)):
            with self.subTest(config=bad_config):
                session = {LIVE_DRAFT_ROOM_KEY: _minimal_room(config=bad_config)}
                out = prepare_live_draft_state(session)
                self.assertIsInstance(out, dict)


if __name__ == "__main__":
    unittest.main()
