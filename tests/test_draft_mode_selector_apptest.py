"""AppTest: Draft Mode radio must not snap Shared → Solo on the same setup page."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
)
from live_draft_setup_ui import render_live_draft_mode_selector
from user_page_preferences import (
    PAGE_KEY_LIVE_DRAFT_SETUP,
    ensure_live_draft_setup_preferences_loaded,
    get_user_page_preferences,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "draft_mode_selector_only_apptest.py"


class _SessionRadioSt:
    """Minimal Streamlit stand-in that owns radio state like st.session_state[key]."""

    def __init__(self, session: dict) -> None:
        self.session_state = session

    def radio(self, label, options, **kwargs):  # noqa: ANN001
        key = kwargs["key"]
        if key not in self.session_state:
            self.session_state[key] = options[0]
        return self.session_state[key]

    def info(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def markdown(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def caption(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


class DraftModeSelectorPageInteractionTests(unittest.TestCase):
    def test_setup_page_order_keeps_shared_after_click(self) -> None:
        """Mirrors streamlit_app Live Draft setup: ensure prefs → render selector."""
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            "_suite_active_workspace_id": "ws1",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SOLO,
            "live_draft_room": {
                "status": "not_started",
                "config": {"draft_setup_mode": SETUP_MODE_SOLO},
            },
            "page_filter_state": {
                "_user_page_preferences": {
                    PAGE_KEY_LIVE_DRAFT_SETUP: {
                        "user_id": "user:daniel",
                        "workspace_id": "ws1",
                        "settings": {"live_draft_setup_mode": SETUP_MODE_SOLO},
                    }
                }
            },
            "_live_draft_mode_radio_label": "Solo Draft — you control all teams (no room code)",
        }

        # Run 1: open setup (solo).
        ensure_live_draft_setup_preferences_loaded(session)
        st = _SessionRadioSt(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            self.assertEqual(render_live_draft_mode_selector(st, session), SETUP_MODE_SOLO)

        # Run 2: user clicks Shared Multiplayer (Streamlit writes key before body).
        session[LIVE_DRAFT_SETUP_MODE_KEY] = SETUP_MODE_SHARED
        ensure_live_draft_setup_preferences_loaded(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            mode = render_live_draft_mode_selector(st, session)

        self.assertEqual(mode, SETUP_MODE_SHARED)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SHARED)

        # Run 3: rerun must remain Shared.
        ensure_live_draft_setup_preferences_loaded(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            self.assertEqual(render_live_draft_mode_selector(st, session), SETUP_MODE_SHARED)


class StreamlitAppTestDraftModeSnapBack(unittest.TestCase):
    def test_real_streamlit_radio_keeps_shared_then_solo(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE))
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)
        at.radio[0].set_value(SETUP_MODE_SHARED)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        at.radio[0].set_value(SETUP_MODE_SOLO)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)


if __name__ == "__main__":
    unittest.main()
