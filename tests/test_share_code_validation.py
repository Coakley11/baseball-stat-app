"""Share code vs internal draft session id validation."""

from __future__ import annotations

import unittest

from draft_room_create_verify import (
    is_plausible_share_code,
    looks_like_internal_draft_session_id,
    share_code_hint,
)


class ShareCodeValidationTests(unittest.TestCase):
    def test_plausible_share_code_six_chars(self) -> None:
        self.assertTrue(is_plausible_share_code("ABC123"))
        self.assertFalse(is_plausible_share_code("5FABA31B"))
        self.assertFalse(is_plausible_share_code("ABC12"))

    def test_internal_session_id_heuristic(self) -> None:
        self.assertTrue(looks_like_internal_draft_session_id("5FABA31B"))
        self.assertFalse(looks_like_internal_draft_session_id("ABC123"))

    def test_share_code_hint_for_session_id(self) -> None:
        hint = share_code_hint("5FABA31B")
        self.assertIn("internal session ID", hint)
        self.assertIn("6-character", hint)


if __name__ == "__main__":
    unittest.main()
