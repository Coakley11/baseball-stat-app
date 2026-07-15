"""Visible Draft Queue render-list resolution."""

from __future__ import annotations

import unittest
from typing import Any

from draft_ui import _resolve_visible_draft_queue


class VisibleQueueResolveTests(unittest.TestCase):
    def test_prefers_widget_key(self) -> None:
        session: dict[str, Any] = {
            "draft_queue": ["Aaron Judge"],
            "draft_state": {"queue": ["Juan Soto"]},
        }
        names, src = _resolve_visible_draft_queue(session, qkey="draft_queue")
        self.assertEqual(names, ["Aaron Judge"])
        self.assertEqual(src, "draft_queue")

    def test_falls_back_to_draft_state(self) -> None:
        session: dict[str, Any] = {
            "draft_queue": [],
            "draft_state": {"queue": ["Aaron Judge", "Juan Soto"]},
        }
        names, src = _resolve_visible_draft_queue(session, qkey="draft_queue")
        self.assertEqual(names, ["Aaron Judge", "Juan Soto"])
        self.assertEqual(src, "draft_state.queue")

    def test_falls_back_to_last_good(self) -> None:
        session: dict[str, Any] = {
            "draft_queue": [],
            "draft_state": {"queue": []},
            "_live_draft_queue_last_good": ["Juan Soto"],
        }
        names, src = _resolve_visible_draft_queue(session, qkey="draft_queue")
        self.assertEqual(names, ["Juan Soto"])
        self.assertEqual(src, "_live_draft_queue_last_good")


if __name__ == "__main__":
    unittest.main()
