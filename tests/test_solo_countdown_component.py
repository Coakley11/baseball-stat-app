"""Packaging tests for the Solo countdown wake Streamlit component."""

from __future__ import annotations

import unittest

from solo_countdown_component import (
    build_solo_expire_token,
    component_frontend_ready,
    get_component_frontend_dir,
    parse_solo_expire_token,
)


class SoloCountdownComponentPackagingTests(unittest.TestCase):
    def test_component_ready(self) -> None:
        self.assertTrue(component_frontend_ready())

    def test_build_and_parse_expire_token(self) -> None:
        room = {"draft_room_id": "abc123", "current_pick_index": 2, "timer_deadline": 1000.5}
        token = build_solo_expire_token(room)
        parsed = parse_solo_expire_token(token)
        assert parsed is not None
        self.assertEqual(parsed["draft_id"], "abc123")
        self.assertEqual(parsed["pick_index"], 2)
        self.assertEqual(parsed["deadline"], 1000.5)

    def test_v2_js_handshake(self) -> None:
        from solo_countdown_component import _SOLO_COUNTDOWN_JS

        self.assertIn("setTriggerValue", _SOLO_COUNTDOWN_JS)
        self.assertIn("browser_deadline_crossed", _SOLO_COUNTDOWN_JS)
        self.assertIn("component_value_sent", _SOLO_COUNTDOWN_JS)
        self.assertNotIn("location.assign", _SOLO_COUNTDOWN_JS)
        self.assertNotIn("setComponentValue", _SOLO_COUNTDOWN_JS)


if __name__ == "__main__":
    unittest.main()
