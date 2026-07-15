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
    def test_unconditional_debug_disabled_by_default(self) -> None:
        self.assertFalse(LDR_TRACE_UNCONDITIONAL)
        self.assertFalse(is_ldr_trace_enabled({}))

    def test_force_flag_enables_logging(self) -> None:
        ss = {"_live_draft_render_trace_force": True}
        self.assertTrue(is_ldr_trace_enabled(ss))

    def test_screenshot_mode_hard_suppresses_ui_and_clears_force(self) -> None:
        from live_draft_render_trace import should_show_ldr_trace_ui

        class _SS(dict):
            pass

        class _St:
            def __init__(self) -> None:
                self.session_state = _SS(
                    {
                        "portfolio_screenshot_mode": True,
                        "_live_draft_render_trace_force": True,
                        "_live_draft_render_trace_enabled": True,
                    }
                )
                self.query_params = {"ldr_trace": "1"}

        st = _St()
        ss = st.session_state
        self.assertFalse(should_show_ldr_trace_ui(ss, st))
        self.assertFalse(ss.get("_live_draft_render_trace_force"))
        self.assertFalse(ss.get("_live_draft_render_trace_enabled"))
        self.assertNotIn("ldr_trace", st.query_params)

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

    def test_post_rerun_path_steps(self) -> None:
        ss = {
            "_live_draft_render_trace_force": True,
            "active_page": "Live Draft Room",
            "_live_draft_last_rerun_source": "timer_fragment_zero",
        }
        ldr_section_done(ss, "header_and_guide")
        for name in (
            "shared_settings",
            "prepare_live_draft_state",
            "poll_fragment",
            "shared_draft_panel",
            "room_body",
        ):
            with ldr_step(ss, name, ui_marker=False, last_rerun_source="timer_fragment_zero"):
                pass
        stall = analyze_ldr_stall(ss)
        self.assertEqual(stall["last_successful_section"], "room_body")
        text = format_ldr_trace_text(ss)
        self.assertIn("shared_settings", text)
        self.assertIn("prepare_live_draft_state", text)

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
