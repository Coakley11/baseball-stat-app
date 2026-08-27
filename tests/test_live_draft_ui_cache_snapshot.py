"""Board-change invalidation must keep the consuming-run Add-to-Queue snapshot."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

if "pandas" not in sys.modules:
    _pd = types.ModuleType("pandas")

    class _DataFrame:
        empty = True

    _pd.DataFrame = _DataFrame  # type: ignore[attr-defined]
    sys.modules["pandas"] = _pd

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY
from live_draft_rec_live_paint import INTERACTIVE_TOP_REC_SNAPSHOT_KEY
from live_draft_ui_cache import (
    REC_CACHE_KEY,
    invalidate_live_draft_ui_caches,
    invalidate_live_draft_ui_caches_after_board_change,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD_CHANGE_SITES = (
    "streamlit_app.py",
    "live_draft_timer_ui.py",
    "live_draft_control_center_ui.py",
    "live_draft_expired_pick.py",
    "live_draft_fast_solo_start.py",
)


class BoardChangeSnapshotTests(unittest.TestCase):
    def test_board_change_keeps_snapshot_after_heavy_paint_done(self) -> None:
        session = {
            HEAVY_PAINT_DONE_KEY: True,
            REC_CACHE_KEY: {"top_rec": "stale"},
            INTERACTIVE_TOP_REC_SNAPSHOT_KEY: {"room_id": "CBA003B1", "top_rec": "lindor"},
        }
        invalidate_live_draft_ui_caches_after_board_change(session, reason="poll_changed")
        self.assertNotIn(REC_CACHE_KEY, session)
        self.assertEqual(session[INTERACTIVE_TOP_REC_SNAPSHOT_KEY]["room_id"], "CBA003B1")

    def test_board_change_drops_snapshot_before_heavy_paint_done(self) -> None:
        session = {
            REC_CACHE_KEY: {"top_rec": "stale"},
            INTERACTIVE_TOP_REC_SNAPSHOT_KEY: {"room_id": "CBA003B1", "top_rec": "lindor"},
        }
        invalidate_live_draft_ui_caches_after_board_change(session, reason="poll_changed")
        self.assertNotIn(REC_CACHE_KEY, session)
        self.assertNotIn(INTERACTIVE_TOP_REC_SNAPSHOT_KEY, session)

    def test_bare_invalidate_still_drops_snapshot(self) -> None:
        session = {
            HEAVY_PAINT_DONE_KEY: True,
            INTERACTIVE_TOP_REC_SNAPSHOT_KEY: {"room_id": "CBA003B1", "top_rec": "lindor"},
        }
        invalidate_live_draft_ui_caches(session)
        self.assertNotIn(INTERACTIVE_TOP_REC_SNAPSHOT_KEY, session)

    def test_board_change_sites_use_snapshot_preserving_helper(self) -> None:
        for rel in BOARD_CHANGE_SITES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn(
                "invalidate_live_draft_ui_caches_after_board_change",
                src,
                msg=f"{rel} must use the snapshot-preserving helper",
            )
            for line in src.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("def "):
                    continue
                if "invalidate_live_draft_ui_caches(" not in stripped:
                    continue
                self.assertIn(
                    "keep_interactive_snapshot",
                    stripped,
                    msg=f"{rel} still has a bare invalidate call: {stripped}",
                )


if __name__ == "__main__":
    unittest.main()
