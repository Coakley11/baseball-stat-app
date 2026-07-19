"""Drafted players leave recommendations + both queue surfaces immediately."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_state import (
    DRAFT_QUEUE_KEY,
    add_player_to_draft_queue,
    remove_drafted_player_from_active_queues,
    remove_player_from_user_draft_queue,
    sync_draft_queue,
)
from live_draft_ui_cache import (
    REC_CACHE_KEY,
    filter_recommendation_tables_for_drafted,
    patch_live_draft_caches_after_pick,
)


def _room_with_stars() -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "ohtans001", "fullName": "Shohei Ohtani", "Primary Position": "UTIL"},
            {"playerID": "judgea001", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "sotoj001", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "other001", "fullName": "Other Player", "Primary Position": "SS"},
        ]
    )
    return {
        "status": "in_progress",
        "teams": ["Team A", "Team B"],
        "current_pick_index": 0,
        "draft_board": [],
        "drafted_player_ids": [],
        "rosters": {"Team A": [], "Team B": []},
        "pool": pool,
        "config": {"your_team": "Team A", "picks_per_team": 4, "num_teams": 2},
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Team A" if i % 2 == 0 else "Team B"}
            for i in range(8)
        ],
    }


class DraftedRecAndQueueTests(unittest.TestCase):
    def test_filter_removes_all_board_drafted_from_rec_tables(self) -> None:
        room = _room_with_stars()
        room["draft_board"] = [
            {"playerID": "ohtans001", "fullName": "Shohei Ohtani"},
            {"playerID": "judgea001", "fullName": "Aaron Judge"},
        ]
        room["drafted_player_ids"] = ["ohtans001", "judgea001"]
        top = room["pool"].copy()
        top, best, pos, sleep = filter_recommendation_tables_for_drafted(
            room, top, top.copy(), top.copy(), top.copy()
        )
        names = set(top["fullName"].astype(str))
        self.assertNotIn("Shohei Ohtani", names)
        self.assertNotIn("Aaron Judge", names)
        self.assertIn("Juan Soto", names)

    def test_patch_cache_drops_drafted_even_if_id_mismatches_name_only_board(self) -> None:
        session = {
            REC_CACHE_KEY: {
                "key": ("old",),
                "top_rec": pd.DataFrame(
                    [
                        {"fullName": "Shohei Ohtani", "playerID": "ohtans001"},
                        {"fullName": "Juan Soto", "playerID": "sotoj001"},
                    ]
                ),
                "best_avail": pd.DataFrame(
                    [{"fullName": "Shohei Ohtani", "playerID": "ohtans001"}]
                ),
                "pos_fit": pd.DataFrame(),
                "value_sleep": pd.DataFrame(),
            }
        }
        room = _room_with_stars()
        room["current_pick_index"] = 1
        # Board only has name (older records) — filter must still drop Ohtani.
        room["draft_board"] = [{"Player": "Shohei Ohtani"}]
        room["drafted_player_ids"] = []
        patch_live_draft_caches_after_pick(
            session, room, player_id="", player_name="Shohei Ohtani"
        )
        top = session[REC_CACHE_KEY]["top_rec"]
        self.assertTrue(all(str(x) != "Shohei Ohtani" for x in top["fullName"].tolist()))
        self.assertIn("Juan Soto", top["fullName"].tolist())

    def test_manual_and_auto_pick_strip_queue_by_id_and_name(self) -> None:
        session: dict = {}
        sync_draft_queue(session, ["Juan Soto", "Aaron Judge", "Other Player"], reason="test_seed")
        self.assertEqual(session[DRAFT_QUEUE_KEY][0], "Juan Soto")
        remove_drafted_player_from_active_queues(session, "sotoj001")
        # Name still present until prune sees board — remove by name too.
        remove_drafted_player_from_active_queues(session, "Juan Soto")
        self.assertNotIn("Juan Soto", session.get(DRAFT_QUEUE_KEY) or [])
        self.assertIn("Aaron Judge", session.get(DRAFT_QUEUE_KEY) or [])

    def test_sidebar_and_main_share_canonical_queue(self) -> None:
        session: dict = {}
        add_player_to_draft_queue(session, "Juan Soto")
        self.assertEqual(session[DRAFT_QUEUE_KEY], ["Juan Soto"])
        self.assertEqual(session.get("_live_draft_queue_sidebar_mirror"), ["Juan Soto"])
        remove_player_from_user_draft_queue(session, "Juan Soto", reason="sidebar_mirror_remove")
        self.assertEqual(session.get(DRAFT_QUEUE_KEY) or [], [])
        self.assertFalse(session.get("_live_draft_queue_sidebar_mirror"))

    def test_make_pick_removes_from_queue_and_recs(self) -> None:
        from live_draft_pick_engine import live_draft_make_pick

        session: dict = {DRAFT_QUEUE_KEY: ["Shohei Ohtani", "Juan Soto"]}
        room = _room_with_stars()
        session[REC_CACHE_KEY] = {
            "key": ("pre",),
            "top_rec": room["pool"].copy(),
            "best_avail": room["pool"].copy(),
            "pos_fit": pd.DataFrame(),
            "value_sleep": pd.DataFrame(),
        }
        ok, _ = live_draft_make_pick(
            room,
            room["pool"].iloc[0].to_dict(),
            session=session,
            pick_source="manual",
            enrich_pick_context=False,
        )
        self.assertTrue(ok)
        self.assertNotIn("Shohei Ohtani", session.get(DRAFT_QUEUE_KEY) or [])
        top = session[REC_CACHE_KEY]["top_rec"]
        self.assertTrue(all(str(x) != "Shohei Ohtani" for x in top["fullName"].tolist()))


if __name__ == "__main__":
    unittest.main()
