"""Tests for Live Draft UX latency instrumentation."""

from __future__ import annotations

import unittest


class LiveDraftUxLatencyTests(unittest.TestCase):
    def test_click_to_settle_records_milestones(self) -> None:
        from live_draft_ux_latency import (
            ACTION_REMOVE_QUEUE,
            latest_ux_latency,
            mark_ux_milestone,
            note_ux_action,
            note_ux_pass_begin,
            note_ux_rerun_scope,
            settle_ux_action,
        )

        session = {"app_developer_mode": True, "_suite_developer_mode_user": True}
        note_ux_action(session, ACTION_REMOVE_QUEUE, source="test", detail="Player A")
        note_ux_pass_begin(session)
        mark_ux_milestone(session, "queue_paint_start", rebuild="queue_panel")
        mark_ux_milestone(session, "rec_cards_paint_start", rebuild="rec_cards")
        note_ux_rerun_scope(session, "fragment")
        note_ux_pass_begin(session)
        mark_ux_milestone(session, "queue_paint_done", rebuild="queue_panel")
        settle_ux_action(session, where="fragment_settled")

        latest = latest_ux_latency(session)
        assert latest is not None
        self.assertEqual(latest["action"], ACTION_REMOVE_QUEUE)
        self.assertEqual(latest["status"], "settled")
        self.assertTrue(latest["second_rerun"])
        self.assertEqual(latest["rerun_scope"], "fragment")
        self.assertIsNotNone(latest["first_visible_ms"])
        self.assertIsNotNone(latest["settled_ms"])
        self.assertIn("rec_cards", latest.get("rebuilds") or [])

    def test_disabled_when_not_developer_mode(self) -> None:
        from live_draft_ux_latency import ACTION_ADD_QUEUE, note_ux_action

        session: dict = {}
        self.assertIsNone(note_ux_action(session, ACTION_ADD_QUEUE, source="test"))

    def test_enabled_for_session_state_proxy_like_mapping(self) -> None:
        """Streamlit session_state is not a dict — Recording must still turn ON."""
        from live_draft_ux_latency import ux_latency_enabled

        class _Proxy:
            def __init__(self) -> None:
                self._data = {"app_developer_mode": True}

            def get(self, key, default=None):
                return self._data.get(key, default)

            def __setitem__(self, key, value) -> None:
                self._data[key] = value

        proxy = _Proxy()
        self.assertFalse(isinstance(proxy, dict))
        self.assertTrue(ux_latency_enabled(proxy))


if __name__ == "__main__":
    unittest.main()
