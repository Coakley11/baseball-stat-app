"""Tests for shared draft UI helpers."""

from __future__ import annotations

import unittest

from draft_ui import draft_disabled_hint, lookup_player_draft_meta


class TestDraftDisabledHint(unittest.TestCase):
    def test_not_your_pick_shortened(self) -> None:
        self.assertEqual(
            draft_disabled_hint("Not your pick (Pick 8: Team B)."),
            "Not your pick",
        )

    def test_other_reason_passthrough(self) -> None:
        self.assertEqual(draft_disabled_hint("Draft is complete."), "Draft is complete.")


class TestLookupPlayerDraftMeta(unittest.TestCase):
    def test_empty_name(self) -> None:
        self.assertEqual(lookup_player_draft_meta({}, ""), {"position": "—", "team": "—"})


if __name__ == "__main__":
    unittest.main()
