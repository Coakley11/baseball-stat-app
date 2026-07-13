"""Same-revision preference drift + full-session hydration ordering tests."""

from __future__ import annotations

import copy
import unittest

from account_fantasy_preferences import (
    PREFS_DOC_KEY,
    SESSION_APPLIED_FP_KEY,
    SESSION_APPLIED_REV_KEY,
    account_preference_fields_match_session,
    install_test_cloud_store,
    load_preference_revision_meta,
    prefs_revision_settings_app,
    prefs_settings_app,
    reassert_account_preferences_after_hydration,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import (
    FANTASY_RESEARCH_SYNC_KEY,
    _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
    _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
    reseed_fantasy_context_toggle_widgets,
)


UPLOAD = "3ce50b4f2e8b"
UPLOAD_CTX = "archive:3ce50b4f2e8b"


def _base_session() -> dict:
    return {
        "_suite_auth_user_id": "daniel",
        "_suite_active_workspace_id": "daniel",
        "_suite_device_id": "dell",
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
            }
        ],
        FANTASY_RESEARCH_SYNC_KEY: True,
        USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
        USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY: True,
    }


class SameRevisionPreferenceDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def _seed_cloud_revision_8(self, session: dict) -> dict:
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        # Force revision 8 by writing from an empty cloud then patching.
        write_account_fantasy_preferences(session, reason="bootstrap")
        app = prefs_settings_app(session)
        doc = copy.deepcopy(self.store[app][PREFS_DOC_KEY])
        doc["revision"] = 8
        doc["research_mode_enabled"] = True
        doc["fantasy_source_override_kind"] = "simulator_board"
        doc["active_draft_id"] = UPLOAD
        doc["active_league_context_id"] = UPLOAD_CTX
        self.store[app][PREFS_DOC_KEY] = doc
        # Keep revision header in sync.
        from account_fantasy_preferences import _save_revision_header

        _save_revision_header(session, doc)
        session[SESSION_APPLIED_REV_KEY] = 8
        return doc

    def test_same_revision_drift_reasserts_toggles_without_bumping_revision(self) -> None:
        dell = _base_session()
        cloud_doc = self._seed_cloud_revision_8(dell)

        # Dell applied rev 8 successfully.
        sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        rev_before = int(self.store[prefs_settings_app(dell)][PREFS_DOC_KEY]["revision"])

        # Simulate legacy full-session hydration restoring stale toggle values.
        dell[FANTASY_RESEARCH_SYNC_KEY] = False
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        dell[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = False
        dell[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = False
        dell[SESSION_APPLIED_REV_KEY] = 8
        match, mismatched = account_preference_fields_match_session(dell, cloud_doc)
        self.assertFalse(match)
        self.assertIn("research_mode_enabled", mismatched)

        result = reassert_account_preferences_after_hydration(dell)
        self.assertTrue(result.get("applied") or result.get("changed"))
        self.assertEqual(result.get("source"), "cloud_reassert_same_revision")
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        reseed_fantasy_context_toggle_widgets(dell)
        self.assertTrue(dell.get(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY))
        self.assertTrue(dell.get(_SIM_CONTEXT_TOGGLE_WIDGET_KEY))
        rev_after = int(self.store[prefs_settings_app(dell)][PREFS_DOC_KEY]["revision"])
        self.assertEqual(rev_before, rev_after)
        self.assertEqual(dell.get(SESSION_APPLIED_REV_KEY), 8)
        self.assertTrue(dell.get(SESSION_APPLIED_FP_KEY))

    def test_same_revision_false_state_reassert(self) -> None:
        dell = _base_session()
        dell[FANTASY_RESEARCH_SYNC_KEY] = False
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        write_account_fantasy_preferences(dell, reason="bootstrap")
        app = prefs_settings_app(dell)
        doc = self.store[app][PREFS_DOC_KEY]
        doc["revision"] = 8
        doc["research_mode_enabled"] = False
        doc["fantasy_source_override_kind"] = "none"
        from account_fantasy_preferences import _save_revision_header

        _save_revision_header(dell, doc)
        dell[SESSION_APPLIED_REV_KEY] = 8
        sync_account_fantasy_preferences(dell, force=True)

        # Hydration wrongly turns toggles on.
        dell[FANTASY_RESEARCH_SYNC_KEY] = True
        dell[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = True
        result = reassert_account_preferences_after_hydration(dell)
        self.assertTrue(result.get("applied") or result.get("changed"))
        self.assertFalse(dell.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertFalse(dell.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        self.assertEqual(int(self.store[app][PREFS_DOC_KEY]["revision"]), 8)

    def test_full_session_hydration_cannot_stick_after_reassert(self) -> None:
        session = _base_session()
        self._seed_cloud_revision_8(session)
        sync_account_fantasy_preferences(session, force=True)

        # apply_baseball_disk_state path simulation: blob wants toggles false.
        from baseball_persistent_state import apply_baseball_disk_state

        class _St:
            session_state = session

        blob = {
            "use_active_league_context_waiver_filter": False,
            "use_live_draft_as_fantasy_context": False,
            "use_simulator_board_as_fantasy_context": False,
            "active_draft_archive_id": UPLOAD,
            "page_filter_state": {},
        }
        apply_baseball_disk_state(_St(), blob)
        # Blob must not overwrite account-owned toggle keys.
        self.assertTrue(session.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
        # Even if something else overwrote them, reassert repairs without bump.
        session[FANTASY_RESEARCH_SYNC_KEY] = False
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = False
        session[SESSION_APPLIED_REV_KEY] = 8
        reassert_account_preferences_after_hydration(session)
        self.assertTrue(session.get(FANTASY_RESEARCH_SYNC_KEY))
        self.assertTrue(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))

    def test_revision_header_is_compact(self) -> None:
        session = _base_session()
        write_account_fantasy_preferences(session, reason="bootstrap")
        meta = load_preference_revision_meta(session)
        self.assertGreater(int(meta.get("revision") or 0), 0)
        self.assertTrue(meta.get("preference_fingerprint"))
        rev_app = prefs_revision_settings_app(session)
        self.assertIn(rev_app, self.store)
        header = self.store[rev_app].get("fantasy_account_prefs_revision")
        self.assertIsInstance(header, dict)
        self.assertIn("revision", header)
        self.assertIn("preference_fingerprint", header)
        # Header must not contain the full preference payload.
        self.assertNotIn("research_mode_enabled", header)


if __name__ == "__main__":
    unittest.main()
