"""Tests for gated library repairs and page render timing."""

from __future__ import annotations

import unittest

from library_repair_scheduler import (
    library_repairs_required,
    mark_library_dirty,
    mark_library_repairs_complete,
    run_gated_library_repairs,
)
from page_render_timing import finish_page_render, mark_navigation_start, record_milestone


class LibraryRepairSchedulerTests(unittest.TestCase):
    def test_read_only_render_skips_repeat_repairs(self) -> None:
        session: dict = {"draft_archive_teams": [{"draft_id": "abc", "draft_name": "T"}]}
        first = run_gated_library_repairs(session, user_mutated=False)
        self.assertTrue(first.get("ran"))
        second = run_gated_library_repairs(session, user_mutated=False)
        self.assertEqual(second.get("skipped"), "read_only_render")

    def test_user_mutation_marks_dirty(self) -> None:
        session: dict = {}
        mark_library_repairs_complete(session)
        self.assertFalse(library_repairs_required(session))
        mark_library_dirty(session, reason="activate")
        self.assertTrue(library_repairs_required(session))


class PageRenderTimingTests(unittest.TestCase):
    def test_milestones_and_total_wall_ms(self) -> None:
        session: dict = {}
        mark_navigation_start(session, "Fantasy Lineup Assistant")
        record_milestone(session, "Fantasy Lineup Assistant", "page_shell_visible")
        summary = finish_page_render(session, "Fantasy Lineup Assistant")
        self.assertIn("total_wall_ms", summary)
        self.assertIn("page_shell_visible", (summary.get("milestones") or {}))


if __name__ == "__main__":
    unittest.main()
