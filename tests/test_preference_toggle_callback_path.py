"""Real user toggle callback path — shared fake cloud, no Streamlit browser."""

from __future__ import annotations

import copy
import unittest

from account_fantasy_preferences import (
    PREFS_DOC_KEY,
    SESSION_APPLIED_REV_KEY,
    ensure_account_preferences_applied_before_controls,
    install_test_cloud_store,
    prefs_settings_app,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    _LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
    _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
    _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
    apply_research_mode_toggle_from_widget,
    apply_simulator_override_toggle_from_widget,
)


UPLOAD = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"


def _session(*, device: str) -> dict:
    return {
        "_suite_auth_user_id": "daniel",
        "_suite_auth_external_id": "ext-daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_device_id": device,
        "active_draft_archive_id": UPLOAD,
        "fantasy_league_context_state": {
            "active_league_context_id": UPLOAD_CTX,
            "contexts": {},
        },
        "draft_archive_teams": [
            {
                "draft_id": UPLOAD,
                "draft_name": "Upload Test Demo",
                "league_context_id": UPLOAD_CTX,
                "players": [{"name": "P1"}],
            }
        ],
        FANTASY_RESEARCH_SYNC_KEY: False,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
        SESSION_APPLIED_REV_KEY: 0,
    }


def _cloud_doc(store: dict, session: dict) -> dict:
    app = prefs_settings_app(session)
    envelope = store.get(app) or {}
    doc = envelope.get(PREFS_DOC_KEY) or {}
    return copy.deepcopy(doc) if isinstance(doc, dict) else {}


class PreferenceToggleCallbackPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def test_phone_callback_writes_cloud_and_dell_applies_widgets(self) -> None:
        phone = _session(device="phone")
        dell = _session(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        sync_account_fantasy_preferences(dell, force=True)

        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        research = apply_research_mode_toggle_from_widget(phone)
        self.assertTrue(research.get("write_verified"), research)
        doc = _cloud_doc(self.store, phone)
        self.assertTrue(doc.get("research_mode_enabled"))

        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        sim = apply_simulator_override_toggle_from_widget(phone)
        self.assertTrue(sim.get("write_verified"), sim)
        doc2 = _cloud_doc(self.store, phone)
        self.assertTrue(doc2.get("research_mode_enabled"), "second toggle must not erase research")
        self.assertEqual(doc2.get("fantasy_source_override_kind"), "simulator_board")
        self.assertEqual(doc2.get("fantasy_source_override_id"), "simulator")

        sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))

        ensure_account_preferences_applied_before_controls(dell)
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))
        self.assertFalse(dell.get(_LIVE_CONTEXT_TOGGLE_WIDGET_KEY))

        # Render preparation again must not flip widgets.
        ensure_account_preferences_applied_before_controls(dell)
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

        # Simulate full-session hydration overwriting ambient toggles with false defaults.
        dell[FANTASY_RESEARCH_SYNC_KEY] = False
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        dell[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = False
        dell[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        ensure_account_preferences_applied_before_controls(dell)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

        # Reverse from Dell → phone.
        dell[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = False
        dell[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        apply_research_mode_toggle_from_widget(dell)
        apply_simulator_override_toggle_from_widget(dell)
        sync_account_fantasy_preferences(phone, force=True)
        ensure_account_preferences_applied_before_controls(phone)
        self.assertFalse(phone.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertFalse(phone.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        self.assertFalse(phone.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertFalse(phone.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

    def test_rapid_consecutive_toggles_preserve_both_fields(self) -> None:
        phone = _session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        apply_research_mode_toggle_from_widget(phone)
        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_simulator_override_toggle_from_widget(phone)
        doc = _cloud_doc(self.store, phone)
        self.assertTrue(doc.get("research_mode_enabled"))
        self.assertEqual(doc.get("fantasy_source_override_kind"), "simulator_board")


if __name__ == "__main__":
    unittest.main()
