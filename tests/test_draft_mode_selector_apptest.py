"""AppTest: Draft Mode radio must not snap or crash after Shared selection."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from live_draft_setup_mode import (
    LIVE_DRAFT_SETUP_MODE_KEY,
    PENDING_LIVE_DRAFT_SETUP_MODE_KEY,
    SETUP_MODE_SHARED,
    SETUP_MODE_SOLO,
    WIDGET_MODE_LOCKED_KEY,
    mark_setup_mode_widget_locked,
    persist_live_draft_setup_mode_preference,
    request_live_draft_setup_mode,
    set_live_draft_setup_mode,
)
from live_draft_setup_ui import render_guest_join_from_setup, render_live_draft_mode_selector
from user_page_preferences import (
    PAGE_KEY_LIVE_DRAFT_SETUP,
    ensure_live_draft_setup_preferences_loaded,
    get_user_page_preferences,
    reset_live_draft_setup_to_defaults,
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
        }

        ensure_live_draft_setup_preferences_loaded(session)
        st = _SessionRadioSt(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            self.assertEqual(render_live_draft_mode_selector(st, session), SETUP_MODE_SOLO)

        session[LIVE_DRAFT_SETUP_MODE_KEY] = SETUP_MODE_SHARED
        ensure_live_draft_setup_preferences_loaded(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            mode = render_live_draft_mode_selector(st, session)

        self.assertEqual(mode, SETUP_MODE_SHARED)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SHARED)

        ensure_live_draft_setup_preferences_loaded(session)
        with mock.patch("suite_workspace.can_show_developer_tools", return_value=False):
            self.assertEqual(render_live_draft_mode_selector(st, session), SETUP_MODE_SHARED)


class GuestJoinDoesNotMutateWidgetKeyTests(unittest.TestCase):
    def test_join_success_persists_without_assigning_widget_key(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
            WIDGET_MODE_LOCKED_KEY: True,
            "_join_shared_draft_from_setup": True,
            "_join_requested_code": "ABC123",
            "_join_requested_team": "Team 2",
            "page_filter_state": {},
        }
        original_id = id(session.get(LIVE_DRAFT_SETUP_MODE_KEY))

        def _fake_join(sess, code, requested_team=""):  # noqa: ANN001
            return True, "joined", {"room_code": code}

        with mock.patch("draft_room_context.join_shared_draft_room", side_effect=_fake_join):
            with mock.patch(
                "live_draft_setup_mode.set_live_draft_setup_mode",
                side_effect=AssertionError("set_live_draft_setup_mode must not be called from guest join"),
            ):
                ok_rerun = render_guest_join_from_setup(mock.Mock(), session)

        self.assertTrue(ok_rerun)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SHARED)
        _ = original_id

    def test_set_after_lock_queues_pending_instead_of_assign(self) -> None:
        session = {LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED}
        mark_setup_mode_widget_locked(session)
        set_live_draft_setup_mode(session, SETUP_MODE_SOLO, persist=False)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        self.assertEqual(session.get(PENDING_LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SOLO)

    def test_persist_helper_does_not_write_widget_key(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
            WIDGET_MODE_LOCKED_KEY: True,
            "page_filter_state": {},
        }
        persist_live_draft_setup_mode_preference(session, SETUP_MODE_SHARED)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SHARED)

    def test_reset_after_lock_uses_pending(self) -> None:
        session = {
            "auth_user_id": "user:daniel",
            "workspace_id": "ws1",
            LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED,
            WIDGET_MODE_LOCKED_KEY: True,
            "page_filter_state": {},
        }
        reset_live_draft_setup_to_defaults(session, st=None)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        self.assertEqual(session.get(PENDING_LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SOLO)
        prefs = get_user_page_preferences("user:daniel", "ws1", PAGE_KEY_LIVE_DRAFT_SETUP, session=session)
        self.assertEqual(prefs.get(LIVE_DRAFT_SETUP_MODE_KEY), SETUP_MODE_SOLO)


class StreamlitAppTestDraftModeSnapBack(unittest.TestCase):
    def test_real_streamlit_radio_keeps_shared_then_solo(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE))
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)

        at.radio[0].set_value(SETUP_MODE_SHARED)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        self.assertEqual(len(at.exception), 0)
        md = " ".join(str(getattr(w, "value", "")) for w in at.markdown)
        self.assertIn("GUEST_JOIN_SECTION=visible", md)

        # Room code widget must not crash / mutate mode.
        if at.text_input:
            at.text_input[0].set_value("ABC123")
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        self.assertEqual(len(at.exception), 0)

        # Simulate join callback after radio (post-widget) — must not raise.
        at.session_state["_join_shared_draft_from_setup"] = True
        at.session_state["_join_requested_code"] = "ABC123"
        at.session_state["_join_requested_team"] = "Team 2"
        with mock.patch(
            "draft_room_context.join_shared_draft_room",
            return_value=(True, "ok", {"room_code": "ABC123"}),
        ):
            at.run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)

        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)

        at.radio[0].set_value(SETUP_MODE_SOLO)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)
        self.assertEqual(len(at.exception), 0)

    def test_reset_setup_via_pending_no_exception(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE))
        at.run()
        at.radio[0].set_value(SETUP_MODE_SHARED)
        at.run()
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)

        # Click reset after radio — uses pending Solo, then next run applies.
        at.button(key="apptest_reset_setup").click()
        at.run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)


class PendingModeMechanismTests(unittest.TestCase):
    def test_request_while_locked_applies_next_seed(self) -> None:
        from live_draft_setup_mode import seed_live_draft_setup_mode_before_widget

        session = {LIVE_DRAFT_SETUP_MODE_KEY: SETUP_MODE_SHARED}
        mark_setup_mode_widget_locked(session)
        request_live_draft_setup_mode(session, SETUP_MODE_SOLO)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SHARED)
        seeded = seed_live_draft_setup_mode_before_widget(session)
        self.assertEqual(seeded, SETUP_MODE_SOLO)
        self.assertEqual(session[LIVE_DRAFT_SETUP_MODE_KEY], SETUP_MODE_SOLO)
        self.assertNotIn(PENDING_LIVE_DRAFT_SETUP_MODE_KEY, session)
        self.assertFalse(session.get(WIDGET_MODE_LOCKED_KEY))


if __name__ == "__main__":
    unittest.main()
