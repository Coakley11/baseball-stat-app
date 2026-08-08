"""Render-deferred heavy paint — live interactive path after HEAVY_PAINT_DONE (F4 regression)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_heavy_paint_ui import (
    DEFER_HEAVY_LOADING_KEY,
    HEAVY_PAINT_DONE_KEY,
    render_deferred_heavy_paint_fragment,
)
from live_draft_rec_live_paint import (
    PREPARED_REC_INTERACTIVE_KEY,
    render_rec_interactive_widgets,
    store_prepared_rec_interactive,
)


class HeavyPaintLiveInteractiveLifecycleTests(unittest.TestCase):
    """F4 invariant: interactive widgets must re-execute after heavy paint is done."""

    def test_after_heavy_paint_done_interactive_path_must_run(self) -> None:
        """Pre-fix architecture skipped paint_body; interactive callback must still run."""
        st = MagicMock()
        st.fragment = None
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        expensive = {"n": 0}
        interactive = {"n": 0}
        via_log: list[str] = []

        def paint_body() -> None:
            expensive["n"] += 1

        def paint_interactive() -> None:
            interactive["n"] += 1

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch(
                    "live_draft_rec_fragment_exec_diag.enter_recommendation_paint_invocation",
                    side_effect=lambda session, st, via="": via_log.append(str(via)),
                ):
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        paint_body,
                        paint_interactive=paint_interactive,
                    )
        self.assertEqual(expensive["n"], 0, "expensive body must not rerun when heavy paint done")
        self.assertGreaterEqual(
            interactive["n"],
            1,
            "live interactive renderer must run when heavy paint is done",
        )
        self.assertIn("full_page_interactive_live", via_log)

    def test_heavy_done_with_fragment_invokes_interactive_inside_fragment_not_full_page(self) -> None:
        st = MagicMock()
        fragment_calls: list[str] = []

        def _fragment_decorator(**kwargs):
            def _wrap(fn):
                def _run():
                    fragment_calls.append("run")
                    fn()

                st._heavy_frag_fn = _run
                return _run

            return _wrap

        st.fragment = _fragment_decorator
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        via_log: list[str] = []

        def paint_interactive() -> None:
            pass

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch(
                    "live_draft_rec_fragment_exec_diag.enter_recommendation_paint_invocation",
                    side_effect=lambda session, st, via="": via_log.append(str(via)),
                ):
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        lambda: None,
                        paint_interactive=paint_interactive,
                    )
        self.assertIn("fragment_interactive_live", via_log)
        self.assertNotIn("full_page_interactive_live", via_log)
        self.assertGreaterEqual(len(fragment_calls), 1)

    def test_first_fragment_paint_runs_expensive_once_then_interactive_on_later_tick(self) -> None:
        st = MagicMock()
        fragment = MagicMock()

        def _fragment_decorator(**kwargs):
            def _wrap(fn):
                st._heavy_frag_fn = fn
                return fn

            return _wrap

        st.fragment = _fragment_decorator
        session: dict[str, Any] = {}
        expensive = {"n": 0}
        interactive = {"n": 0}

        def paint_body() -> None:
            expensive["n"] += 1
            session[HEAVY_PAINT_DONE_KEY] = True

        def paint_interactive() -> None:
            interactive["n"] += 1

        defer_sequence = iter([True, False, False])

        def _should_defer(_session: dict[str, Any]) -> bool:
            return next(defer_sequence, False)

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", side_effect=_should_defer):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch("live_draft_fast_solo_start.clear_defer_heavy_first_paint"):
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        paint_body,
                        paint_interactive=paint_interactive,
                    )
                    if hasattr(st, "_heavy_frag_fn"):
                        st._heavy_frag_fn()
                    if hasattr(st, "_heavy_frag_fn"):
                        st._heavy_frag_fn()
        self.assertEqual(expensive["n"], 1)
        self.assertGreaterEqual(interactive["n"], 1)

    def test_render_rec_interactive_uses_prepared_cache_not_empty(self) -> None:
        import pandas as pd

        st = MagicMock()
        session: dict[str, Any] = {
            "_live_draft_rec_cache": {
                "top_rec": pd.DataFrame([{"fullName": "Francisco Lindor", "Primary Position": "SS", "playerID": "592789"}]),
            },
        }
        store_prepared_rec_interactive(
            session,
            room_id="ROOM1",
            gaps=[],
            category_needs=[],
            max_cards=1,
        )
        room = {"draft_room_id": "ROOM1", "current_pick_index": 0, "status": "paused"}
        with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
            with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
                ok = render_rec_interactive_widgets(st, session, room)
        self.assertTrue(ok)
        cards.assert_called_once()

    def test_prepared_payload_stable_across_rerender(self) -> None:
        session: dict[str, Any] = {}
        store_prepared_rec_interactive(session, room_id="R", gaps=["C"], category_needs=["HR"], max_cards=3)
        ts1 = session[PREPARED_REC_INTERACTIVE_KEY]["prepared_ts"]
        store_prepared_rec_interactive(session, room_id="R", gaps=["C"], category_needs=["HR"], max_cards=3)
        ts2 = session[PREPARED_REC_INTERACTIVE_KEY]["prepared_ts"]
        self.assertGreaterEqual(ts2, ts1)
        self.assertEqual(session[PREPARED_REC_INTERACTIVE_KEY]["gaps"], ["C"])


if __name__ == "__main__":
    unittest.main()
