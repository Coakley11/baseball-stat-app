"""Draft Queue headshots: offline first, then a few cached MLB lookups per run (D4J review
2026-11-08: queue rows showed only the generic ⚾ because the pool rarely carries MLBAM ids and
the id cache starts empty after a Cloud restart)."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

import player_photos as pp


class QueueHeadshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_patch = mock.patch.object(pp, "_load_mlbam_cache", return_value={})
        self.save_patch = mock.patch.object(pp, "_save_mlbam_cache")
        self.seed_patch = mock.patch.object(pp, "_seed_mlbam_id", return_value=None)
        for p in (self.cache_patch, self.save_patch, self.seed_patch):
            p.start()
            self.addCleanup(p.stop)

    def test_a_pool_row_with_an_mlbam_id_needs_no_lookup(self) -> None:
        s: dict = {}
        row = pd.Series({"fullName": "Aaron Judge", "MLBAM ID": 592450})
        with mock.patch.object(pp, "_search_mlbam_via_api") as api:
            info = pp.queue_photo_info(s, "Aaron Judge", row)
        api.assert_not_called()
        self.assertTrue(info["has_photo"])
        self.assertIn("592450", info["headshot_url"])

    def test_a_missing_id_is_looked_up_once_then_cached(self) -> None:
        s: dict = {}
        pp.reset_queue_photo_budget(s)
        with mock.patch.object(pp, "_search_mlbam_via_api", return_value=663728) as api:
            first = pp.queue_photo_info(s, "Cal Raleigh")
            second = pp.queue_photo_info(s, "Cal Raleigh")
        self.assertEqual(api.call_count, 1)
        self.assertTrue(first["has_photo"] and second["has_photo"])
        self.assertIn("663728", second["headshot_url"])

    def test_lookups_are_capped_per_run(self) -> None:
        s: dict = {}
        pp.reset_queue_photo_budget(s)
        names = [f"Player {i}" for i in range(pp.QUEUE_PHOTO_API_PER_RUN + 3)]
        with mock.patch.object(pp, "_search_mlbam_via_api", return_value=None) as api:
            for n in names:
                pp.queue_photo_info(s, n)
        self.assertEqual(api.call_count, pp.QUEUE_PHOTO_API_PER_RUN)

    def test_not_found_is_not_requested_again_within_the_hour(self) -> None:
        s: dict = {}
        pp.reset_queue_photo_budget(s)
        with mock.patch.object(pp, "_search_mlbam_via_api", return_value=None) as api:
            a = pp.queue_photo_info(s, "Nobody Known")
            pp.reset_queue_photo_budget(s)
            b = pp.queue_photo_info(s, "Nobody Known")
        self.assertEqual(api.call_count, 1)
        self.assertFalse(a["has_photo"] or b["has_photo"])
        self.assertIn("⚾", pp.render_queue_headshot_inline_html(b))

    def test_inline_headshot_renders_an_image(self) -> None:
        html = pp.render_queue_headshot_inline_html({"headshot_url": "https://img/x.png", "full_name": "A"})
        self.assertIn('<img src="https://img/x.png"', html)

    def test_both_queues_use_the_cached_lookup(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.assertIn("queue_photo_info(session, pname, pool_row)", (root / "draft_ui.py").read_text(encoding="utf-8"))
        self.assertIn("queue_photo_info(session, name)", (root / "live_draft_sidebar_queue.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
