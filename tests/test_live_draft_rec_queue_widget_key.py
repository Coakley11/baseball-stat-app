"""Collision-safe rec-card Add-to-Queue widget keys (Commit B behavior)."""

from __future__ import annotations

import unittest
from typing import Any

from live_draft_rec_queue_click_trace import (
    COLLISION_SAFE_REC_QUEUE_KEY_TEMPLATE,
    LEGACY_REC_QUEUE_KEY_TEMPLATE,
    WIDGET_REGISTRY_KEY,
    build_rec_card_queue_widget_key,
    register_rec_queue_widget,
)


class RecQueueWidgetKeyTests(unittest.TestCase):
    def test_key_scheme_documentation(self) -> None:
        self.assertIn("{pick_index}", LEGACY_REC_QUEUE_KEY_TEMPLATE)
        self.assertIn("{room_id}", COLLISION_SAFE_REC_QUEUE_KEY_TEMPLATE)
        self.assertIn("{surface}", COLLISION_SAFE_REC_QUEUE_KEY_TEMPLATE)

    def test_widget_keys_unique_per_player(self) -> None:
        session: dict[str, Any] = {}
        room = "E9648CBC"
        for pid, name in [("592789", "Francisco Lindor"), ("608369", "Aaron Judge"), ("660271", "Mike Trout")]:
            key = build_rec_card_queue_widget_key(
                room_id=room,
                pick_index=0,
                stable_key=pid,
                surface="rec_card",
            )
            register_rec_queue_widget(
                session,
                room_id=room,
                pick_index=0,
                player_id=pid,
                player_name=name,
                widget_key=key,
            )
        reg = session.get(WIDGET_REGISTRY_KEY) or {}
        self.assertEqual(len(reg), 3)
        self.assertEqual(len(set(reg.keys())), 3)

    def test_room_change_avoids_legacy_collision(self) -> None:
        stable = "592789"
        k1 = build_rec_card_queue_widget_key(room_id="E9648CBC", pick_index=0, stable_key=stable)
        k2 = build_rec_card_queue_widget_key(room_id="AAAABBCC", pick_index=0, stable_key=stable)
        legacy1 = f"rec_card_queue_0_{stable}"
        legacy2 = f"rec_card_queue_0_{stable}"
        self.assertEqual(legacy1, legacy2)
        self.assertNotEqual(k1, k2)

    def test_pick_change_differs(self) -> None:
        room = "E9648CBC"
        stable = "592789"
        k0 = build_rec_card_queue_widget_key(room_id=room, pick_index=0, stable_key=stable)
        k1 = build_rec_card_queue_widget_key(room_id=room, pick_index=1, stable_key=stable)
        self.assertNotEqual(k0, k1)


if __name__ == "__main__":
    unittest.main()
