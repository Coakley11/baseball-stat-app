"""Tests for isolated Stage1 DOM click capture normalization and grading."""

from __future__ import annotations

import unittest

from scripts.stage1_dom_click_capture import (
    CAPTURE_TARGET_FRAGMENT_PROBE,
    CAPTURE_TARGET_FRANCISCO_ADD,
    CAPTURE_TARGET_PAUSE,
    normalize_dom_click_event,
    summarize_dom_click_capture,
)


class Stage1DomClickCaptureTests(unittest.TestCase):
    def test_normalizes_isTrusted_to_is_trusted(self) -> None:
        row = normalize_dom_click_event({"type": "click", "isTrusted": True, "target_text": "Pause Draft"})
        self.assertTrue(row["is_trusted"])
        self.assertNotIn("isTrusted", row)

    def test_pause_events_do_not_satisfy_fragment_probe(self) -> None:
        events = [
            {"type": "click", "is_trusted": True, "target_text": "⏸ Pause Draft"},
        ]
        summary = summarize_dom_click_capture(events, capture_target=CAPTURE_TARGET_FRAGMENT_PROBE)
        self.assertFalse(summary["trusted_dom_click"])
        self.assertTrue(summary["unexpected_event_targets"])

    def test_probe_events_do_not_satisfy_francisco(self) -> None:
        events = [
            {
                "type": "click",
                "is_trusted": True,
                "target_text": "Stage1 Recommendation Widget Probe",
            },
        ]
        summary = summarize_dom_click_capture(events, capture_target=CAPTURE_TARGET_FRANCISCO_ADD)
        self.assertFalse(summary["trusted_dom_click"])

    def test_francisco_trusted_click_requires_add_to_queue_text(self) -> None:
        events = [
            {"type": "click", "is_trusted": True, "target_text": "⭐ Add to Queue"},
        ]
        summary = summarize_dom_click_capture(events, capture_target=CAPTURE_TARGET_FRANCISCO_ADD)
        self.assertTrue(summary["trusted_dom_click"])
        self.assertEqual(summary["event_count"], 1)

    def test_cleared_buffer_only_counts_new_events(self) -> None:
        events = [
            {"type": "click", "is_trusted": True, "target_text": "Pause Draft"},
            {"type": "click", "is_trusted": True, "target_text": "Stage1 Recommendation Widget Probe"},
        ]
        pause_only = summarize_dom_click_capture(events[:1], capture_target=CAPTURE_TARGET_PAUSE)
        self.assertTrue(pause_only["trusted_dom_click"])
        probe_only = summarize_dom_click_capture(events[1:], capture_target=CAPTURE_TARGET_FRAGMENT_PROBE)
        self.assertTrue(probe_only["trusted_dom_click"])


if __name__ == "__main__":
    unittest.main()
