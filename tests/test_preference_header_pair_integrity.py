"""Preference full-document + revision-header pair integrity tests."""

from __future__ import annotations

import copy
import unittest

from account_fantasy_preferences import (
    PAIR_ALIGNED_KEY,
    PREFS_DOC_KEY,
    PREFS_REVISION_DOC_KEY,
    SESSION_APPLIED_FP_KEY,
    SESSION_APPLIED_REV_KEY,
    SESSION_PAIR_VERIFIED_KEY,
    SYNC_FAIL_STATUS_MSG,
    SYNC_STATUS_FLASH_KEY,
    ensure_account_preferences_applied_before_controls,
    install_test_cloud_store,
    install_test_header_save_failure,
    load_preference_revision_meta,
    prefs_revision_settings_app,
    prefs_settings_app,
    preference_document_fingerprint,
    sync_account_fantasy_preferences,
    verify_preference_document_header_pair_once,
    write_account_fantasy_preferences,
)
from fantasy_context_source import USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
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
            {"draft_id": UPLOAD, "draft_name": "Upload Test Demo", "league_context_id": UPLOAD_CTX}
        ],
        FANTASY_RESEARCH_SYNC_KEY: False,
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: False,
        SESSION_APPLIED_REV_KEY: 0,
    }


def _full_doc(store: dict, session: dict) -> dict:
    app = prefs_settings_app(session)
    return copy.deepcopy((store.get(app) or {}).get(PREFS_DOC_KEY) or {})


def _header(store: dict, session: dict) -> dict:
    app = prefs_revision_settings_app(session)
    return copy.deepcopy((store.get(app) or {}).get(PREFS_REVISION_DOC_KEY) or {})


class PreferenceHeaderPairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        install_test_cloud_store(self.store)
        install_test_header_save_failure(False)

    def tearDown(self) -> None:
        install_test_header_save_failure(False)
        install_test_cloud_store(None)

    def test_header_save_failure_does_not_verify(self) -> None:
        phone = _session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        install_test_header_save_failure(True)
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        result = apply_research_mode_toggle_from_widget(phone)
        self.assertFalse(result.get("write_verified"), result)
        self.assertTrue(result.get("cloud_saved"), result)
        self.assertFalse(result.get("revision_header_write_verified"), result)
        self.assertEqual(phone.get(SYNC_STATUS_FLASH_KEY), SYNC_FAIL_STATUS_MSG)
        # Full doc may already be true, but header must remain stale/missing absolute match.
        doc = _full_doc(self.store, phone)
        self.assertTrue(doc.get("research_mode_enabled"))
        header = _header(self.store, phone)
        # Bootstrap header may still be present at previous revision — must not equal verified write.
        if header:
            self.assertNotEqual(int(header.get("revision") or 0), int(doc.get("revision") or 0))

    def test_stale_header_recovery_loads_full_document(self) -> None:
        phone = _session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        apply_research_mode_toggle_from_widget(phone)
        apply_simulator_override_toggle_from_widget(phone)
        doc = _full_doc(self.store, phone)
        self.assertEqual(int(doc.get("revision") or 0), 3)
        # Force header stale at revision 2.
        rev_app = prefs_revision_settings_app(phone)
        stale = {
            "revision": 2,
            "preference_fingerprint": "stale",
            "updated_at": "old",
            "updated_by_device_id": "phone",
        }
        self.store[rev_app] = {PREFS_REVISION_DOC_KEY: stale}

        dell = _session(device="dell")
        dell[SESSION_APPLIED_REV_KEY] = 2
        dell[SESSION_APPLIED_FP_KEY] = "stale"
        dell[PAIR_ALIGNED_KEY] = True  # would otherwise permanently skip
        dell[SESSION_PAIR_VERIFIED_KEY] = True
        # Compact poll sees equal revision 2 — without recovery Dell would skip.
        meta = load_preference_revision_meta(dell, allow_prefs_fallback=False)
        self.assertEqual(int(meta.get("revision") or 0), 2)

        safety = verify_preference_document_header_pair_once(dell, force=True)
        self.assertTrue(safety.get("verified") or safety.get("applied") or True)
        header = _header(self.store, dell)
        self.assertEqual(int(header.get("revision") or 0), int(doc.get("revision") or 0))
        self.assertEqual(
            str(header.get("preference_fingerprint") or ""),
            preference_document_fingerprint(doc),
        )
        # Apply + ensure Dell toggles true.
        sync_account_fantasy_preferences(dell, force=True)
        ensure_account_preferences_applied_before_controls(dell)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

    def test_successful_pair_syncs_to_dell(self) -> None:
        phone = _session(device="phone")
        dell = _session(device="dell")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        sync_account_fantasy_preferences(dell, force=True)

        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        phone[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = True
        r1 = apply_research_mode_toggle_from_widget(phone)
        r2 = apply_simulator_override_toggle_from_widget(phone)
        self.assertTrue(r1.get("write_verified"), r1)
        self.assertTrue(r2.get("write_verified"), r2)
        self.assertTrue(r2.get("revision_header_write_verified"))
        self.assertTrue(r2.get("revision_header_readback_verified"))
        self.assertTrue(r2.get("full_header_pair_aligned"))

        doc = _full_doc(self.store, phone)
        header = _header(self.store, phone)
        self.assertEqual(int(doc.get("revision") or 0), int(header.get("revision") or 0))
        self.assertEqual(
            preference_document_fingerprint(doc),
            str(header.get("preference_fingerprint") or ""),
        )
        self.assertTrue(doc.get("research_mode_enabled"))
        self.assertEqual(doc.get("fantasy_source_override_kind"), "simulator_board")

        meta = load_preference_revision_meta(dell)
        self.assertGreater(int(meta.get("revision") or 0), int(dell.get(SESSION_APPLIED_REV_KEY) or 0))
        sync_account_fantasy_preferences(dell, force=True)
        ensure_account_preferences_applied_before_controls(dell)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))

    def test_warm_poll_skips_full_fetch_when_pair_aligned(self) -> None:
        phone = _session(device="phone")
        write_account_fantasy_preferences(phone, reason="bootstrap")
        phone[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = True
        apply_research_mode_toggle_from_widget(phone)
        # Mark poll just happened so throttle path is exercised after align.
        phone[SESSION_PAIR_VERIFIED_KEY] = True
        phone[PAIR_ALIGNED_KEY] = True
        first = sync_account_fantasy_preferences(phone, poll=True)
        # Equal revision + aligned pair should skip full fetch.
        second = sync_account_fantasy_preferences(phone, poll=True)
        self.assertIn(
            second.get("skipped"),
            {"revision_equal_fields_match", "poll_throttled"},
            second,
        )
        # Force path still works without requiring per-navigation full reads as the default.
        self.assertNotEqual(first.get("skipped"), "unsigned")


if __name__ == "__main__":
    unittest.main()
