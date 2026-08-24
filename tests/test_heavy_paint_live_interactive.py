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

    def test_heavy_done_does_not_mount_run_every_fragment_for_interactive_widgets(self) -> None:
        """CASE_II: after heavy paint, Add-to-Queue must not live under fragment(run_every=1)."""
        st = MagicMock()
        fragment_kwargs: list[dict[str, Any]] = []
        fragment_invocations = {"n": 0}

        def _fragment_decorator(**kwargs):
            fragment_kwargs.append(dict(kwargs))

            def _wrap(fn):
                def _run():
                    fragment_invocations["n"] += 1
                    fn()

                return _run

            return _wrap

        st.fragment = _fragment_decorator
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        via_log: list[str] = []
        interactive = {"n": 0}

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
                        lambda: None,
                        paint_interactive=paint_interactive,
                    )
        self.assertEqual(interactive["n"], 1)
        self.assertIn("full_page_interactive_live", via_log)
        self.assertNotIn("fragment_interactive_live", via_log)
        self.assertEqual(fragment_kwargs, [], "must not mount fragment(run_every=…) after heavy paint")
        self.assertEqual(fragment_invocations["n"], 0)
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "script_run_no_run_every")

    def test_heavy_done_with_fragment_api_still_registers_on_script_run(self) -> None:
        """Even when st.fragment exists, post-done interactive path stays on ScriptRun."""
        st = MagicMock()
        st.fragment = MagicMock(side_effect=AssertionError("run_every fragment must not be used after done"))
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
        self.assertIn("full_page_interactive_live", via_log)
        st.fragment.assert_not_called()

    def test_first_fragment_paint_runs_expensive_once_then_interactive_on_script_run(self) -> None:
        st = MagicMock()

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
        self.assertEqual(
            interactive["n"],
            0,
            "post-done fragment ticks must not re-register Add-to-Queue under run_every",
        )
        self.assertTrue(session.get(HEAVY_PAINT_DONE_KEY))
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "pending_script_run_handoff")

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                render_deferred_heavy_paint_fragment(
                    st,
                    session,
                    paint_body,
                    paint_interactive=paint_interactive,
                )
        self.assertEqual(expensive["n"], 1)
        self.assertGreaterEqual(interactive["n"], 1)
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "script_run_no_run_every")

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
