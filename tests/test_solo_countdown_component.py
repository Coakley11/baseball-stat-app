"""Packaging tests for the Solo countdown wake Streamlit component."""

from __future__ import annotations

import unittest
from pathlib import Path

from solo_countdown_component import (
    build_solo_expire_token,
    component_frontend_ready,
    get_component_frontend_dir,
    parse_solo_expire_token,
)


class SoloCountdownComponentPackagingTests(unittest.TestCase):
    def test_frontend_index_exists(self) -> None:
        index = get_component_frontend_dir() / "index.html"
        self.assertTrue(index.is_file())
        content = index.read_text(encoding="utf-8")
        self.assertIn("streamlit:componentReady", content)
        self.assertIn("apiVersion: 1", content)
        self.assertIn("streamlit:setComponentValue", content)
        self.assertIn("solo-expire-client", content)
        self.assertNotIn("location.assign", content)
        self.assertIn("expiration_send_claimed", content)
        self.assertIn("expiration_send_suppressed_duplicate", content)
        self.assertIn("__soloExpirationSendClaims", content)
        self.assertNotIn("expire_token_resend_allowed", content)

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


if __name__ == "__main__":
    unittest.main()
