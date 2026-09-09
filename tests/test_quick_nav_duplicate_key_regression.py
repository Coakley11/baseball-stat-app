"""Regression: Shared Draft transition must not register quick-nav Queue twice.

Root cause: full_page paint_body registers live_draft_quick_nav_queue, then
interactive fails (empty shared pool), and fallback re-invoked paint_body in
the same ScriptRun → StreamlitDuplicateElementKey.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_heavy_paint_ui import (
    HEAVY_PAINT_DONE_KEY,
    PAINT_BODY_RAN_THIS_SCRIPT_KEY,
    render_deferred_heavy_paint_fragment,
)
from live_draft_navigation import render_live_draft_quick_nav_compact


class QuickNavDuplicateKeyRegressionTests(unittest.TestCase):
    def test_full_page_path_skips_second_paint_body_when_interactive_fails(self) -> None:
        """Shared empty-pool path: paint_body once, never duplicate quick-nav keys."""
        st = MagicMock()
        st.fragment = None
        session: dict[str, Any] = {}
        body_calls: list[str] = []
        registered_keys: list[str] = []

        def paint_body() -> None:
            body_calls.append("body")
            # Mirror decision-panel ownership: quick-nav registers once per paint_body.
            def _track_button(*_a, **kwargs):
                key = str(kwargs.get("key") or "")
                if key in registered_keys:
                    raise RuntimeError(f"StreamlitDuplicateElementKey:{key}")
                if key:
                    registered_keys.append(key)
                return True

            st_local = MagicMock()
            st_local.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
            for col in st_local.columns.return_value:
                col.button.side_effect = _track_button
            render_live_draft_quick_nav_compact(st_local, session)

        def paint_interactive() -> bool:
            return False

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch("live_draft_fast_solo_start.clear_defer_heavy_first_paint"):
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        paint_body,
                        paint_interactive=paint_interactive,
                    )

        self.assertEqual(body_calls, ["body"])
        self.assertIn("live_draft_quick_nav_queue", registered_keys)
        self.assertEqual(registered_keys.count("live_draft_quick_nav_queue"), 1)
        self.assertTrue(session.get(HEAVY_PAINT_DONE_KEY))
        self.assertEqual(
            session.get("_live_draft_rec_interactive_fallback_paint_body_skipped"),
            "paint_body_already_ran_this_script",
        )
        self.assertFalse(session.get("_live_draft_rec_interactive_fallback_ok"))

    def test_done_path_still_runs_fallback_paint_body_once(self) -> None:
        """HEAVY_PAINT_DONE paints rankings/QT once; interactive recovery must not re-paint body."""
        st = MagicMock()
        st.fragment = None
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        body_calls: list[str] = []
        interactive_n = {"n": 0}

        def paint_body() -> None:
            body_calls.append("body")

        def paint_interactive() -> bool:
            interactive_n["n"] += 1
            return interactive_n["n"] > 1

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                render_deferred_heavy_paint_fragment(
                    st,
                    session,
                    paint_body,
                    paint_interactive=paint_interactive,
                )

        self.assertEqual(body_calls, ["body"])
        self.assertTrue(session.get("_live_draft_rec_interactive_fallback_ok"))
        self.assertEqual(
            session.get("_live_draft_rec_interactive_fallback_paint_body_skipped"),
            "paint_body_already_ran_this_script",
        )
        # Cleared at entry of next deferred-heavy call, but still set after this run.
        self.assertTrue(session.get(PAINT_BODY_RAN_THIS_SCRIPT_KEY))


if __name__ == "__main__":
    unittest.main()
