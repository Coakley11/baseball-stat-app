"""Smoke tests for Live Draft render tracer."""

from __future__ import annotations

import unittest

from live_draft_render_trace import (
    LDR_TRACE_LAST_STEP_KEY,
    LDR_TRACE_UNCONDITIONAL,
    analyze_ldr_stall,
    build_ldr_workspace_compare_snapshot,
    format_ldr_trace_text,
    format_next_behavior_label,
    is_ldr_trace_enabled,
    ldr_rerun,
    ldr_section,
    ldr_section_done,
    ldr_step,
)


class LiveDraftRenderTraceTests(unittest.TestCase):
    def test_unconditional_debug_enabled(self) -> None:
        self.assertTrue(LDR_TRACE_UNCONDITIONAL)
        self.assertTrue(is_ldr_trace_enabled({}))

    def test_records_last_successful_section(self) -> None:
        ss = {
            "_suite_active_workspace_id": "daniel",
            "_live_draft_render_trace_force": True,
            "active_page": "Live Draft Room",
        }
        ldr_section(ss, "page_entry")
        ldr_section_done(ss, "page_entry")
        ldr_section(ss, "room_body")
        ldr_section_done(ss, "room_body")
        text = format_ldr_trace_text(ss)
        self.assertIn("page_entry", text)
        self.assertIn("LAST SUCCESSFUL SECTION: room_body", text)

    def test_analyze_stall_entered_not_completed(self) -> None:
        ss = {"_live_draft_render_trace_force": True, "active_page": "Live Draft Room"}
        ldr_section_done(ss, "room_headers")
        ldr_section(ss, "room_controls_timer")
        stall = analyze_ldr_stall(ss)
        self.assertEqual(stall["last_successful_section"], "room_headers")
        self.assertEqual(stall["next_section_begun"], "room_controls_timer")
        self.assertEqual(stall["next_behavior"], "entered_not_completed")

    def test_analyze_stall_rerun(self) -> None:
        ss = {"_live_draft_render_trace_force": True, "active_page": "Live Draft Room"}
        ldr_section_done(ss, "poll_fragment")
        ldr_rerun(ss, "poll_fragment", reason="poll_changed")
        stall = analyze_ldr_stall(ss)
        self.assertEqual(stall["last_successful_section"], "poll_fragment")
        self.assertEqual(stall["next_behavior"], "rerun")
        self.assertIn(
            "poll",
            format_next_behavior_label(stall["next_behavior"], terminal=stall.get("terminal")),
        )

    def test_ldr_step_records_elapsed_and_stall_point(self) -> None:
        ss = {"_live_draft_render_trace_force": True, "active_page": "Live Draft Room"}
        ldr_section_done(ss, "room_headers")
        with ldr_step(ss, "timer_render_countdown", ui_marker=False):
            pass
        with self.assertRaises(RuntimeError):
            with ldr_step(ss, "timer_attach_fragment", ui_marker=False):
                raise RuntimeError("boom")
        stall = analyze_ldr_stall(ss)
        self.assertEqual(stall["last_successful_section"], "timer_render_countdown")
        self.assertEqual(stall["next_section_begun"], "timer_attach_fragment")
        self.assertEqual(stall["next_behavior"], "exception")
        self.assertEqual(ss.get(LDR_TRACE_LAST_STEP_KEY), "timer_attach_fragment")
        text = format_ldr_trace_text(ss)
        self.assertIn("ms", text)

    def test_compare_snapshot_keys(self) -> None:
        ss = {
            "_suite_active_workspace_id": "daniel",
            "active_shared_draft_room_code": "ABCD12",
            "live_draft_room": {
                "draft_room_id": "tmp-1",
                "status": "in_progress",
                "teams": ["Team X", "Team Y"],
                "config": {"user_team": "Team X", "league_name": "Practice"},
            },
            "live_draft_my_team": "Team X",
        }
        snap = build_ldr_workspace_compare_snapshot(ss)
        self.assertEqual(snap["workspace_id"], "daniel")
        self.assertEqual(snap["room_code"], "ABCD12")
        self.assertEqual(snap["temporary_draft_id"], "tmp-1")
        self.assertEqual(snap["live_draft_my_team"], "Team X")
        self.assertIn("effective_source_kind", snap)
        self.assertIn("poll_diag", snap)


if __name__ == "__main__":
    unittest.main()
