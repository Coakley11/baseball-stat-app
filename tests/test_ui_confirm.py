"""Destructive actions need a second, explicit Confirm (ui_confirm.confirm_destructive_action).

Before 2026-10-27 these ran on one tap: Reset Draft Room Simulator, Delete Live Draft Room
draft, Leave shared room, Cancel Shared Room (host), chat message Delete.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _app() -> None:
    import streamlit as st

    from ui_confirm import confirm_destructive_action

    st.session_state.setdefault("ran", 0)
    if confirm_destructive_action(st, key="t", label="Delete it", warning="Really?", confirm_label="Delete now"):
        st.session_state["ran"] += 1


class ConfirmDestructiveActionTests(unittest.TestCase):
    def _at(self) -> AppTest:
        at = AppTest.from_function(_app, default_timeout=60)
        at.run()
        return at

    def _button(self, at: AppTest, label: str):
        return next(b for b in at.button if b.label == label)

    def test_first_tap_only_asks(self) -> None:
        at = self._at()
        self._button(at, "Delete it").click().run()
        self.assertEqual(at.session_state["ran"], 0)
        self.assertEqual(at.warning[0].value, "Really?")

    def test_confirm_runs_once_and_cancel_never(self) -> None:
        at = self._at()
        self._button(at, "Delete it").click().run()
        self._button(at, "Cancel").click().run()
        self.assertEqual(at.session_state["ran"], 0)
        self.assertEqual([b.label for b in at.button], ["Delete it"])
        self._button(at, "Delete it").click().run()
        self._button(at, "Delete now").click().run()
        self.assertEqual(at.session_state["ran"], 1)
        at.run()
        self.assertEqual(at.session_state["ran"], 1)
        self.assertEqual([b.label for b in at.button], ["Delete it"])

    def test_stale_request_lapses(self) -> None:
        at = self._at()
        self._button(at, "Delete it").click().run()
        at.session_state["_confirm_armed::t"] = time.time() - 600
        at.run()
        self.assertEqual([b.label for b in at.button], ["Delete it"])
        self.assertEqual(at.session_state["ran"], 0)


class CallSitesTests(unittest.TestCase):
    def test_the_five_one_tap_actions_now_confirm(self) -> None:
        sites = {
            "streamlit_app.py": ('key="draft_room_reset_simulator_btn"', 'key="draft_room_delete_live_draft_btn"'),
            "draft_ui_multiplayer.py": ('key="shared_draft_leave_btn"',),
            "live_draft_setup_ui.py": ('key="live_draft_lobby_cancel_btn"',),
            "live_draft_chat_ui.py": ('key="ld_chat_delete_btn"',),
        }
        for name, keys in sites.items():
            src = (ROOT / name).read_text(encoding="utf-8")
            for key in keys:
                at = src.index(key)
                self.assertIn("confirm_destructive_action(", src[max(0, at - 400):at], f"{name} {key}")


if __name__ == "__main__":
    unittest.main()
