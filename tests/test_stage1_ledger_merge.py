"""Tests for merged Stage 1A server ledger scrape helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stage1_parent_observer_probe import merge_ledger_rows  # noqa: E402


class Stage1LedgerMergeTests(unittest.TestCase):
    def test_merge_by_event_id_survives_rerun_shape(self) -> None:
        existing = [{"event_id": "run:1:a", "event": "production_stage1_script_begin", "ts": 1.0}]
        incoming = [
            {"event_id": "run:1:a", "event": "production_stage1_script_begin", "ts": 1.0},
            {"event_id": "run:2:b", "event": "production_stage1_declaration_returned", "ts": 2.0},
        ]
        merged = merge_ledger_rows(existing, incoming)
        self.assertEqual(len(merged), 2)
        events = {r["event"] for r in merged}
        self.assertIn("production_stage1_declaration_returned", events)

    def test_unrelated_render_not_level5(self) -> None:
        from live_draft_stage1_receipt_levels import classify_receipt_levels, refine_a5a_subclass

        levels = classify_receipt_levels(
            expected_token="T|0|1",
            iframe_send_stages=["tick_cancelled"],
            coalesced_value="",
        )
        self.assertFalse(levels["LEVEL_1_IFRAME_SEND_EXECUTED"])
        self.assertEqual(refine_a5a_subclass(levels, unrelated_render_after_send=True), "A5a6")


if __name__ == "__main__":
    unittest.main()
