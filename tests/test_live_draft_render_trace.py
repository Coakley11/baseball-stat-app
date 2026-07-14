"""Smoke tests for Live Draft render tracer."""

from __future__ import annotations

import unittest

from live_draft_render_trace import (
    format_ldr_trace_text,
    ldr_section,
    ldr_section_done,
)


class LiveDraftRenderTraceTests(unittest.TestCase):
    def test_records_last_successful_section(self) -> None:
        ss = {"_suite_active_workspace_id": "daniel", "_live_draft_render_trace_force": True}
        ldr_section(ss, "page_entry")
        ldr_section_done(ss, "room_body")
        text = format_ldr_trace_text(ss)
        self.assertIn("page_entry", text)
        self.assertIn("LAST SUCCESSFUL SECTION: room_body", text)


if __name__ == "__main__":
    unittest.main()
