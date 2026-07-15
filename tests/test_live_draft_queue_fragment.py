"""Phase 6A — queue fragment isolation contracts."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class LiveDraftQueueFragmentTests(unittest.TestCase):
    def test_queue_mutate_uses_fragment_rerun_not_app(self) -> None:
        from live_draft_queue_fragment import (
            QUEUE_FRAGMENT_MUTATE_KEY,
            QUEUE_FRAGMENT_PICK_KEY,
            render_live_draft_queue_fragment,
        )

        session: dict[str, Any] = {
            "draft_queue": ["Player A"],
            "live_draft_room": {"draft_board": [], "status": "in_progress", "config": {}},
        }
        st = MagicMock()
        calls: list[dict[str, Any]] = []

        def _fragment(fn=None, **_kwargs):
            if fn is None:

                def _decorator(inner):
                    return inner

                return _decorator

            def _runner():
                return fn()

            return _runner

        st.fragment = _fragment

        def _rerun(**kwargs):
            calls.append(dict(kwargs))

        st.rerun.side_effect = _rerun

        def _fake_panel(_st, sess, **_kwargs):
            from draft_state import remove_player_from_draft_queue

            remove_player_from_draft_queue(sess, "Player A")
            return True

        with patch("draft_ui.render_draft_queue_panel", side_effect=_fake_panel):
            render_live_draft_queue_fragment(st, session, queue_container=st, render_cards=None)

        self.assertTrue(session.get(QUEUE_FRAGMENT_MUTATE_KEY))
        self.assertFalse(bool(session.get(QUEUE_FRAGMENT_PICK_KEY)))
        self.assertEqual(calls, [{"scope": "fragment"}])
        self.assertEqual(session.get("draft_queue"), [])

    def test_draft_from_queue_escalates_to_app_rerun(self) -> None:
        from live_draft_queue_fragment import (
            QUEUE_FRAGMENT_PICK_KEY,
            render_live_draft_queue_fragment,
        )

        session: dict[str, Any] = {
            "draft_queue": ["Player A"],
            "live_draft_room": {"draft_board": [], "status": "in_progress", "config": {}},
            "_pending_manual_draft_pick": {"player_name": "Player A"},
        }
        st = MagicMock()
        calls: list[dict[str, Any]] = []

        def _fragment(fn=None, **_kwargs):
            if fn is None:

                def _decorator(inner):
                    return inner

                return _decorator

            def _runner():
                return fn()

            return _runner

        st.fragment = _fragment

        def _rerun(**kwargs):
            calls.append(dict(kwargs))

        st.rerun.side_effect = _rerun

        with patch("draft_ui.render_draft_queue_panel", return_value=True):
            render_live_draft_queue_fragment(st, session, queue_container=st, render_cards=None)

        self.assertTrue(session.get(QUEUE_FRAGMENT_PICK_KEY))
        self.assertEqual(calls, [{"scope": "app"}])

    def test_render_cards_invoked_inside_fragment_body(self) -> None:
        from live_draft_queue_fragment import render_live_draft_queue_fragment

        session: dict[str, Any] = {
            "draft_queue": [],
            "live_draft_room": {"draft_board": [], "status": "in_progress", "config": {}},
        }
        st = MagicMock()

        def _fragment(fn=None, **_kwargs):
            if fn is None:

                def _decorator(inner):
                    return inner

                return _decorator

            def _runner():
                return fn()

            return _runner

        st.fragment = _fragment
        cards_called = {"n": 0}

        def _cards() -> None:
            cards_called["n"] += 1

        with patch("draft_ui.render_draft_queue_panel", return_value=False):
            render_live_draft_queue_fragment(
                st, session, queue_container=st, render_cards=_cards
            )

        self.assertEqual(cards_called["n"], 1)
        st.rerun.assert_not_called()


if __name__ == "__main__":
    unittest.main()
