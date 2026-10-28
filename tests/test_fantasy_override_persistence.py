"""Fantasy Source override checkboxes survive navigation, refresh, and stale cloud reads."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from account_fantasy_preferences import (
    FANTASY_OVERRIDE_SELECTION_KEY,
    PREFS_DOC_KEY,
    install_test_cloud_store,
    prefs_settings_app,
    reassert_account_preferences_after_hydration,
    write_account_fantasy_preferences,
)
from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import (
    _LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
    _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
    _prepare_context_checkbox_widget,
    apply_live_override_toggle_from_widget,
    apply_simulator_override_toggle_from_widget,
)


def _session(*, user_id: str = "daniel", workspace: str = "daniel") -> dict:
    return {
        "_suite_auth_user_id": user_id,
        "_suite_active_workspace_id": workspace,
        "_suite_device_id": "phone",
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
    }


class FantasyOverridePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def _cloud_doc(self, session: dict) -> dict:
        app = prefs_settings_app(session)
        return (self.store.get(app) or {}).get(PREFS_DOC_KEY) or {}

    def test_stale_cloud_reassert_does_not_clear_checked_simulator_override(self) -> None:
        session = _session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(session)
        self.assertTrue(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])

        # Cloud write did not land; the stored doc is still the older "none".
        doc = self._cloud_doc(session)
        doc["fantasy_source_override_kind"] = "none"
        doc["updated_at"] = "2020-01-01T00:00:00+00:00"
        session.pop(_SIM_CONTEXT_TOGGLE_WIDGET_KEY, None)

        trace = reassert_account_preferences_after_hydration(session)
        self.assertTrue(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY], trace)
        _prepare_context_checkbox_widget(
            session,
            persisted_key=USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
            widget_key=_SIM_CONTEXT_TOGGLE_WIDGET_KEY,
        )
        self.assertTrue(session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY])

    def test_turning_override_off_survives_older_cloud_on(self) -> None:
        session = _session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(session)
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        apply_simulator_override_toggle_from_widget(session)
        doc = self._cloud_doc(session)
        doc["fantasy_source_override_kind"] = "simulator_board"
        doc["updated_at"] = "2020-01-01T00:00:00+00:00"

        reassert_account_preferences_after_hydration(session)
        self.assertFalse(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])

    def test_overrides_are_mutually_exclusive(self) -> None:
        session = _session()
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(session)
        session[_LIVE_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_live_override_toggle_from_widget(session)
        self.assertTrue(session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY])
        self.assertFalse(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])
        self.assertEqual(session[FANTASY_OVERRIDE_SELECTION_KEY]["override_kind"], "live_draft_room")

    def test_refresh_restores_override_without_a_board(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        session = _session()
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(session)
        self.assertNotIn("draft_room_table", session)
        st = MagicMock()
        st.session_state = session
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob[FANTASY_OVERRIDE_SELECTION_KEY]["override_kind"], "simulator_board")
        self.assertNotIn(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY, blob)

        restored: dict = {"_suite_auth_user_id": "daniel", "_suite_active_workspace_id": "daniel"}
        st2 = MagicMock()
        st2.session_state = restored
        apply_baseball_disk_state(st2, blob)
        self.assertTrue(restored[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])
        self.assertFalse(restored[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY])

    def test_other_account_selection_does_not_apply(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state

        blob = {
            FANTASY_OVERRIDE_SELECTION_KEY: {
                "user_id": "ariel",
                "workspace_id": "ariel",
                "override_kind": "simulator_board",
                "override_id": "simulator",
                "selected_at": "2026-10-28T00:00:00+00:00",
                "local_seq": 1,
            }
        }
        restored = {"_suite_auth_user_id": "daniel", "_suite_active_workspace_id": "daniel"}
        st = MagicMock()
        st.session_state = restored
        apply_baseball_disk_state(st, blob)
        self.assertNotIn(FANTASY_OVERRIDE_SELECTION_KEY, restored)
        self.assertFalse(bool(restored.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY)))

    def test_newer_cloud_selection_from_other_device_still_applies(self) -> None:
        session = _session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        apply_simulator_override_toggle_from_widget(session)
        doc = self._cloud_doc(session)
        doc["fantasy_source_override_kind"] = "simulator_board"
        doc["fantasy_source_override_id"] = "simulator"
        doc["updated_at"] = "2099-01-01T00:00:00+00:00"

        reassert_account_preferences_after_hydration(session)
        self.assertTrue(session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY])
        self.assertEqual(session[FANTASY_OVERRIDE_SELECTION_KEY]["override_kind"], "simulator_board")


if __name__ == "__main__":
    unittest.main()
