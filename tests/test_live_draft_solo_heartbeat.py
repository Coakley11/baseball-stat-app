"""Architecture tests for Solo Live Draft single-heartbeat rendering."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TestSoloStaticBannerPaint(unittest.TestCase):
    def test_on_clock_solo_uses_static_paint_before_shared_fragment(self) -> None:
        src = (ROOT / "live_draft_on_clock_ui.py").read_text(encoding="utf-8")
        self.assertIn("solo_banner_uses_static_paint", src)
        self.assertIn("page_static_js", src)
        static_idx = src.index("page_static_js")
        fragment_idx = src.index("@fragment(run_every=1)")
        self.assertLess(static_idx, fragment_idx)

    def test_sidebar_skips_fragment_on_live_draft_room(self) -> None:
        src = (ROOT / "draft_ui.py").read_text(encoding="utf-8")
        self.assertIn("_render_live_draft_room_sidebar_snapshot", src)
        self.assertIn('if page == "Live Draft Room":', src)


class TestSoloHeartbeatModule(unittest.TestCase):
    def test_heartbeat_does_not_render_banner_html(self) -> None:
        src = (ROOT / "live_draft_solo_heartbeat.py").read_text(encoding="utf-8")
        self.assertNotIn("_render_on_clock_banner_html", src)
        self.assertIn("expire_current_pick_and_advance", src)

    def test_component_on_change_reads_session_state(self) -> None:
        for rel in ("live_draft_solo_heartbeat.py", "live_draft_solo_persistent_wake.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("st.session_state.get(key)", src)
        hb = (ROOT / "live_draft_solo_heartbeat.py").read_text(encoding="utf-8")
        start = hb.index("def _on_component_change")
        block = hb[start : start + 320]
        self.assertNotIn("build_solo_expire_token(room)", block)

    def test_component_wake_uses_on_change_only(self) -> None:
        src = (ROOT / "live_draft_solo_heartbeat.py").read_text(encoding="utf-8")
        self.assertNotIn("return process_solo_component_wake(st, session, room, value)", src)
        self.assertIn("on_change=_on_component_change", src)

    def test_shared_banner_repaint_token(self) -> None:
        from live_draft_solo_heartbeat import shared_banner_should_repaint

        session: dict = {}
        self.assertTrue(shared_banner_should_repaint(session, pick_index=0, deadline=100.0))
        self.assertFalse(shared_banner_should_repaint(session, pick_index=0, deadline=100.0))
        self.assertTrue(shared_banner_should_repaint(session, pick_index=1, deadline=100.0))


class TestSidebarSnapshotCopy(unittest.TestCase):
    def test_sidebar_timer_skips_fragment_on_ldr_page(self) -> None:
        from draft_ui import render_draft_sidebar_timer

        session = {
            "active_page": "Live Draft Room",
            "live_draft_room": {
                "status": "in_progress",
                "current_pick_index": 0,
                "config": {"timer_seconds": 60, "draft_setup_mode": "solo"},
                "pick_order": [{"Team": "A", "Round": 1, "Pick": 1}],
                "draft_board": [],
                "timer_deadline": __import__("time").time() + 30,
            },
            "live_draft_setup_mode": "solo",
        }
        st = mock.MagicMock()
        st.sidebar = mock.MagicMock()
        st.sidebar.caption = mock.MagicMock()
        st.fragment = mock.MagicMock()
        with mock.patch("draft_actions.draft_status_summary", return_value={"live_draft_active": True, "timer_seconds": 30}):
            with mock.patch("draft_ui._render_sidebar_timer_caption"):
                render_draft_sidebar_timer(st, session)
        st.fragment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
